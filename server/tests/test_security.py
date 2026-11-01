import time

from percival_server.auth.ratelimit import FailureLimiter
from percival_server.auth.security import (
    TOKEN_PREFIX,
    hash_password,
    hash_token,
    new_api_token,
    password_problem,
    verify_password,
)


def test_password_round_trip():
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong")
    assert not verify_password("not-a-hash", "whatever")


def test_short_password_is_refused():
    assert password_problem("short") is not None
    assert password_problem("long enough now") is None


def test_tokens_have_a_recognisable_prefix_and_stable_hash():
    token = new_api_token()
    assert token.startswith(TOKEN_PREFIX)
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != hash_token(new_api_token())


def test_limiter_blocks_after_max_failures(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    limiter = FailureLimiter(max_failures=3, window_seconds=60)

    for _ in range(3):
        assert limiter.retry_after("1.2.3.4") == 0
        limiter.fail("1.2.3.4")
    assert limiter.retry_after("1.2.3.4") == 60
    assert limiter.retry_after("5.6.7.8") == 0

    clock[0] += 61
    assert limiter.retry_after("1.2.3.4") == 0


def test_limiter_reset_on_success():
    limiter = FailureLimiter(max_failures=1, window_seconds=60)
    limiter.fail("bob")
    assert limiter.retry_after("bob") > 0
    limiter.reset("bob")
    assert limiter.retry_after("bob") == 0
