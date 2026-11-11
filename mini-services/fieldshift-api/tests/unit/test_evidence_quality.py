"""A5 evidence quality: honest component semantics, no fabricated values,
separate concepts, and evidence-backed confidence mapping."""

from __future__ import annotations

import datetime as dt

from app.recommendations.evidence_quality import (
    assess_evidence_quality,
    evidence_backed_confidence,
)
from app.recommendations.registry import RecommendationContext


class _Ctx:
    """Minimal stand-in exposing the fields assess_evidence_quality reads."""

    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence


def _fresh_climate() -> dict:
    end = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
    start = end - dt.timedelta(days=365)
    return {
        "climate": {
            "source": {"kind": "feature_run", "id": "r1"},
            "period": {"start": start.date().isoformat(), "end": end.date().isoformat()},
            "is_synthetic": False,
            "metrics": [],
        }
    }


def test_full_quality_components_computed():
    ctx = _Ctx(_fresh_climate())
    report = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
    assert report["score"] is not None
    for key in ("completeness", "recency", "coverage", "source_reliability", "measurement_uncertainty"):
        assert report["components"][key]["value"] is not None
        assert report["components"][key]["basis"]
    # Honest None components (not fabricatable today):
    assert report["components"]["spatial_resolution"]["value"] is None
    assert report["components"]["agreement"]["value"] is None
    assert report["components"]["spatial_resolution"]["basis"]
    assert report["components"]["agreement"]["basis"]


def test_recency_bands():
    now = dt.datetime.now(dt.UTC)

    def _ctx(age_days: int) -> _Ctx:
        end = now - dt.timedelta(days=age_days)
        return _Ctx({"climate": {"period": {"start": "2020-01-01", "end": end.date().isoformat()}}})

    fresh = assess_evidence_quality(_ctx(2), "climate", expected_sections=("climate",))
    stale = assess_evidence_quality(_ctx(200), "climate", expected_sections=("climate",))
    ancient = assess_evidence_quality(_ctx(500), "climate", expected_sections=("climate",))
    assert fresh["components"]["recency"]["value"] == 1.0
    assert stale["components"]["recency"]["value"] == 0.3
    assert ancient["components"]["recency"]["value"] == 0.1
    assert stale["score"] < fresh["score"]


def test_data_gaps_lower_uncertainty_component():
    with_data = _Ctx(_fresh_climate())
    without = _Ctx({"data_gaps": ["climate"], "climate": _fresh_climate()["climate"]})
    report_with = assess_evidence_quality(with_data, "climate", expected_sections=("climate",))
    # Now with a data gap recorded for climate:
    ctx_gap = _Ctx({"data_gaps": ["climate"]})
    report_gap = assess_evidence_quality(ctx_gap, "climate", expected_sections=("climate",))
    assert report_gap["components"]["measurement_uncertainty"]["value"] == 0.0
    assert report_with["components"]["measurement_uncertainty"]["value"] == 1.0
    assert report_gap["score"] < report_with["score"]


def test_synthetic_source_flags_reliability():
    ctx = _Ctx({
        "climate": {
            "source": {"kind": "feature_run", "id": "r1"},
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "is_synthetic": True,
        }
    })
    report = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
    assert report["components"]["source_reliability"]["value"] == 0.5
    assert "synthetic" in report["components"]["source_reliability"]["basis"]


def test_missing_sections_lower_completeness():
    ctx = _Ctx(_fresh_climate())
    partial = assess_evidence_quality(ctx, "water", expected_sections=("water", "climate"))
    assert partial["components"]["completeness"]["value"] == 0.5


def test_confidence_mapping_documented_not_calibrated():
    quality = {"score": 0.8}
    value = evidence_backed_confidence(quality)
    assert value == round(0.3 + 0.7 * 0.8, 2)
    assert evidence_backed_confidence({"score": None}) is None
    assert evidence_backed_confidence({}) is None


def test_generator_recs_carry_kind_and_quality():
    """Integration with the generators: threshold screenings use
    evidence_quality kind; data-gap recs use deterministic_rule."""
    from app.recommendations import registry as registry_module

    # Force generator registration without importing the app package twice.
    import app.recommendations.generators  # noqa: F401

    reg = registry_module.registry
    ctx = registry_module.RecommendationContext(
        field={"id": "11111111-1111-1111-1111-111111111111", "name": "F", "area_ha": 10.0},
        evidence={
            "climate": {
                "source": {"kind": "feature_run", "id": "r1"},
                "period": {"start": "2025-01-01", "end": "2025-12-31"},
                "is_synthetic": False,
                "metrics": [
                    {"code": "dry_spell_max_days_monthly", "value": 18, "unit": "days",
                     "aggregation_level": "monthly", "period": "2025-04"},
                ],
            },
            "data_gaps": ["water", "soil", "rotation", "management"],
        },
        anomalies=[],
    )
    recs = reg.run_with_context(None, ctx.field, ctx)
    dry_spell = [r for r in recs if r.generator and "dry_spell" in r.generator]
    assert dry_spell
    rec = dry_spell[0]
    assert rec.confidence_kind == "evidence_quality"
    assert rec.confidence is not None
    assert rec.evidence_quality and rec.evidence_quality.get("score") is not None
    # The basis string must NOT imply calibration:
    assert "NOT a calibrated probability" in rec.confidence_basis

    gap = [r for r in recs if r.generator and "data_gap" in r.generator]
    assert gap
    assert gap[0].confidence_kind == "deterministic_rule"
