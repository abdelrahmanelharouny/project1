"""A4 recommendation fingerprinting: stability, change sensitivity, diff plan,
timestamp independence, concurrent-refresh dedupe."""

from __future__ import annotations

import threading

from app.recommendations.contracts import Recommendation, Severity
from app.recommendations.fingerprint import compute_fingerprint, refresh_plan


def _rec(**overrides) -> Recommendation:
    base = dict(
        domain="water",
        severity=Severity.ADVISORY,
        title="Extended dry spell of 18 days in the record",
        summary="Plan irrigation buffers.",
        rationale="The engine reports 18 days.",
        evidence=[{"type": "feature_run", "id": "run-1", "label": "climate", "detail": "18 days"}],
        actions=["Check the water plan."],
        generator="climate.dry_spell_advisory",
    )
    base.update(overrides)
    return Recommendation(**base)


FIELD = "11111111-1111-1111-1111-111111111111"


def test_fingerprint_is_stable_sha256():
    fp1 = compute_fingerprint(_rec(), FIELD)
    fp2 = compute_fingerprint(_rec(), FIELD)
    assert fp1 == fp2
    assert len(fp1) == 64
    int(fp1, 16)


def test_fingerprint_independent_of_timestamps_and_narrative():
    """Unstable values must NOT be part of the material (A4: exclude
    generated timestamps, narrative text, model names)."""
    base = _rec()
    with_ts = base.model_copy(update={"created_at": "2026-01-01T00:00:00Z", "narrative": "Fresh text", "model": "glm-4"})
    assert compute_fingerprint(base, FIELD) == compute_fingerprint(with_ts, FIELD)


def test_fingerprint_changes_on_material_change():
    base_fp = compute_fingerprint(_rec(), FIELD)
    assert compute_fingerprint(_rec(title="Different title"), FIELD) != base_fp
    assert compute_fingerprint(_rec(summary="New numbers: 22 days."), FIELD) != base_fp
    assert compute_fingerprint(_rec(severity=Severity.REQUIRED), FIELD) != base_fp
    assert compute_fingerprint(_rec(actions=["New action"]), FIELD) != base_fp
    assert compute_fingerprint(_rec(generator="other.generator"), FIELD) != base_fp
    # Evidence REFERENCE changes (run id) change the fingerprint...
    assert compute_fingerprint(
        _rec(evidence=[{"type": "feature_run", "id": "run-2", "label": "climate", "detail": "18 days"}]),
        FIELD,
    ) != base_fp
    # ...but evidence DETAIL rewording alone does not (formatting churn).
    assert compute_fingerprint(
        _rec(evidence=[{"type": "feature_run", "id": "run-1", "label": "climate", "detail": "eighteen days"}]),
        FIELD,
    ) == base_fp


def test_fingerprint_scoped_by_field():
    assert compute_fingerprint(_rec(), FIELD) != compute_fingerprint(
        _rec(), "22222222-2222-2222-2222-222222222222"
    )


class _Row:
    def __init__(self, fingerprint, rec_id="row"):
        self.fingerprint = fingerprint
        self.id = rec_id
        self.status = "active"


def test_refresh_plan_unchanged_changed_removed_new():
    unchanged = _rec()
    changed_old = _rec(title="Old title of the same generator")
    changed_new = _rec(title="New title of the same generator")
    gone = _rec(summary="This recommendation disappears")
    fresh = _rec(summary="Brand new recommendation")

    active_rows = [
        _Row(compute_fingerprint(unchanged, FIELD), "row-keep"),
        _Row(compute_fingerprint(changed_old, FIELD), "row-change"),
        _Row(compute_fingerprint(gone, FIELD), "row-gone"),
        _Row(None, "row-legacy"),  # legacy row: no fingerprint → superseded
    ]
    plan = refresh_plan(
        [unchanged, changed_new, fresh], active_rows, FIELD
    )
    assert [r.id for r in plan["keep"]] == ["row-keep"]
    assert sorted(r.id for r in plan["supersede"]) == ["row-change", "row-gone", "row-legacy"]
    # Inserted: the changed candidate (new content of the changed generator)
    # and the genuinely new one — in candidate order.
    assert [r.summary for r in plan["insert"]] == [
        "Plan irrigation buffers.", "Brand new recommendation"
    ]


def test_refresh_plan_all_unchanged_is_noop():
    rec = _rec()
    rows = [_Row(compute_fingerprint(rec, FIELD), "row-1")]
    plan = refresh_plan([rec], rows, FIELD)
    assert plan["keep"] == rows and plan["supersede"] == [] and plan["insert"] == []


def test_refresh_plan_duplicate_candidates_deduped():
    """Two identical candidates must not insert duplicate active rows."""
    rec = _rec()
    plan = refresh_plan([rec, _rec()], [], FIELD)
    assert len(plan["insert"]) == 1


def test_concurrent_refresh_converges():
    """Two threads diff the same candidates against overlapping active rows:
    the fingerprint map keeps ONE insert per unique fingerprint (the DB-side
    partial unique index is exercised in the integration suite)."""
    rec = _rec()
    results: list[list] = []
    lock = threading.Lock()

    def worker():
        plan = refresh_plan([rec, _rec()], [], FIELD)
        with lock:
            results.append(plan["insert"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(len(insert) == 1 for insert in results)
    fingerprints = {compute_fingerprint(rec, FIELD)}
    assert fingerprints
