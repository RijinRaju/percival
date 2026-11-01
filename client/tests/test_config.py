import pytest

from percival.config import Settings
from percival.naming import Headers, Keys


def test_explicit_args_beat_env(monkeypatch):
    monkeypatch.setenv("PERCIVAL_CODE_VERSION", "from-env")
    assert Settings.build().code_version == "from-env"
    assert Settings.build(code_version="abc123").code_version == "abc123"


def test_env_bool_and_lists(monkeypatch):
    monkeypatch.setenv("PERCIVAL_CAPTURE_ARGS", "no")
    s = Settings.build(redact_kwargs=["ssn", "card"])
    assert s.capture_args is False
    assert s.redact_kwargs == ("ssn", "card")


def test_bad_stale_action():
    with pytest.raises(ValueError):
        Settings.build(stale_action="explode")


def test_keys_follow_prefix():
    keys = Keys("acme:")
    assert keys.events == "acme:events"
    assert keys.worker("w1@host") == "acme:worker:w1@host"
    assert keys.once("app.send", "42", "20450") == "acme:once:app.send:42:20450"


def test_header_names_are_namespaced():
    assert Headers.REQUIRED_VERSION.endswith("_required_version")
