from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from percival_server.auth.deps import SESSION_COOKIE
from percival_server.auth.security import hash_token, new_secret
from percival_server.config import ServerConfig
from percival_server.models import Session as UserSession
from percival_server.models import User


def start_session(db: Session, user: User, config: ServerConfig, response: Response) -> str:
    """Creates the session, sets the cookie, returns the csrf token."""
    raw, csrf = new_secret(), new_secret()
    now = datetime.now(timezone.utc)
    db.add(
        UserSession(
            token_hash=hash_token(raw),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=now + timedelta(hours=config.session_hours),
        )
    )
    user.last_login_at = now
    # tidy up while we're here
    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=config.session_hours * 3600,
        httponly=True,
        secure=config.secure_cookies,
        samesite="lax",
        path="/",
    )
    return csrf


def end_session(db: Session, request: Request, response: Response) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(raw)))
    response.delete_cookie(SESSION_COOKIE, path="/")
