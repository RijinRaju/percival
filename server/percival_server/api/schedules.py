from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from percival.naming import Headers
from percival.redaction import REDACTED
from percival.schedules import next_runs
from percival_server import audit, live
from percival_server.auth.deps import Principal, require_read, require_write
from percival_server.connections import Connections
from percival_server.db import get_db
from percival_server.models import Run, ScheduleMeta, utcnow
from percival_server.schedules import store
from percival_server.schedules.spec import InvalidSchedule, ScheduleIn, SchedulePatch, build

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _import_action(app: Celery, name: str, entry: dict[str, Any]) -> str:
    if entry["schedule"]["type"] not in ("crontab", "interval"):
        return "unsupported"
    # workers redact what they publish, importing that would write "[redacted]"
    # into real task arguments. the CLI importer reads the real config instead
    if REDACTED in json.dumps([entry.get("args"), entry.get("kwargs")]):
        return "redacted"
    return "exists" if store.exists(app, name) else "create"


def _conns(request: Request) -> Connections:
    conns: Connections = request.app.state.connections
    return conns


def _celery(request: Request) -> Celery:
    return _conns(request).celery()


def _get(app: Celery, name: str) -> Any:
    try:
        return store.get(app, name)
    except store.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no schedule called {name!r}") from exc


def _snapshot(entry: Any) -> dict[str, Any] | None:
    try:
        return store.to_spec(entry).model_dump(mode="json", exclude={"notes"})
    except ValueError:
        return None


def _last_runs(db: Session, names: list[str]) -> dict[str, Run]:
    if not names:
        return {}
    latest = (
        select(func.max(Run.id))
        .where(Run.schedule.in_(names), Run.status != "running")
        .group_by(Run.schedule)
    )
    rows = db.scalars(select(Run).where(Run.id.in_(latest)))
    return {r.schedule: r for r in rows if r.schedule}


def _decorate(
    data: dict[str, Any],
    meta: ScheduleMeta | None,
    last: Run | None,
    workers: list[dict[str, Any]],
    beat: dict[str, Any] | None,
) -> dict[str, Any]:
    data["notes"] = meta.notes if meta else ""
    data["updated_at"] = meta.updated_at if meta else None
    data["updated_by"] = meta.updated_by if meta else None
    data["last_run"] = (
        {"id": last.id, "status": last.status, "ts": last.ts, "worker": last.worker}
        if last
        else None
    )
    data["coverage"] = live.queue_coverage(workers, data["queue"], data["required_version"])
    # has beat looked at the schedule since we last changed it? can only tell
    # when the percival scheduler is running, plain redbeat has no heartbeat
    if beat is None or meta is None:
        data["applied"] = None
    else:
        data["applied"] = bool(beat["last_tick"] and beat["last_tick"] >= meta.updated_at)
    return data


