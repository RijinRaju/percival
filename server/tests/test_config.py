import json
import logging

import pytest
from fastapi.testclient import TestClient

from percival_server.config import ConfigError, ServerConfig
from percival_server.crypto import SecretBox
from percival_server.logs import JsonFormatter
from percival_server.main import create_app

KEY = "k" * 40


def test_production_refuses_to_start_without_a_secret(monkeypatch):
    monkeypatch.delenv("PERCIVAL_SECRET_KEY", raising=False)
    monkeypatch.setenv("PERCIVAL_ENV", "production")
    with pytest.raises(ConfigError, match="SECRET_KEY"):
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
