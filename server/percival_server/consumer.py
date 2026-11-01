"""Moves run events from the redis stream into the runs table.

Uses a consumer group, so events written while the panel is down are picked
up when it comes back, and two panel replicas don't double count.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.exceptions import ResponseError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from percival.naming import NAME
from percival_server import live
from percival_server.connections import Connections, NotConfigured
from percival_server.models import Run

log = logging.getLogger(__name__)

GROUP = f"{NAME}-panel"
RUNNING = "running"
STARTED = "started"

_RUN_FIELDS = (
    "task_id",
    "task",
    "schedule",
    "worker",
    "code_version",
    "required_version",
    "queue",
    "args",
    "kwargs",
    "exc_type",
    "exc_message",
    "traceback",
    "retries",
)
_EXTRA_FIELDS = ("requeued", "bounces", "dedupe_key", "terminated", "expired")


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def apply_events(db: Session, events: list[dict[str, Any]]) -> int:
    """Turn events into run rows. A "started" opens a row, the outcome from the
    same worker closes it. Outcomes without a start (blocked, revoked before
    running) get a row of their own."""
    written = 0
    for event in events:
        status = event.get("status")
        task = event.get("task")
        if not status or not task:
            continue

        fields = {k: event.get(k) for k in _RUN_FIELDS if event.get(k) is not None}
        extra = {k: event[k] for k in _EXTRA_FIELDS if k in event}
        ts = _dt(event.get("ts")) or datetime.now(timezone.utc)

        if status == STARTED:
            db.add(Run(status=RUNNING, started_at=_dt(event.get("started_at")), ts=ts, **fields))
            written += 1
            continue

        row = None
        if event.get("task_id"):
            row = db.scalar(
                select(Run)
                .where(
                    Run.task_id == event["task_id"],
                    Run.status == RUNNING,
                    Run.worker == event.get("worker"),
                )
                .order_by(Run.id.desc())
                .limit(1)
            )
        if row is None:
            row = Run(started_at=_dt(event.get("started_at")))
            db.add(row)

        for key, value in fields.items():
            setattr(row, key, value)
        row.status = status
        row.ts = ts
        row.finished_at = _dt(event.get("finished_at"))
        row.duration = event.get("duration")
        if extra:
            row.extra = {**(row.extra or {}), **extra}
        written += 1
    return written


def cleanup(db: Session, retention_days: int, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    result = db.execute(delete(Run).where(Run.ts < cutoff))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


class EventConsumer:
    batch = 500
    block_ms = 2000
    workers_every = 30.0
    cleanup_every = 3600.0

    def __init__(self, conns: Connections, sessions: sessionmaker[Session]) -> None:
        self.conns = conns
        self.sessions = sessions
        self.name = f"{socket.gethostname()}-{os.getpid()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._group_ready_for: str | None = None
        self._last_workers = 0.0
        self._last_cleanup = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="event-consumer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except NotConfigured:
                self._stop.wait(5)
            except Exception:
                log.exception("event consumer hiccup, retrying shortly")
                self._stop.wait(5)

    def _ensure_group(self) -> None:
        stream = self.conns.keys.events
        if self._group_ready_for == stream:
            return
        try:
            self.conns.redis().xgroup_create(stream, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready_for = stream

    def step(self, block_ms: int | None = None) -> int:
        """One round: read a batch, store it, ack it. Returns events handled."""
        self._ensure_group()
        client = self.conns.redis()
        stream = self.conns.keys.events
        response: Any = client.xreadgroup(
            GROUP,
            self.name,
            {stream: ">"},
            count=self.batch,
            block=self.block_ms if block_ms is None else block_ms,
        )
        handled = 0
        for _stream, entries in response or []:
            ids, events = [], []
            for entry_id, fields in entries:
                ids.append(entry_id)
                raw = fields.get(b"data") or fields.get("data")
                try:
                    events.append(json.loads(raw))
                except (TypeError, ValueError):
                    log.warning("skipping unreadable event %s", entry_id)
            with self.sessions() as db:
                handled += apply_events(db, events)
                db.commit()
            client.xack(stream, GROUP, *ids)

        self._housekeeping()
        return handled

    def _housekeeping(self) -> None:
        now = time.monotonic()
        if now - self._last_workers >= self.workers_every:
            self._last_workers = now
            workers = live.read_workers(self.conns)
            with self.sessions() as db:
                live.remember_workers(db, workers)
                db.commit()
        if now - self._last_cleanup >= self.cleanup_every:
            self._last_cleanup = now
            with self.sessions() as db:
                removed = cleanup(db, self.conns.settings.retention_days)
                db.commit()
            if removed:
                log.info("removed %d runs past retention", removed)
