from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from percival_server.models import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with(connection)
        return
    # only for `alembic revision --autogenerate` during development
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "sqlite://")
    with engine.begin() as conn:
        _run_with(conn)


def _run_with(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # sqlite can't ALTER much, batch mode works around it
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
