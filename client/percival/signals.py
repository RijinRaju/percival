"""Hooks celery's task signals and turns them into run events."""

from __future__ import annotations

import time
from typing import Any

from celery import signals

from percival import runtime
from percival.events import Status, build_event, emit
from percival.gate import required_mismatch

# task id -> start time, only for tasks running in this process
_started: dict[str, float] = {}

_UID = "percival.signals"

_HOOKS = (
    ("task_prerun", "on_prerun"),
    ("task_postrun", "on_postrun"),
    ("task_success", "on_success"),
    ("task_failure", "on_failure"),
    ("task_retry", "on_retry"),
    ("task_revoked", "on_revoked"),
)


def connect() -> None:
    # dispatch_uid keeps a second init() call from doubling every event
    for signal_name, handler_name in _HOOKS:
        getattr(signals, signal_name).connect(
            globals()[handler_name], weak=False, dispatch_uid=f"{_UID}.{signal_name}"
        )


def disconnect() -> None:
    for signal_name, _ in _HOOKS:
        getattr(signals, signal_name).disconnect(dispatch_uid=f"{_UID}.{signal_name}")
    _started.clear()


def started_at(task_id: str | None) -> float | None:
    return _started.get(task_id) if task_id else None


def on_prerun(
    sender: Any = None,
    task_id: str | None = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    **_: Any,
) -> None:
    rt = runtime.get_optional()
    if rt is None or task is None:
        return
    # the gate is about to refuse this one, it'll report blocked_stale_worker
    # itself and a "started" right before it would just be confusing
    if required_mismatch(task.request, rt.settings.code_version) is not None:
        return
    now = time.time()
    if task_id:
        _started[task_id] = now
    emit(rt, build_event(rt, Status.STARTED, task=task, args=args, kwargs=kwargs, started_at=now))


def on_postrun(sender: Any = None, task_id: str | None = None, **_: Any) -> None:
    # success/failure/retry already read the start time by now, this is just
    # cleanup (and covers Ignore/Reject which have no signal of their own)
    if task_id:
        _started.pop(task_id, None)


def on_success(sender: Any = None, result: Any = None, **_: Any) -> None:
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    task_id = getattr(sender.request, "id", None)
    emit(rt, build_event(rt, Status.SUCCESS, task=sender, started_at=started_at(task_id)))


def on_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: Any = None,
    kwargs: Any = None,
    einfo: Any = None,
    **_: Any,
) -> None:
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    emit(
        rt,
        build_event(
            rt,
            Status.FAILURE,
            task=sender,
            args=args,
            kwargs=kwargs,
            started_at=started_at(task_id),
            **_exception_fields(rt, exception, einfo),
        ),
    )


def on_retry(
    sender: Any = None, request: Any = None, reason: Any = None, einfo: Any = None, **_: Any
) -> None:
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    exc = reason if isinstance(reason, BaseException) else None
    fields = _exception_fields(rt, exc, einfo)
    if exc is None and reason is not None:
        fields["exc_message"] = str(reason)
    emit(
        rt,
        build_event(
            rt,
            Status.RETRY,
            task=sender,
            request=request,
            started_at=started_at(getattr(request, "id", None)),
            **fields,
        ),
    )


def on_revoked(
    sender: Any = None,
    request: Any = None,
    terminated: bool = False,
    signum: Any = None,
    expired: bool = False,
    **_: Any,
) -> None:
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    task_id = getattr(request, "id", None)
    emit(
        rt,
        build_event(
            rt,
            Status.REVOKED,
            task=sender,
            request=request,
            started_at=started_at(task_id),
            terminated=bool(terminated),
            expired=bool(expired),
        ),
    )
    if task_id:
        _started.pop(task_id, None)


def _exception_fields(rt: runtime.Runtime, exc: BaseException | None, einfo: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if exc is not None:
        fields["exc_type"] = type(exc).__name__
        fields["exc_message"] = str(exc)[: rt.settings.max_value_chars]
    if einfo is not None:
        tb = str(getattr(einfo, "traceback", "") or einfo)
        limit = rt.settings.max_traceback_chars
        # keep the tail, that's where the actual error is
        fields["traceback"] = tb if len(tb) <= limit else "...\n" + tb[-limit:]
    return fields
