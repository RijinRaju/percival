from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import fakeredis
from celery import Celery
from celery.schedules import crontab, schedule

from percival.beat import Entry, apply_zone
from percival.naming import Headers
from percival.schedules import describe, next_runs, zoned_crontab

UTC = timezone.utc
KOLKATA = ZoneInfo("Asia/Kolkata")
LONDON = ZoneInfo("Europe/London")


def local(dt, zone):
    return dt.astimezone(zone).replace(tzinfo=None)


def test_next_runs_respects_schedule_zone():
    cron = zoned_crontab(minute="0", hour="9", timezone="Asia/Kolkata")
    now = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)  # 05:30 in Kolkata

    runs = next_runs(cron, 3, now=now)

    assert [local(r, KOLKATA) for r in runs] == [
        datetime(2026, 11, 2, 9, 0),
        datetime(2026, 11, 3, 9, 0),
        datetime(2026, 11, 4, 9, 0),
    ]
    assert runs[0] == datetime(2026, 11, 2, 3, 30, tzinfo=UTC)


def test_wall_clock_survives_dst():
    # London leaves BST on 2026-10-25, 9:00 local should stay 9:00
    cron = zoned_crontab(minute="0", hour="9", timezone="Europe/London")
    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

    runs = next_runs(cron, 4, now=now)

    assert [local(r, LONDON).hour for r in runs] == [9, 9, 9, 9]
    assert runs[0].hour == 8  # BST, UTC+1
    assert runs[-1].hour == 9  # GMT


def test_weekday_is_decided_in_the_schedule_zone():
    # monday 01:00 in Kolkata is still sunday in UTC
    cron = zoned_crontab(minute="0", hour="1", day_of_week="mon", timezone="Asia/Kolkata")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    (first,) = next_runs(cron, 1, now=now)
    assert local(first, KOLKATA) == datetime(2026, 11, 2, 1, 0)
    assert first.astimezone(UTC).weekday() == 6


def test_interval_next_runs():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    runs = next_runs(schedule(run_every=timedelta(minutes=5)), 3, now=now)
    assert [r - now for r in runs] == [timedelta(minutes=5 * i) for i in (1, 2, 3)]


def test_zoned_crontab_describes_its_zone():
    cron = zoned_crontab(minute="*/5", timezone="UTC")
    assert describe(cron)["timezone"] == "UTC"
    assert "UTC" in repr(cron)


def test_apply_zone_only_touches_crontabs_with_the_header():
    headers = {"headers": {Headers.TIMEZONE: "Asia/Kolkata"}}
    assert isinstance(apply_zone(crontab(hour="9"), headers), zoned_crontab)
    assert type(apply_zone(crontab(hour="9"), {})) is crontab
    assert type(apply_zone(schedule(30), headers)) is schedule
    # a typo in the zone shouldn't take beat down
    bad = {"headers": {Headers.TIMEZONE: "Mars/Olympus"}}
    assert type(apply_zone(crontab(hour="9"), bad)) is crontab


def test_entry_round_trips_through_redis_with_its_zone():
    app = Celery("t", set_as_current=False)
    app.conf.redbeat_redis_url = "redis://fake/0"
    app.redbeat_redis = fakeredis.FakeRedis(decode_responses=True)

    Entry(
        "digest",
        "proj.send_digest",
        crontab(minute="0", hour="9"),
        options={"headers": {Headers.TIMEZONE: "Asia/Kolkata"}},
        app=app,
    ).save()

    loaded = Entry.from_key(Entry.generate_key(app, "digest"), app=app)
    assert isinstance(loaded.schedule, zoned_crontab)
    assert loaded.schedule.zone_name == "Asia/Kolkata"
