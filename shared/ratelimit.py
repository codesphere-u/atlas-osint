"""Rate limiting primitives.

* :class:`AsyncRateLimiter` – in-process sliding-window limiter used by
  collectors to respect each source's published rate limit.
* :class:`WindowRateLimiter` – fixed-window counter for the API, backed by
  Redis when configured (so limits hold across replicas) or memory otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any


class AsyncRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, key: str, limit: int, per_seconds: float) -> None:
        if limit <= 0:
            return
        async with self._locks[key]:
            while True:
                now = time.monotonic()
                events = self._events[key]
                while events and now - events[0] >= per_seconds:
                    events.popleft()
                if len(events) < limit:
                    events.append(now)
                    return
                await asyncio.sleep(max(0.01, per_seconds - (now - events[0])))


class WindowRateLimiter:
    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._counts: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int, int]:
        """Register a hit. Returns (allowed, remaining, reset_in_seconds)."""
        now = int(time.time())
        window = now // window_seconds
        reset = (window + 1) * window_seconds - now
        bucket = f"atlas:rl:{key}:{window}"
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(bucket)
                pipe.expire(bucket, window_seconds + 1)
                count = int(pipe.execute()[0])
                return count <= limit, max(0, limit - count), reset
            except Exception:
                logging.getLogger("atlas.ratelimit").warning("redis rate limiter unavailable; using memory")
        with self._lock:
            w, c = self._counts.get(key, (window, 0))
            if w != window:
                w, c = window, 0
            c += 1
            self._counts[key] = (w, c)
            if len(self._counts) > 50_000:  # bound memory
                self._counts = {k: v for k, v in self._counts.items() if v[0] == window}
        return c <= limit, max(0, limit - c), reset
