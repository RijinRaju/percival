---
title: Moving an existing beat_schedule into Percival
description: Import the entries of your Celery beat_schedule into RedBeat with the percival import command or the panel, then manage them without redeploys.
---

# Moving an existing beat_schedule

If your schedules are in `app.conf.beat_schedule` today, you can bring them
over in one step.

```
percival import --app proj.celery:app --redis-url redis://localhost:6379/0
```

This is a dry run. It prints what would be created or changed and writes
nothing. Add `--apply` to write the entries to RedBeat.

You can also press **import** on the panel's board. It lists what your
workers published and lets you pick.

## Afterwards

Remove the imported entries from `beat_schedule`. RedBeat re-syncs config
entries every time beat starts, so anything left in config overwrites what
you change in the panel.

Then run beat with `percival.beat.Scheduler`, as described in
[Running beat](beat.md).
