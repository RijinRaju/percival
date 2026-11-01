from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from percival_server import __version__
from percival_server.api import accounts, auth, cluster, history, schedules, setup
from percival_server.api.auth import LoginLimits
from percival_server.auth.deps import Principal, require_user
from percival_server.config import ServerConfig
from percival_server.connections import Connections, NotConfigured, RedisFactory
from percival_server.consumer import EventConsumer
from percival_server.crypto import SecretBox
from percival_server.db import make_engine, make_sessionmaker, migrate


def create_app(
    config: ServerConfig | None = None, *, redis_factory: RedisFactory | None = None
) -> FastAPI:
    config = config or ServerConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        consumer = None
        if config.run_consumer:
            consumer = EventConsumer(app.state.connections, app.state.sessionmaker)
            consumer.start()
        yield
        if consumer:
            consumer.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Percival",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.secrets = SecretBox(config.secret_key)
    app.state.login_limits = LoginLimits()

    engine = make_engine(config.database_url)
    migrate(engine)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    app.state.connections = Connections(app.state.secrets, redis_factory)
    with app.state.sessionmaker() as db:
        app.state.connections.load(db)

    api = APIRouter(prefix="/api/v1")
    api.include_router(setup.router)
    api.include_router(auth.router)
    api.include_router(accounts.router)
    api.include_router(schedules.router)
    api.include_router(history.router)
    api.include_router(cluster.router)
    app.include_router(api)

    # api docs, for logged-in users only (the schema lists every endpoint)
    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi(_: Principal = Depends(require_user)) -> dict[str, Any]:
        return app.openapi()

    @app.get("/api/docs", include_in_schema=False)
    def docs(_: Principal = Depends(require_user)) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Percival API")

    @app.exception_handler(NotConfigured)
    def _not_configured(request: Request, exc: NotConfigured) -> JSONResponse:
        return JSONResponse({"detail": "finish setup first"}, status_code=503)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        # no auth, so nothing in here that says anything about the setup
        return {"status": "ok", "version": __version__}

    return app
