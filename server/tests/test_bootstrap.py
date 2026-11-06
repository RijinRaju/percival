from dataclasses import replace

import fakeredis
import pytest
from fastapi.testclient import TestClient

from percival_server.config import ConfigError
from percival_server.main import create_app
from percival_server.models import Setting, User

from .conftest import ADMIN


@pytest.fixture
def env_config(config):
    return replace(
        config,
        broker_url="redis://:s3cret@redis:6379/0",
        redis_url="redis://:s3cret@redis:6379/0",
        admin_username=ADMIN["username"],
        admin_password=ADMIN["password"],
    )


@pytest.fixture
def env_app(env_config, redis_server):
    def factory(url, decode):
        return fakeredis.FakeRedis(server=redis_server, decode_responses=decode)

    return create_app(env_config, redis_factory=factory)


def test_env_admin_and_connections_skip_the_wizard(env_app):
    client = TestClient(env_app)
    assert client.get("/api/v1/setup").json() == {
        "needs_setup": False,
        "connections_from_env": True,
    }
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    assert client.get("/api/v1/schedules").status_code == 200

    # urls live in the env only, nothing secret lands in the db
    with env_app.state.sessionmaker() as db:
        assert db.get(Setting, "redis_url") is None


def test_env_admin_is_created_once(env_config, redis_server):
    def factory(url, decode):
        return fakeredis.FakeRedis(server=redis_server, decode_responses=decode)

    create_app(env_config, redis_factory=factory)
    # a restart with a different password must not touch the existing user
    app = create_app(
        replace(env_config, admin_password="another-long-password"), redis_factory=factory
    )
    with app.state.sessionmaker() as db:
        assert db.query(User).count() == 1
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json=ADMIN).status_code == 200


def test_weak_env_admin_password_stops_startup(env_config):
    with pytest.raises(ConfigError, match="ADMIN_PASSWORD"):
        create_app(replace(env_config, admin_password="short"))


def test_wizard_only_asks_for_the_admin_when_env_has_connections(env_config, redis_server):
    def factory(url, decode):
        return fakeredis.FakeRedis(server=redis_server, decode_responses=decode)

    app = create_app(
        replace(env_config, admin_username=None, admin_password=None), redis_factory=factory
    )
    client = TestClient(app)
    assert client.get("/api/v1/setup").json()["connections_from_env"] is True
    assert client.post("/api/v1/setup", json=ADMIN).status_code == 201


def test_env_connections_cant_be_edited_from_settings(env_app):
    client = TestClient(env_app)
    client.headers["X-CSRF-Token"] = client.post("/api/v1/auth/login", json=ADMIN).json()[
        "csrf_token"
    ]
    current = client.get("/api/v1/settings/connections").json()
    assert current["from_env"] is True
    assert "s3cret" not in current["redis_url"]

    resp = client.put("/api/v1/settings/connections", json={"redis_url": "redis://other"})
    assert resp.status_code == 409
    resp = client.put("/api/v1/settings/connections", json={"retention_days": 7})
    assert resp.status_code == 200
    assert resp.json()["retention_days"] == 7
