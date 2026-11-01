"""First-run wizard: admin account + where the broker and redis are.

Every route here is open until the first user exists, then setup is closed
for good and connection changes go through /settings.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from percival.naming import NAME
from percival_server import audit
from percival_server.auth.deps import ALL_SCOPES, Principal, current_principal
from percival_server.auth.security import hash_password, password_problem
from percival_server.auth.sessions import start_session
from percival_server.connections import ConnectionSettings, check_broker, check_redis
from percival_server.db import get_db
from percival_server.models import User

router = APIRouter(prefix="/setup", tags=["setup"])


def needs_setup(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) == 0


class SetupStatus(BaseModel):
    needs_setup: bool


class ConnectionTest(BaseModel):
    kind: Literal["broker", "redis"]
    url: str = Field(min_length=3, max_length=2000)


class TestResult(BaseModel):
    ok: bool
    message: str


class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str
    broker_url: str = Field(min_length=3, max_length=2000)
    redis_url: str = Field(min_length=3, max_length=2000)
    redbeat_key_prefix: str = Field(default="redbeat:", max_length=100)
    key_prefix: str = Field(default=NAME, max_length=100)


@router.get("", response_model=SetupStatus)
def status_(db: Session = Depends(get_db)) -> SetupStatus:
    return SetupStatus(needs_setup=needs_setup(db))


@router.post("/test", response_model=TestResult)
def test_connection(
    body: ConnectionTest, request: Request, db: Session = Depends(get_db)
) -> TestResult:
    # after setup this would be a way to probe the network, so it needs a login
    if not needs_setup(db):
        current_principal(request, db)
    if body.kind == "redis":
        ok, msg = check_redis(body.url, request.app.state.connections.redis_factory)
    else:
        ok, msg = check_broker(body.url)
    return TestResult(ok=ok, message=msg)


@router.post("", status_code=status.HTTP_201_CREATED)
def complete(
    body: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict[str, str]:
    if not needs_setup(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "setup is already done")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    user = User(username=body.username.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()

    settings = ConnectionSettings(
        broker_url=body.broker_url.strip(),
        redis_url=body.redis_url.strip(),
        redbeat_key_prefix=body.redbeat_key_prefix,
        key_prefix=body.key_prefix,
    )
    request.app.state.connections.save(db, settings)

    who = Principal(
        name=user.username, kind="user", source="ui", user_id=user.id, scopes=set(ALL_SCOPES)
    )
    audit.record(db, who, "setup.complete", after=settings.masked())
    csrf = start_session(db, user, request.app.state.config, response)
    db.commit()
    return {"username": user.username, "csrf_token": csrf}
