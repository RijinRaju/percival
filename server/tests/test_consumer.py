import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from percival_server.connections import ConnectionSettings
from percival_server.consumer import EventConsumer, apply_events, cleanup
from percival_server.live import expected_version, queue_coverage, version_summary
from percival_server.models import Run, WorkerSeen


@pytest.fixture
def configured(app):
    with app.state.sessionmaker() as db:
        app.state.connections.save(
            db, ConnectionSettings(broker_url="memory://", redis_url="redis://r/0")
        )
        db.commit()
    return app


def ev(status, **kw):
    base = {
        "status": status,
        "task_id": "t1",
        "task": "proj.send",
        "worker": "w1",
        "code_version": "v2",
        "ts": time.time(),
    }
    return {**base, **kw}


def runs(app):
    with app.state.sessionmaker() as db:
        return list(db.scalars(select(Run).order_by(Run.id)))


def test_started_then_success_is_one_row(configured):
    t0 = time.time()
    with configured.state.sessionmaker() as db:
        apply_events(db, [ev("started", started_at=t0, args=[1])])
        apply_events(db, [ev("success", started_at=t0, finished_at=t0 + 2, duration=2.0)])
        db.commit()

    (row,) = runs(configured)
    assert row.status == "success"
    assert row.duration == 2.0
    assert row.args == [1]


def test_blocked_then_success_elsewhere_are_two_rows(configured):
    with configured.state.sessionmaker() as db:
        apply_events(
            db,
            [
                ev("blocked_stale_worker", worker="old", code_version="v1", requeued=True),
                ev("started", worker="new"),
                ev("success", worker="new"),
            ],
        )
        db.commit()

    blocked, ok = runs(configured)
    assert blocked.status == "blocked_stale_worker"
    assert blocked.extra == {"requeued": True}
    assert ok.status == "success" and ok.worker == "new"


def test_consumer_reads_acks_and_snapshots_workers(configured):
    conns = configured.state.connections
    client = conns.redis()
    client.xadd(conns.keys.events, {"data": json.dumps(ev("started"))})
    client.xadd(conns.keys.events, {"data": json.dumps(ev("failure", exc_type="ValueError"))})
    client.set(
        conns.keys.worker("w1"),
        json.dumps({"hostname": "w1", "code_version": "v2", "queues": ["celery"], "pid": 1}),
    )

    consumer = EventConsumer(conns, configured.state.sessionmaker)
    assert consumer.step(block_ms=10) == 2
    # acked, so nothing comes back
    assert consumer.step(block_ms=10) == 0

    (row,) = runs(configured)
    assert row.status == "failure" and row.exc_type == "ValueError"
    with configured.state.sessionmaker() as db:
        assert db.get(WorkerSeen, "w1").code_version == "v2"


def test_cleanup_respects_retention(configured):
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with configured.state.sessionmaker() as db:
        db.add(Run(task="a", status="success", ts=now - timedelta(days=40)))
        db.add(Run(task="b", status="success", ts=now - timedelta(days=5)))
        db.commit()
        assert cleanup(db, 30, now=now) == 1
        db.commit()
    assert [r.task for r in runs(configured)] == ["b"]


def w(host, version, started, queues=("celery",)):
    return {
        "hostname": host,
        "code_version": version,
        "queues": list(queues),
        "started_at": datetime(2026, 1, 1, started, tzinfo=timezone.utc),
        "alive": True,
    }


def test_version_summary_flags_the_old_ones():
    workers = [w("a", "v1", 1), w("b", "v1", 2), w("c", "v2", 5)]
    summary = version_summary(workers)
    assert summary["current"] == "v2"
    assert summary["mismatch"] is True
    assert summary["versions"][0] == {"version": "v2", "count": 1, "workers": ["c"], "stale": False}
    assert summary["versions"][1]["stale"] is True

    assert version_summary([w("a", "v1", 1)])["mismatch"] is False


def test_version_summary_trusts_the_deploy_over_start_times():
    # the old worker restarted last, which used to make it look current
    workers = [w("new", "v2", 1), w("old", "v1", 5)]
    assert version_summary(workers)["current"] == "v1"
    summary = version_summary(workers, expected="v2")
    assert summary["current"] == "v2"
    assert [v["version"] for v in summary["versions"] if v["stale"]] == ["v1"]
    # nobody runs the expected version yet: fall back to the guess
    assert version_summary(workers, expected="v3")["current"] == "v1"


def test_expected_version():
    assert expected_version(["v2", "v2", None, "v1"], {"code_version": "v9"}) == "v2"
    assert expected_version([None], {"code_version": "v9"}) == "v9"
    assert expected_version([], None) is None


def test_queue_coverage():
    workers = [w("a", "v1", 1), w("b", "v2", 2), w("c", "v2", 3, queues=("emails",))]
    assert queue_coverage(workers, None, "v2") == {
        "queue": "celery",
        "consumers": 2,
        "matching": 1,
        "stale": 1,
    }
    assert queue_coverage(workers, "emails", "v1")["matching"] == 0
