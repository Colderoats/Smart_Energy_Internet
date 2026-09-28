"""
In-memory sliding-window rate limiter, keyed per client IP and endpoint.

Per-process state: correct for the single uvicorn worker this project runs.
Multiple workers would each keep their own counters (limit x workers).
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, spec: str) -> None:
        """Record a hit; raise 429 if more than <max>/<window s> hits are recent."""
        limit, window = (int(x) for x in spec.split("/"))
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            retry = int(hits[0] + window - now) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()
