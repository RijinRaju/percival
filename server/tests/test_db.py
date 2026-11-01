from datetime import datetime, timedelta, timezone

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from percival_server.db import make_engine, make_sessionmaker, migrate
from percival_server.models import Base, Run


def test_migrations_match_models(config):
    engine = make_engine(config.database_url)
    migrate(engine)

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], "models changed without a migration, run alembic revision --autogenerate"


def test_migrate_twice_is_fine(config):
    engine = make_engine(config.database_url)
    migrate(engine)
    migrate(engine)
    assert "runs" in inspect(engine).get_table_names()


def test_datetimes_come_back_as_utc(config):
    engine = make_engine(config.database_url)
    migrate(engine)
    db = make_sessionmaker(engine)()

    ist = timezone(timedelta(hours=5, minutes=30))
    db.add(Run(task="t", status="success", ts=datetime(2026, 1, 1, 9, 0, tzinfo=ist)))
    db.commit()

    run = db.query(Run).one()
    assert run.ts == datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc)
    assert run.ts.tzinfo is not None
