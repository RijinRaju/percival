# Percival

A self-hosted control panel for Celery. Change schedules without restarting
beat or workers, and stop the two things ping monitors can't see: a task
running twice, and a stale worker running old code.

> Early days. The client library and the panel (API + web UI) work and are
> tested. The MCP server and the Docker image are next. Expect breaking
> changes until 0.1.

## Why I built this

Our schedules lived in a hand-edited `beat_schedule`. Changing one meant
editing config, redeploying, and restarting beat and every worker by hand.

We changed an email task from "Monday and Thursday" to "every 5 minutes,
per user timezone". During the rollout one worker hadn't restarted yet. It
was still on the old code while beat was already firing every 5 minutes, and
users got emails they were never supposed to get.

Nothing told us the workers were on different versions, and nothing stopped
the task from running twice. Flower doesn't manage beat schedules,
django-celery-beat is tied to Django, RedBeat has no UI, and Healthchecks or
Cronitor only know whether a ping arrived. None of them would have caught
this.

## What the client does today

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

That one call sets up:

- **Run events.** started, success, failure, retry and revoked go to a Redis
  stream with timing, worker, code version and redacted args. Anything named
  like `password`, `token`, `secret` and so on is replaced before it leaves
  the worker. Positional args are matched to parameter names, so
  `send(user, api_token)` is covered too.
- **Worker heartbeat.** Every 30s each worker writes its hostname, queues and
  code version. Dead workers age out after 90s.
- **Task metadata.** Signature, docstring and source of each registered task,
  so the panel can show them. It is read-only. The panel never runs or stores
  your code. Pass `publish_source=False` if you don't want source sent.
- **Stale worker gate.** If a message carries a required code version and the
  worker is on a different one, the task body does not run. By default the
  message goes back on the queue after a short delay so an up-to-date worker
  can pick it up. It's recorded as `blocked_stale_worker`.

### Stopping duplicate runs

```python
from percival import once_per

@app.task
@once_per(key=lambda user_id, **kw: user_id, window="1d")
def send_digest(user_id):
    ...
```

The second run for the same key in the same window is skipped and recorded as
`skipped_duplicate`. A few things worth knowing:

- Fixed windows (`"5m"`, `"1h"`, `"1d"`) line up with the unix epoch, so `"1d"`
  is a UTC calendar day. For something like "once per user per local day",
  pass a callable as `window` that returns the bucket, e.g. the user's local
  date.
- If Redis is unreachable the run is **skipped** by default. Sending twice is
  usually worse than sending late. Set `fail_open=True` if your task is the
  other way round.
- If the task raises (including `self.retry()`), the key is released so the
  retry can actually run.

### Importing an existing beat_schedule

```
pip install "percival[import]"
percival import --app proj.celery:app --redis-url redis://localhost:6379/0
```

This is a dry run that prints what would be created or changed. Add `--apply`
to write the entries to RedBeat, then run beat with
`celery beat -S percival.beat.Scheduler` (see below).

After importing, remove those entries from `beat_schedule`. RedBeat re-syncs
config entries every time beat starts, so anything left in config will
overwrite what you change in the panel.

## Running beat

```
celery -A proj beat -S percival.beat.Scheduler
```

That's RedBeat with three additions: crontabs follow their own timezone
(DST included), beat writes a heartbeat so the panel knows it's alive and
whether your last change was picked up, and it checks for new schedules every
15 seconds instead of up to every 5 minutes.

Plain `redbeat.RedBeatScheduler` still works with everything the panel
writes. You just lose the three things above.

## The panel

Docker image is coming. Until then, from a checkout:

```
cd web && npm ci && npm run build && cd ..
pip install -e client -e server
PERCIVAL_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")   percival-server
```

Open http://127.0.0.1:8080. The first visit walks you through creating an
admin and pointing it at your broker and Redis. Keep the secret key somewhere
safe: it encrypts the stored connection URLs, and the server refuses to start
without it unless `PERCIVAL_ENV=development`.

| env | default | |
|---|---|---|
| `PERCIVAL_SECRET_KEY` | none | required in production |
| `PERCIVAL_DATABASE_URL` | SQLite in `./data` | Postgres works too |
| `PERCIVAL_HOST` / `PERCIVAL_PORT` | `127.0.0.1` / `8080` | |
| `PERCIVAL_SECURE_COOKIES` | on in production | turn off only for plain http on localhost |

Put it behind a reverse proxy with TLS if anyone besides you will reach it.
API docs are at `/api/docs` once you're logged in.

## Configuration

Every option can be passed to `init()` or set as an env var:

| option | env | default |
|---|---|---|
| `redis_url` | `PERCIVAL_REDIS_URL` | `redis://localhost:6379/0` |
| `code_version` | `PERCIVAL_CODE_VERSION` | `unknown` |
| `key_prefix` | `PERCIVAL_KEY_PREFIX` | `percival` |
| `capture_args` | `PERCIVAL_CAPTURE_ARGS` | `true` |
| `redact_kwargs` | | password, token, secret, api_key, ... |
| `stale_action` | `PERCIVAL_STALE_ACTION` | `requeue` (or `drop`) |
| `dedupe_fail_open` | `PERCIVAL_DEDUPE_FAIL_OPEN` | `false` |

If `code_version` is left at `unknown`, any schedule that requires a version
is blocked on that worker. That's on purpose.

## Roadmap

- [x] client: events, heartbeat, metadata, version gate, `once_per`
- [x] `percival import`
- [x] per-schedule timezones (`percival.beat.Scheduler`)
- [x] server: API, auth, schedules on top of RedBeat, run history, audit log
- [x] web UI
- [ ] MCP server (read-only by default, writes need human approval)
- [ ] Docker image and a demo compose stack

## Development

```
python -m venv .venv
.venv/bin/pip install -e "client[dev]" -e "server[dev]"
(cd client && pytest)
(cd server && pytest)

# ui with hot reload, proxies /api to a panel on :8080
cd web && npm ci && npm run dev
```

## License

MIT
