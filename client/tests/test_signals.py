import json

import pytest
from celery import Celery

from percival import signals
from percival.events import Status
from percival.redaction import REDACTED


@pytest.fixture
def app(rt):
    app = Celery("t", set_as_current=False)
    app.conf.task_always_eager = True
    signals.connect()
    yield app
    signals.disconnect()


def read_events(rt):
    entries = rt.redis.get().xrange(rt.keys.events)
    return [json.loads(fields[b"data"]) for _, fields in entries]


def test_success_run_records_start_and_finish(app, rt):
    @app.task
    def add(x, y):
        return x + y

    add.apply(args=(1, 2))
    events = read_events(rt)

    assert [e["status"] for e in events] == [Status.STARTED, Status.SUCCESS]
    done = events[-1]
    assert done["task"] == add.name
    assert done["args"] == [1, 2]
    assert done["code_version"] == "v1"
    assert done["duration"] >= 0


def test_failure_keeps_traceback_and_hides_secrets(app, rt):
    @app.task
    def login(username, password):
        raise ValueError("nope")

    login.apply(args=("bob", "hunter2"))
    failed = read_events(rt)[-1]

    assert failed["status"] == Status.FAILURE
    assert failed["exc_type"] == "ValueError"
    assert failed["exc_message"] == "nope"
    assert "ValueError" in failed["traceback"]
    assert failed["args"] == ["bob", REDACTED]
    assert "hunter2" not in json.dumps(failed)


def test_capture_args_off(app, rt):
    rt.settings = rt.settings.with_(capture_args=False)

    @app.task
    def ping(x):
        return x

    ping.apply(args=(1,))
    assert all("args" not in e for e in read_events(rt))


def test_connecting_twice_does_not_duplicate(app, rt):
    signals.connect()

    @app.task
    def noop():
        return None

    noop.apply()
    assert len(read_events(rt)) == 2


def test_redis_down_does_not_break_the_task(app, rt):
    class Broken:
        def xadd(self, *a, **kw):
            raise ConnectionError("redis is gone")

    rt.redis.get = lambda: Broken()

    @app.task
    def still_works():
        return "ok"

    assert still_works.apply().get() == "ok"
