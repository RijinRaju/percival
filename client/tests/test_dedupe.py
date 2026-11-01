import json

import pytest
from celery import Celery

from percival import signals
from percival.dedupe import once_per, parse_window
from percival.events import Status


@pytest.fixture
def app(rt):
    app = Celery("t", set_as_current=False)
    app.conf.task_always_eager = True
    signals.connect()
    yield app
    signals.disconnect()


def statuses(rt):
    entries = rt.redis.get().xrange(rt.keys.events)
    return [json.loads(f[b"data"])["status"] for _, f in entries]


def test_parse_window():
    assert parse_window("5m") == 300
    assert parse_window("1d") == 86400
    with pytest.raises(ValueError):
        parse_window("tomorrow")
    with pytest.raises(ValueError):
        parse_window("0h")


def test_bad_window_fails_at_decoration_time():
    with pytest.raises(ValueError):
        once_per(window="every day")


def test_second_dispatch_is_skipped(app, rt):
    sent = []

    @app.task(shared=False)
    @once_per(key=lambda user_id, **kw: user_id, window="1d")
    def send_digest(user_id):
        sent.append(user_id)

    first = send_digest.apply(args=(1,))
    second = send_digest.apply(args=(1,))
    other_user = send_digest.apply(args=(2,))

    assert sent == [1, 2]
    assert first.state == "SUCCESS"
    assert second.state == "IGNORED"
    assert other_user.state == "SUCCESS"
    assert statuses(rt).count(Status.SKIPPED_DUPLICATE) == 1
    # the skipped one must not also show up as a success
    assert statuses(rt).count(Status.SUCCESS) == 2


def test_callable_window_is_the_bucket(app, rt):
    sent = []
    today = {"value": "2026-11-01"}

    @app.task(shared=False)
    @once_per(key=lambda user_id: user_id, window=lambda user_id: today["value"])
    def remind(user_id):
        sent.append(today["value"])

    remind.apply(args=(1,))
    remind.apply(args=(1,))
    today["value"] = "2026-11-02"
    remind.apply(args=(1,))

    assert sent == ["2026-11-01", "2026-11-02"]


def test_failure_releases_the_key_so_retry_can_run(app, rt):
    attempts = []

    @app.task(shared=False)
    @once_per(key=lambda n: n, window="1h")
    def flaky(n):
        attempts.append(n)
        if len(attempts) == 1:
            raise RuntimeError("smtp down")

    flaky.apply(args=(1,))
    flaky.apply(args=(1,))

    assert attempts == [1, 1]


def test_bound_task_key_does_not_see_self(app, rt):
    seen = []

    @app.task(shared=False, bind=True)
    @once_per(key=lambda user_id: user_id)
    def bound(self, user_id):
        seen.append((self.name, user_id))

    bound.apply(args=(9,))
    bound.apply(args=(9,))
    assert len(seen) == 1


class _DownRedis:
    def set(self, *a, **kw):
        raise ConnectionError("redis down")

    def xadd(self, *a, **kw):
        pass


def test_redis_down_skips_by_default(app, rt):
    sent = []

    @app.task(shared=False)
    @once_per(key=lambda n: n)
    def send(n):
        sent.append(n)

    rt.redis.get = lambda: _DownRedis()
    assert send.apply(args=(1,)).state == "IGNORED"
    assert sent == []


def test_redis_down_fail_open(app, rt):
    sent = []

    @app.task(shared=False)
    @once_per(key=lambda n: n, fail_open=True)
    def send(n):
        sent.append(n)

    rt.redis.get = lambda: _DownRedis()
    send.apply(args=(1,))
    assert sent == [1]


def test_works_when_called_directly(rt):
    calls = []

    @once_per(key=lambda n: n)
    def plain(n):
        calls.append(n)
        return "done"

    assert plain(1) == "done"
    assert plain(1) is None
    assert calls == [1]
