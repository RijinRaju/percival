# percival

The client half of [Percival](https://github.com/RijinRaju/percival), a
self-hosted control panel for Celery. You install it in your Celery project.
It lets the panel change schedules without restarting beat or workers, and it
stops two things a ping monitor can't see: a task running twice, and a stale
worker running old code.

Needs Celery 5.3+ and Redis. The broker can be Redis or RabbitMQ.

## Setup

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
```

Then run the panel, one container:

```
docker run -d -p 8080:8080 -v percival:/data \
  -e PERCIVAL_REDIS_URL=redis://host.docker.internal:6379/0 \
  -e PERCIVAL_ADMIN_PASSWORD=pick-a-long-one \
  ghcr.io/rijinraju/percival
```

Or install it with `pip install percival-server`.

## What `init()` sets up

- **Run events.** Started, success, failure, retry and revoked go to a Redis
  stream, with timing, worker, code version and redacted args. Anything named
  like `password`, `token` or `secret` is replaced before it leaves the worker.
- **Worker heartbeat.** Every worker reports its hostname, queues and code
  version every 30 seconds.
- **Task metadata.** The signature, docstring and source of each task, so the
  panel can show them. Pass `publish_source=False` to keep source private.
- **Stale worker gate.** A schedule can require a code version. A worker on a
  different version doesn't run the task. The message goes back on the queue
  for an up-to-date worker.

## Stopping duplicate runs

```python
from percival import once_per


@app.task
@once_per(key=lambda user_id, **kw: user_id, window="1d")
def send_digest(user_id): ...
```

A second run for the same key in the same window is skipped and recorded.

## Moving an existing `beat_schedule`

```
percival import --app proj.celery:app --redis-url redis://localhost:6379/0 --apply
```

Then remove those entries from `beat_schedule`.

The [full README](https://github.com/RijinRaju/percival#readme) has every
option and a `docker compose up` demo.
