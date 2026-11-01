from __future__ import annotations

from fastapi import FastAPI

from percival_server import __version__
from percival_server.config import ServerConfig
from percival_server.crypto import SecretBox
from percival_server.db import make_engine, make_sessionmaker, migrate


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or ServerConfig.from_env()

    app = FastAPI(
        title="Percival",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.secrets = SecretBox(config.secret_key)

    engine = make_engine(config.database_url)
    migrate(engine)
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        # no auth, so nothing in here that says anything about the setup
        return {"status": "ok", "version": __version__}

    return app
