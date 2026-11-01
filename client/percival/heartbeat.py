"""Worker heartbeat: who is alive and which code version they are running.

Runs as a daemon thread in the worker's main process. Each beat rewrites one
key with a TTL, so a worker that dies without saying goodbye just ages out.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from celery import signals

from percival import __version__, runtime
from percival.runtime import Runtime

log = logging.getLogger(__name__)

_UID = "percival.heartbeat"


class Heartbeat:
    def __init__(
        self, rt: Runtime, hostname: str, queues: list[str], tasks: list[str] | None = None
    ) -> None:
        self.rt = rt
        self.hostname = hostname
        self.queues = queues
        self.tasks = tasks or []
        self.started_at = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "pid": os.getpid(),
            "code_version": self.rt.settings.code_version,
            "queues": self.queues,
            "tasks": self.tasks,
            "started_at": self.started_at,
            "last_seen": time.time(),
            "client_version": __version__,
        }

    def beat(self) -> None:
        try:
            self.rt.redis.get().set(
                self.rt.keys.worker(self.hostname),
                json.dumps(self.payload()),
                ex=self.rt.settings.heartbeat_ttl,
            )
        except Exception:
            log.warning("percival: heartbeat failed for %s", self.hostname, exc_info=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.beat()
            self._stop.wait(self.rt.settings.heartbeat_interval)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="percival-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            # clean exit, drop the key right away instead of waiting for the TTL
            self.rt.redis.get().delete(self.rt.keys.worker(self.hostname))
        except Exception:
            log.debug("percival: could not remove heartbeat key", exc_info=True)


_active: Heartbeat | None = None


def consumer_queues(consumer: Any) -> list[str]:
    task_consumer = getattr(consumer, "task_consumer", None)
    queues = getattr(task_consumer, "queues", None) or []
    return sorted({q.name for q in queues if getattr(q, "name", None)})


def user_task_names(app: Any) -> list[str]:
    return sorted(name for name in app.tasks if not name.startswith("celery."))


def on_worker_ready(sender: Any = None, **_: Any) -> None:
    global _active
    rt = runtime.get_optional()
    if rt is None or sender is None:
        return
    rt.hostname = sender.hostname
    rt.queues = consumer_queues(sender)
    if _active is not None:
        _active.stop()
    _active = Heartbeat(rt, sender.hostname, rt.queues, user_task_names(sender.app))
    _active.start()


def on_worker_shutdown(sender: Any = None, **_: Any) -> None:
    global _active
    if _active is not None:
        _active.stop()
        _active = None


def connect() -> None:
    signals.worker_ready.connect(on_worker_ready, weak=False, dispatch_uid=_UID + ".ready")
    signals.worker_shutdown.connect(on_worker_shutdown, weak=False, dispatch_uid=_UID + ".down")


def disconnect() -> None:
    signals.worker_ready.disconnect(dispatch_uid=_UID + ".ready")
    signals.worker_shutdown.disconnect(dispatch_uid=_UID + ".down")
    on_worker_shutdown()
