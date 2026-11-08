"""Who is making this request, and are they allowed to.

Two ways in:
- browser: session cookie, plus an X-CSRF-Token header on anything that
  changes state (the token comes from /auth/me)
- scripts: ``Authorization: Bearer perc_...`` with read/write scopes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from percival.naming import NAME
from percival_server.auth.security import hash_token, same
from percival_server.db import get_db
from percival_server.models import ApiToken, User
from percival_server.models import Session as UserSession

SESSION_COOKIE = f"{NAME}_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

READ = "read"
WRITE = "write"
ALL_SCOPES = (READ, WRITE)

Source = Literal["ui", "api"]


@dataclass
class Principal:
    name: str
    kind: Literal["user", "token"]
    source: Source
    user_id: int | None = None
    token_id: int | None = None
    scopes: set[str] = field(default_factory=set)
    csrf_token: str | None = None

    def can(self, scope: str) -> bool:
        return scope in self.scopes


def _unauthorized(detail: str = "not logged in") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


def _from_token(request: Request, db: Session, raw: str) -> Principal:
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        raise _unauthorized("invalid or revoked token")

    now = datetime.now(timezone.utc)
    # don't write on every request, once a minute is plenty for "last used"
    if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
        token.last_used_at = now
        db.commit()

    return Principal(
        name=token.name,
        kind="token",
        source="api",
        token_id=token.id,
        scopes=token.scope_set,
    )


def _from_session(request: Request, db: Session, raw: str) -> Principal:
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw)))
    if sess is None or sess.expires_at <= datetime.now(timezone.utc):
        raise _unauthorized("session expired")
    user = db.get(User, sess.user_id)
    if user is None:
        raise _unauthorized()

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not same(sent, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or bad CSRF token")

    # every user is an admin in v1, roles come later
    return Principal(
        name=user.username,
        kind="user",
        source="ui",
        user_id=user.id,
        scopes=set(ALL_SCOPES),
        csrf_token=sess.csrf_token,
    )


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return _from_token(request, db, auth[7:].strip())
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _from_session(request, db, cookie)
    raise _unauthorized()


def require_read(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.can(READ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token lacks the read scope")
    return principal


def require_write(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.can(WRITE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token lacks the write scope")
    return principal


def require_user(principal: Principal = Depends(current_principal)) -> Principal:
    """Things only a logged-in person may do: managing users and tokens.
    A leaked token shouldn't be able to mint more tokens."""
    if principal.kind != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "log in to do this, tokens can't")
    return principal
