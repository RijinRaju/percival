from fastapi.testclient import TestClient
from sqlalchemy import select

from percival_server.models import AuditLog, Setting

from .conftest import ADMIN, do_setup


def test_setup_once_then_closed(client):
    assert client.get("/api/v1/setup").json()["needs_setup"] is True
    do_setup(client)
    assert client.get("/api/v1/setup").json()["needs_setup"] is False

    again = client.post(
        "/api/v1/setup",
        json={**ADMIN, "broker_url": "memory://", "redis_url": "redis://x"},
    )
    assert again.status_code == 409


def test_setup_rejects_weak_password(client):
    resp = client.post(
        "/api/v1/setup",
        json={"username": "a", "password": "short", "broker_url": "memory://", "redis_url": "r"},
    )
    assert resp.status_code == 422


def test_connection_secrets_are_encrypted_at_rest(app, admin):
    with app.state.sessionmaker() as db:
        row = db.get(Setting, "redis_url")
        assert row.encrypted
        assert "s3cret" not in row.value


def test_connection_test_is_open_during_setup_only(client):
    resp = client.post("/api/v1/setup/test", json={"kind": "redis", "url": "redis://x"})
    assert resp.json()["ok"] is True

    do_setup(client)
    fresh = TestClient(client.app)
    resp = fresh.post("/api/v1/setup/test", json={"kind": "redis", "url": "redis://x"})
    assert resp.status_code == 401


def test_login_logout_and_me(client):
    do_setup(client)
    anon = TestClient(client.app)
    assert anon.get("/api/v1/auth/me").status_code == 401

    resp = anon.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]
    assert anon.get("/api/v1/auth/me").json()["username"] == "admin"

    anon.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert anon.get("/api/v1/auth/me").status_code == 401


def test_session_cookie_flags(client):
    do_setup(client)
    resp = TestClient(client.app).post("/api/v1/auth/login", json=ADMIN)
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_writes_without_csrf_are_refused(client):
    do_setup(client)
    # logged in through setup, but no csrf header set
    resp = client.post("/api/v1/tokens", json={"name": "x"})
    assert resp.status_code == 403
    resp = client.post("/api/v1/tokens", json={"name": "x"}, headers={"X-CSRF-Token": "nope"})
    assert resp.status_code == 403


def test_login_is_throttled(client):
    do_setup(client)
    anon = TestClient(client.app)
    for _ in range(5):
        assert anon.post("/api/v1/auth/login", json={**ADMIN, "password": "x"}).status_code == 401
    blocked = anon.post("/api/v1/auth/login", json=ADMIN)
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_tokens_shown_once_scoped_and_revocable(client, admin):
    created = client.post("/api/v1/tokens", json={"name": "ci", "scopes": ["read"]}).json()
    raw = created["token"]
    assert raw.startswith("perc_")
    assert all("token" not in t for t in client.get("/api/v1/tokens").json())

    bot = TestClient(client.app, headers={"Authorization": f"Bearer {raw}"})
    me = bot.get("/api/v1/auth/me").json()
    assert me["kind"] == "token" and me["scopes"] == ["read"]
    # tokens can't manage tokens, even with write
    assert bot.get("/api/v1/tokens").status_code == 403

    client.delete(f"/api/v1/tokens/{created['id']}")
    assert bot.get("/api/v1/auth/me").status_code == 401


def test_users_and_audit_trail(app, client, admin):
    resp = client.post("/api/v1/users", json={"username": "bob", "password": "bobs-password-1"})
    assert resp.status_code == 201
    bob_id = resp.json()["id"]
    assert (
        client.post(
            "/api/v1/users", json={"username": "bob", "password": "bobs-password-1"}
        ).status_code
        == 409
    )

    me_id = next(u["id"] for u in client.get("/api/v1/users").json() if u["username"] == "admin")
    assert client.delete(f"/api/v1/users/{me_id}").status_code == 409
    assert client.delete(f"/api/v1/users/{bob_id}").status_code == 204

    with app.state.sessionmaker() as db:
        actions = list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))
        assert actions == ["setup.complete", "user.create", "user.delete"]
        assert all(a.source == "ui" for a in db.scalars(select(AuditLog)))


def test_connection_settings_are_masked(client, admin):
    data = client.get("/api/v1/settings/connections").json()
    assert data["redis_url"] == "redis://:****@redis:6379/0"

    updated = client.put("/api/v1/settings/connections", json={"retention_days": 7}).json()
    assert updated["retention_days"] == 7
    assert updated["redis_url"] == "redis://:****@redis:6379/0"
