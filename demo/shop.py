"""A pretend shop backend for the demo. Nothing here is special, it's the
kind of celery app percival is meant to sit next to: a few tasks and one
percival.init() call."""

import os
import random
import sys
import time

from celery import Celery
from celery.schedules import crontab

import percival
from percival import once_per
from percival.naming import Headers

REDIS = os.environ.get("REDIS_URL", "redis://redis:6379/0")
VERSION = os.environ.get("GIT_SHA", "unknown")

app = Celery("shop", broker=REDIS)
app.conf.redbeat_redis_url = REDIS
app.conf.timezone = "UTC"
# no result backend here, and this stops beat adding celery.backend_cleanup
app.conf.result_expires = None
# short bounce so a blocked task shows up on the new worker within seconds
percival.init(app, redis_url=REDIS, code_version=VERSION, requeue_delay=2)


@app.task
def hello(name):
    """Says hi. The two workers say it differently, so you can tell who ran it."""
    if VERSION == "a1b2c3d":
        return f"hello {name}"  # the old wording
    return f"hi {name}, from {VERSION}"


@app.task
@once_per(key=lambda user_id: user_id, window="2m")
def send_digest(user_id):
    """At most one digest per user per 2 minutes, however often it's triggered."""
    time.sleep(0.5)
    return f"digest sent to user {user_id}"


@app.task
def sync_inventory(warehouse, api_token):
    """Talks to a flaky supplier API. Fails about a third of the time."""
    time.sleep(random.uniform(0.2, 1.5))
    if random.random() < 0.35:
        raise ConnectionError(f"supplier api timed out for {warehouse}")
    return {"warehouse": warehouse, "updated": random.randint(10, 400)}


@app.task
def cleanup_carts(days=7):
    """Deletes abandoned carts older than ``days``."""
    return f"removed {random.randint(0, 50)} carts"


@app.task
def weekly_report():
    """Monday and Thursday report for the ops team, 9:00 India time."""
    return "report sent"


NEW = "e4f5a6b"

# what the demo starts with. in a real project these would come from your
# beat_schedule via `percival import`, or be created in the panel.
SCHEDULES = {
    "say-hello": {
        "task": "shop.hello",
        "schedule": 20.0,
        "args": ["there"],
        "options": {"headers": {Headers.REQUIRED_VERSION: NEW}},
    },
    "digest-user-42": {
        "task": "shop.send_digest",
        "schedule": 30.0,
        "args": [42],
        "options": {"headers": {Headers.REQUIRED_VERSION: NEW}},
    },
    "sync-inventory": {
        "task": "shop.sync_inventory",
        "schedule": 60.0,
        "kwargs": {"warehouse": "berlin-2", "api_token": "sk_live_not_a_real_token"},
        "options": {"headers": {Headers.REQUIRED_VERSION: NEW}},
    },
    "weekly-report": {
        "task": "shop.weekly_report",
        "schedule": crontab(minute=0, hour=9, day_of_week="mon,thu"),
        "options": {
            "headers": {Headers.REQUIRED_VERSION: NEW, Headers.TIMEZONE: "Asia/Kolkata"}
        },
    },
    # no version gate on purpose, the panel flags it
    "nightly-cleanup": {
        "task": "shop.cleanup_carts",
        "schedule": crontab(minute=0, hour=2),
        "kwargs": {"days": 7},
    },
}


def seed():
    """Writes SCHEDULES to redbeat, but only the ones that don't exist yet, so
    edits made in the panel survive a `docker compose up` again."""
    from percival import importer

    app.conf.beat_schedule = SCHEDULES
    planned = importer.plan(app)
    fresh = [p for p in planned if p.action == importer.CREATE]
    importer.apply(app, fresh)
    print(f"seeded {len(fresh)} schedules, {len(planned) - len(fresh)} were already there")


if __name__ == "__main__" and sys.argv[1:] == ["seed"]:
    seed()
