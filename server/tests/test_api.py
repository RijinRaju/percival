import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from percival_server.consumer import apply_events
from percival_server.models import AuditLog

DIGEST = {
    "name": "digest",
    "task": "proj.send_digest",
    "schedule": {"type": "crontab", "minute": "0", "hour": "9", "day_of_week": "mon,thu"},
    "timezone": "Asia/Kolkata",
    "kwargs": {"kind": "weekly"},
    "options": {"queue": "emails", "required_version": "v2"},
    "notes": "the one that went wrong",
}


def parse_utc(value):
    # python 3.10's fromisoformat doesn't take the trailing Z
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def redis(app):
    return app.state.connections.redis()


@pytest.fixture
def keys(app):
    return app.state.connections.keys


def heartbeat(redis, keys, host, version, queues=("emails",), tasks=("proj.send_digest",)):
    redis.set(
        keys.worker(host),
        json.dumps(
            {
                "hostname": host,
                "code_version": version,
                "queues": list(queues),
                "tasks": list(tasks),
                "pid": 1,
                "started_at": time.time(),
                "last_seen": time.time(),
            }
        ),
    )


def token(client, *scopes):
    raw = client.post("/api/v1/tokens", json={"name": "bot", "scopes": list(scopes)}).json()
    return TestClient(client.app, headers={"Authorization": f"Bearer {raw['token']}"})


def audit_rows(app):
    with app.state.sessionmaker() as db:
        return [(a.action, a.source, a.target) for a in db.scalars(select(AuditLog))]


def test_schedule_lifecycle(app, client, admin):
    created = client.post("/api/v1/schedules", json=DIGEST)
    assert created.status_code == 201, created.text
    assert created.json()["timezone"] == "Asia/Kolkata"
    assert client.post("/api/v1/schedules", json=DIGEST).status_code == 409

    one = client.get("/api/v1/schedules/digest").json()
    assert one["notes"] == "the one that went wrong"
    assert len(one["next_runs"]) == 5

    patched = client.patch("/api/v1/schedules/digest", json={"options": {"queue": "emails"}})
    assert patched.json()["required_version"] is None
    assert patched.json()["kwargs"] == {"kind": "weekly"}

    assert (
        client.post("/api/v1/schedules/digest/pause", json={"reason": "rollout"}).json()["enabled"]
        is False
    )
    assert client.get("/api/v1/schedules/digest/next-runs").json() == []
    assert client.post("/api/v1/schedules/digest/resume").json()["enabled"] is True

    assert client.delete("/api/v1/schedules/digest").status_code == 204
    assert client.get("/api/v1/schedules/digest").status_code == 404

    actions = [a for a, _, _ in audit_rows(app) if a.startswith("schedule")]
    assert actions == [
        "schedule.create",
        "schedule.update",
        "schedule.pause",
        "schedule.resume",
        "schedule.delete",
    ]


def test_update_audit_has_before_and_after(app, client, admin):
    client.post("/api/v1/schedules", json=DIGEST)
    client.patch("/api/v1/schedules/digest", json={"schedule": {"type": "interval", "every": 300}})
    with app.state.sessionmaker() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "schedule.update"))
    assert row.before["schedule"]["type"] == "crontab"
    assert row.after["schedule"] == {"type": "interval", "every": 300.0}


def test_bad_input_is_a_422(client, admin):
    bad_cron = {**DIGEST, "schedule": {"type": "crontab", "minute": "61"}}
    assert client.post("/api/v1/schedules", json=bad_cron).status_code == 422
    assert (
        client.post("/api/v1/schedules", json={**DIGEST, "timezone": "Nope/Nope"}).status_code
        == 422
    )


def test_preview(client, admin):
    resp = client.post(
        "/api/v1/schedules/preview",
        json={"schedule": {"type": "crontab", "minute": "*/15"}, "count": 3},
    )
    runs = [parse_utc(r) for r in resp.json()]
    assert len(runs) == 3
    assert all(r.minute % 15 == 0 for r in runs)


