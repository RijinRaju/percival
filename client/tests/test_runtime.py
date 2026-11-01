import pytest

from percival import runtime
from percival.runtime import RedisHandle


def test_current_without_init_is_a_clear_error():
    runtime.reset()
    with pytest.raises(RuntimeError, match="not initialised"):
        runtime.current()


def test_handle_rebuilds_client_after_fork(monkeypatch):
    made = []
    handle = RedisHandle("redis://x", factory=lambda url: made.append(url) or object())

    first = handle.get()
    assert handle.get() is first

    monkeypatch.setattr("os.getpid", lambda: 999_999)
    assert handle.get() is not first
    assert len(made) == 2
