"""Lightweight observability counters (Master §50).

Structured logs now; metrics/tracing hooks are the extension point for later
OpenTelemetry work. Counters are in-memory per process — job tables remain the
durable source of truth.
"""

import logging
import statistics
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


def _prom_name(name: str) -> str:
    """Metric names: [a-zA-Z_:][a-zA-Z0-9_:]* — normalize everything else."""
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch in "_:") else "_")
    return "".join(out)


def _prom_escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_prometheus() -> str:
    """Render the in-process metrics in Prometheus text exposition (0.0.4).

    Dependency-free. Counters export as `counter`-typed series; latency
    samples export as summary-style series (`_seconds` with `_count`,
    `_sum`, `_median`). Only route-template/aggregation tags are exported —
    never user-identifying values (the docstring contract of the endpoint).
    """
    lines: list[str] = []

    def _emit(name: str, help_text: str, mtype: str, value: str, suffix: str = "") -> None:
        prom = _prom_name(name)
        lines.append(f"# HELP {prom}{suffix} {help_text}")
        lines.append(f"# TYPE {prom}{suffix} {mtype}")
        lines.append(f"{prom}{suffix} {value}")

    for name in sorted(_counters):
        value = _counters[name]
        _emit(
            name,
            f"CropTwist counter {name}",
            "counter",
            str(int(value)),
        )

    for name in sorted(_latencies):
        samples = list(_latencies[name])
        if not samples:
            continue
        total = sum(samples)
        median = statistics.median(samples)
        _prom = _prom_name(name)
        lines.append(f"# HELP {_prom}_seconds CropTwist latency {name}")
        lines.append(f"# TYPE {_prom}_seconds summary")
        lines.append(f"{_prom}_seconds_count {len(samples)}")
        lines.append(f"{_prom}_seconds_sum {total:.6f}")
        lines.append(f"{_prom}_seconds_median {median:.6f}")

    if not lines:
        lines.append("# HELP croptwist_metrics_present Whether any metrics exist")
        lines.append("# TYPE croptwist_metrics_present gauge")
        lines.append("croptwist_metrics_present 0")
    return "\n".join(lines) + "\n"