def test_run_now_sends_with_schedule_headers(app, client, admin):
    client.post("/api/v1/schedules", json=DIGEST)
    sent = []
    celery = app.state.connections.celery()
    celery.send_task = lambda name, **kw: sent.append((name, kw)) or type("R", (), {"id": "abc"})()

    resp = client.post("/api/v1/schedules/digest/run-now", json={"reason": "testing"})
    assert resp.json() == {"task_id": "abc"}
    name, kw = sent[0]
    assert name == "proj.send_digest"
    assert kw["queue"] == "emails"
    assert kw["headers"]["percival_schedule"] == "digest"
    assert kw["headers"]["percival_required_version"] == "v2"


def test_scopes_and_audit_source(app, client, admin):
    reader = token(client, "read")
    writer = token(client, "write")

    assert reader.get("/api/v1/schedules").status_code == 200
    assert reader.post("/api/v1/schedules", json=DIGEST).status_code == 403
    assert writer.post("/api/v1/schedules", json=DIGEST).status_code == 201
    # bearer requests don't need csrf
    assert writer.post("/api/v1/schedules/digest/pause").status_code == 200

    assert ("schedule.pause", "api", "digest") in audit_rows(app)


def test_list_shows_coverage_and_last_run(app, client, admin, redis, keys):
    client.post("/api/v1/schedules", json=DIGEST)
    heartbeat(redis, keys, "old@box", "v1")
    heartbeat(redis, keys, "new@box", "v2")
    with app.state.sessionmaker() as db:
        apply_events(
            db,
            [
                {
                    "status": "blocked_stale_worker",
                    "task": "proj.send_digest",
                    "task_id": "x",
                    "schedule": "digest",
                    "worker": "old@box",
                    "ts": time.time(),
                },
            ],
        )
        db.commit()

    (row,) = client.get("/api/v1/schedules").json()
    assert row["coverage"] == {"queue": "emails", "consumers": 2, "matching": 1, "stale": 1}
    assert row["last_run"]["status"] == "blocked_stale_worker"
    assert row["applied"] is None  # no percival beat heartbeat

    redis.set(keys.beat, json.dumps({"last_tick": time.time() + 5, "started_at": time.time()}))
    assert client.get("/api/v1/schedules").json()[0]["applied"] is True


def test_status_reports_mismatch_and_affected(client, admin, redis, keys):
    client.post("/api/v1/schedules", json=DIGEST)
    client.post(
        "/api/v1/schedules",
        json={**DIGEST, "name": "unprotected", "options": {"queue": "emails"}},
    )
    heartbeat(redis, keys, "old@box", "v1")
    time.sleep(0.01)
    heartbeat(redis, keys, "new@box", "v2")

    data = client.get("/api/v1/status").json()
    assert data["versions"]["mismatch"] is True
    assert data["versions"]["current"] == "v2"
    affected = {a["name"]: a["protected"] for a in data["affected_schedules"]}
    assert affected == {"digest": True, "unprotected": False}


def test_runs_filters_and_detail(app, client, admin):
    now = time.time()
    with app.state.sessionmaker() as db:
        apply_events(
            db,
            [
                {
                    "status": "blocked_stale_worker",
                    "task": "t",
                    "task_id": "m1",
                    "worker": "old",
                    "schedule": "digest",
                    "ts": now,
                },
                {"status": "started", "task": "t", "task_id": "m1", "worker": "new", "ts": now},
                {"status": "success", "task": "t", "task_id": "m1", "worker": "new", "ts": now},
                {
                    "status": "failure",
                    "task": "t",
                    "task_id": "m2",
                    "worker": "new",
                    "ts": now,
                    "traceback": "Traceback...\nValueError: boom",
                    "exc_type": "ValueError",
                },
            ],
        )
        db.commit()

    everything = client.get("/api/v1/runs").json()["items"]
    assert len(everything) == 3
    failures = client.get("/api/v1/runs", params={"status": "failure"}).json()["items"]
    assert [r["task_id"] for r in failures] == ["m2"]

    detail = client.get(f"/api/v1/runs/{failures[0]['id']}").json()
    assert "ValueError: boom" in detail["traceback"]

    success = next(r for r in everything if r["status"] == "success")
    attempts = client.get(f"/api/v1/runs/{success['id']}").json()["attempts"]
    assert [a["status"] for a in attempts] == ["blocked_stale_worker", "success"]

    page = client.get("/api/v1/runs", params={"limit": 2}).json()
    assert page["next_before_id"] is not None
    rest = client.get("/api/v1/runs", params={"before_id": page["next_before_id"]}).json()
    assert len(rest["items"]) == 1


