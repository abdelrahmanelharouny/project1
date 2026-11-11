"""AI-layer metrics (P1 observability).

Extends the in-process counter pattern of app/data_platform/observability.py
(same `_counters`/`_latencies` stores, so one Prometheus endpoint serves both)
with AI-specific series:

- bridge_requests_total / bridge_errors_total (+ bridge_error_total_<kind>)
- bridge_latency_seconds (histogram via observe_latency)
- bridge_circuit_state (gauge-ish counter set: 0/1/2 = closed/open/half_open)
- narrative_cache_hits / narrative_cache_misses
- advisor_latency_seconds
- recommendation_refresh_seconds
- recommendation_fingerprint_reused / _superseded / _created
- structured_response_validation_failures
- citation_validation_failures
- numeric_consistency_failures
- prompt_injection_suspected
- feedback_events_total (per state)

No sensitive data is ever a metric value or tag: farm names, prompts and
answers stay out of here (only states, kinds and latency numbers).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.data_platform.observability import _counters, _latencies, incr, observe_latency  # noqa: F401

logger = logging.getLogger("croptwist.metrics.ai")


def record_latency_sample(name: str, seconds: float) -> None:
    """Record one latency sample into the shared observability store."""
    _latencies.setdefault(name, []).append(seconds)


# Circuit-breaker state codes (exported as a counter triple so Prometheus
# text exposition needs no gauge support in the tiny renderer).
CIRCUIT_STATE_CODES = {"closed": 0, "open": 1, "half_open": 2}


def set_circuit_state(state: str) -> None:
    """Record the current circuit-breaker state (closed|open|half_open)."""
    code = CIRCUIT_STATE_CODES.get(state)
    if code is None:
        return
    # Store as a direct value (overwrite, not increment) using the raw store.
    _counters["bridge_circuit_state"] = code
    logger.info("circuit state", extra={"state": state})


def incr_validation_failure(kind: str) -> None:
    """Structured-response / citation / numeric validation failure counter."""
    incr(f"{kind}_failures_total")
    incr("ai_validation_failures_total")


@contextmanager
def observe_advisor() -> Iterator[None]:
    with observe_latency("advisor_latency_seconds"):
        yield


@contextmanager
def observe_refresh() -> Iterator[None]:
    with observe_latency("recommendation_refresh_seconds"):
        yield


def record_feedback_event(state: str) -> None:
    incr("feedback_events_total", state=state)


def snapshot_ai() -> dict[str, Any]:
    """Machine-readable AI metrics snapshot (used by tests + debug endpoint)."""
    from app.data_platform.observability import snapshot as _snap

    return _snap()
