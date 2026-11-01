import fakeredis
import pytest
from fastapi.testclient import TestClient

from percival_server.config import DEVELOPMENT, ServerConfig
from percival_server.main import create_app

ADMIN = {"username": "admin", "password": "a-long-enough-password"}


@pytest.fixture
def config(tmp_path):
    return ServerConfig(
        env=DEVELOPMENT,
        secret_key="test-secret-" + "x" * 40,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secure_cookies=False,
        static_dir=None,
        run_consumer=False,
    )


@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture
def app(config, redis_server):
    def factory(url, decode):
        return fakeredis.FakeRedis(server=redis_server, decode_responses=decode)

    return create_app(config, redis_factory=factory)


@pytest.fixture
def client(app):
    return TestClient(app)


def do_setup(client):
    resp = client.post(
        "/api/v1/setup",
        json={
            **ADMIN,
            "broker_url": "memory://",
            "redis_url": "redis://:s3cret@redis:6379/0",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["csrf_token"]


@pytest.fixture
def admin(client):
    """A client that went through setup and is logged in. Returns the csrf token."""
    csrf = do_setup(client)
    client.headers["X-CSRF-Token"] = csrf
    return csrf
