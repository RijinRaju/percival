"""The user's broker and redis, as entered in the setup wizard.

URLs often carry passwords, so they're stored encrypted and masked whenever
they're shown back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import redis
from celery import Celery
from sqlalchemy.orm import Session

from percival.naming import NAME, Keys
from percival_server.crypto import SecretBox
from percival_server.models import Setting

SECRET_FIELDS = {"broker_url", "redis_url"}
DEFAULT_RETENTION_DAYS = 30

# (url, decode_responses) -> client. redbeat wants decoded strings, we mostly want bytes
RedisFactory = Callable[[str, bool], "redis.Redis"]


@dataclass
class ConnectionSettings:
    broker_url: str
    redis_url: str
    redbeat_key_prefix: str = "redbeat:"
    key_prefix: str = NAME
    retention_days: int = DEFAULT_RETENTION_DAYS

    def masked(self) -> dict[str, Any]:
        data = asdict(self)
        data["broker_url"] = mask_url(self.broker_url)
        data["redis_url"] = mask_url(self.redis_url)
        return data


def mask_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.password is None:
        return url
    user = parts.username or ""
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{user}:****@{host}" if user else f":****@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _default_redis(url: str, decode: bool) -> redis.Redis:
    return redis.Redis.from_url(
        url, decode_responses=decode, socket_timeout=5, socket_connect_timeout=5
    )


class Connections:
    def __init__(self, box: SecretBox, redis_factory: RedisFactory | None = None) -> None:
        self._box = box
        self.redis_factory = redis_factory or _default_redis
        self._lock = threading.Lock()
        self._settings: ConnectionSettings | None = None
        self._redis: redis.Redis | None = None
        self._celery: Celery | None = None

    # storage

    def load(self, db: Session) -> ConnectionSettings | None:
        rows = {row.key: row for row in db.query(Setting).all()}
        if "broker_url" not in rows or "redis_url" not in rows:
            return None
        values: dict[str, Any] = {}
        for key, row in rows.items():
            values[key] = self._box.decrypt(row.value) if row.encrypted else row.value
        settings = ConnectionSettings(
            broker_url=values["broker_url"],
            redis_url=values["redis_url"],
            redbeat_key_prefix=values.get("redbeat_key_prefix", "redbeat:"),
            key_prefix=values.get("key_prefix", NAME),
            retention_days=int(values.get("retention_days", DEFAULT_RETENTION_DAYS)),
        )
        self._use(settings)
        return settings

    def save(self, db: Session, settings: ConnectionSettings) -> None:
        for key, value in asdict(settings).items():
            encrypted = key in SECRET_FIELDS
            stored = self._box.encrypt(str(value)) if encrypted else str(value)
            row = db.get(Setting, key)
            if row is None:
                db.add(Setting(key=key, value=stored, encrypted=encrypted))
            else:
                row.value, row.encrypted = stored, encrypted
        self._use(settings)

    def _use(self, settings: ConnectionSettings) -> None:
        with self._lock:
            if settings != self._settings:
                self._settings = settings
                self._redis = None
                self._celery = None

    # live handles

    @property
    def settings(self) -> ConnectionSettings:
        if self._settings is None:
            raise NotConfigured()
        return self._settings

    @property
    def configured(self) -> bool:
        return self._settings is not None

    @property
    def keys(self) -> Keys:
        return Keys(self.settings.key_prefix)

    def redis(self) -> redis.Redis:
        with self._lock:
            if self._redis is None:
                self._redis = self.redis_factory(self.settings.redis_url, False)
            return self._redis

    def celery(self) -> Celery:
        """A celery app that only knows the broker and redbeat, used to write
        schedules and to send 'run now' messages. It has no tasks of its own."""
        with self._lock:
            if self._celery is None:
                s = self.settings
                app = Celery(f"{NAME}-panel", broker=s.broker_url, set_as_current=False)
                app.conf.redbeat_redis_url = s.redis_url
                app.conf.redbeat_key_prefix = s.redbeat_key_prefix
                app.conf.broker_connection_retry_on_startup = False
                app.redbeat_redis = self.redis_factory(s.redis_url, True)
                # redbeat attaches its config lazily, and generate_key() blows up
                # without it if nothing else touched redbeat first
                from redbeat.schedulers import ensure_conf

                ensure_conf(app)
                self._celery = app
            return self._celery


class NotConfigured(RuntimeError):
    pass


def check_redis(url: str, factory: RedisFactory | None = None) -> tuple[bool, str]:
    try:
        client = (factory or _default_redis)(url, True)
        client.ping()
    except Exception as exc:
        return False, _short_error(exc)
    try:
        version = client.info("server").get("redis_version")
    except Exception:
        # some redis-compatible servers don't do INFO, the ping is what matters
        version = None
    return True, f"connected, redis {version}" if version else "connected"


def check_broker(url: str) -> tuple[bool, str]:
    from kombu import Connection

    try:
        with Connection(url, connect_timeout=4) as conn:
            conn.ensure_connection(max_retries=1, timeout=4)
            return True, f"connected via {conn.transport_cls}"
    except Exception as exc:
        return False, _short_error(exc)


def _short_error(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text if len(text) < 300 else text[:300] + "..."
