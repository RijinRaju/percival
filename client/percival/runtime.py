"""Process-wide state set up by ``percival.init``.

Celery's prefork pool forks after we've been initialised, and a redis client
created in the parent must not be reused in the child (shared sockets), so the
handle rebuilds its client whenever the pid changes.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import redis

from percival.config import Settings
from percival.naming import Keys

ClientFactory = Callable[[str], "redis.Redis"]


def _default_factory(url: str) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        socket_timeout=5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


class RedisHandle:
    def __init__(self, url: str, factory: ClientFactory | None = None) -> None:
        self.url = url
        self._factory = factory or _default_factory
        self._client: redis.Redis | None = None
        self._pid: int | None = None
        self._lock = threading.Lock()

    def get(self) -> redis.Redis:
        pid = os.getpid()
        if self._client is None or self._pid != pid:
            with self._lock:
                if self._client is None or self._pid != pid:
                    self._client = self._factory(self.url)
                    self._pid = pid
        return self._client


@dataclass
class Runtime:
    settings: Settings
    keys: Keys
    redis: RedisHandle
    # filled in once the worker tells us who it is
    hostname: str | None = None
    queues: list[str] = field(default_factory=list)


_current: Runtime | None = None


def configure(settings: Settings, client_factory: ClientFactory | None = None) -> Runtime:
    global _current
    _current = Runtime(
        settings=settings,
        keys=Keys(settings.key_prefix),
        redis=RedisHandle(settings.redis_url, client_factory),
    )
    return _current


def current() -> Runtime:
    if _current is None:
        raise RuntimeError("percival is not initialised, call percival.init(app) first")
    return _current


def get_optional() -> Runtime | None:
    return _current


def reset() -> None:
    global _current
    _current = None
