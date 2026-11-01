"""Stale-worker gate.

If a message carries a required code version and this worker runs something
else, the task body is not executed. This is the thing that would have stopped
an old worker from mailing everyone during a rollout.

Why wrap ``task.run`` instead of using ``task_prerun``: celery catches and logs
exceptions raised inside signal handlers, so a prerun hook can't stop a task.
We wrap at ``worker_init``, which fires after the app is finalized but before
the consumer (and prefork children) build their tracers, so the tracers pick
up the wrapped ``run``.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from celery import signals
from celery.exceptions import Ignore

from percival import runtime
from percival.events import Status, build_event, emit, get_header
from percival.naming import NAME, Headers
from percival.runtime import Runtime

log = logging.getLogger(__name__)

_UID = "percival.gate"
_MARK = f"__{NAME}_gated__"


def required_mismatch(request: Any, code_version: str) -> str | None:
    """The required version if this worker doesn't satisfy it, else None."""
    required = get_header(request, Headers.REQUIRED_VERSION)
    if not required:
        return None
    required = str(required)
    return None if required == code_version else required


def wrap_task(task: Any) -> bool:
    run = task.run
    if getattr(run, _MARK, False):
        return False

    @functools.wraps(run)
    def gated(*args: Any, **kwargs: Any) -> Any:
        rt = runtime.get_optional()
        if rt is not None:
            enforce(rt, task, args, kwargs)
        return run(*args, **kwargs)

    setattr(gated, _MARK, True)
    task.run = gated
    return True


def install(app: Any) -> int:
    wrapped = 0
    for name, task in app.tasks.items():
        if name.startswith("celery."):
            continue
        if wrap_task(task):
            wrapped += 1
    return wrapped


def enforce(rt: Runtime, task: Any, args: Any, kwargs: Any) -> None:
    request = task.request
    required = required_mismatch(request, rt.settings.code_version)
    if required is None:
        return

    bounces = int(get_header(request, Headers.REQUEUES) or 0)
    requeued = False
    if rt.settings.stale_action == "requeue":
        if bounces < rt.settings.max_requeues:
            requeued = _requeue(rt, task, request, args, kwargs, bounces + 1)
        else:
            log.error(
                "percival: %s[%s] bounced %d times between stale workers, dropping it",
                task.name,
                request.id,
                bounces,
            )

    log.warning(
        "percival: blocked %s[%s], message wants version %s but this worker runs %s",
        task.name,
        request.id,
        required,
        rt.settings.code_version,
    )
    emit(
        rt,
        build_event(
            rt,
            Status.BLOCKED_STALE_WORKER,
            task=task,
            args=args,
            kwargs=kwargs,
            requeued=requeued,
            bounces=bounces,
        ),
    )
    raise Ignore()


def _requeue(rt: Runtime, task: Any, request: Any, args: Any, kwargs: Any, bounces: int) -> bool:
    headers = {
        Headers.REQUIRED_VERSION: get_header(request, Headers.REQUIRED_VERSION),
        Headers.SCHEDULE: get_header(request, Headers.SCHEDULE),
        Headers.REQUEUES: bounces,
    }
    options: dict[str, Any] = {
        "task_id": request.id,
        "headers": {k: v for k, v in headers.items() if v is not None},
        "countdown": rt.settings.requeue_delay,
    }
    info = getattr(request, "delivery_info", None) or {}
    if info.get("exchange") is not None:
        options["exchange"] = info["exchange"]
    if info.get("routing_key"):
        options["routing_key"] = info["routing_key"]
    if info.get("priority") is not None:
        options["priority"] = info["priority"]
    try:
        task.apply_async(args=list(args), kwargs=dict(kwargs), **options)
        return True
    except Exception:
        log.exception("percival: could not requeue blocked task %s[%s]", task.name, request.id)
        return False


def on_worker_init(sender: Any = None, **_: Any) -> None:
    app = getattr(sender, "app", None)
    if app is None or runtime.get_optional() is None:
        return
    count = install(app)
    log.debug("percival: version gate installed on %d tasks", count)


def connect() -> None:
    signals.worker_init.connect(on_worker_init, weak=False, dispatch_uid=_UID + ".init")


def disconnect() -> None:
    signals.worker_init.disconnect(dispatch_uid=_UID + ".init")
