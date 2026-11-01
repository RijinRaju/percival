"""Plain-dict descriptions of celery schedule objects.

Used for publishing the app's ``beat_schedule`` to the panel and by the
importer. Keep this free of redbeat imports, workers don't need redbeat.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from celery.schedules import crontab, schedule, solar

CRON_FIELDS = ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")


def describe(sched: Any) -> dict[str, Any]:
    if isinstance(sched, crontab):
        return {
            "type": "crontab",
            **{f: str(getattr(sched, f"_orig_{f}")) for f in CRON_FIELDS},
        }
    if isinstance(sched, solar):
        return {"type": "solar", "event": sched.event, "lat": sched.lat, "lon": sched.lon}
    if isinstance(sched, schedule):
        return {"type": "interval", "every": sched.run_every.total_seconds()}
    if isinstance(sched, timedelta):
        return {"type": "interval", "every": sched.total_seconds()}
    if isinstance(sched, (int, float)):
        return {"type": "interval", "every": float(sched)}
    return {"type": "unknown", "repr": repr(sched)}


def humanize(desc: dict[str, Any]) -> str:
    kind = desc.get("type")
    if kind == "interval":
        return "every " + _seconds_to_words(float(desc["every"]))
    if kind == "crontab":
        return " ".join(desc[f] for f in CRON_FIELDS)
    if kind == "solar":
        return f"solar {desc['event']} at {desc['lat']},{desc['lon']}"
    return str(desc.get("repr", "?"))


def _seconds_to_words(seconds: float) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size and seconds % size == 0:
            n = int(seconds // size)
            return f"{n} {unit}" + ("s" if n != 1 else "")
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds}s"


def describe_beat_schedule(beat_schedule: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, entry in (beat_schedule or {}).items():
        desc = describe(entry.get("schedule"))
        out[name] = {
            "task": entry.get("task"),
            "schedule": desc,
            "human": humanize(desc),
            "args": list(entry.get("args") or ()),
            "kwargs": dict(entry.get("kwargs") or {}),
            "options": dict(entry.get("options") or {}),
            "relative": bool(entry.get("relative", False)),
        }
    return out
