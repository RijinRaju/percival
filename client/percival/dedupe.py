"""``@once_per``: run a task at most once per key per time window.

    @app.task
    @once_per(key=lambda user_id, **kw: user_id, window="1d")
    def send_digest(user_id): ...

Backed by ``SET NX EX`` in redis. Fixed windows ("5m", "1h", "1d") are
aligned to the unix epoch, so "1d" means one UTC calendar day. For anything
else, like the recipient's local date, pass a callable as ``window`` and it
becomes the bucket.

If the task raises (including celery's Retry) the key is released again,
otherwise a failed attempt would block its own retry for the whole window.
"""

from __future__ import annotations

import functools
import logging
import re
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, TypeVar

from celery import Task, current_task
from celery.exceptions import Ignore

from percival import runtime
from percival.events import Status, build_event, emit

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$")

# ttl for callable windows when none is given, generous on purpose
DEFAULT_CALLABLE_TTL = 2 * 86400


def parse_window(window: str) -> int:
    match = _WINDOW_RE.match(window)
    if not match:
        raise ValueError(f"can't parse window {window!r}, use something like '5m', '1h', '1d'")
    seconds = int(match.group(1)) * _UNITS[match.group(2)]
    if seconds <= 0:
        raise ValueError("window has to be longer than zero")
    return seconds


def once_per(
    key: Callable[..., Any] | None = None,
    window: str | Callable[..., Any] = "1d",
    *,
    name: str | None = None,
    ttl: int | None = None,
    fail_open: bool | None = None,
    release_on_error: bool = True,
) -> Callable[[F], F]:
    # validate up front so a typo fails at import, not at 3am
    window_seconds = parse_window(window) if isinstance(window, str) else None
    if window_seconds is None and not callable(window):
        raise TypeError("window must be a string like '1d' or a callable")

    def decorator(fn: F) -> F:
        fallback_name = f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            rt = runtime.current()
            task = _running_task()
            task_name = name or (task.name if task is not None else fallback_name)

            # bind=True tasks get self first, the key function shouldn't see it
            user_args = args[1:] if args and isinstance(args[0], Task) else args
            key_value = str(key(*user_args, **kwargs)) if key is not None else "_"

            if window_seconds is not None:
                bucket = str(int(time.time() // window_seconds))
                expire = ttl or window_seconds
            else:
                bucket = str(window(*user_args, **kwargs))  # type: ignore[operator]
                expire = ttl or DEFAULT_CALLABLE_TTL

            redis_key = rt.keys.once(task_name, key_value, bucket)
            holder = getattr(getattr(task, "request", None), "id", None) or "direct"
            should_fail_open = rt.settings.dedupe_fail_open if fail_open is None else fail_open

            try:
                acquired = bool(rt.redis.get().set(redis_key, holder, nx=True, ex=expire))
            except Exception as exc:
                if should_fail_open:
                    log.warning(
                        "percival: once_per can't reach redis, running %s anyway",
                        task_name,
                        exc_info=True,
                    )
                    return fn(*args, **kwargs)
                log.error(
                    "percival: once_per can't reach redis, skipping %s", task_name, exc_info=True
                )
                _report(
                    rt,
                    Status.DEDUPE_UNAVAILABLE,
                    task,
                    task_name,
                    fn,
                    user_args,
                    kwargs,
                    redis_key,
                    exc_type=type(exc).__name__,
                    exc_message=str(exc),
                )
                return _skip(task)

            if not acquired:
                _report(
                    rt, Status.SKIPPED_DUPLICATE, task, task_name, fn, user_args, kwargs, redis_key
                )
                return _skip(task)

            try:
                return fn(*args, **kwargs)
            except BaseException:
                if release_on_error:
                    _release(rt, redis_key, holder)
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


def _running_task() -> Any:
    task = current_task
    if not task:
        return None
    request = getattr(task, "request", None)
    if request is None or getattr(request, "called_directly", True):
        return None
    return task


def _skip(task: Any) -> None:
    # inside a worker, Ignore keeps celery from also recording a "success"
    if task is not None:
        raise Ignore()
    return None


def _release(rt: runtime.Runtime, redis_key: str, holder: str) -> None:
    try:
        client = rt.redis.get()
        # only delete it if it's still ours
        current = client.get(redis_key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == holder:
            client.delete(redis_key)
    except Exception:
        log.warning("percival: could not release once_per key %s", redis_key, exc_info=True)


def _report(
    rt: runtime.Runtime,
    status: str,
    task: Any,
    task_name: str,
    fn: Callable[..., Any],
    args: Any,
    kwargs: Any,
    redis_key: str,
    **extra: Any,
) -> None:
    subject = task if task is not None else SimpleNamespace(name=task_name, request=None, run=fn)
    emit(
        rt,
        build_event(
            rt, status, task=subject, args=args, kwargs=kwargs, dedupe_key=redis_key, **extra
        ),
    )
