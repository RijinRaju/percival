"""Reading and writing schedules in RedBeat's own format.

Everything goes through ``percival.beat.Entry`` (a RedBeatSchedulerEntry), so
what we write is exactly what beat reads, and the zset score is computed
with the schedule's timezone applied.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from celery import Celery
from redbeat.decoder import RedBeatJSONDecoder
from redbeat.schedulers import get_redis

from percival.beat import Entry
from percival.naming import Headers
from percival.schedules import describe, humanize, next_runs
from percival_server.schedules.spec import CrontabSpec, ScheduleIn, build


class NotFound(KeyError):
    pass


def _key(app: Celery, name: str) -> str:
    key: str = Entry.generate_key(app, name)
    return key


def list_entries(app: Celery) -> list[Entry]:
    client = get_redis(app)
    keys = client.zrange(app.redbeat_conf.schedule_key, 0, -1)
    if not keys:
        return []
    with client.pipeline() as pipe:
        for key in keys:
            pipe.hget(key, "definition")
            pipe.hget(key, "meta")
        raw = pipe.execute()

    entries = []
    for i in range(0, len(raw), 2):
        definition, meta = raw[i], raw[i + 1]
        if not definition:
            continue
        entries.append(_from_raw(app, definition, meta))
    entries.sort(key=lambda e: e.name)
    return entries


def _from_raw(app: Celery, definition: str, meta: str | None) -> Entry:
    data = json.loads(definition, cls=RedBeatJSONDecoder)
    decoded_meta = Entry.decode_meta(meta)
    data.update(decoded_meta)
    entry = Entry(app=app, **data)
    entry.last_run_at = decoded_meta.get("last_run_at")
    return entry


def get(app: Celery, name: str) -> Entry:
    try:
        return Entry.from_key(_key(app, name), app=app)
    except KeyError as exc:
        raise NotFound(name) from exc


def exists(app: Celery, name: str) -> bool:
    return bool(get_redis(app).exists(_key(app, name)))


def save(app: Celery, spec: ScheduleIn, *, origin: str, previous: Entry | None = None) -> Entry:
    headers = dict(((previous.options or {}).get("headers") or {}) if previous else {})
    headers[Headers.SCHEDULE] = spec.name
    headers.setdefault(Headers.ORIGIN, origin)
    headers[Headers.TIMEZONE] = spec.timezone
    if spec.options.required_version:
        headers[Headers.REQUIRED_VERSION] = spec.options.required_version
    else:
        headers.pop(Headers.REQUIRED_VERSION, None)

    options: dict[str, Any] = {"headers": headers}
    if spec.options.queue:
        options["queue"] = spec.options.queue
    if spec.options.priority is not None:
        options["priority"] = spec.options.priority
    if spec.options.expires is not None:
        options["expires"] = spec.options.expires

    entry = Entry(
        name=spec.name,
        task=spec.task,
        schedule=build(spec.schedule, spec.timezone),
        args=spec.args,
        kwargs=spec.kwargs,
        enabled=spec.enabled,
        options=options,
        app=app,
    )
    if previous is not None and previous.last_run_at is not None:
        # keeps the next run where it was instead of counting from "now"
        entry.last_run_at = previous.last_run_at
    entry.save()
    return entry


def set_enabled(app: Celery, name: str, enabled: bool) -> Entry:
    entry = get(app, name)
    entry.enabled = enabled
    entry.save()
    return entry


def delete(app: Celery, name: str) -> None:
    get(app, name).delete()


def to_spec(entry: Entry) -> ScheduleIn:
    """The other direction, used for PATCH and for audit diffs."""
    desc = describe(entry.schedule)
    options = entry.options or {}
    headers = options.get("headers") or {}
    sched: Any
    if desc["type"] == "crontab":
        sched = CrontabSpec(**{k: v for k, v in desc.items() if k not in ("type", "timezone")})
    elif desc["type"] == "interval":
        sched = {"type": "interval", "every": desc["every"]}
    elif desc["type"] == "once":
        sched = {"type": "once", "at": desc["at"]}
    else:
        raise ValueError(f"can't edit a {desc['type']} schedule from the panel")
    return ScheduleIn.model_validate(
        {
            "name": entry.name,
            "task": entry.task,
            "schedule": sched,
            "timezone": headers.get(Headers.TIMEZONE) or "UTC",
            "args": list(entry.args or []),
            "kwargs": dict(entry.kwargs or {}),
            "options": {
                "queue": options.get("queue"),
                "priority": options.get("priority"),
                "expires": options.get("expires"),
                "required_version": headers.get(Headers.REQUIRED_VERSION),
            },
            "enabled": bool(entry.enabled),
        },
        # stored data may predate validation rules, don't refuse to show it
        strict=False,
    )


def serialize(entry: Entry, now: datetime | None = None, count: int = 1) -> dict[str, Any]:
    desc = describe(entry.schedule)
    options = entry.options or {}
    headers = options.get("headers") or {}
    upcoming = [] if not entry.enabled else next_runs(entry.schedule, count, now=now)
    return {
        "name": entry.name,
        "task": entry.task,
        "schedule": desc,
        "human": humanize(desc),
        "timezone": headers.get(Headers.TIMEZONE),
        "args": list(entry.args or []),
        "kwargs": dict(entry.kwargs or {}),
        "queue": options.get("queue"),
        "priority": options.get("priority"),
        "expires": options.get("expires"),
        "required_version": headers.get(Headers.REQUIRED_VERSION),
        "origin": headers.get(Headers.ORIGIN),
        "enabled": bool(entry.enabled),
        "last_run_at": entry.last_run_at,
        "total_run_count": getattr(entry, "total_run_count", None),
        "next_runs": upcoming,
    }
