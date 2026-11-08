"""Client side of Percival. Installed in the Celery project, not in the panel.

import percival
percival.init(app, redis_url="redis://...", code_version=os.environ["GIT_SHA"])
"""

from __future__ import annotations

import logging
from typing import Any

__version__ = "0.1.3"

from percival.config import UNKNOWN_VERSION, Settings
from percival.dedupe import once_per
from percival.runtime import ClientFactory, Runtime

log = logging.getLogger(__name__)

__all__ = ["Settings", "__version__", "init", "once_per", "shutdown"]


def init(
    app: Any,
    redis_url: str | None = None,
    code_version: str | None = None,
    *,
    client_factory: ClientFactory | None = None,
    **options: Any,
) -> Runtime:
    """Wire percival into a celery app. Safe to call more than once.

    Any field of :class:`percival.Settings` can be passed as a keyword, e.g.
    ``redact_kwargs=[...]``, ``stale_action="drop"``, ``capture_args=False``.
    ``client_factory`` exists for tests, you shouldn't need it.
    """
    # imported here so `import percival` stays cheap for things like the CLI
    from percival import gate, heartbeat, metadata, runtime, signals

    settings = Settings.build(redis_url=redis_url, code_version=code_version, **options)
    if settings.code_version == UNKNOWN_VERSION:
        log.warning(
            "percival: no code_version set. pass code_version= or set PERCIVAL_CODE_VERSION, "
            "otherwise schedules that require a version will be blocked on this worker"
        )

    rt = runtime.configure(settings, client_factory=client_factory)
    signals.connect()
    heartbeat.connect()
    metadata.connect()
    gate.connect()

    # if the worker is already up (init called late), gate the tasks now
    if getattr(app, "finalized", False):
        gate.install(app)
    return rt


def shutdown() -> None:
    """Undo init(). Mostly useful in tests."""
    from percival import gate, heartbeat, metadata, runtime, signals

    signals.disconnect()
    heartbeat.disconnect()
    metadata.disconnect()
    gate.disconnect()
    runtime.reset()
