import json

import pytest
from celery import Celery

from percival import gate, signals
from percival.events import Status
from percival.naming import Headers


@pytest.fixture
def app(rt):
    app = Celery("t", set_as_current=False)
    app.conf.task_always_eager = True
    signals.connect()
    yield app
    signals.disconnect()


def statuses(rt):
    entries = rt.redis.get().xrange(rt.keys.events)
    return [json.loads(f[b"data"]) for _, f in entries]


def make_task(app, calls):
    @app.task(shared=False)
    def send_email(user_id):
        calls.append(user_id)
        return "sent"

    gate.install(app)
    return send_email


def test_matching_version_runs(app, rt):
    calls = []
    send_email = make_task(app, calls)

    send_email.apply(args=(1,), headers={Headers.REQUIRED_VERSION: "v1"})

    assert calls == [1]
    assert [e["status"] for e in statuses(rt)] == [Status.STARTED, Status.SUCCESS]


def test_no_header_means_no_gate(app, rt):
    calls = []
    send_email = make_task(app, calls)
    send_email.apply(args=(1,))
    assert calls == [1]


def test_stale_worker_does_not_run_the_task(app, rt, monkeypatch):
    calls, requeued = [], []
    send_email = make_task(app, calls)
    monkeypatch.setattr(send_email, "apply_async", lambda **kw: requeued.append(kw))

    result = send_email.apply(
        args=(1,),
        headers={Headers.REQUIRED_VERSION: "v2", Headers.SCHEDULE: "digest"},
    )

    assert calls == []
    assert result.state == "IGNORED"
    events = statuses(rt)
    assert [e["status"] for e in events] == [Status.BLOCKED_STALE_WORKER]
    assert events[0]["required_version"] == "v2"
    assert events[0]["schedule"] == "digest"
    assert events[0]["requeued"] is True

    (sent,) = requeued
    assert sent["args"] == [1]
    assert sent["headers"][Headers.REQUEUES] == 1
    assert sent["headers"][Headers.SCHEDULE] == "digest"
    assert sent["task_id"] == result.id


def test_drop_mode_does_not_requeue(app, rt, monkeypatch):
    rt.settings = rt.settings.with_(stale_action="drop")
    calls, requeued = [], []
    send_email = make_task(app, calls)
    monkeypatch.setattr(send_email, "apply_async", lambda **kw: requeued.append(kw))

    send_email.apply(args=(1,), headers={Headers.REQUIRED_VERSION: "v2"})

    assert calls == [] and requeued == []
    assert statuses(rt)[0]["requeued"] is False


def test_gives_up_after_max_requeues(app, rt, monkeypatch):
    rt.settings = rt.settings.with_(max_requeues=3)
    calls, requeued = [], []
    send_email = make_task(app, calls)
    monkeypatch.setattr(send_email, "apply_async", lambda **kw: requeued.append(kw))

    send_email.apply(args=(1,), headers={Headers.REQUIRED_VERSION: "v2", Headers.REQUEUES: 3})

    assert requeued == []
    assert statuses(rt)[0]["bounces"] == 3


def test_install_is_idempotent(app, rt):
    calls = []
    send_email = make_task(app, calls)
    assert gate.install(app) == 0
    send_email.apply(args=(5,))
    assert calls == [5]


def test_signature_survives_wrapping(app, rt):
    import inspect

    send_email = make_task(app, [])
    assert str(inspect.signature(send_email.run)) == "(user_id)"
