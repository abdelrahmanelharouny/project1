"""Vegetation recommendations (P2.A) — satellite intelligence signals.

Reads the vegetation stress signals produced by the satellite intelligence
layer (same-month baselines, dormancy context, cross-domain cause context)
plus vegetation data gaps. The generator NEVER claims disease, pest or
nutrient deficiency from NDVI — it relays the observed statistical change,
the corroborating environmental evidence, and the explicit not-supported
list from the stress engine.

The vegetation evidence is computed on read by app.vegetation.service; this
generator calls that service (cheap, indexed queries) and converts signals
into registry recommendations. When no satellite data exists it emits one
honest data-gap recommendation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.evidence_quality import (
    assess_evidence_quality,
    evidence_backed_confidence,
)
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("croptwist.recommendations.vegetation")

SEVERITY_BY_LEVEL = {
    "info": Severity.INFO,
    "advisory": Severity.ADVISORY,
    "recommended": Severity.RECOMMENDED,
    "required": Severity.REQUIRED,
}


@registry.generator("vegetation")
def vegetation_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """One honest data-gap recommendation when no satellite scenes exist."""
    try:
        from app.db.models_p2 import SatelliteScene
        from sqlalchemy import func, select

        count = db.scalar(
            select(func.count(SatelliteScene.id)).where(SatelliteScene.field_id == field.id)
        )
        if (count or 0) > 0:
            return []
    except Exception:  # noqa: BLE001 — table missing should never break the refresh
        return []
    quality = assess_evidence_quality(ctx, "vegetation", expected_sections=())
    return [
        Recommendation(
            domain="vegetation",
            severity=Severity.INFO,
            title="No satellite observations — vegetation screening is unavailable",
            summary=(
                "No satellite scenes exist for this field, so vegetation stress "
                "screening cannot run (a synthetic fixture exists for demos but "
                "is never real evidence)."
            ),
            rationale=(
                "Vegetation intelligence derives from per-scene index statistics "
                "over the field boundary. Without scenes the platform keeps the "
                "signal unavailable instead of estimating vegetation condition."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: vegetation",
            )],
            confidence=0.9,
            confidence_kind="deterministic_rule",
            confidence_basis="The absence of rows is directly observable.",
            evidence_quality=quality,
            actions=[{
                "title": "Ingest a satellite product",
                "detail": "Run a data job with provider_code=sentinel2 (live) or satellite_sim (fixture).",
            }],
        )
    ]


@registry.generator("vegetation")
def vegetation_stress_advisories(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """Convert vegetation stress signals into recommendations."""
    from app.vegetation.service import vegetation_summary

    try:
        summary = vegetation_summary(db, field, index="ndvi")
    except Exception as exc:  # noqa: BLE001
        logger.warning("vegetation summary failed: %s", exc)
        return []
    signals = summary.get("stress_signals") or []
    findings = summary.get("findings") or []
    gaps = summary.get("data_gaps") or []
    recommendations: list[Recommendation] = []

    quality = assess_evidence_quality(
        ctx, "vegetation", expected_sections=("climate",)
    )

    for signal in signals[:3]:
        observed = signal.get("observed_change") or {}
        context = signal.get("possible_context") or []
        not_supported = signal.get("not_supported") or []
        severity = SEVERITY_BY_LEVEL.get(signal.get("severity", "info"), Severity.INFO)
        period = observed.get("period") or {}
        period_label = f"{period.get('year', '?')}-{period.get('month', '?'):02d}" if period.get("month") else str(period)
        context_summary = "; ".join(
            c.get("detail", c.get("factor", "")) for c in context[:3]
        ) or "no corroborating environmental evidence — cause unknown"
        recommendations.append(
            Recommendation(
                domain="vegetation",
                severity=severity,
                title=f"Vegetation decline signal for {period_label}",
                summary=(
                    f"Satellite NDVI is statistically below the same-month baseline "
                    f"for {period_label} ({observed.get('detail', '')})."
                ),
                rationale=(
                    f"Observed change: {observed.get('detail') or 'statistical decline against the same-month seasonal baseline'}. "
                    f"Environmental context: {context_summary}. "
                    f"This signal does NOT diagnose {', '.join(not_supported[:2])}."
                ),
                evidence=[
                    evidence_item(
                        type="vegetation_signal",
                        id=None,
                        label="vegetation",
                        detail=observed.get("detail", "same-month baseline anomaly"),
                    ),
                    *[
                        evidence_item(
                            type="environment_context",
                            id=None,
                            label="climate" if c.get("factor") in ("temperature", "rainfall") else ("water" if c.get("factor") == "water_deficit" else "rotation"),
                            detail=c.get("detail", c.get("factor", "")),
                        )
                        for c in context[:3]
                    ],
                ],
                confidence=evidence_backed_confidence(quality),
                confidence_kind="evidence_quality",
                confidence_basis="Evidence-quality heuristic (completeness/recency of climate + vegetation streams).",
                evidence_quality=quality,
                actions=[{
                    "title": "Ground-truth the affected area",
                    "detail": (
                        "Walk the field during the next window and compare against the "
                        "scene metadata (date, cloud cover); record irrigation and "
                        "crop-stage context."
                    ),
                }],
            )
        )

    # Insufficient baseline → one info recommendation (history gap).
    insufficient = [f for f in findings if f.get("kind") == "insufficient_baseline"]
    if insufficient and not recommendations:
        recommendations.append(
            Recommendation(
                domain="vegetation",
                severity=Severity.INFO,
                title="Vegetation history is too short for seasonal comparison",
                summary=(
                    "Satellite scenes exist but the record spans fewer than 2 "
                    "years, so same-month baselines cannot be formed yet."
                ),
                rationale=(
                    "Seasonal vegetation intelligence compares the SAME calendar "
                    "month across years; shorter records are reported as a data "
                    "gap rather than screened with unstable baselines."
                ),
                evidence=[evidence_item(
                    type="data_gap", id=None, label="vegetation",
                    detail=insufficient[0].get("detail", "insufficient same-month baseline"),
                )],
                confidence=0.9,
                confidence_kind="deterministic_rule",
                confidence_basis="Record length is directly observable.",
                evidence_quality=quality,
                actions=[{
                    "title": "Keep ingesting scenes",
                    "detail": "Seasonal baselines form automatically once >= 2 years of scenes accumulate.",
                }],
            )
        )

    for gap in gaps[:2]:
        recommendations.append(
            Recommendation(
                domain="vegetation",
                severity=Severity.INFO,
                title="Vegetation data gap",
                summary=gap,
                rationale="Reported by the vegetation intelligence layer's honest gap accounting.",
                evidence=[evidence_item(type="data_gap", id=None, label="vegetation", detail=gap)],
                confidence=0.9,
                confidence_kind="deterministic_rule",
                confidence_basis="Gap state is directly observable.",
                evidence_quality=quality,
            )
        )
    return recommendations[:5]
