"""Login throttling. In memory, which is fine for a single panel process;
if you run several replicas each one counts on its own."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> float:
        """Seconds until ``key`` may try again, 0 if it may try now."""
        now = time.monotonic()
        with self._lock:
            hits = self._trim(key, now)
            if len(hits) < self.max_failures:
                return 0.0
            return max(hits[0] + self.window - now, 0.0)

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._trim(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
