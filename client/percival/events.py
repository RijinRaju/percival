"""Run events, pushed to a Redis Stream that the panel consumes."""

from __future__ import annotations

import json
import logging
import socket
import time
from typing import Any

from percival.naming import Headers
from percival.redaction import capture_args
from percival.runtime import Runtime

log = logging.getLogger(__name__)


class Status:
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    BLOCKED_STALE_WORKER = "blocked_stale_worker"
    # once_per could not reach redis and fail_open is off, so the run was skipped
    DEDUPE_UNAVAILABLE = "dedupe_unavailable"


def emit(rt: Runtime, event: dict[str, Any]) -> None:
    """Best effort. A broken redis must never take a task down with it."""
    try:
        payload = json.dumps(event, default=repr, separators=(",", ":"))
        rt.redis.get().xadd(
            rt.keys.events,
            {"data": payload},
            maxlen=rt.settings.events_maxlen,
            approximate=True,
        )
    except Exception:
        log.warning(
            "percival: could not record %s event for %s",
            event.get("status"),
            event.get("task_id"),
            exc_info=True,
        )


def get_header(request: Any, name: str) -> Any:
    """Custom headers end up in different places depending on the message
    protocol and celery version, so look in both."""
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if isinstance(headers, dict) and name in headers:
        return headers[name]
    return getattr(request, name, None)


def build_event(
    rt: Runtime,
    status: str,
    *,
    task: Any,
    request: Any = None,
    args: Any = None,
    kwargs: Any = None,
    started_at: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    settings = rt.settings
    now = time.time()
    if request is None:
        request = getattr(task, "request", None)

    event: dict[str, Any] = {
        "status": status,
        "task_id": getattr(request, "id", None),
        "task": getattr(task, "name", None),
        "schedule": get_header(request, Headers.SCHEDULE),
        "required_version": get_header(request, Headers.REQUIRED_VERSION),
        "worker": getattr(request, "hostname", None) or rt.hostname or socket.gethostname(),
        "code_version": settings.code_version,
        "retries": getattr(request, "retries", None),
        "queue": _queue_of(request),
        "ts": now,
    }
    if started_at is not None:
        event["started_at"] = started_at
        if status != Status.STARTED:
            event["finished_at"] = now
            event["duration"] = round(now - started_at, 6)

    if settings.capture_args:
        if args is None and kwargs is None and request is not None:
            args = getattr(request, "args", None)
            kwargs = getattr(request, "kwargs", None)
        event.update(
            capture_args(
                getattr(task, "run", None),
                args,
                kwargs,
                settings.redact_kwargs,
                settings.max_value_chars,
            )
        )

    event.update({k: v for k, v in extra.items() if v is not None})
    return event


def _queue_of(request: Any) -> str | None:
    info = getattr(request, "delivery_info", None)
    if isinstance(info, dict):
        queue = info.get("routing_key") or info.get("queue")
        return str(queue) if queue else None
    return None
