"""Plain-dict descriptions of celery schedule objects.

Used for publishing the app's ``beat_schedule`` to the panel and by the
importer. Keep this free of redbeat imports, workers don't need redbeat.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from celery.schedules import BaseSchedule, crontab, schedule, solar

CRON_FIELDS = ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")


# lowercase like celery's own schedule classes
class zoned_crontab(crontab):  # type: ignore[misc]
    """A crontab evaluated in its own timezone instead of the app's.

    Stock celery takes the zone from ``app.timezone``, and RedBeat doesn't
    store one at all, so this is how per-schedule timezones work. DST is
    handled as wall clock time: "9:00 Europe/London" stays 9:00 local.
    """

    def __init__(
        self,
        minute: Any = "*",
        hour: Any = "*",
        day_of_week: Any = "*",
        day_of_month: Any = "*",
        month_of_year: Any = "*",
        *,
        timezone: str,
        **kwargs: Any,
    ) -> None:
        self.zone_name = timezone
        self.zone = ZoneInfo(timezone)
        super().__init__(minute, hour, day_of_week, day_of_month, month_of_year, **kwargs)

    @classmethod
    def from_crontab(cls, cron: crontab, timezone: str, **kwargs: Any) -> zoned_crontab:
        return cls(*(getattr(cron, f"_orig_{f}") for f in CRON_FIELDS), timezone=timezone, **kwargs)

    @property
    def tz(self) -> Any:
        return self.zone

    @property
    def utc_enabled(self) -> bool:
        # makes to_local() leave our aware datetimes alone
        return True

    def now(self) -> datetime:
        current = self.nowfun() if self.nowfun else datetime.now(timezone.utc)
        aware: datetime = self.maybe_make_aware(current)
        return aware.astimezone(self.zone)

    def remaining_delta(self, last_run_at: datetime, tz: Any = None, ffwd: Any = None) -> Any:
        # celery compares last_run_at.hour/day against the cron fields as-is,
        # so it has to be in our zone first, not whatever it was stored in
        last_run_at = self.maybe_make_aware(last_run_at).astimezone(self.zone)
        if ffwd is None:
            return super().remaining_delta(last_run_at, tz)
        return super().remaining_delta(last_run_at, tz, ffwd)

    def remaining_estimate(self, last_run_at: datetime, ffwd: Any = None) -> timedelta:
        # same as celery >= 5.5. older versions subtract two datetimes in the
        # same zone, which python does in wall clock time, so a 9:00 London
        # run lands at 8:00 the week the clocks go back
        if ffwd is None:
            start, ends_in, now = self.remaining_delta(last_run_at)
        else:
            start, ends_in, now = self.remaining_delta(last_run_at, ffwd=ffwd)
        end: datetime = start + ends_in
        current: datetime = now
        return end.astimezone(timezone.utc) - current.astimezone(timezone.utc)

    def __reduce__(self) -> Any:
        return (
            _rebuild_zoned,
            (*(getattr(self, f"_orig_{f}") for f in CRON_FIELDS), self.zone_name),
        )

    def __repr__(self) -> str:
        return f"<zoned_crontab: {humanize(describe(self))} {self.zone_name}>"


def _rebuild_zoned(*args: Any) -> zoned_crontab:
    *fields, zone = args
    return zoned_crontab(*fields, timezone=zone)


def describe(sched: Any) -> dict[str, Any]:
    if isinstance(sched, crontab):
        desc = {
            "type": "crontab",
            **{f: str(getattr(sched, f"_orig_{f}")) for f in CRON_FIELDS},
        }
        if isinstance(sched, zoned_crontab):
            desc["timezone"] = sched.zone_name
        return desc
    # redbeat's rrule, duck typed so this module doesn't need redbeat
    if getattr(sched, "count", None) == 1 and getattr(sched, "dtstart", None) is not None:
        return {"type": "once", "at": sched.dtstart.isoformat()}
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
    if kind == "once":
        return f"once at {desc['at']}"
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


def next_runs(sched: Any, count: int = 5, now: datetime | None = None) -> list[datetime]:
    """The next ``count`` fire times after ``now``, in UTC.

    Goes through the schedule's own ``remaining_estimate`` with a pinned
    clock, so the preview uses exactly the maths beat will use.
    """
    if not isinstance(sched, BaseSchedule):
        sched = schedule(run_every=sched)
    cursor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: list[datetime] = []
    # pin the clock on the object itself and put it back after. copying would
    # be nicer but redbeat's rrule doesn't survive copy.copy
    original = sched.nowfun
    try:
        for _ in range(count):
            current = cursor
            sched.nowfun = lambda current=current: current
            remaining = sched.remaining_estimate(current)
            if remaining is None:
                break
            if remaining.total_seconds() <= 0:
                # an interval reports "due now" against itself, step past it
                remaining = getattr(sched, "run_every", None) or timedelta(seconds=1)
            cursor = (current + remaining).astimezone(timezone.utc)
            out.append(cursor)
    finally:
        sched.nowfun = original
    return out
