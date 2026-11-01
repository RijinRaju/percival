"""Every name we put into Redis or onto a Celery message comes from here.

The project might get renamed, and the panel reads the same keys, so nothing
else in the codebase should hardcode the "percival" string.
"""

from __future__ import annotations

NAME = "percival"
ENV_PREFIX = NAME.upper() + "_"


class Headers:
    """Custom message headers. The panel writes them into RedBeat entry options."""

    REQUIRED_VERSION = f"{NAME}_required_version"
    SCHEDULE = f"{NAME}_schedule"
    REQUEUES = f"{NAME}_requeues"
    # where an entry came from: "imported", "ui", "api"
    ORIGIN = f"{NAME}_origin"
    # IANA zone a crontab should be evaluated in, see percival.beat
    TIMEZONE = f"{NAME}_timezone"


class Keys:
    """Redis key layout, scoped under a configurable prefix."""

    def __init__(self, prefix: str = NAME) -> None:
        self.prefix = prefix.rstrip(":")

    @property
    def events(self) -> str:
        return f"{self.prefix}:events"

    @property
    def tasks(self) -> str:
        return f"{self.prefix}:tasks"

    @property
    def beat(self) -> str:
        return f"{self.prefix}:beat"

    @property
    def beat_schedule(self) -> str:
        return f"{self.prefix}:beat_schedule"

    def worker(self, hostname: str) -> str:
        return f"{self.prefix}:worker:{hostname}"

    @property
    def worker_pattern(self) -> str:
        return f"{self.prefix}:worker:*"

    def once(self, task: str, key: str, bucket: str) -> str:
        return f"{self.prefix}:once:{task}:{key}:{bucket}"
