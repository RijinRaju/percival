from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal

from percival.naming import ENV_PREFIX, NAME

DEFAULT_REDACT = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
)

UNKNOWN_VERSION = "unknown"

StaleAction = Literal["requeue", "drop"]


def _env(name: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    return value if value else None


def _env_bool(name: str) -> bool | None:
    value = _env(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    redis_url: str = "redis://localhost:6379/0"
    code_version: str = UNKNOWN_VERSION
    key_prefix: str = NAME

    # what goes into run events
    capture_args: bool = True
    redact_kwargs: tuple[str, ...] = DEFAULT_REDACT
    max_value_chars: int = 2_000
    max_traceback_chars: int = 20_000

    # what the stale-worker gate does with a blocked message
    stale_action: StaleAction = "requeue"
    requeue_delay: float = 5.0
    max_requeues: int = 50

    heartbeat_interval: float = 30.0
    heartbeat_ttl: int = 90

    events_maxlen: int = 100_000
    publish_source: bool = True
    source_max_lines: int = 300

    # once_per behaviour when redis is down; False means skip the run
    dedupe_fail_open: bool = False

    @classmethod
    def build(cls, **overrides: Any) -> Settings:
        """Explicit arguments win, then PERCIVAL_* env vars, then defaults."""
        values: dict[str, Any] = {}

        env_map: dict[str, Any] = {
            "redis_url": _env("REDIS_URL"),
            "code_version": _env("CODE_VERSION"),
            "key_prefix": _env("KEY_PREFIX"),
            "capture_args": _env_bool("CAPTURE_ARGS"),
            "dedupe_fail_open": _env_bool("DEDUPE_FAIL_OPEN"),
            "stale_action": _env("STALE_ACTION"),
        }
        values.update({k: v for k, v in env_map.items() if v is not None})
        values.update({k: v for k, v in overrides.items() if v is not None})

        redact = values.get("redact_kwargs")
        if redact is not None and not isinstance(redact, tuple):
            values["redact_kwargs"] = _as_tuple(redact)

        settings = cls(**values)
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.stale_action not in ("requeue", "drop"):
            raise ValueError(f"stale_action must be 'requeue' or 'drop', got {self.stale_action!r}")
        if self.heartbeat_ttl <= self.heartbeat_interval:
            raise ValueError("heartbeat_ttl has to be larger than heartbeat_interval")

    def with_(self, **changes: Any) -> Settings:
        return replace(self, **changes)


def _as_tuple(items: Iterable[str] | str) -> tuple[str, ...]:
    if isinstance(items, str):
        return tuple(s.strip() for s in items.split(",") if s.strip())
    return tuple(items)
