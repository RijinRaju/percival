"""Move an app's static ``beat_schedule`` into RedBeat so it can be managed live.

We go through redbeat's own entry class for writing, so whatever ends up in
redis is exactly what ``redbeat.RedBeatScheduler`` expects to read.

One thing to know: RedBeat re-syncs ``beat_schedule`` entries from config
every time beat starts. If you import and keep the same names in config,
the config wins on the next restart. Remove them from config after import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from celery.schedules import BaseSchedule
from celery.schedules import schedule as celery_schedule

from percival.naming import Headers
from percival.schedules import describe, humanize

CREATE = "create"
UPDATE = "update"
SAME = "same"
SKIP = "skip"


@dataclass
class Planned:
    name: str
    task: str
    schedule: Any
    args: list[Any]
    kwargs: dict[str, Any]
    options: dict[str, Any]
    action: str = CREATE
    changes: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def human(self) -> str:
        return humanize(describe(self.schedule))


def _redbeat(app: Any) -> Any:
    try:
        from redbeat.schedulers import RedBeatSchedulerEntry, ensure_conf
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "the importer needs celery-redbeat installed: pip install celery-redbeat"
        ) from exc
    ensure_conf(app)
    return RedBeatSchedulerEntry


def configure_redbeat(app: Any, redis_url: str | None, key_prefix: str | None) -> None:
    # redbeat caches its config on the app the first time it's touched, so
    # this has to happen before anything else asks for it
    if redis_url:
        app.conf.redbeat_redis_url = redis_url
    if key_prefix:
        app.conf.redbeat_key_prefix = key_prefix
    if hasattr(app, "redbeat_conf"):
        del app.redbeat_conf


def _normalise_schedule(value: Any) -> Any:
    # crontab/solar/schedule all share BaseSchedule, crontab is not a schedule subclass
    if isinstance(value, BaseSchedule):
        return value
    # plain numbers and timedeltas are what beat_schedule usually has
    return celery_schedule(run_every=value)


def plan(
    app: Any,
    *,
    require_version: str | None = None,
    only: list[str] | None = None,
) -> list[Planned]:
    entry_cls = _redbeat(app)
    beat_schedule = app.conf.beat_schedule or {}
    planned: list[Planned] = []

    for name, raw in beat_schedule.items():
        if only and name not in only:
            continue

        options = dict(raw.get("options") or {})
        headers = dict(options.get("headers") or {})
        headers.setdefault(Headers.SCHEDULE, name)
        headers.setdefault(Headers.ORIGIN, "imported")
        if require_version:
            headers[Headers.REQUIRED_VERSION] = require_version
        options["headers"] = headers

        item = Planned(
            name=name,
            task=raw.get("task", ""),
            schedule=raw.get("schedule"),
            args=list(raw.get("args") or ()),
            kwargs=dict(raw.get("kwargs") or {}),
            options=options,
        )

        if not item.task:
            item.action, item.note = SKIP, "no task name"
            planned.append(item)
            continue
        if raw.get("relative"):
            # redbeat ignores relative=True, better to say so than to silently shift times
            item.note = "relative=True is not supported by redbeat, will run unaligned"
        try:
            item.schedule = _normalise_schedule(item.schedule)
        except Exception as exc:
            item.action, item.note = SKIP, f"unsupported schedule: {exc}"
            planned.append(item)
            continue

        key = entry_cls.generate_key(app, name)
        try:
            existing = entry_cls.from_key(key, app=app)
        except KeyError:
            existing = None

        if existing is not None:
            item.changes = _diff(existing, item)
            item.action = UPDATE if item.changes else SAME
        planned.append(item)

    return planned


def _diff(existing: Any, item: Planned) -> list[str]:
    changes = []
    if existing.task != item.task:
        changes.append("task")
    if _encode(existing.schedule) != _encode(item.schedule):
        changes.append("schedule")
    if list(existing.args or ()) != item.args:
        changes.append("args")
    if dict(existing.kwargs or {}) != item.kwargs:
        changes.append("kwargs")
    if _encode(existing.options or {}) != _encode(item.options):
        changes.append("options")
    return changes


def _encode(value: Any) -> str:
    from redbeat.decoder import RedBeatJSONEncoder

    return json.dumps(value, cls=RedBeatJSONEncoder, sort_keys=True)


def apply(app: Any, planned: list[Planned]) -> int:
    entry_cls = _redbeat(app)
    written = 0
    for item in planned:
        if item.action not in (CREATE, UPDATE):
            continue
        entry = entry_cls(
            name=item.name,
            task=item.task,
            schedule=item.schedule,
            args=item.args,
            kwargs=item.kwargs,
            options=item.options,
            app=app,
        )
        if item.action == UPDATE:
            # keep the paused/running state and the last run, otherwise an
            # update would either resume a paused job or make it fire right away
            old = entry_cls.from_key(entry.key, app=app)
            entry.enabled = old.enabled
            entry.last_run_at = old.last_run_at
        entry.save()
        written += 1
    return written


def render(planned: list[Planned]) -> str:
    if not planned:
        return "nothing in beat_schedule"
    rows = [("", "NAME", "TASK", "SCHEDULE", "NOTES")]
    marks = {CREATE: "+", UPDATE: "~", SAME: "=", SKIP: "!"}
    for item in planned:
        notes = item.note
        if item.changes:
            notes = (
                "changed: " + ", ".join(item.changes) + ("; " + notes if notes else "")
            ).strip()
        rows.append((marks[item.action], item.name, item.task, item.human, notes))

    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    lines = []
    for row in rows:
        cells = [row[i].ljust(widths[i]) for i in range(4)] + [row[4]]
        lines.append("  ".join(cells).rstrip())

    counts = {a: sum(1 for p in planned if p.action == a) for a in marks}
    lines.append("")
    lines.append(
        f"{counts[CREATE]} new, {counts[UPDATE]} changed, "
        f"{counts[SAME]} unchanged, {counts[SKIP]} skipped"
    )
    return "\n".join(lines)
