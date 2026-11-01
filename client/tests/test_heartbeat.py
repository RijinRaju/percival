import json
from types import SimpleNamespace

from percival import heartbeat
from percival.heartbeat import Heartbeat


def read(rt, hostname):
    raw = rt.redis.get().get(rt.keys.worker(hostname))
    return json.loads(raw) if raw else None


def test_beat_writes_payload_with_ttl(rt):
    hb = Heartbeat(rt, "w1@box", ["default"], ["app.send"])
    hb.beat()

    data = read(rt, "w1@box")
    assert data["code_version"] == "v1"
    assert data["queues"] == ["default"]
    assert data["tasks"] == ["app.send"]
    ttl = rt.redis.get().ttl(rt.keys.worker("w1@box"))
    assert 0 < ttl <= rt.settings.heartbeat_ttl


def test_stop_removes_key(rt):
    hb = Heartbeat(rt, "w2@box", [])
    hb.start()
    hb.stop()
    assert read(rt, "w2@box") is None


def test_worker_ready_picks_up_queues_and_tasks(rt):
    consumer = SimpleNamespace(
        hostname="w3@box",
        task_consumer=SimpleNamespace(
            queues=[SimpleNamespace(name="emails"), SimpleNamespace(name="default")]
        ),
        app=SimpleNamespace(tasks={"celery.backend_cleanup": 1, "proj.send": 1}),
    )
    heartbeat.on_worker_ready(sender=consumer)
    try:
        data = read(rt, "w3@box")
        assert data["queues"] == ["default", "emails"]
        assert data["tasks"] == ["proj.send"]
        assert rt.hostname == "w3@box"
    finally:
        heartbeat.on_worker_shutdown()
    assert read(rt, "w3@box") is None
