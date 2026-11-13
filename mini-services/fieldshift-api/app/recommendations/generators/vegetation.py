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
                actions=[
                    (
                        "Walk the field during the next window and compare against the "
                        "scene metadata (date, cloud cover); record irrigation and "
                        "crop-stage context."
                    )
                ],
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
                actions=[
                    "Keep ingesting scenes: seasonal baselines form automatically once >= 2 years accumulate.",
                ],
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


@registry.generator("vegetation")
def vegetation_condition_context(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """P06: satellite-condition context from the field satellite profile.

    Deterministic and quality-gated: an ADVISORY condition-context signal is
    emitted ONLY when the freshest valid NDVI observation is materially below
    its prior-observation baseline (z <= -1.5), the evidence is fresh within
    the documented 45-day window, pixel support is real (>= 5 valid pixels)
    and the baseline comparison is not flagged weak. Nothing is emitted when
    evidence is insufficient — no squeeze, no extrapolation, no diagnosis.

    Confidence comes ONLY from the evidence-quality heuristic (never bumped
    because satellite data exists); the rationale carries quality context and
    the explicit non-claim.
    """
    from app.vegetation.field_profile import FRESH_SATELLITE_DAYS, field_satellite_profile

    try:
        profile = field_satellite_profile(db, field, index="ndvi")
    except Exception as exc:  # noqa: BLE001 — profile failure must not break refresh
        logger.warning("satellite profile failed: %s", exc)
        return []

    latest = profile.get("latest_valid_observation")
    if latest is None:
        return []
    # De-duplication: the monthly stress engine gets priority. When it
    # already produced signals, the same decline must NOT be re-counted as
    # independent evidence at scene granularity (one observation, one vote).
    try:
        from app.vegetation.service import vegetation_summary

        stress = vegetation_summary(db, field, index="ndvi").get("stress_signals") or []
        if stress:
            return []
    except Exception:  # noqa: BLE001 — screen failure should not double-count either
        return []
    quality_summary = profile.get("quality_summary") or {}
    comparison = profile.get("comparison") or {}
    z = comparison.get("z_score_vs_baseline")
    fresh = quality_summary.get("fresh")
    valid_pixels = (latest.get("valid_pixels") or 0) or 0
    coverage = latest.get("valid_pixel_fraction")

    if profile.get("insufficient_evidence") or comparison.get("weak_evidence"):
        quality = assess_evidence_quality(ctx, "vegetation", expected_sections=())
        return [
            Recommendation(
                domain="vegetation",
                severity=Severity.INFO,
                title="Satellite evidence is not sufficient for condition screening",
                summary=(
                    "Satellite observations exist but cannot support a condition "
                    "comparison yet (single scene, weak baseline or sub-threshold "
                    "pixel support)."
                ),
                rationale=(
                    "Insufficient-evidence gate from the field satellite profile: "
                    + "; ".join(
                        (profile.get("insufficient_evidence") or {}).get("reasons", [])
                        or ["baseline comparison flagged weak"]
                    )
                ),
                evidence=[
                    evidence_item(
                        type="vegetation_signal",
                        id=None,
                        label="satellite_profile",
                        detail=(
                            f"{quality_summary.get('valid_observations')} valid observation(s); "
                            f"latest {latest.get('observed_at')}"
                        ),
                    )
                ],
                confidence=0.9,
                confidence_kind="deterministic_rule",
                confidence_basis="Observation counts are directly observable.",
                evidence_quality=quality,
                actions=[
                    "Acquire more scenes over subsequent passes to accumulate a baseline.",
                ],
            )
        ]

    if z is None or z > -1.5 or not fresh or valid_pixels < 5 or (coverage is not None and coverage < 0.5):
        return []

    quality = assess_evidence_quality(ctx, "vegetation", expected_sections=("climate",))
    delta = comparison.get("delta_vs_baseline_mean")
    return [
        Recommendation(
            domain="vegetation",
            severity=Severity.ADVISORY,
            title="Latest satellite NDVI is statistically below its prior baseline",
            summary=(
                f"NDVI {latest.get('value')} at {str(latest.get('observed_at'))[:10]} sits "
                f"{delta} below the mean of prior valid observations "
                f"(z={z}, {valid_pixels} valid field pixels)."
            ),
            rationale=(
                "Deterministic statistical screening of the freshest valid "
                f"satellite observation (scene {latest.get('scene_id')}, "
                f"{latest.get('spatial_resolution_m')} m, cloud "
                f"{latest.get('cloud_cover_pct')}%). Evidence is fresh "
                f"({quality_summary.get('freshness_days_since_last')} days). This is a "
                "vegetation-condition CONTEXT signal, not a diagnosis: it does not "
                "identify disease, pest, nutrient deficiency or drought. Corroborate "
                "with field observation and the environmental engines before action."
            ),
            evidence=[
                evidence_item(
                    type="vegetation_signal",
                    id=None,
                    label="satellite_profile",
                    detail=(
                        f"z={z}, delta={delta}, valid_pixels={valid_pixels}, "
                        f"coverage={coverage}"
                    ),
                ),
                *[
                    evidence_item(
                        type="environment_context",
                        id=None,
                        label="climate",
                        detail="cross-check temperature/rainfall context in the evidence pack",
                    )
                ],
            ],
            confidence=evidence_backed_confidence(quality),
            confidence_kind="evidence_quality",
            confidence_basis=(
                "Evidence-quality heuristic; satellite resolution component is "
                "documented, never silently inflated."
            ),
            evidence_quality=quality,
            actions=[
                "Inspect the field and compare against the scene preview in Map & Satellite.",
                "Record crop stage and management events to sharpen future comparisons.",
            ],
        )
    ]
