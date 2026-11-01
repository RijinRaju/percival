from percival.redaction import REDACTED, capture_args, scrub

PATTERNS = ("password", "token")


def test_nested_keys_are_hidden():
    data = {"user": "bob", "auth": {"Access_Token": "abc", "scopes": ["a"]}}
    assert scrub(data, PATTERNS) == {
        "user": "bob",
        "auth": {"Access_Token": REDACTED, "scopes": ["a"]},
    }


def test_positional_args_use_the_signature():
    def send(user_id, api_token, *, retries=3):
        pass

    captured = capture_args(send, [7, "s3cr3t"], {"retries": 1}, PATTERNS)
    assert captured == {"args": [7, REDACTED], "kwargs": {"retries": 1}}


def test_varargs_are_left_alone_but_still_scrubbed():
    def fanout(*items):
        pass

    captured = capture_args(fanout, [{"password": "x"}, "ok"], None, PATTERNS)
    assert captured["args"] == [{"password": REDACTED}, "ok"]


def test_odd_values_become_strings_and_get_capped():
    class Thing:
        def __repr__(self):
            return "T" * 50

    assert scrub(Thing(), PATTERNS, max_chars=10).startswith("TTTTTTTTTT...")
    assert scrub("x" * 30, PATTERNS, max_chars=10).endswith("[20 more chars]")


def test_signature_failure_does_not_break_capture():
    captured = capture_args(print, ["hello"], {}, PATTERNS)
    assert captured["args"] == ["hello"]
