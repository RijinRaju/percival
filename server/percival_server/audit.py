"""Audit trail for every write. The caller commits, so the audit row and the
change it describes land in the same transaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from percival_server.auth.deps import Principal
from percival_server.models import AuditLog


def record(
    db: Session,
    who: Principal,
    action: str,
    target: str | None = None,
    *,
    before: Any = None,
    after: Any = None,
) -> AuditLog:
    entry = AuditLog(
        actor=who.name,
        actor_type=who.kind,
        source=who.source,
        action=action,
        target=target,
        before=before,
        after=after,
    )
    db.add(entry)
    return entry
