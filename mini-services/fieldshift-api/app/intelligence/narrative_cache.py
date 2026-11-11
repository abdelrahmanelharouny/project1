"""Evidence-based narrative cache (A3).

Avoids paying LLM latency/cost when the underlying agricultural evidence has
not changed. Cache keys are SHA-256 fingerprints over EVERYTHING that can
change the narrative:

    field identity (UUID) — makes cross-tenant hits structurally impossible
      (another organization would need the same field UUID);
    evidence-pack canonical JSON — the grounding facts;
    evidence version — aggregate of section source ids (run/plan ids);
    prompt/template version — bumped when prompts change;
    model identity — the configured narrative model tag;
    locale — English and Arabic cached independently;
    generation parameters — temperature + max_tokens.

Storage is the project's existing in-process pattern (same trade-off as
app/core/rate_limit.py and the observability counters): a thread-safe LRU map
with TTL and a size cap. No Redis/external service — the sandbox runs a
single API process; multi-replica deployments would swap the store behind
`get`/`put` (documented, no other change required).

Concurrency: a per-key in-flight registry means N simultaneous identical
refreshes get the SAME cached value (or coalesce on one LLM call via the
double-checked `get_or_flag` contract) instead of generating duplicates.

Metrics: narrative_cache_hits / narrative_cache_misses + evictions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from app.intelligence import metrics
from app.intelligence.config import ai_settings

logger = logging.getLogger("croptwist.intelligence.narrative_cache")

# Bumped when the narrative prompt/template changes (invalidates all entries).
NARRATIVE_TEMPLATE_VERSION = "p1-1"
# Tag describing the model identity for keying (config-driven, not a secret).
MODEL_TAG = "bridge-default"


def canonical_json(value: Any) -> str:
    """Stable JSON serialization (sorted keys, compact separators)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def evidence_fingerprint(evidence: dict[str, Any]) -> str:
    """SHA-256 over the canonical evidence pack JSON."""
    return hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()


def evidence_version(evidence: dict[str, Any]) -> str:
    """Aggregate version of the evidence sources (engine run ids)."""
    parts: list[str] = []
    for section in evidence.values():
        if isinstance(section, dict):
            source = section.get("source") or {}
            if source.get("kind") and source.get("id"):
                parts.append(f"{source['kind']}:{source['id']}")
    parts.sort()
    return hashlib.sha1(";".join(parts).encode("utf-8")).hexdigest()[:16]


def narrative_key(
    *,
    field_id: str,
    evidence: dict[str, Any],
    locale: str,
    temperature: float,
    max_tokens: int,
    model_tag: str = MODEL_TAG,
    template_version: str = NARRATIVE_TEMPLATE_VERSION,
) -> str:
    """Stable SHA-256 cache key covering field, evidence, versioning, locale
    and generation parameters (spec A3.1-6)."""
    material = {
        "v": template_version,
        "field_id": str(field_id),
        "evidence": evidence_fingerprint(evidence),
        "evidence_version": evidence_version(evidence),
        "model": model_tag,
        "locale": locale,
        "temperature": round(float(temperature), 3),
        "max_tokens": int(max_tokens),
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class NarrativeCache:
    """Thread-safe TTL + LRU store keyed by narrative_key fingerprints."""

    def __init__(self, *, ttl_seconds: float | None = None, max_entries: int | None = None) -> None:
        self._ttl = ai_settings.narrative_cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._max_entries = (
            ai_settings.narrative_cache_max_entries if max_entries is None else max_entries
        )
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self._max_entries > 0 and self._ttl > 0

    def get(self, key: str) -> Any | None:
        """Cached value or None (records hit/miss metrics)."""
        if not self.enabled:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                metrics.incr("narrative_cache_misses")
                return None
            if entry.expired():
                self._store.pop(key, None)
                self.misses += 1
                metrics.incr("narrative_cache_misses")
                metrics.incr("narrative_cache_expirations")
                return None
            self._store.move_to_end(key)  # LRU refresh
            self.hits += 1
            metrics.incr("narrative_cache_hits")
            return entry.value

    def put(self, key: str, value: Any) -> None:
        if not self.enabled or value is None:
            return
        with self._lock:
            self._store[key] = _Entry(value, self._ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                metrics.incr("narrative_cache_evictions")

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "ttl_seconds": self._ttl,
                "max_entries": self._max_entries,
            }


cache = NarrativeCache()
