"""Server configuration, read from the environment once at startup.

Connection details for the user's broker and redis are *not* here, those are
entered in the setup wizard and stored encrypted in the database.
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

    @property
    def is_production(self) -> bool:
        return self.env == PRODUCTION

    @classmethod
    def from_env(cls) -> ServerConfig:
        env = (_env("ENV", PRODUCTION) or PRODUCTION).lower()
        if env not in (PRODUCTION, DEVELOPMENT):
            raise ConfigError(f"{ENV_PREFIX}ENV must be {PRODUCTION} or {DEVELOPMENT}")

        secret = _env("SECRET_KEY")
        if not secret:
            if env == PRODUCTION:
                raise ConfigError(
                    f"{ENV_PREFIX}SECRET_KEY is not set. It encrypts stored connection "
                    "secrets, so the server won't start without it in production. Generate "
                    'one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            secret = secrets.token_urlsafe(48)
            log.warning(
                "no %sSECRET_KEY, using a throwaway one. sessions and saved connection "
                "settings won't survive a restart",
                ENV_PREFIX,
            )
        elif len(secret) < 32:
            raise ConfigError(f"{ENV_PREFIX}SECRET_KEY should be at least 32 characters")

        data_dir = Path(_env("DATA_DIR", "./data") or "./data")
        database_url = _env("DATABASE_URL") or f"sqlite:///{data_dir / 'percival.db'}"
        static = _env("STATIC_DIR")
        static_dir = Path(static) if static else Path(__file__).parent / "static"

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
        )
