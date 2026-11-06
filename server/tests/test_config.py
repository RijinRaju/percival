import json
import logging

import pytest
from fastapi.testclient import TestClient

from percival_server.config import ConfigError, ServerConfig
from percival_server.crypto import SecretBox
from percival_server.logs import JsonFormatter
from percival_server.main import create_app

KEY = "k" * 40


def test_production_without_a_secret_keeps_one_in_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("PERCIVAL_SECRET_KEY", raising=False)
    monkeypatch.setenv("PERCIVAL_ENV", "production")
    monkeypatch.setenv("PERCIVAL_DATA_DIR", str(tmp_path / "data"))
    first = ServerConfig.from_env().secret_key
    assert len(first) >= 32
    assert (tmp_path / "data" / "secret_key").read_text().strip() == first
    # a restart has to find the same key, or stored urls become unreadable
    assert ServerConfig.from_env().secret_key == first


def test_broker_and_redis_from_env(monkeypatch):
    monkeypatch.setenv("PERCIVAL_ENV", "development")
    monkeypatch.setenv("PERCIVAL_REDIS_URL", "redis://r:6379/0")
    config = ServerConfig.from_env()
    assert config.connections_from_env
    assert config.broker_url == "redis://r:6379/0"

    # rabbit broker: redis can't be guessed
    monkeypatch.delenv("PERCIVAL_REDIS_URL")
    monkeypatch.setenv("CELERY_BROKER_URL", "amqp://guest@rabbit//")
    with pytest.raises(ConfigError, match="REDIS_URL"):
        ServerConfig.from_env()


def test_admin_password_without_username_means_admin(monkeypatch):
    monkeypatch.setenv("PERCIVAL_ENV", "development")
    monkeypatch.setenv("PERCIVAL_ADMIN_PASSWORD", "a-long-enough-password")
    assert ServerConfig.from_env().admin_username == "admin"
    monkeypatch.delenv("PERCIVAL_ADMIN_PASSWORD")
    monkeypatch.setenv("PERCIVAL_ADMIN_USERNAME", "ops")
    with pytest.raises(ConfigError, match="ADMIN_PASSWORD"):
        ServerConfig.from_env()


def test_development_makes_up_a_key(monkeypatch):
    monkeypatch.delenv("PERCIVAL_SECRET_KEY", raising=False)
    monkeypatch.setenv("PERCIVAL_ENV", "development")
    config = ServerConfig.from_env()
    assert len(config.secret_key) >= 32
    assert config.secure_cookies is False


def test_short_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("PERCIVAL_SECRET_KEY", "short")
    with pytest.raises(ConfigError):
        ServerConfig.from_env()


def test_secret_box_round_trip_and_wrong_key():
    box = SecretBox(KEY)
    token = box.encrypt("redis://:hunter2@redis:6379/0")
    assert "hunter2" not in token
    assert box.decrypt(token) == "redis://:hunter2@redis:6379/0"
    with pytest.raises(ValueError, match="SECRET_KEY"):
        SecretBox("x" * 40).decrypt(token)


def test_health_is_public_and_boring(config):
    client = TestClient(create_app(config))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "version"}


def test_json_log_lines():
    record = logging.LogRecord("percival", logging.INFO, "", 0, "hello %s", ("there",), None)
    record.task = "proj.send"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello there"
    assert line["task"] == "proj.send"