def test_tasks_and_workers(client, admin, redis, keys):
    heartbeat(redis, keys, "w1", "v2")
    redis.hset(
        keys.tasks,
        "proj.send_digest",
        json.dumps(
            {
                "name": "proj.send_digest",
                "signature": "(user_id)",
                "doc": "Mail it.",
                "source": "def send_digest(user_id): ...",
                "published_at": time.time(),
            }
        ),
    )
    client.post("/api/v1/schedules", json=DIGEST)

    (task,) = client.get("/api/v1/tasks").json()
    assert task["workers"] == ["w1"]
    assert task["schedules"] == 1
    detail = client.get("/api/v1/tasks/proj.send_digest").json()
    assert detail["meta"]["signature"] == "(user_id)"
    assert detail["schedules"] == ["digest"]

    workers = client.get("/api/v1/workers").json()
    assert workers["workers"][0]["alive"] is True
    assert "tasks" not in workers["workers"][0]


def test_import_from_published_beat_schedule(app, client, admin, redis, keys):
    redis.set(
        keys.beat_schedule,
        json.dumps(
            {
                "timezone": "Europe/London",
                "code_version": "v2",
                "entries": {
                    "cleanup": {
                        "task": "proj.cleanup",
                        "human": "every 5 minutes",
                        "schedule": {"type": "interval", "every": 300.0},
                        "args": [],
                        "kwargs": {},
                        "options": {},
                    },
                    "secret": {
                        "task": "proj.sync",
                        "human": "every 1 hour",
                        "schedule": {"type": "interval", "every": 3600.0},
                        "args": [],
                        "kwargs": {"api_token": "[redacted]"},
                        "options": {},
                    },
                },
            }
        ),
    )
    available = client.get("/api/v1/schedules/import/available").json()
    actions = {e["name"]: e["action"] for e in available["entries"]}
    assert actions == {"cleanup": "create", "secret": "redacted"}

    result = client.post("/api/v1/schedules/import", json={"names": ["cleanup", "secret"]}).json()
    assert result == {"created": ["cleanup"], "skipped": ["secret"]}
    assert client.get("/api/v1/schedules/cleanup").json()["origin"] == "imported"


def test_api_docs_need_a_login(client, admin):
    assert client.get("/api/docs").status_code == 200
    assert TestClient(client.app).get("/api/docs").status_code == 401


def test_endpoints_before_setup(client):
    # nobody can log in yet, so everything is a 401 rather than a crash
    assert client.get("/api/v1/schedules").status_code == 401


def test_datetimes_are_utc_iso(client, admin):
    client.post("/api/v1/schedules", json=DIGEST)
    first = client.get("/api/v1/schedules/digest").json()["next_runs"][0]
    assert parse_utc(first).tzinfo is not None
    assert parse_utc(first).utcoffset() == timezone.utc.utcoffset(None)


def test_edit_works_as_the_first_redbeat_call(app, config, redis_server, admin, client):
    # found running it for real: a fresh process whose first request was a
    # PATCH crashed because redbeat's config wasn't attached to the app yet
    client.post("/api/v1/schedules", json=DIGEST)
    from percival_server.main import create_app

    def factory(url, decode):
        import fakeredis

        return fakeredis.FakeRedis(server=redis_server, decode_responses=decode)

    fresh = TestClient(create_app(config, redis_factory=factory))
    csrf = fresh.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "a-long-enough-password"}
    ).json()["csrf_token"]
    resp = fresh.patch(
        "/api/v1/schedules/digest", json={"notes": "edited"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200, resp.text
