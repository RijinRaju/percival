import json
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from percival import metadata
from percival.schedules import describe, humanize


def make_app():
    app = Celery("proj", set_as_current=False)

    @app.task
    def send_digest(user_id: int, *, dry_run: bool = False):
        """Mail the weekly digest."""
        return user_id

    app.conf.beat_schedule = {
        "digest": {
            "task": send_digest.name,
            "schedule": crontab(minute="0", hour="9", day_of_week="mon,thu"),
            "kwargs": {"api_token": "abc"},
        },
        "cleanup": {"task": "proj.cleanup", "schedule": timedelta(minutes=5)},
    }
    return app, send_digest


def test_publish_writes_tasks_and_beat_schedule(rt):
    app, send_digest = make_app()
    metadata.publish(app, rt)
    client = rt.redis.get()

    meta = json.loads(client.hget(rt.keys.tasks, send_digest.name))
    assert meta["signature"] == "(user_id: int, *, dry_run: bool = False)"
    assert meta["doc"] == "Mail the weekly digest."
    assert "def send_digest" in meta["source"]
    assert meta["code_version"] == "v1"
    # celery's own tasks are noise
    assert not any(k.startswith(b"celery.") for k in client.hkeys(rt.keys.tasks))

    beat = json.loads(client.get(rt.keys.beat_schedule))
    assert beat["entries"]["digest"]["schedule"]["day_of_week"] == "mon,thu"
    assert beat["entries"]["digest"]["kwargs"] == {"api_token": "[redacted]"}
    assert beat["entries"]["cleanup"]["human"] == "every 5 minutes"


def test_source_can_be_turned_off(rt):
    rt.settings = rt.settings.with_(publish_source=False)
    app, send_digest = make_app()
    metadata.publish(app, rt)
    meta = json.loads(rt.redis.get().hget(rt.keys.tasks, send_digest.name))
    assert "source" not in meta


def test_describe_schedule_types():
    assert describe(30)["every"] == 30.0
    assert describe(crontab(minute="*/5"))["minute"] == "*/5"
    assert humanize(describe(timedelta(hours=1))) == "every 1 hour"
    assert humanize(describe(90)) == "every 90s"
