"""Lightweight observability counters (Master §50).

Structured logs now; metrics/tracing hooks are the extension point for later
OpenTelemetry work. Counters are in-memory per process — job tables remain the
durable source of truth.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("croptwist.metrics")

_counters: dict[str, int] = {}
_latencies: dict[str, list[float]] = {}


def incr(name: str, value: int = 1, **tags: Any) -> None:
    key = name
    _counters[key] = _counters.get(key, 0) + value
    logger.info("metric", extra={"metric": name, "value": value, "tags": tags})


@contextmanager
def observe_latency(name: str, **tags: Any) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        _latencies.setdefault(name, []).append(elapsed)
        logger.info("latency", extra={"metric": name, "seconds": round(elapsed, 4), "tags": tags})


def record_ingestion(provider_code: str, received: int, rejected: int, inserted: int, status: str) -> None:
    incr("ingestion_jobs_total", 1, provider=provider_code, status=status)
    incr("ingestion_records_received", received, provider=provider_code)
    incr("ingestion_records_rejected", rejected, provider=provider_code)
    incr("ingestion_records_inserted", inserted, provider=provider_code)


def snapshot() -> dict[str, Any]:
    return {
        "counters": dict(_counters),
        "latency_p50_seconds": {
            k: sorted(v)[len(v) // 2] for k, v in _latencies.items() if v
        },
    }
