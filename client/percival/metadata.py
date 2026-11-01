"""Publishes read-only info about registered tasks so the panel can show them.

Nothing here is ever executed by the panel. Source is shown for reference only
and can be switched off with ``publish_source=False``.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from typing import Any

from celery import signals

from percival import runtime
from percival.redaction import scrub
from percival.runtime import Runtime
from percival.schedules import describe_beat_schedule

log = logging.getLogger(__name__)

_UID = "percival.metadata"


def task_metadata(task: Any, rt: Runtime) -> dict[str, Any]:
    func = inspect.unwrap(task.run)
    meta: dict[str, Any] = {
        "name": task.name,
        "module": getattr(func, "__module__", None) or type(task).__module__,
        "signature": _signature(task.run),
        "doc": inspect.getdoc(func) or inspect.getdoc(task) or "",
        "queue": getattr(task, "queue", None),
        "code_version": rt.settings.code_version,
        "hostname": rt.hostname,
        "published_at": time.time(),
    }
    if rt.settings.publish_source:
        meta["source"] = _source(func, task, rt.settings.source_max_lines)
    return meta


def _signature(func: Any) -> str | None:
    try:
        return str(inspect.signature(func))
    except (TypeError, ValueError):
        return None


def _source(func: Any, task: Any, max_lines: int) -> str | None:
    for target in (func, type(task)):
        try:
            lines = inspect.getsource(target).splitlines()
        except (OSError, TypeError):
            continue
        if len(lines) > max_lines:
            lines = [*lines[:max_lines], f"# ... {len(lines) - max_lines} more lines"]
        return "\n".join(lines)
    return None


def publish(app: Any, rt: Runtime) -> None:
    client = rt.redis.get()
    pipe = client.pipeline(transaction=False)
    count = 0
    for name, task in app.tasks.items():
        if name.startswith("celery."):
            continue
        try:
            pipe.hset(rt.keys.tasks, name, json.dumps(task_metadata(task, rt), default=repr))
            count += 1
        except Exception:
            log.warning("percival: skipping metadata for %s", name, exc_info=True)

    beat = describe_beat_schedule(app.conf.beat_schedule or {})
    # beat_schedule args can hold secrets just like task args can
    beat = scrub(beat, rt.settings.redact_kwargs, rt.settings.max_value_chars)
    pipe.set(
        rt.keys.beat_schedule,
        json.dumps(
            {
                "entries": beat,
                "timezone": str(app.conf.timezone or "UTC"),
                "code_version": rt.settings.code_version,
                "hostname": rt.hostname,
                "published_at": time.time(),
            },
            default=repr,
        ),
    )
    pipe.execute()
    log.debug("percival: published metadata for %d tasks", count)


def on_worker_ready(sender: Any = None, **_: Any) -> None:
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    try:
        publish(sender.app, rt)
    except Exception:
        log.warning("percival: could not publish task metadata", exc_info=True)


def connect() -> None:
    signals.worker_ready.connect(on_worker_ready, weak=False, dispatch_uid=_UID + ".ready")


def disconnect() -> None:
    signals.worker_ready.disconnect(dispatch_uid=_UID + ".ready")
