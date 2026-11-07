---
title: Running Celery beat with Percival
description: Run celery beat with percival.beat.Scheduler, a RedBeat scheduler with per-schedule timezones, a heartbeat and 15 second pickup of schedule changes.
---

# Running beat

```
celery -A proj beat -S percival.beat.Scheduler
```

Schedules live in Redis, managed by [RedBeat](https://github.com/sibson/redbeat),
which is installed with the client. `percival.beat.Scheduler` is RedBeat with
three additions:

- **Crontabs follow their own timezone.** Each schedule can have one, and
  daylight saving time is handled as wall clock time: "9:00 Europe/London"
  stays 9:00 local when the clocks change.
- **A heartbeat.** Beat writes one every tick, so the panel knows it's alive
  and whether your last change was picked up.
- **Faster pickup.** It checks for new schedules every 15 seconds instead of
  up to every 5 minutes.

Plain `redbeat.RedBeatScheduler` still works with everything the panel
writes. You just lose the three things above.

## Run one beat

As with any Celery beat, run exactly one. RedBeat takes a lock in Redis so a
second beat waits instead of double firing. If beat is killed hard, the lock
stays until it times out (about 25 minutes by default). The panel shows a
banner when that happens.

## Keep Redis persistent

Your schedules are stored in Redis, so turn on Redis persistence (AOF or RDB
snapshots). If Redis loses its data, the schedules go with it.
