---
title: Percival compared with Flower, django-celery-beat and RedBeat
description: How Percival differs from Flower, django-celery-beat, RedBeat, Healthchecks and Cronitor for managing and monitoring Celery beat schedules.
---

# How it compares

Each of these tools is good at its job. None of them would have caught the
incident that started Percival: a stale worker running old code while beat
fired a new schedule.

| | change schedules from a UI | no restarts | per-schedule timezone | stale worker gate | duplicate guard |
|---|---|---|---|---|---|
| **Percival** | yes | yes | yes | yes | yes |
| Flower | no | n/a | n/a | no | no |
| django-celery-beat | yes (Django admin) | yes | yes | no | no |
| RedBeat | no UI | yes | no | no | no |
| Healthchecks, Cronitor | no | n/a | n/a | no | no |

**Flower** shows workers and tasks as they run. It doesn't manage beat
schedules. Percival and Flower can run side by side.

**django-celery-beat** stores schedules in your Django database and edits
them in the Django admin. It's tied to Django. Percival works with any
Celery app.

**RedBeat** keeps schedules in Redis so they can change at runtime, but it has
no UI. Percival is built on RedBeat and adds the panel, timezones and a
heartbeat.

**Healthchecks and Cronitor** tell you whether a ping arrived on time. They
can't tell a duplicate run from a correct one, or know which version of your
code a worker runs.
