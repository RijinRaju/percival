"""End to end against a real (in-thread) worker with the memory transport.

The unit tests use eager mode, which skips the bit that matters most for the
gate: whether our wrapped run() is the one the worker's tracer calls.
"""

import json
import time

import fakeredis
import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker

import percival
from percival.events import Status
from percival.naming import Headers


@pytest.fixture
def worker_app():
    server = fakeredis.FakeServer()
    app = Celery("proj", broker="memory://", backend="cache+memory://", set_as_current=False)
    app.conf.worker_hijack_root_logger = False
    calls = []

    @app.task(shared=False)
    def send_email(user_id):
        calls.append(user_id)
        return "sent"

    rt = percival.init(
        app,
        redis_url="redis://fake/0",
        code_version="new",
        stale_action="drop",
        client_factory=lambda url: fakeredis.FakeRedis(server=server),
    )
    with start_worker(app, pool="solo", perform_ping_check=False, shutdown_timeout=10):
        yield app, send_email, calls, rt
    percival.shutdown()


def wait_for(rt, status, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for _, fields in rt.redis.get().xrange(rt.keys.events):
            event = json.loads(fields[b"data"])
            if event["status"] == status:
                return event
        time.sleep(0.05)
    raise AssertionError(f"no {status} event within {timeout}s")


def test_real_worker_runs_and_records(worker_app):
    _, send_email, calls, rt = worker_app
    send_email.apply_async(args=(1,), headers={Headers.REQUIRED_VERSION: "new"})

    event = wait_for(rt, Status.SUCCESS)
    assert calls == [1]
    assert event["required_version"] == "new"


def test_real_worker_blocks_stale_version(worker_app):
    _, send_email, calls, rt = worker_app
    send_email.apply_async(
        args=(2,), headers={Headers.REQUIRED_VERSION: "newer", Headers.SCHEDULE: "digest"}
    )

    event = wait_for(rt, Status.BLOCKED_STALE_WORKER)
    assert calls == []
    assert event["schedule"] == "digest"
    assert event["code_version"] == "new"
