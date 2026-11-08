"""Panel metadata. Schedules themselves live in RedBeat (redis), only the
things RedBeat has no place for (notes, who changed what) are kept here."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite forgets the timezone, so always hand back aware UTC datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # first chars of the token, shown in the UI so people can tell them apart
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(100))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @property
    def scope_set(self) -> set[str]:
        return {s for s in self.scopes.split(",") if s}


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)


class ScheduleMeta(Base):
    __tablename__ = "schedule_meta"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(20), default="ui")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(150))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(150))


class Run(Base):
    """One execution attempt. A blocked attempt and the later successful one
    for the same task id are separate rows on purpose."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(255))
    schedule: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    worker: Mapped[str | None] = mapped_column(String(255))
    code_version: Mapped[str | None] = mapped_column(String(100))
    required_version: Mapped[str | None] = mapped_column(String(100))
    queue: Mapped[str | None] = mapped_column(String(200))
    args: Mapped[Any] = mapped_column(JSON, nullable=True)
    kwargs: Mapped[Any] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration: Mapped[float | None] = mapped_column(Float)
    exc_type: Mapped[str | None] = mapped_column(String(255))
    exc_message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[Any] = mapped_column(JSON, nullable=True)
    # when we last heard about this run, what the history is sorted by
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        Index("ix_runs_ts", "ts"),
        Index("ix_runs_task_ts", "task", "ts"),
        Index("ix_runs_schedule_ts", "schedule", "ts"),
        Index("ix_runs_status_ts", "status", "ts"),
    )


class WorkerSeen(Base):
    """Heartbeats expire in redis, this is how dead workers stay visible."""

    __tablename__ = "workers_seen"

    hostname: Mapped[str] = mapped_column(String(255), primary_key=True)
    code_version: Mapped[str | None] = mapped_column(String(100))
    queues: Mapped[Any] = mapped_column(JSON, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(150))
    actor_type: Mapped[str] = mapped_column(String(20))  # user | token | system
    source: Mapped[str] = mapped_column(String(10), index=True)  # ui | api
    action: Mapped[str] = mapped_column(String(50), index=True)
    target: Mapped[str | None] = mapped_column(String(255), index=True)
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
