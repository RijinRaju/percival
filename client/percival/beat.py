"""RedBeat scheduler with per-schedule timezones and a heartbeat.

    celery -A proj beat -S percival.beat.Scheduler

It's stock RedBeat underneath. Entries stay in RedBeat's format, so plain
``redbeat.RedBeatScheduler`` still reads them (crontabs just fall back to the
app timezone). What this adds:

- crontabs with a ``percival_timezone`` header are evaluated in that zone
- a heartbeat key so the panel knows beat is alive, when it last ticked and
  who holds the lock
- a shorter default loop interval, so a newly created schedule is picked up
  in seconds instead of up to 5 minutes
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from typing import Any

from celery.schedules import crontab
from redbeat.schedulers import RedBeatScheduler, RedBeatSchedulerEntry

from percival import __version__, runtime
from percival.naming import Headers
from percival.schedules import zoned_crontab

log = logging.getLogger(__name__)

DEFAULT_MAX_INTERVAL = 15


def apply_zone(sched: Any, options: dict[str, Any] | None, app: Any = None) -> Any:
    headers = (options or {}).get("headers") or {}
    zone = headers.get(Headers.TIMEZONE)
    if not zone or not isinstance(sched, crontab) or isinstance(sched, zoned_crontab):
        return sched
    try:
        return zoned_crontab.from_crontab(sched, zone, app=app)
    except Exception:
        log.warning("percival: unknown timezone %r, using the app timezone", zone)
        return sched


class Entry(RedBeatSchedulerEntry):  # type: ignore[misc]
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.schedule = apply_zone(self.schedule, self.options, self.app)  # type: ignore[has-type]


class Scheduler(RedBeatScheduler):  # type: ignore[misc]
    Entry = Entry

    def __init__(self, app: Any, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("max_interval") is None and not app.conf.beat_max_loop_interval:
            kwargs["max_interval"] = DEFAULT_MAX_INTERVAL
        super().__init__(app, *args, **kwargs)
        self._started_at = time.time()

    def tick(self, *args: Any, **kwargs: Any) -> Any:
        result = super().tick(*args, **kwargs)
        self._heartbeat()
        return result

    def _heartbeat(self) -> None:
        rt = runtime.get_optional()
        if rt is None:
            return
        payload = {
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "scheduler": f"{type(self).__module__}.{type(self).__name__}",
            "started_at": self._started_at,
            "last_tick": time.time(),
            "max_interval": self.max_interval,
            "lock_key": self.lock_key,
            "code_version": rt.settings.code_version,
            "client_version": __version__,
        }
        try:
            rt.redis.get().set(
                rt.keys.beat,
                json.dumps(payload),
                ex=int(max(self.max_interval * 3, 60)),
            )
        except Exception:
            log.debug("percival: beat heartbeat failed", exc_info=True)
