---
title: Adding Percival to your Celery project
description: Install the percival client, call percival.init() and get run events, worker versions, a stale worker gate and duplicate protection for your Celery tasks.
---

# In your Celery project

The client is the part you install next to your Celery app. Workers and beat
both need it.

```
pip install percival
```

```python
# proj/celery.py
import os
from celery import Celery
import percival

app = Celery("proj")
percival.init(
    app,
    redis_url="redis://localhost:6379/0",
    code_version=os.environ["GIT_SHA"],
)
```

It needs Celery 5.3 or newer and Redis. The broker can be Redis or RabbitMQ.

## What `init()` sets up

**Run events.** Started, success, failure, retry and revoked go to a Redis
stream, with timing, worker, code version and redacted args. Anything named
like `password`, `token`, `secret` and so on is replaced before it leaves the
worker. Positional args are matched to parameter names, so
`send(user, api_token)` is covered too.

**Worker heartbeat.** Every 30 seconds each worker writes its hostname,
queues and code version. Dead workers age out after 90 seconds.

**Task metadata.** The signature, docstring and source of each registered
task, so the panel can show them. It's read only. The panel never runs or
stores your code. Pass `publish_source=False` if you don't want source sent.

**Stale worker gate.** If a message carries a required code version and the
worker is on a different one, the task body doesn't run. By default the
message goes back on the queue after a short delay so an up-to-date worker
can pick it up. It's recorded as `blocked_stale_worker`.

## Picking a code version

`code_version` is whatever identifies a deploy: a git SHA, a release tag, an
image tag. Workers from the same deploy must report the same value.

If you leave it at `unknown`, any schedule that requires a version is blocked
on that worker. That's on purpose.

## Stopping duplicate runs

```python
from percival import once_per

@app.task
@once_per(key=lambda user_id, **kw: user_id, window="1d")
def send_digest(user_id):
    ...
```

The second run for the same key in the same window is skipped and recorded as
`skipped_duplicate`. A few things worth knowing:

- Fixed windows (`"5m"`, `"1h"`, `"1d"`) line up with the unix epoch, so
  `"1d"` is a UTC calendar day. For something like "once per user per local
  day", pass a callable as `window` that returns the bucket, such as the
  user's local date.
- If Redis is unreachable the run is **skipped** by default. Sending twice is
  usually worse than sending late. Set `fail_open=True` if your task is the
  other way round.
- If the task raises (including `self.retry()`), the key is released so the
  retry can actually run.

## Options

Every option can be passed to `init()` or set as an environment variable.

| option | env | default |
|---|---|---|
| `redis_url` | `PERCIVAL_REDIS_URL` | `redis://localhost:6379/0` |
| `code_version` | `PERCIVAL_CODE_VERSION` | `unknown` |
| `key_prefix` | `PERCIVAL_KEY_PREFIX` | `percival` |
| `capture_args` | `PERCIVAL_CAPTURE_ARGS` | `true` |
| `redact_kwargs` | | password, token, secret, api_key, ... |
| `stale_action` | `PERCIVAL_STALE_ACTION` | `requeue` (or `drop`) |
| `dedupe_fail_open` | `PERCIVAL_DEDUPE_FAIL_OPEN` | `false` |
