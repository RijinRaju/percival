---
title: Self-hosting the Percival panel
description: Run the Percival panel for Celery as one Docker container, configured with environment variables like Flower. Logins, Postgres, reverse proxy and backups.
---

# Self-hosting the panel

The panel is one container, configured the way you'd configure Flower: with
environment variables.

```
docker run -d -p 8080:8080 -v percival:/data \
  -e PERCIVAL_REDIS_URL=redis://redis:6379/0 \
  -e PERCIVAL_ADMIN_USERNAME=rijin \
  -e PERCIVAL_ADMIN_PASSWORD=pick-a-long-one \
  ghcr.io/rijinraju/percival
```

Everything is optional. Leave out the URLs or the admin and the first visit
asks for them instead. Connections entered there are stored encrypted.

## Settings

| env | default | |
|---|---|---|
| `PERCIVAL_REDIS_URL` | none | where RedBeat and `percival.init()` keep their keys |
| `PERCIVAL_BROKER_URL` | the Redis URL | needed when the broker isn't Redis; `CELERY_BROKER_URL` works too |
| `PERCIVAL_ADMIN_USERNAME` / `PERCIVAL_ADMIN_PASSWORD` | `admin` / none | creates the first admin on startup, only if nobody exists yet |
| `PERCIVAL_SECRET_KEY` | generated into `/data/secret_key` | set it yourself if `/data` isn't somewhere you trust |
| `PERCIVAL_DATABASE_URL` | SQLite in `/data` | Postgres works too |
| `PERCIVAL_REDBEAT_KEY_PREFIX` / `PERCIVAL_KEY_PREFIX` | `redbeat:` / `percival` | only if you changed them in your Celery config |
| `PERCIVAL_SECURE_COOKIES` | on | turn off only for plain http on localhost |

## Logins

The first admin comes from `PERCIVAL_ADMIN_USERNAME` and
`PERCIVAL_ADMIN_PASSWORD`, or from the setup page on the first visit.
Passwords need at least 10 characters.

The environment variables are only read while there are no users. Changing
them later doesn't change an existing password, so a restart never undoes a
password you changed in the panel. Add more users, change your password and
create API tokens under Settings.

## Data and backups

Keep `/data` on a volume. It holds users, run history, the audit log and the
generated secret key. Back it up with the rest of your data.

The schedules themselves live in Redis, so turn on Redis persistence.

## Behind a reverse proxy

Put the panel behind a reverse proxy with TLS (nginx, Caddy, Traefik) if
anyone besides you will reach it. API docs are at `/api/docs` once you're
logged in.

## Without Docker

```
pip install percival-server
PERCIVAL_REDIS_URL=redis://localhost:6379/0 \
PERCIVAL_ADMIN_PASSWORD=pick-a-long-one \
percival-server
```

It listens on `127.0.0.1:8080`. Change that with `PERCIVAL_HOST` and
`PERCIVAL_PORT`, and the data directory with `PERCIVAL_DATA_DIR`.
