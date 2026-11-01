"""What a schedule looks like over the API, and turning that into celery objects."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import schedule
from pydantic import BaseModel, Field, field_validator

from percival.schedules import zoned_crontab

# beat_schedule allows any name, so imported ones can have spaces etc. the only
# hard rule is no slashes (they go in URLs) and no control characters
NAME_RE = re.compile(r"^[^\s/\x00-\x1f][^/\x00-\x1f]{0,199}$")


class CrontabSpec(BaseModel):
    type: Literal["crontab"] = "crontab"
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


class IntervalSpec(BaseModel):
    type: Literal["interval"] = "interval"
    every: float = Field(gt=0, description="seconds")


class OnceSpec(BaseModel):
    type: Literal["once"] = "once"
    at: datetime


ScheduleSpec = Annotated[CrontabSpec | IntervalSpec | OnceSpec, Field(discriminator="type")]


class Options(BaseModel):
    queue: str | None = Field(default=None, max_length=200)
    priority: int | None = Field(default=None, ge=0, le=255)
    expires: float | None = Field(default=None, gt=0, description="seconds after dispatch")
    required_version: str | None = Field(default=None, max_length=100)


class ScheduleIn(BaseModel):
    name: str
    task: str = Field(min_length=1, max_length=255)
    schedule: ScheduleSpec
    timezone: str = "UTC"
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    options: Options = Field(default_factory=Options)
    enabled: bool = True
    notes: str = Field(default="", max_length=5000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError("no slashes, and it can't start with a space")
        return value

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


class SchedulePatch(BaseModel):
    task: str | None = Field(default=None, min_length=1, max_length=255)
    schedule: ScheduleSpec | None = None
    timezone: str | None = None
    args: list[Any] | None = None
    kwargs: dict[str, Any] | None = None
    options: Options | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


class InvalidSchedule(ValueError):
    pass


def build(spec: CrontabSpec | IntervalSpec | OnceSpec, tz: str) -> Any:
    """Celery schedule object for a spec. Raises InvalidSchedule with
    something a human can act on."""
    if isinstance(spec, CrontabSpec):
        try:
            return zoned_crontab(
                spec.minute,
                spec.hour,
                spec.day_of_week,
                spec.day_of_month,
                spec.month_of_year,
                timezone=tz,
            )
        except ValueError as exc:
            raise InvalidSchedule(f"bad cron expression: {exc}") from exc
    if isinstance(spec, IntervalSpec):
        return schedule(run_every=spec.every)

    from redbeat.schedules import rrule

    at = spec.at if spec.at.tzinfo else spec.at.replace(tzinfo=ZoneInfo(tz))
    if at <= datetime.now(timezone.utc):
        raise InvalidSchedule("that time is already in the past")
    return rrule("MINUTELY", dtstart=at, count=1)
