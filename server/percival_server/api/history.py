"""Run history and the audit log. Both are append-mostly and can get big, so
they page with ``before_id`` (newest first) instead of offsets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from percival_server.auth.deps import Principal, require_read
from percival_server.db import get_db
from percival_server.models import AuditLog, Run

router = APIRouter(tags=["history"])

RUN_LIST_FIELDS = (
    "id",
    "task_id",
    "task",
    "schedule",
    "status",
    "worker",
    "code_version",
    "required_version",
    "queue",
    "args",
    "kwargs",
    "started_at",
    "finished_at",
    "duration",
    "exc_type",
    "exc_message",
    "retries",
    "ts",
)


def run_summary(run: Run) -> dict[str, Any]:
    return {f: getattr(run, f) for f in RUN_LIST_FIELDS}


def _page(query: Select[Any], model: Any, before_id: int | None, limit: int) -> Select[Any]:
    if before_id is not None:
        query = query.where(model.id < before_id)
    return query.order_by(model.id.desc()).limit(limit)


@router.get("/runs")
def list_runs(
    schedule: str | None = None,
    task: str | None = None,
    run_status: list[str] | None = Query(None, alias="status"),
    worker: str | None = None,
    since: datetime | None = Query(None, alias="from"),
    until: datetime | None = Query(None, alias="to"),
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
) -> dict[str, Any]:
    query = select(Run)
    if schedule:
        query = query.where(Run.schedule == schedule)
    if task:
        query = query.where(Run.task == task)
    if run_status:
        query = query.where(Run.status.in_(run_status))
    if worker:
        query = query.where(Run.worker == worker)
    if since:
        query = query.where(Run.ts >= since)
    if until:
        query = query.where(Run.ts < until)

    rows = list(db.scalars(_page(query, Run, before_id, limit)))
    return {
        "items": [run_summary(r) for r in rows],
        "next_before_id": rows[-1].id if len(rows) == limit else None,
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int, db: Session = Depends(get_db), _: Principal = Depends(require_read)
) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
    attempts = []
    if run.task_id:
        # the same message can show up more than once, e.g. blocked on a stale
        # worker and then run on a fresh one
        attempts = [
            run_summary(r)
            for r in db.scalars(select(Run).where(Run.task_id == run.task_id).order_by(Run.id))
        ]
    return {
        **run_summary(run),
        "traceback": run.traceback,
        "extra": run.extra,
        "attempts": attempts,
    }


@router.get("/audit-log")
def audit_log(
    action: str | None = None,
    actor: str | None = None,
    source: str | None = None,
    target: str | None = None,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_read),
) -> dict[str, Any]:
    query = select(AuditLog)
    if action:
        # "schedule" matches schedule.create, schedule.pause, ...
        query = query.where(AuditLog.action.startswith(action))
    if actor:
        query = query.where(AuditLog.actor == actor)
    if source:
        query = query.where(AuditLog.source == source)
    if target:
        query = query.where(AuditLog.target == target)
    rows = list(db.scalars(_page(query, AuditLog, before_id, limit)))
    return {
        "items": [
            {
                "id": r.id,
                "ts": r.ts,
                "actor": r.actor,
                "actor_type": r.actor_type,
                "source": r.source,
                "action": r.action,
                "target": r.target,
                "before": r.before,
                "after": r.after,
            }
            for r in rows
        ],
        "next_before_id": rows[-1].id if len(rows) == limit else None,
    }
