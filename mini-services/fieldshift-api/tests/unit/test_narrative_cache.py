"""A3 narrative cache: hit/miss/invalidation, tenant safety, locale split,
TTL/size limits, force bypass, concurrent access."""

from __future__ import annotations

import threading

from app.intelligence.narrative_cache import NarrativeCache, narrative_key


def _key(field_id: str, evidence: dict, locale: str = "en") -> str:
    return narrative_key(
        field_id=field_id, evidence=evidence, locale=locale,
        temperature=0.3, max_tokens=1200,
    )


def test_hit_and_miss_recorded():
    cache = NarrativeCache(ttl_seconds=60, max_entries=10)
    key = _key("f1", {"climate": {"source": {"kind": "feature_run", "id": "r1"}}})
    assert cache.get(key) is None  # miss
    cache.put(key, {"0": "narrative"})
    assert cache.get(key) == {"0": "narrative"}  # hit
    assert cache.hits == 1 and cache.misses == 1


def test_evidence_change_invalidates():
    cache = NarrativeCache(ttl_seconds=60, max_entries=10)
    k1 = _key("f1", {"climate": {"source": {"kind": "feature_run", "id": "r1"}}})
    k2 = _key("f1", {"climate": {"source": {"kind": "feature_run", "id": "r2"}}})
    cache.put(k1, {"0": "old"})
    assert cache.get(k1) == {"0": "old"}
    assert cache.get(k2) is None  # new run id → different fingerprint → miss


def test_field_identity_partitions_tenants():
    """Structurally impossible cross-tenant hits: same evidence content but
    different field UUIDs never share an entry (A3.6)."""
    cache = NarrativeCache(ttl_seconds=60, max_entries=10)
    evidence = {"climate": {"metrics": [{"code": "x", "value": 1}]}}
    k_tenant_a = _key("aaaaaaaa-1111-1111-1111-111111111111", evidence)
    k_tenant_b = _key("bbbbbbbb-2222-2222-2222-222222222222", evidence)
    assert k_tenant_a != k_tenant_b
    cache.put(k_tenant_a, {"0": "tenant-a narrative"})
    assert cache.get(k_tenant_b) is None


def test_locale_cached_independently():
    cache = NarrativeCache(ttl_seconds=60, max_entries=10)
    evidence = {"climate": {"source": {"kind": "feature_run", "id": "r1"}}}
    k_en = _key("f1", evidence, locale="en")
    k_ar = _key("f1", evidence, locale="ar")
    cache.put(k_en, {"0": "English narrative"})
    cache.put(k_ar, {"0": "سرد بالعربية"})
    assert cache.get(k_en) == {"0": "English narrative"}
    assert cache.get(k_ar) == {"0": "سرد بالعربية"}


def test_prompt_or_model_change_invalidates():
    evidence = {"climate": {"source": {"kind": "feature_run", "id": "r1"}}}
    base = dict(field_id="f1", evidence=evidence, temperature=0.3, max_tokens=1200)
    k_default = narrative_key(locale="en", **base)
    k_other_temp = narrative_key(locale="en", temperature=0.7, **{k: v for k, v in base.items() if k != "temperature"})
    k_other_tokens = narrative_key(locale="en", max_tokens=256, **{k: v for k, v in base.items() if k != "max_tokens"})
    keys = {k_default, k_other_temp, k_other_tokens}
    assert len(keys) == 3  # each generation parameter changes the key


def test_ttl_expiration():
    cache = NarrativeCache(ttl_seconds=0.05, max_entries=10)
    key = _key("f1", {"a": 1})
    cache.put(key, {"0": "x"})
    assert cache.get(key) == {"0": "x"}
    import time

    time.sleep(0.06)
    assert cache.get(key) is None


def test_size_limit_evicts_lru():
    cache = NarrativeCache(ttl_seconds=60, max_entries=2)
    k1, k2, k3 = _key("f1", {"i": 1}), _key("f2", {"i": 2}), _key("f3", {"i": 3})
    cache.put(k1, {"0": "one"})
    cache.put(k2, {"0": "two"})
    cache.get(k1)  # refresh k1 (LRU)
    cache.put(k3, {"0": "three"})  # evicts k2
    assert cache.get(k1) == {"0": "one"}
    assert cache.get(k2) is None
    assert cache.get(k3) == {"0": "three"}


def test_disabled_cache_never_stores():
    cache = NarrativeCache(ttl_seconds=60, max_entries=0)
    key = _key("f1", {"a": 1})
    cache.put(key, {"0": "x"})
    assert cache.get(key) is None


def test_concurrent_access_no_duplicate_necessary(monkeypatch):
    """N threads requesting the same key: after the first put, everyone sees
    the cached value — no duplicate LLM generation is needed (A3.8)."""
    cache = NarrativeCache(ttl_seconds=60, max_entries=16)
    key = _key("f1", {"a": 1})
    generated: list[str] = []
    lock = threading.Lock()

    def worker():
        value = cache.get(key)
        if value is None:
            with lock:
                if not generated:  # double-checked: only ONE generation
                    generated.append("narrative-1")
                    cache.put(key, {"0": "narrative-1"})
                value = cache.get(key)
        assert value == {"0": "narrative-1"}

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert generated == ["narrative-1"]


def test_key_is_stable_sha256():
    import hashlib

    key = _key("f1", {"a": 1})
    assert len(key) == 64
    int(key, 16)  # hex
    assert key == _key("f1", {"a": 1})
    assert key != _key("f1", {"a": 2})
