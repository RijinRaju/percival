<p>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/percival-tile-dark.svg">
    <img src="brand/percival-tile.svg" width="72" height="72" alt="Percival logo">
  </picture>
</p>

# Percival

A self-hosted control panel for Celery. Change schedules without restarting
beat or workers, and stop the two things ping monitors can't see: a task
running twice, and a stale worker running old code.

Docs: https://percivalhq.dev

## Quickstart

If you already run Celery with Redis, it's three commands and a few lines of
code. Your tasks stay where they are; Percival only decides when they run and
shows you what happened.

```
pip install percival
```

```python
# proj/celery.py, right after app = Celery(...)
import os, percival
percival.init(
    app,
    redis_url="redis://localhost:6379/0",
    code_version=os.environ.get("GIT_SHA", "dev"),  # whatever identifies a deploy
)
```

```
celery -A proj beat -S percival.beat.Scheduler
docker run -d -p 8080:8080 -v percival:/data \
  -e PERCIVAL_REDIS_URL=redis://host.docker.internal:6379/0 \
  -e PERCIVAL_ADMIN_PASSWORD=pick-a-long-one \
  ghcr.io/rijinraju/percival
```

Restart your workers, open http://localhost:8080 and log in as `admin`. Your
tasks show up under Tasks; pick one and give it a schedule. Already have a
`beat_schedule`? Press **import** on the board.

`host.docker.internal` is how a container reaches Redis on your own machine
(Docker Desktop). On a server, use the Redis hostname your workers use. If
your broker is RabbitMQ, also pass `PERCIVAL_BROKER_URL`.

### Just want to see it?

```
git clone https://github.com/RijinRaju/percival && cd percival/demo
docker compose up
```

Open http://localhost:8080 and log in as `demo` / `percival-demo`. It runs
Redis, beat, the panel and two workers on different versions of a small shop
app. Within a minute you'll see the old worker refuse tasks meant for the new
one, duplicate digests being skipped, a flaky task failing with its API token
redacted, and a crontab that runs at 9:00 India time. `docker compose down`
throws it all away.

> Early days. Until 1.0, expect breaking changes between minor versions
> (0.1 to 0.2). Pin the version you use.

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
percival import --app proj.celery:app --redis-url redis://localhost:6379/0
```

(Or press **import** on the board, which lists what your workers published.)

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

The panel is one container, configured the way you'd configure Flower: with
environment variables.

```
docker run -d -p 8080:8080 -v percival:/data \
  -e PERCIVAL_REDIS_URL=redis://redis:6379/0 \
  -e PERCIVAL_ADMIN_PASSWORD=pick-a-long-one \
  ghcr.io/rijinraju/percival
```

Everything is optional. Leave out the URLs or the admin and the first visit
asks for them instead (connections entered there are stored encrypted).

| env | default | |
|---|---|---|
| `PERCIVAL_REDIS_URL` | none | where RedBeat and `percival.init()` keep their keys |
| `PERCIVAL_BROKER_URL` | the Redis URL | needed when the broker isn't Redis; `CELERY_BROKER_URL` works too |
| `PERCIVAL_ADMIN_USERNAME` / `PERCIVAL_ADMIN_PASSWORD` | `admin` / none | creates the first admin on startup, only if nobody exists yet |
| `PERCIVAL_SECRET_KEY` | generated into `/data/secret_key` | set it yourself if `/data` isn't somewhere you trust |
| `PERCIVAL_DATABASE_URL` | SQLite in `/data` | Postgres works too |
| `PERCIVAL_REDBEAT_KEY_PREFIX` / `PERCIVAL_KEY_PREFIX` | `redbeat:` / `percival` | only if you changed them in your Celery config |
| `PERCIVAL_SECURE_COOKIES` | on | turn off only for plain http on localhost |

Keep `/data` on a volume: it holds users, run history and the generated key.
The schedules themselves live in Redis, so turn on Redis persistence.

Without Docker, from a checkout:

```
cd web && npm ci && npm run build && cd ..
pip install -e client -e server
percival-server
```

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
is blocked on that worker, since there's no way to tell it's current.

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
