"""Users, API tokens and connection settings. Logged-in users only."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from percival_server import audit
from percival_server.auth.deps import ALL_SCOPES, Principal, require_user
from percival_server.auth.security import (
    TOKEN_PREFIX,
    hash_password,
    hash_token,
    new_api_token,
    password_problem,
    verify_password,
)
from percival_server.connections import ConnectionSettings
from percival_server.db import get_db
from percival_server.models import ApiToken, User
from percival_server.models import Session as UserSession

router = APIRouter(tags=["accounts"])


# users


class UserOut(BaseModel):
    id: int
    username: str
    created_at: datetime
    last_login_at: datetime | None


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _check_password(password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: Principal = Depends(require_user)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: NewUser, db: Session = Depends(get_db), who: Principal = Depends(require_user)
) -> User:
    _check_password(body.password)
    username = body.username.strip()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "that username is taken")
    user = User(username=username, password_hash=hash_password(body.password))
    db.add(user)
    audit.record(db, who, "user.create", username)
    db.commit()
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, db: Session = Depends(get_db), who: Principal = Depends(require_user)
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    if user.id == who.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "you can't delete yourself")
    if (db.scalar(select(func.count()).select_from(User)) or 0) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "can't delete the last user")
    audit.record(db, who, "user.delete", user.username)
    db.delete(user)
    db.commit()


@router.post("/users/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange, db: Session = Depends(get_db), who: Principal = Depends(require_user)
) -> None:
    user = db.get(User, who.user_id)
    if user is None or not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "current password is wrong")
    _check_password(body.new_password)
    user.password_hash = hash_password(body.new_password)
    # log out everywhere else
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit.record(db, who, "user.password", user.username)
    db.commit()


# tokens


class TokenOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class NewToken(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


class CreatedToken(TokenOut):
    token: str


def _token_out(t: ApiToken) -> dict[str, object]:
    return {
        "id": t.id,
        "name": t.name,
        "prefix": t.prefix,
        "scopes": sorted(t.scope_set),
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "revoked_at": t.revoked_at,
    }


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(
    db: Session = Depends(get_db), _: Principal = Depends(require_user)
) -> list[dict[str, object]]:
    rows = db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc()))
    return [_token_out(t) for t in rows]


@router.post("/tokens", response_model=CreatedToken, status_code=status.HTTP_201_CREATED)
def create_token(
    body: NewToken, db: Session = Depends(get_db), who: Principal = Depends(require_user)
) -> dict[str, object]:
    scopes = set(body.scopes)
    if not scopes or not scopes <= set(ALL_SCOPES):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "scopes must be read and/or write"
        )
    if "write" in scopes:
        scopes.add("read")

    raw = new_api_token()
    token = ApiToken(
        name=body.name.strip(),
        prefix=raw[: len(TOKEN_PREFIX) + 6],
        token_hash=hash_token(raw),
        scopes=",".join(sorted(scopes)),
        created_by_id=who.user_id,
    )
    db.add(token)
    audit.record(db, who, "token.create", token.name, after={"scopes": sorted(scopes)})
    db.commit()
    # the only time the full token is ever returned
    return {**_token_out(token), "token": raw}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int, db: Session = Depends(get_db), who: Principal = Depends(require_user)
) -> None:
    token = db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such token")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        audit.record(db, who, "token.revoke", token.name)
        db.commit()


# connection settings


class ConnectionsIn(BaseModel):
    # leave a url out to keep the stored one, so the masked value never has
    # to round-trip through the browser
    broker_url: str | None = None
    redis_url: str | None = None
    redbeat_key_prefix: str | None = None
    key_prefix: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


@router.get("/settings/connections")
def get_connections(request: Request, _: Principal = Depends(require_user)) -> dict[str, object]:
    masked: dict[str, object] = request.app.state.connections.settings.masked()
    return masked


@router.put("/settings/connections")
def update_connections(
    body: ConnectionsIn,
    request: Request,
    db: Session = Depends(get_db),
    who: Principal = Depends(require_user),
) -> dict[str, object]:
    conns = request.app.state.connections
    current: ConnectionSettings = conns.settings
    changes = body.model_dump(exclude_none=True)
    updated = ConnectionSettings(**{**current.__dict__, **changes})
    conns.save(db, updated)
    audit.record(db, who, "settings.update", before=current.masked(), after=updated.masked())
    db.commit()
    return updated.masked()
