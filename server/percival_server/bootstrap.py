"""Startup steps driven by env vars, so a container can come up configured
without anyone clicking through the setup wizard."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from percival.naming import ENV_PREFIX
from percival_server import audit
from percival_server.auth.deps import ALL_SCOPES, Principal
from percival_server.auth.security import hash_password, password_problem
from percival_server.config import ConfigError, ServerConfig
from percival_server.connections import Connections
from percival_server.models import User

log = logging.getLogger(__name__)


def apply_env_connections(config: ServerConfig, conns: Connections) -> None:
    if not config.connections_from_env:
        return
    assert config.broker_url is not None and config.redis_url is not None
    settings = conns.use_env(
        config.broker_url,
        config.redis_url,
        redbeat_key_prefix=config.redbeat_key_prefix,
        key_prefix=config.key_prefix,
    )
    shown = settings.masked()
    log.info("connections from env: broker %s, redis %s", shown["broker_url"], shown["redis_url"])


def ensure_admin(config: ServerConfig, db: Session) -> None:
    """Creates the env admin if nobody exists yet. Never touches an existing
    user, changing the env password later does nothing on purpose."""
    if not config.admin_username or not config.admin_password:
        return
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        return
    problem = password_problem(config.admin_password)
    if problem:
        raise ConfigError(f"{ENV_PREFIX}ADMIN_PASSWORD: {problem}")

    user = User(username=config.admin_username, password_hash=hash_password(config.admin_password))
    db.add(user)
    db.flush()
    who = Principal(
        name=user.username, kind="user", source="api", user_id=user.id, scopes=set(ALL_SCOPES)
    )
    audit.record(db, who, "setup.env_admin", user.username)
    db.commit()
    log.info("created admin %r from %sADMIN_USERNAME", user.username, ENV_PREFIX)
