---
title: Percival, a control panel for Celery beat
description: Change Celery beat schedules from a UI without restarting beat or workers, and stop duplicate runs and stale workers running old code. Self-hosted, open source.
---

# Percival

A self-hosted control panel for Celery. Change schedules without restarting
beat or workers, and stop the two things ping monitors can't see: a task
running twice, and a stale worker running old code.

Your tasks stay in your code. Percival decides when they run, shows you what
happened, and keeps an old deploy from running a schedule meant for a new
one.

## Quickstart

If you already run Celery with Redis, it's three commands and a few lines of
code.

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
tasks show up under Tasks. Pick one and give it a schedule. Already have a
`beat_schedule`? Press **import** on the board.

`host.docker.internal` is how a container reaches Redis on your own machine
(Docker Desktop). On a server, use the Redis hostname your workers use. If
your broker is RabbitMQ, also pass `PERCIVAL_BROKER_URL`.

## See it without touching your code

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

!!! note "The demo is for your own machine"
    Its login is public on purpose. Don't run the demo stack on a server
    anyone else can reach. For real use, follow
    [Self-hosting the panel](guide/panel.md).

## What you get

- **Schedules you can change live.** Edit a crontab or interval in the panel
  and beat picks it up within 15 seconds. No redeploy, no restarts.
- **Per-schedule timezones.** "9:00 in Asia/Kolkata" stays 9:00 local,
  daylight saving time included.
- **A stale worker gate.** A schedule can require a code version. A worker
  still on the old deploy hands the task back instead of running old code.
- **Duplicate protection.** `@once_per` skips the second run for the same key
  in the same window.
- **Run history.** Every start, success, failure and retry, with timing,
  worker, version and args (secrets redacted before they leave the worker).
- **An audit log** of who changed which schedule.

## Why I built this

Our schedules lived in a hand-edited `beat_schedule`. Changing one meant
editing config, redeploying, and restarting beat and every worker by hand.

We changed an email task from "Monday and Thursday" to "every 5 minutes,
per user timezone". During the rollout one worker hadn't restarted yet. It
was still on the old code while beat was already firing every 5 minutes, and
users got emails they were never supposed to get.

Nothing told us the workers were on different versions, and nothing stopped
the task from running twice. Percival is the tool that would have caught it.

Percival is open source under the MIT license.
[Source on GitHub](https://github.com/RijinRaju/percival),
packages on [PyPI](https://pypi.org/project/percival/).
