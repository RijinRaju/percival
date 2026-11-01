from datetime import datetime, timedelta, timezone

import pytest
from celery.schedules import crontab
from redbeat.schedulers import RedBeatSchedulerEntry

from percival.beat import Entry
from percival.naming import Headers
from percival.schedules import zoned_crontab
from percival_server.connections import ConnectionSettings
from percival_server.schedules import store
from percival_server.schedules.spec import InvalidSchedule, ScheduleIn


@pytest.fixture
def celery_app(app):
    conns = app.state.connections
    with app.state.sessionmaker() as db:
        conns.save(db, ConnectionSettings(broker_url="memory://", redis_url="redis://r/0"))
        db.commit()
    return conns.celery()


def spec(**overrides):
    base = {
        "name": "digest",
        "task": "proj.send_digest",
        "schedule": {"type": "crontab", "minute": "0", "hour": "9", "day_of_week": "mon,thu"},
        "timezone": "Asia/Kolkata",
        "kwargs": {"kind": "weekly"},
        "options": {"queue": "emails", "required_version": "abc123"},
    }
    return ScheduleIn.model_validate({**base, **overrides})


def test_saved_entry_is_readable_by_stock_redbeat(celery_app):
    store.save(celery_app, spec(), origin="ui")

    # plain redbeat (no percival.beat) still understands it
    stock = RedBeatSchedulerEntry.from_key(Entry.generate_key(celery_app, "digest"), app=celery_app)
    assert isinstance(stock.schedule, crontab)
    assert stock.options["queue"] == "emails"
    headers = stock.options["headers"]
    assert headers[Headers.SCHEDULE] == "digest"
    assert headers[Headers.REQUIRED_VERSION] == "abc123"
    assert headers[Headers.TIMEZONE] == "Asia/Kolkata"

    # and our entry class brings the timezone back
    ours = store.get(celery_app, "digest")
    assert isinstance(ours.schedule, zoned_crontab)


def test_list_and_serialize(celery_app):
    store.save(celery_app, spec(), origin="ui")
    store.save(
        celery_app,
        spec(name="ping", schedule={"type": "interval", "every": 30}, timezone="UTC"),
        origin="api",
    )

    entries = store.list_entries(celery_app)
    assert [e.name for e in entries] == ["digest", "ping"]

    now = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)  # a monday
    data = store.serialize(entries[0], now=now, count=2)
    assert data["human"] == "0 9 mon,thu * *"
    assert data["timezone"] == "Asia/Kolkata"
    assert data["required_version"] == "abc123"
    # 9:00 IST monday = 03:30 UTC
    assert data["next_runs"][0] == datetime(2026, 11, 2, 3, 30, tzinfo=timezone.utc)


def test_pause_resume_keeps_everything_else(celery_app):
    store.save(celery_app, spec(), origin="ui")
    store.set_enabled(celery_app, "digest", False)
    paused = store.get(celery_app, "digest")
    assert paused.enabled is False
    assert paused.kwargs == {"kind": "weekly"}
    assert store.serialize(paused)["next_runs"] == []

    store.set_enabled(celery_app, "digest", True)
    assert store.get(celery_app, "digest").enabled is True


def test_update_keeps_last_run_and_origin(celery_app):
    store.save(celery_app, spec(), origin="imported")
    before = store.get(celery_app, "digest")

    updated = spec(options={"queue": "emails"})  # required_version removed
    store.save(celery_app, updated, origin="ui", previous=before)

    after = store.get(celery_app, "digest")
    assert after.last_run_at == before.last_run_at
    assert after.options["headers"][Headers.ORIGIN] == "imported"
    assert Headers.REQUIRED_VERSION not in after.options["headers"]


def test_to_spec_round_trip(celery_app):
    original = spec()
    store.save(celery_app, original, origin="ui")
    back = store.to_spec(store.get(celery_app, "digest"))
    assert back.model_dump(exclude={"notes"}) == original.model_dump(exclude={"notes"})


def test_delete_and_not_found(celery_app):
    store.save(celery_app, spec(), origin="ui")
    store.delete(celery_app, "digest")
    assert not store.exists(celery_app, "digest")
    with pytest.raises(store.NotFound):
        store.get(celery_app, "digest")


def test_one_off_and_bad_input(celery_app):
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    store.save(celery_app, spec(name="once", schedule={"type": "once", "at": soon}), origin="ui")
    data = store.serialize(store.get(celery_app, "once"), count=3)
    assert data["schedule"]["type"] == "once"
    assert len(data["next_runs"]) == 1

    with pytest.raises(InvalidSchedule, match="past"):
        store.save(
            celery_app,
            spec(name="late", schedule={"type": "once", "at": "2020-01-01T00:00:00Z"}),
            origin="ui",
        )
    with pytest.raises(InvalidSchedule, match="cron"):
        store.save(celery_app, spec(schedule={"type": "crontab", "minute": "99"}), origin="ui")
    with pytest.raises(ValueError):
        spec(timezone="Mars/Base")
    with pytest.raises(ValueError):
        spec(name="a/b")
    assert spec(name="say hi").name == "say hi"
