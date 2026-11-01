import sys
import types
from datetime import timedelta

import fakeredis
import pytest
from celery import Celery
from celery.schedules import crontab, schedule
from redbeat.schedulers import RedBeatSchedulerEntry

from percival import cli, importer
from percival.naming import Headers


@pytest.fixture
def app():
    app = Celery("proj", set_as_current=False)
    app.conf.redbeat_redis_url = "redis://fake/0"
    app.redbeat_redis = fakeredis.FakeRedis(decode_responses=True)
    app.conf.beat_schedule = {
        "digest": {
            "task": "proj.send_digest",
            "schedule": crontab(minute="0", hour="9", day_of_week="mon,thu"),
            "kwargs": {"kind": "weekly"},
        },
        "cleanup": {"task": "proj.cleanup", "schedule": timedelta(minutes=5)},
        "ping": {"task": "proj.ping", "schedule": 30.0, "options": {"queue": "fast"}},
    }
    return app


def by_name(planned):
    return {p.name: p for p in planned}


def load(app, name):
    return RedBeatSchedulerEntry.from_key(RedBeatSchedulerEntry.generate_key(app, name), app=app)


def test_dry_run_plans_creates_and_writes_nothing(app):
    planned = importer.plan(app)

    assert {p.action for p in planned} == {importer.CREATE}
    assert app.redbeat_redis.keys("*") == []
    table = importer.render(planned)
    assert "3 new, 0 changed" in table
    assert "every 5 minutes" in table


def test_apply_writes_entries_redbeat_can_read(app):
    importer.apply(app, importer.plan(app, require_version="abc123"))

    digest = load(app, "digest")
    assert isinstance(digest.schedule, crontab)
    assert digest.schedule._orig_day_of_week == "mon,thu"
    assert digest.kwargs == {"kind": "weekly"}
    headers = digest.options["headers"]
    assert headers[Headers.SCHEDULE] == "digest"
    assert headers[Headers.ORIGIN] == "imported"
    assert headers[Headers.REQUIRED_VERSION] == "abc123"

    cleanup = load(app, "cleanup")
    assert isinstance(cleanup.schedule, schedule)
    assert cleanup.schedule.run_every == timedelta(minutes=5)
    assert load(app, "ping").options["queue"] == "fast"

    # new entries must not fire the moment beat picks them up
    assert digest.last_run_at is not None


def test_second_run_is_a_no_op_then_detects_changes(app):
    importer.apply(app, importer.plan(app))
    assert {p.action for p in importer.plan(app)} == {importer.SAME}

    app.conf.beat_schedule["cleanup"]["schedule"] = timedelta(minutes=10)
    app.conf.beat_schedule["ping"]["args"] = [1]
    planned = by_name(importer.plan(app))

    assert planned["cleanup"].action == importer.UPDATE
    assert planned["cleanup"].changes == ["schedule"]
    assert planned["ping"].changes == ["args"]
    assert planned["digest"].action == importer.SAME


def test_update_keeps_paused_state(app):
    importer.apply(app, importer.plan(app))
    entry = load(app, "cleanup")
    entry.enabled = False
    entry.save()

    app.conf.beat_schedule["cleanup"]["schedule"] = timedelta(minutes=10)
    importer.apply(app, importer.plan(app))

    assert load(app, "cleanup").enabled is False


def test_bad_entries_are_skipped_not_fatal(app):
    app.conf.beat_schedule["broken"] = {"schedule": 10}
    planned = by_name(importer.plan(app))
    assert planned["broken"].action == importer.SKIP
    assert importer.apply(app, list(planned.values())) == 3


def test_cli_dry_run_and_apply(app, monkeypatch, capsys):
    module = types.ModuleType("fakeproj_celery")
    module.app = app
    monkeypatch.setitem(sys.modules, "fakeproj_celery", module)

    assert cli.main(["import", "--app", "fakeproj_celery", "--only", "digest"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert app.redbeat_redis.keys("*") == []

    cli.main(["import", "--app", "fakeproj_celery:app", "--only", "digest", "--apply"])
    assert "wrote 1 entries" in capsys.readouterr().out
    assert load(app, "digest").task == "proj.send_digest"


def test_apply_takes_entries_out_of_redbeat_statics(app):
    # beat already ran once with beat_schedule in config, so redbeat remembers
    # those names as "statics" and would delete them once they leave config
    importer.plan(app)
    statics = app.redbeat_conf.statics_key
    app.redbeat_redis.sadd(statics, "digest", "cleanup", "ping", "not-ours")

    importer.apply(app, importer.plan(app))

    assert app.redbeat_redis.smembers(statics) == {"not-ours"}
