"""Server configuration, read from the environment once at startup.

Broker and redis can be given here (like you would with flower) or entered in
the setup wizard, in which case they're stored encrypted in the database.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from percival.naming import ENV_PREFIX

log = logging.getLogger(__name__)

PRODUCTION = "production"
DEVELOPMENT = "development"


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    return value if value not in (None, "") else default


def _flag(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerConfig:
    env: str
    secret_key: str
    database_url: str
    secure_cookies: bool
    static_dir: Path | None
    session_hours: int = 24 * 14
    run_consumer: bool = True
    # mcp write tools, used from M5 on
    mcp_write_enabled: bool = False
    mcp_require_approval: bool = True
    # when set, these win over whatever the wizard or /settings saved
    broker_url: str | None = None
    redis_url: str | None = None
    redbeat_key_prefix: str | None = None
    key_prefix: str | None = None
    # creates the first admin on startup, so a container needs no clicking
    admin_username: str | None = None
    admin_password: str | None = None

    @property
    def connections_from_env(self) -> bool:
        return self.broker_url is not None and self.redis_url is not None

    @property
    def is_production(self) -> bool:
        return self.env == PRODUCTION

    @classmethod
    def from_env(cls) -> ServerConfig:
        env = (_env("ENV", PRODUCTION) or PRODUCTION).lower()
        if env not in (PRODUCTION, DEVELOPMENT):
            raise ConfigError(f"{ENV_PREFIX}ENV must be {PRODUCTION} or {DEVELOPMENT}")

        data_dir = Path(_env("DATA_DIR", "./data") or "./data")
        secret = _env("SECRET_KEY")
        if not secret:
            if env == PRODUCTION:
                secret = _secret_from_file(data_dir)
            else:
                secret = secrets.token_urlsafe(48)
                log.warning(
                    "no %sSECRET_KEY, using a throwaway one. sessions and saved connection "
                    "settings won't survive a restart",
                    ENV_PREFIX,
                )
        elif len(secret) < 32:
            raise ConfigError(f"{ENV_PREFIX}SECRET_KEY should be at least 32 characters")

        database_url = _env("DATABASE_URL") or f"sqlite:///{data_dir / 'percival.db'}"
        static = _env("STATIC_DIR")
        static_dir = Path(static) if static else Path(__file__).parent / "static"
        conns = _connections_from_env()
        admin = _admin_from_env()

        return cls(
            env=env,
            secret_key=secret,
            database_url=database_url,
            # browsers drop Secure cookies on plain http://localhost in some
            # setups, so dev defaults to off
            secure_cookies=_flag("SECURE_COOKIES", env == PRODUCTION),
            static_dir=static_dir if static_dir.exists() else None,
            run_consumer=_flag("RUN_CONSUMER", True),
            mcp_write_enabled=_flag("MCP_WRITE_ENABLED", False),
            mcp_require_approval=_flag("MCP_REQUIRE_APPROVAL", True),
            broker_url=conns["broker_url"],
            redis_url=conns["redis_url"],
            redbeat_key_prefix=conns["redbeat_key_prefix"],
            key_prefix=conns["key_prefix"],
            admin_username=admin["admin_username"],
            admin_password=admin["admin_password"],
        )


def _secret_from_file(data_dir: Path) -> str:
    """No key given: keep a generated one next to the database.

    Less separation than a key from a secret store, but a fresh container then
    starts with zero flags and still survives restarts.
    """
    path = data_dir / "secret_key"
    try:
        if path.exists():
            secret = path.read_text(encoding="utf-8").strip()
            if len(secret) >= 32:
                return secret
        data_dir.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(48)
        path.write_text(secret, encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        raise ConfigError(
            f"{ENV_PREFIX}SECRET_KEY is not set and {path} can't be written ({exc}). "
            "Set the key, or make the data dir writable."
        ) from exc
    log.warning("no %sSECRET_KEY, generated one at %s. back it up with the data", ENV_PREFIX, path)
    return secret


def _connections_from_env() -> dict[str, str | None]:
    redis_url = _env("REDIS_URL")
    # CELERY_BROKER_URL too, so the env you already give workers and flower works here
    broker_url = _env("BROKER_URL") or os.environ.get("CELERY_BROKER_URL") or None
    if broker_url and not redis_url and broker_url.startswith(("redis://", "rediss://")):
        redis_url = broker_url
    if redis_url and not broker_url:
        broker_url = redis_url
    if broker_url and not redis_url:
        raise ConfigError(
            f"the broker isn't redis, so {ENV_PREFIX}REDIS_URL is needed too "
            "(it's where RedBeat keeps schedules and workers send events)"
        )
    return {
        "broker_url": broker_url,
        "redis_url": redis_url,
        "redbeat_key_prefix": _env("REDBEAT_KEY_PREFIX"),
        "key_prefix": _env("KEY_PREFIX"),
    }


def _admin_from_env() -> dict[str, str | None]:
    username, password = _env("ADMIN_USERNAME"), _env("ADMIN_PASSWORD")
    if password and not username:
        username = "admin"
    if username and not password:
        raise ConfigError(f"{ENV_PREFIX}ADMIN_USERNAME is set but {ENV_PREFIX}ADMIN_PASSWORD isn't")
    return {"admin_username": username, "admin_password": password}
