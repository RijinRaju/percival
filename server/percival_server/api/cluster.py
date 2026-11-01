"""Workers, beat and registered tasks: the state of the user's Celery setup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from percival_server import live
from percival_server.api.history import run_summary
from percival_server.auth.deps import Principal, require_read
from percival_server.connections import Connections
from percival_server.db import get_db
from percival_server.models import Run, WorkerSeen
from percival_server.schedules import store

router = APIRouter(tags=["cluster"])

# dead workers stay listed this long after their last heartbeat
FORGET_AFTER = timedelta(hours=24)


def _conns(request: Request) -> Connections:
    conns: Connections = request.app.state.connections
    return conns


def all_workers(conns: Connections, db: Session) -> list[dict[str, Any]]:
    alive = live.read_workers(conns)
    seen = {w["hostname"] for w in alive}
    cutoff = datetime.now(timezone.utc) - FORGET_AFTER
    dead: list[dict[str, Any]] = [
        {
            "hostname": row.hostname,
            "code_version": row.code_version,
            "queues": row.queues or [],
            "pid": row.pid,
            "started_at": row.started_at,
            "last_seen": row.last_seen,
            "alive": False,
        }
        for row in db.scalars(select(WorkerSeen).where(WorkerSeen.last_seen >= cutoff))
        if row.hostname not in seen
    ]
    return sorted(alive, key=lambda w: w["hostname"]) + sorted(dead, key=lambda w: w["hostname"])


@router.get("/workers")
def workers(
    request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> dict[str, Any]:
    everyone = all_workers(_conns(request), db)
    for w in everyone:
        w.pop("tasks", None)  # can be long, /tasks has it
    return {"workers": everyone, "versions": live.version_summary(everyone)}


@router.get("/status")
def overview(
    request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> dict[str, Any]:
    """Everything the header bar needs in one request."""
    conns = _conns(request)
    workers = live.read_workers(conns)
    versions = live.version_summary(workers)

    affected = []
    if versions["mismatch"]:
        stale = {v["version"] for v in versions["versions"] if v["stale"]}
        for entry in store.list_entries(conns.celery()):
            data = store.serialize(entry, count=0)
            queue = data["queue"] or live.DEFAULT_QUEUE
            on_queue = [w for w in workers if queue in (w.get("queues") or [])]
            if any(w.get("code_version") in stale for w in on_queue):
                affected.append(
                    {
                        "name": entry.name,
                        "queue": queue,
                        "required_version": data["required_version"],
                        # without a required version a stale worker will just run it
                        "protected": bool(data["required_version"]),
                    }
                )

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    counts = dict(
        db.execute(
            select(Run.status, func.count()).where(Run.ts >= since).group_by(Run.status)
        ).all()
    )
    return {
        "beat": live.read_beat(conns),
        "lock": live.read_lock(conns),
        "workers_alive": len(workers),
        "versions": versions,
        "affected_schedules": affected,
        "runs_24h": counts,
    }


@router.get("/tasks")
def tasks(
    request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> list[dict[str, Any]]:
    conns = _conns(request)
    meta = live.read_task_meta(conns)
    workers = live.read_workers(conns)

    names = set(meta)
    hosts: dict[str, list[dict[str, Any]]] = {}
    for w in workers:
        for name in w.get("tasks") or []:
            names.add(name)
            hosts.setdefault(name, []).append(w)

    latest = select(func.max(Run.id)).where(Run.status != "running").group_by(Run.task)
    last = {r.task: r for r in db.scalars(select(Run).where(Run.id.in_(latest)))}
    scheduled: dict[str, int] = {}
    for entry in store.list_entries(conns.celery()):
        scheduled[entry.task] = scheduled.get(entry.task, 0) + 1

    out = []
    for name in sorted(names):
        m = meta.get(name, {})
        on = hosts.get(name, [])
        out.append(
            {
                "name": name,
                "module": m.get("module"),
                "signature": m.get("signature"),
                "doc": (m.get("doc") or "").split("\n\n")[0],
                "workers": sorted(w["hostname"] for w in on),
                "versions": sorted({w.get("code_version") or "unknown" for w in on}),
                "schedules": scheduled.get(name, 0),
                "last_run": (
                    {"status": last[name].status, "ts": last[name].ts} if name in last else None
                ),
            }
        )
    return out


@router.get("/tasks/{name}")
def task_detail(
    name: str, request: Request, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> dict[str, Any]:
    conns = _conns(request)
    meta = live.read_task_meta(conns).get(name)
    on = [w for w in live.read_workers(conns) if name in (w.get("tasks") or [])]
    if meta is None and not on:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no worker has published this task")
    runs = db.scalars(select(Run).where(Run.task == name).order_by(Run.id.desc()).limit(20))
    schedules = [e.name for e in store.list_entries(conns.celery()) if e.task == name]
    return {
        "name": name,
        "meta": meta,
        "workers": [{"hostname": w["hostname"], "code_version": w.get("code_version")} for w in on],
        "schedules": schedules,
        "recent_runs": [run_summary(r) for r in runs],
    }
