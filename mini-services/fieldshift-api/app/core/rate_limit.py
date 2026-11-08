"""In-process sliding-window rate limiter (auth hardening P0-2).

Deliberately small and dependency-free: a per-(bucket, key) deque of
monotonic timestamps, pruned on every check. Suited to the single-process
sandbox/dev deployment; a multi-replica production deployment should swap
this for a shared store (Redis) behind the same `check()` signature.

The limit is read from `settings.auth_rate_limit_per_minute` AT CALL TIME so
tests can monkeypatch the settings attribute directly. A value <= 0 disables
limiting entirely.
"""

import threading
import time
from collections import deque

from app.core.config import settings
from app.core.errors import TooManyRequests

_WINDOW_SECONDS = 60.0

# (bucket, key) -> deque[timestamps] (monotonic seconds, ascending)
_store: dict[tuple[str, str], deque[float]] = {}
_lock = threading.Lock()


def check(bucket: str, key: str) -> None:
    """Count one request against the sliding window; raise on exhaustion."""
    limit = settings.auth_rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    with _lock:
        timestamps = _store.setdefault((bucket, key), deque())
        cutoff = now - _WINDOW_SECONDS
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= limit:
            # Ceiling of the time until the oldest in-window request expires.
            retry_after = max(int(_WINDOW_SECONDS - (now - timestamps[0])) + 1, 1)
            raise TooManyRequests(
                "Too many requests — slow down and try again shortly.",
                retry_after_seconds=retry_after,
            )
        timestamps.append(now)


def _reset_store() -> None:
    """Clear all counters (test isolation helper)."""
    with _lock:
        _store.clear()
