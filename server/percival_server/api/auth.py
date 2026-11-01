from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from percival_server.auth.deps import Principal, current_principal
from percival_server.auth.ratelimit import FailureLimiter
from percival_server.auth.security import hash_password, needs_rehash, verify_password
from percival_server.auth.sessions import end_session, start_session
from percival_server.db import get_db
from percival_server.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginLimits:
    def __init__(self) -> None:
        self.by_ip = FailureLimiter(max_failures=20, window_seconds=15 * 60)
        self.by_username = FailureLimiter(max_failures=5, window_seconds=15 * 60)


# checked against when the username doesn't exist, so a wrong username takes
# as long as a wrong password and doesn't reveal which accounts exist
_DUMMY_HASH = hash_password("not-a-real-password-just-burning-time")


class LoginRequest(BaseModel):
    username: str
    password: str


class Me(BaseModel):
    username: str
    kind: str
    csrf_token: str | None
    scopes: list[str]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=Me)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> Me:
    limits: LoginLimits = request.app.state.login_limits
    ip, name = _client_ip(request), body.username.strip().lower()
    wait = max(limits.by_ip.retry_after(ip), limits.by_username.retry_after(name))
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed logins, try again later",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    user = db.scalar(select(User).where(User.username == body.username.strip()))
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not valid:
        limits.by_ip.fail(ip)
        limits.by_username.fail(name)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")

    limits.by_username.reset(name)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    csrf = start_session(db, user, request.app.state.config, response)
    db.commit()
    return Me(username=user.username, kind="user", csrf_token=csrf, scopes=["read", "write"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    end_session(db, request, response)
    db.commit()


@router.get("/me", response_model=Me)
def me(who: Principal = Depends(current_principal)) -> Me:
    return Me(
        username=who.name, kind=who.kind, csrf_token=who.csrf_token, scopes=sorted(who.scopes)
    )
