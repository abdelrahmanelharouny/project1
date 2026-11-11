"""A4 integration: fingerprinted refresh — unchanged/changed/removed/new,
concurrent refresh, historical preservation, and narrative cache interplay.

The bridge is disabled for refresh tests (narrative None → rules mode);
narrative-cache behavior has its own dedicated tests.
"""

from __future__ import annotations

import threading

import pytest

from app.core.database import SessionLocal
from app.db import models_ai
from sqlalchemy import select

from tests.conftest import auth_headers, client, farm_with_field  # noqa: F401


@pytest.fixture(autouse=True)
def _llm_disabled():
    """The sandbox runs a REAL bridge on 127.0.0.1 (internal hosts bypass the
    conftest transport fake) — disable it so refresh behavior is deterministic
    rules-only. Narrative enrichment is covered by the Arabic/cache suites."""
    from app.intelligence.config import ai_settings

    old = ai_settings.llm_enabled
    ai_settings.llm_enabled = False
    yield
    ai_settings.llm_enabled = old


def _rec_rows(db, field_id):
    return db.scalars(
        select(models_ai.AIRecommendation)
        .where(models_ai.AIRecommendation.field_id == field_id)
        .order_by(models_ai.AIRecommendation.created_at.asc())
    ).all()


def _refresh(client, headers, field_id, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    resp = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh{'?' + query if query else ''}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_first_refresh_inserts_with_fingerprints(client, farm_with_field):
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    payload = _refresh(client, headers, field_id)
    assert payload["recommendations"]
    assert payload["engine"]["mode"] == "rules"

    db = SessionLocal()
    try:
        rows = _rec_rows(db, field_id)
        assert all(r.fingerprint for r in rows)
        # One active row per candidate; no duplicates.
        active = [r for r in rows if r.status == "active"]
        fps = [r.fingerprint for r in active]
        assert len(fps) == len(set(fps))
    finally:
        db.close()


def test_second_refresh_is_noop_churn_free(client, farm_with_field):
    """Unchanged evidence → the second refresh must NOT supersede/reinsert:
    same active rows, same ids, no new history (A4.4)."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    first = _refresh(client, headers, field_id)
    first_ids = [r["id"] for r in first["recommendations"]]

    db = SessionLocal()
    try:
        before = _rec_rows(db, field_id)
        n_before = len(before)
    finally:
        db.close()

    second = _refresh(client, headers, field_id)
    assert [r["id"] for r in second["recommendations"]] == first_ids
    assert second["counts"]["total"] == first["counts"]["total"]

    db = SessionLocal()
    try:
        after = _rec_rows(db, field_id)
        assert len(after) == n_before, "no-op refresh must not create history rows"
        assert all(r.status == "active" for r in after)
    finally:
        db.close()


def test_changed_engine_output_supersedes_only_changed_rec(client, farm_with_field):
    """A materially changed evidence pack (a feature run appears) changes the
    climate candidates: the climate data-gap rec is REMOVED (superseded), new
    climate advisories are INSERTED, and the other domains' recs stay active
    with their original ids and rows untouched."""
    import datetime as dt

    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    first = _refresh(client, headers, field_id)
    assert first["recommendations"]

    first_climate = [
        r for r in first["recommendations"] if r["domain"] == "climate"
    ]
    first_climate_ids = {r["id"] for r in first_climate}
    first_other_ids = {r["id"] for r in first["recommendations"] if r["domain"] != "climate"}

    # New engine output: a succeeded feature run with a dry-spell metric.
    db = SessionLocal()
    try:
        from app.db import models as dbm

        run = dbm.FeatureRun(
            field_id=field_id,
            status="succeeded",
            calendar_timezone="UTC",
            hemisphere="north",
            period_start=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
            period_end=dt.datetime(2025, 12, 31, tzinfo=dt.UTC),
            aggregation_levels=["monthly"],
            requested_variables=["dry_spell_max_days"],
            source_selection={},
            feature_engine_version="test",
            feature_catalog_version="test",
            is_synthetic=False,
        )
        db.add(run)
        db.flush()
        db.add(dbm.FeatureValue(
            run_id=run.id, field_id=field_id,
            feature_code="dry_spell_max_days_monthly",
            aggregation_level="monthly", period_label="2025-04",
            period_start=dt.datetime(2025, 4, 1, tzinfo=dt.UTC),
            period_end=dt.datetime(2025, 4, 30, tzinfo=dt.UTC),
            value=18.0, unit="days", quality_status="valid",
        ))
        db.commit()
    finally:
        db.close()

    second = _refresh(client, headers, field_id)
    second_ids = {r["id"] for r in second["recommendations"]}

    # Other domains kept their rows (fingerprints unchanged).
    assert first_other_ids <= second_ids
    # Climate data-gap rec removed; new climate advisory inserted.
    assert not (first_climate_ids & second_ids)
    second_climate = [r for r in second["recommendations"] if r["domain"] == "climate"]
    assert second_climate
    assert any("dry spell" in r["title"].lower() for r in second_climate)

    db = SessionLocal()
    try:
        rows = _rec_rows(db, field_id)
        superseded = [r for r in rows if r.status == "superseded"]
        assert any(str(r.id) in first_climate_ids for r in superseded), "old climate rec superseded"
        assert all(str(r.id) not in first_other_ids for r in superseded), "other domains untouched"
    finally:
        db.close()


def test_removal_and_history_preservation(client, farm_with_field):
    """When a candidate disappears, its active row is superseded (never
    deleted) and its feedback-relevant history stays queryable."""
    from app.recommendations import registry as registry_module

    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    _refresh(client, headers, field_id)

    # Remove every registered generator temporarily → next refresh has NO
    # candidates → all actives superseded.
    reg = registry_module.registry
    saved: dict[str, list] = {}
    for domain, fns in reg._generators.items():  # noqa: SLF001
        saved[domain] = list(fns)
        fns.clear()
    try:
        payload = _refresh(client, headers, field_id)
        assert payload["recommendations"] == []
    finally:
        for domain, fns in saved.items():
            reg._generators[domain] = fns  # noqa: SLF001

    db = SessionLocal()
    try:
        rows = _rec_rows(db, field_id)
        assert rows, "history preserved"
        assert all(r.status == "superseded" for r in rows)
    finally:
        db.close()

    # And the next refresh brings them back as fresh actives.
    payload = _refresh(client, headers, field_id)
    assert payload["recommendations"]


def test_concurrent_refresh_no_duplicate_active_fingerprints(client, farm_with_field):
    """Two concurrent refreshes must converge: exactly one active row per
    fingerprint (the FOR UPDATE lock serializes; the partial unique index is
    the backstop)."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]

    # First refresh primes the state so both workers diff the same evidence.
    _refresh(client, headers, field_id)

    results: list[dict | Exception] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker():
        # Each thread gets its own TestClient-scoped session via the app's
        # dependency; we drive the service directly to avoid client thread
        # safety questions and commit independently.
        db = SessionLocal()
        try:
            from app.db import models as dbm

            field = db.get(dbm.Field, field_id)
            barrier.wait(timeout=10)
            from app.recommendations.service import refresh_field_recommendations

            payload = refresh_field_recommendations(db, field, force=True)
            db.commit()
            with lock:
                results.append(payload)
        except Exception as exc:  # noqa: BLE001
            with lock:
                results.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    payloads = [r for r in results if isinstance(r, dict)]
    assert len(payloads) == 2, f"both refreshes must succeed: {results}"

    db = SessionLocal()
    try:
        active = [r for r in _rec_rows(db, field_id) if r.status == "active"]
        fps = [r.fingerprint for r in active if r.fingerprint]
        assert len(fps) == len(set(fps)), "duplicate active fingerprints are forbidden"
    finally:
        db.close()


def test_refresh_accepts_locale_and_force_params(client, farm_with_field):
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    payload = _refresh(client, headers, field_id, locale="ar", force="true")
    assert payload["recommendations"]
    # Bridge disabled in tests → no narratives, but the params must not break.
    assert payload["engine"]["mode"] == "rules"
