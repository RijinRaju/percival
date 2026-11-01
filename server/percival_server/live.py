"""What's happening right now, straight from redis: worker heartbeats, the
beat heartbeat, and the task metadata workers publish on start."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from percival_server.connections import Connections
from percival_server.models import WorkerSeen

DEFAULT_QUEUE = "celery"


def _ts(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def read_workers(conns: Connections) -> list[dict[str, Any]]:
    client = conns.redis()
    keys = sorted(client.scan_iter(match=conns.keys.worker_pattern, count=500))
    if not keys:
        return []
    workers = []
    for raw in client.mget(keys):
        if not raw:
            continue  # expired between scan and mget
        data = json.loads(raw)
        data["started_at"] = _ts(data.get("started_at"))
        data["last_seen"] = _ts(data.get("last_seen"))
        data["alive"] = True
        workers.append(data)
    return workers


def remember_workers(db: Session, workers: list[dict[str, Any]]) -> None:
    for w in workers:
        row = db.get(WorkerSeen, w["hostname"])
        if row is None:
            row = WorkerSeen(hostname=w["hostname"])
            db.add(row)
        row.code_version = w.get("code_version")
        row.queues = w.get("queues")
        row.pid = w.get("pid")
        row.started_at = w.get("started_at")
        row.last_seen = w.get("last_seen") or datetime.now(timezone.utc)


def version_summary(workers: list[dict[str, Any]]) -> dict[str, Any]:
    """Which version is current and who's behind.

    "Current" is whatever the most recently started live worker runs. That's
    a guess, but during a rollout it's the right one: new pods come up on the
    new version while old ones are still draining.
    """
    alive = [w for w in workers if w.get("alive")]
    if not alive:
        return {"current": None, "versions": [], "mismatch": False}

    newest = max(
        alive, key=lambda w: w.get("started_at") or datetime.min.replace(tzinfo=timezone.utc)
    )
    current = newest.get("code_version")
    groups: dict[str, list[str]] = {}
    for w in alive:
        groups.setdefault(w.get("code_version") or "unknown", []).append(w["hostname"])

    versions = [
        {"version": v, "count": len(hosts), "workers": sorted(hosts), "stale": v != current}
        for v, hosts in sorted(groups.items(), key=lambda kv: (kv[0] != current, kv[0]))
    ]
    return {"current": current, "versions": versions, "mismatch": len(groups) > 1}


def queue_coverage(
    workers: list[dict[str, Any]], queue: str | None, required: str | None
) -> dict[str, Any]:
    """For one schedule: who will pick it up, and who would refuse it."""
    queue = queue or DEFAULT_QUEUE
    consumers = [w for w in workers if w.get("alive") and queue in (w.get("queues") or [])]
    if not required:
        return {"queue": queue, "consumers": len(consumers), "matching": len(consumers), "stale": 0}
    matching = [w for w in consumers if w.get("code_version") == required]
    return {
        "queue": queue,
        "consumers": len(consumers),
        "matching": len(matching),
        "stale": len(consumers) - len(matching),
    }


def read_beat(conns: Connections) -> dict[str, Any] | None:
    raw = conns.redis().get(conns.keys.beat)
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    data["last_tick"] = _ts(data.get("last_tick"))
    data["started_at"] = _ts(data.get("started_at"))
    return data


def read_lock(conns: Connections) -> dict[str, Any] | None:
    """Who holds redbeat's lock. A beat that was killed hard keeps it until the
    ttl runs out, and any new beat just sits there, worth showing."""
    lock_key = conns.settings.redbeat_key_prefix + ":lock"
    client = conns.redis()
    holder = client.get(lock_key)
    if holder is None:
        return None
    ttl = client.ttl(lock_key)
    return {"key": lock_key, "ttl": ttl if ttl and ttl > 0 else None}


def read_task_meta(conns: Connections) -> dict[str, dict[str, Any]]:
    raw = conns.redis().hgetall(conns.keys.tasks)
    out = {}
    for name, value in raw.items():
        meta = json.loads(value)
        meta["published_at"] = _ts(meta.get("published_at"))
        out[name.decode() if isinstance(name, bytes) else name] = meta
    return out


def read_published_beat_schedule(conns: Connections) -> dict[str, Any] | None:
    raw = conns.redis().get(conns.keys.beat_schedule)
    return json.loads(raw) if raw else None