@router.get("")
def list_schedules(
    request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> list[dict[str, Any]]:
    conns = _conns(request)
    entries = store.list_entries(conns.celery())
    names = [e.name for e in entries]
    metas = {
        m.name: m for m in db.scalars(select(ScheduleMeta).where(ScheduleMeta.name.in_(names)))
    }
    last = _last_runs(db, names)
    workers = live.read_workers(conns)
    beat = live.read_beat(conns)
    now = datetime.now(timezone.utc)
    return [
        _decorate(
            store.serialize(e, now=now, count=5), metas.get(e.name), last.get(e.name), workers, beat
        )
        for e in entries
    ]


@router.get("/{name}")
def get_schedule(
    name: str, request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> dict[str, Any]:
    conns = _conns(request)
    entry = _get(conns.celery(), name)
    return _decorate(
        store.serialize(entry, count=5),
        db.get(ScheduleMeta, name),
        _last_runs(db, [name]).get(name),
        live.read_workers(conns),
        live.read_beat(conns),
    )


@router.get("/{name}/next-runs")
def get_next_runs(
    name: str,
    request: Request,
    count: int = Query(5, ge=1, le=50),
    _: Principal = Depends(require_read),
) -> list[datetime]:
    entry = _get(_celery(request), name)
    return next_runs(entry.schedule, count) if entry.enabled else []


class Preview(BaseModel):
    schedule: dict[str, Any]
    timezone: str = "UTC"
    count: int = Field(5, ge=1, le=50)


@router.post("/preview")
def preview(body: Preview, _: Principal = Depends(require_read)) -> list[datetime]:
    """Next runs for a schedule that isn't saved yet, for the form preview."""
    try:
        draft = ScheduleIn.model_validate(
            {
                "name": "preview",
                "task": "preview",
                "schedule": body.schedule,
                "timezone": body.timezone,
            }
        )
        return next_runs(build(draft.schedule, draft.timezone), body.count)
    except (InvalidSchedule, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _unknown_task_warning(conns: Connections, task: str) -> list[str]:
    known = set(live.read_task_meta(conns))
    for w in live.read_workers(conns):
        known.update(w.get("tasks") or [])
    if known and task not in known:
        return [f"no live worker has registered {task}, it will fail until one does"]
    return []


@router.post("", status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleIn,
    request: Request,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    conns = _conns(request)
    app = conns.celery()
    if store.exists(app, body.name):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{body.name!r} already exists")
    try:
        entry = store.save(app, body, origin=who.source)
    except InvalidSchedule as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    meta = db.get(ScheduleMeta, body.name) or ScheduleMeta(name=body.name)
    meta.notes, meta.origin = body.notes, who.source
    meta.created_by = meta.updated_by = who.name
    meta.updated_at = utcnow()
    db.merge(meta)
    audit.record(db, who, "schedule.create", body.name, after=_snapshot(entry))
    db.commit()
    return {**store.serialize(entry, count=5), "warnings": _unknown_task_warning(conns, body.task)}


@router.patch("/{name}")
def update_schedule(
    name: str,
    body: SchedulePatch,
    request: Request,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    conns = _conns(request)
    app = conns.celery()
    previous = _get(app, name)
    try:
        current = store.to_spec(previous)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    meta = db.get(ScheduleMeta, name)
    changes = body.model_dump(exclude_unset=True)
    merged = current.model_dump()
    merged.update(changes)
    merged["notes"] = changes.get("notes", meta.notes if meta else "")
    try:
        spec = ScheduleIn.model_validate(merged)
        entry = store.save(app, spec, origin=who.source, previous=previous)
    except InvalidSchedule as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if meta is None:
        meta = ScheduleMeta(
            name=name, origin=previous.options.get("headers", {}).get(Headers.ORIGIN) or "imported"
        )
        db.add(meta)
    meta.notes = spec.notes
    meta.updated_by = who.name
    meta.updated_at = utcnow()
    audit.record(
        db, who, "schedule.update", name, before=_snapshot(previous), after=_snapshot(entry)
    )
    db.commit()
    return {**store.serialize(entry, count=5), "warnings": _unknown_task_warning(conns, spec.task)}


class Reason(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


def _toggle(
    name: str, enabled: bool, request: Request, db: Session, who: Principal, reason: str | None
) -> dict[str, Any]:
    app = _celery(request)
    before = _get(app, name)
    entry = store.set_enabled(app, name, enabled)
    meta = db.get(ScheduleMeta, name) or ScheduleMeta(name=name, origin="imported")
    meta.updated_by, meta.updated_at = who.name, utcnow()
    db.merge(meta)
    audit.record(
        db,
        who,
        "schedule.resume" if enabled else "schedule.pause",
        name,
        before={"enabled": before.enabled},
        after={"enabled": enabled, "reason": reason},
    )
    db.commit()
    return store.serialize(entry, count=5)


@router.post("/{name}/pause")
def pause(
    name: str,
    request: Request,
    body: Reason | None = None,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    return _toggle(name, False, request, db, who, body.reason if body else None)


@router.post("/{name}/resume")
def resume(
    name: str,
    request: Request,
    body: Reason | None = None,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    return _toggle(name, True, request, db, who, body.reason if body else None)


@router.post("/{name}/run-now", status_code=status.HTTP_202_ACCEPTED)
def run_now(
    name: str,
    request: Request,
    body: Reason | None = None,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    app = _celery(request)
    entry = _get(app, name)
    options = dict(entry.options or {})
    headers = dict(options.pop("headers", None) or {})
    headers[Headers.SCHEDULE] = name
    result = app.send_task(
        entry.task, args=entry.args, kwargs=entry.kwargs, headers=headers, **options
    )
    audit.record(
        db,
        who,
        "schedule.run_now",
        name,
        after={"task_id": result.id, "reason": body.reason if body else None},
    )
    db.commit()
    return {"task_id": result.id}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> None:
    app = _celery(request)
    entry = _get(app, name)
    snapshot = _snapshot(entry)
    store.delete(app, name)
    meta = db.get(ScheduleMeta, name)
    if meta:
        db.delete(meta)
    audit.record(db, who, "schedule.delete", name, before=snapshot)
    db.commit()


# import from what workers published


@router.get("/import/available")
def importable(request: Request, _: Principal = Depends(require_read)) -> dict[str, Any]:
    """The beat_schedule a worker published on startup, and what importing it
    would do. Nothing is written here."""
    conns = _conns(request)
    published = live.read_published_beat_schedule(conns)
    if not published:
        return {"available": False, "entries": []}
    app = conns.celery()
    out = []
    for name, entry in published["entries"].items():
        action = _import_action(app, name, entry)
        out.append({"name": name, "task": entry["task"], "human": entry["human"], "action": action})
    return {
        "available": True,
        "timezone": published.get("timezone"),
        "code_version": published.get("code_version"),
        "hostname": published.get("hostname"),
        "entries": out,
    }


class ImportRequest(BaseModel):
    names: list[str]
    required_version: str | None = None


@router.post("/import")
def import_published(
    body: ImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_write),
) -> dict[str, Any]:
    conns = _conns(request)
    published = live.read_published_beat_schedule(conns) or {"entries": {}}
    app = conns.celery()
    created, skipped = [], []
    for name in body.names:
        entry = published["entries"].get(name)
        if entry is None or _import_action(app, name, entry) != "create":
            skipped.append(name)
            continue
        sched = dict(entry["schedule"])
        options = entry.get("options") or {}
        spec = ScheduleIn.model_validate(
            {
                "name": name,
                "task": entry["task"],
                "schedule": sched,
                "timezone": published.get("timezone") or "UTC",
                "args": entry.get("args") or [],
                "kwargs": entry.get("kwargs") or {},
                "options": {
                    "queue": options.get("queue"),
                    "priority": options.get("priority"),
                    "required_version": body.required_version,
                },
            }
        )
        saved = store.save(app, spec, origin="imported")
        db.merge(
            ScheduleMeta(name=name, origin="imported", created_by=who.name, updated_by=who.name)
        )
        audit.record(db, who, "schedule.import", name, after=_snapshot(saved))
        created.append(name)
    db.commit()
    return {"created": created, "skipped": skipped}
