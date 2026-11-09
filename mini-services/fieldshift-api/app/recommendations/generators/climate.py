"""Climate recommendations.

Reads the climate section of the evidence pack (latest succeeded feature run)
plus the statistical anomaly findings. Thresholds are documented screening
heuristics over the engine's own metric values — the engine computes the
metrics, this module only compares and explains them (no new science).
"""

from __future__ import annotations

import logging
from typing import Any

from app.intelligence.anomaly import Z_THRESHOLD
from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("fieldshift.recommendations.climate")

# Documented screening thresholds (heuristic, applied to engine metric values).
DRY_SPELL_ADVISORY_DAYS = 14   # ≥ 2 weeks under the WMO dry-day convention
HOT_DAYS_ADVISORY_COUNT = 30   # days ≥ 35 °C within a season/crop season
PRECIP_Z_STRONG = 2.0          # engine's own z-anomaly, conventional "unusual"
MAX_ANOMALY_RECS = 3


def _metric(metrics: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    for m in metrics:
        if str(m.get("code", "")).startswith(prefix):
            return m
    return None


@registry.generator("climate")
def climate_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    if ctx.section("climate") is not None:
        return []
    return [
        Recommendation(
            domain="climate",
            severity=Severity.INFO,
            title="No climate data yet — run a feature run to unlock climate advice",
            summary=(
                "This field has no succeeded feature run, so no climate metrics "
                "and no climate-informed recommendations can be produced."
            ),
            rationale=(
                "The intelligence layer reads the latest succeeded feature run "
                "for climate evidence. Without one, seasonal precipitation, "
                "temperature extremes and dry-spell screening all stay "
                "unevaluated (data gaps are reported, never estimated)."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: climate",
            )],
            actions=[
                "Create a feature run for this field "
                "(POST /api/v1/fields/{id}/feature-runs).",
            ],
            confidence=0.95,
            confidence_basis="deterministic: absence of a succeeded feature_run row for the field",
        )
    ]


@registry.generator("climate")
def dry_spell_advisory(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("climate") or {}
    metrics = section.get("metrics") or []
    metric = _metric(metrics, "dry_spell_max_days")
    if metric is None or metric.get("value") is None:
        return []
    value = float(metric["value"])
    if value < DRY_SPELL_ADVISORY_DAYS:
        return []
    run_id = (section.get("source") or {}).get("id")
    return [
        Recommendation(
            domain="climate",
            severity=Severity.ADVISORY,
            title=f"Extended dry spell of {value:g} days in the record",
            summary=(
                "Plan irrigation buffers and moisture conservation for the "
                "dry-spell period; the longest spell exceeds two weeks."
            ),
            rationale=(
                f"The latest feature run reports {metric.get('code')} = {value:g} {metric.get('unit')} "
                f"in {metric.get('period')} (WMO dry-day convention: a day is dry "
                "below 1 mm). Spells of this length deplete the root zone between "
                "rains and are the field's dominant water-stress signal."
            ),
            evidence=[evidence_item(
                type="feature_run", id=run_id, label="climate",
                detail=f"{metric.get('code')} = {value:g} {metric.get('unit')} ({metric.get('period')})",
            )],
            actions=[
                "Check the water plan's deficit windows against this dry spell.",
                "Prioritise moisture conservation (mulch/residue cover) ahead of the dry season.",
            ],
            confidence=0.75,
            confidence_basis=(
                f"deterministic: engine metric {metric.get('code')} >= "
                f"{DRY_SPELL_ADVISORY_DAYS}-day screening threshold"
            ),
        )
    ]


@registry.generator("climate")
def hot_days_advisory(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("climate") or {}
    metrics = section.get("metrics") or []
    metric = _metric(metrics, "hot_days_35c_count")
    if metric is None or metric.get("value") is None:
        return []
    value = float(metric["value"])
    if value < HOT_DAYS_ADVISORY_COUNT:
        return []
    run_id = (section.get("source") or {}).get("id")
    return [
        Recommendation(
            domain="climate",
            severity=Severity.ADVISORY,
            title=f"{value:g} hot days (≥ 35 °C) recorded in {metric.get('period')}",
            summary=(
                "Heat stress is material in this record — schedule heat-sensitive "
                "operations away from peak heat and verify crop choice."
            ),
            rationale=(
                f"The latest feature run reports {metric.get('code')} = {value:g} {metric.get('unit')} "
                f"in {metric.get('period')}, at or above the {HOT_DAYS_ADVISORY_COUNT}-day "
                "season screening level for days ≥ 35 °C (generic climate index — "
                "crop-specific thresholds await the versioned crop knowledge base)."
            ),
            evidence=[evidence_item(
                type="feature_run", id=run_id, label="climate",
                detail=f"{metric.get('code')} = {value:g} {metric.get('unit')} ({metric.get('period')})",
            )],
            actions=[
                "Shift field operations away from peak-heat hours.",
                "Re-check crop suitability and sowing window for heat escape.",
            ],
            confidence=0.7,
            confidence_basis=(
                f"deterministic: engine metric {metric.get('code')} >= "
                f"{HOT_DAYS_ADVISORY_COUNT}-day screening threshold"
            ),
        )
    ]


@registry.generator("climate")
def precipitation_anomaly_advisory(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("climate") or {}
    metrics = section.get("metrics") or []
    metric = _metric(metrics, "precipitation_anomaly_z")
    if metric is None or metric.get("value") is None:
        return []
    value = float(metric["value"])
    if abs(value) < PRECIP_Z_STRONG:
        return []
    run_id = (section.get("source") or {}).get("id")
    direction = "above" if value > 0 else "below"
    return [
        Recommendation(
            domain="climate",
            severity=Severity.ADVISORY,
            title=(
                f"Precipitation strongly {'above' if value > 0 else 'below'} normal "
                f"(z = {value:g}) in {metric.get('period')}"
            ),
            summary=(
                "The engine's own anomaly index flags this month as statistically "
                "unusual — review drainage or irrigation plans accordingly."
            ),
            rationale=(
                f"The latest feature run reports {metric.get('code')} = {value:g} (dimensionless "
                f"z against the run's reference climatology), beyond the ±{PRECIP_Z_STRONG:g} "
                "screening level. The value is the engine's own z-feature — no "
                "re-computation or forecast is involved."
            ),
            evidence=[evidence_item(
                type="feature_run", id=run_id, label="climate",
                detail=f"{metric.get('code')} = {value:g} ({metric.get('period')})",
            )],
            actions=[
                (
                    "Review drainage/waterlogging risk for the wet anomaly."
                    if value > 0
                    else "Review irrigation adequacy for the dry anomaly."
                ),
            ],
            confidence=0.7,
            confidence_basis=(
                f"deterministic: engine z-feature |{metric.get('code')}| >= {PRECIP_Z_STRONG:g}"
            ),
        )
    ]


@registry.generator("climate")
def statistical_anomaly_advisories(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """One advisory per statistically unusual metric (top |z| first)."""
    out: list[Recommendation] = []
    section = ctx.section("climate") or {}
    run_id = (section.get("source") or {}).get("id")
    covered_prefixes = ("dry_spell_max_days", "hot_days_35c_count", "precipitation_anomaly_z")
    for finding in ctx.anomalies:
        if len(out) >= MAX_ANOMALY_RECS:
            break
        code = str(finding.get("metric", ""))
        if any(code.startswith(p) for p in covered_prefixes):
            continue  # already covered by the dedicated rules above
        if finding.get("kind") == "trend":
            title = (
                f"{code} is trending {finding.get('direction')} its usual range"
            )
        else:
            title = (
                f"{code} unusually {finding.get('direction')} its own baseline "
                f"(z = {finding.get('z')})"
            )
        out.append(
            Recommendation(
                domain="climate",
                severity=Severity.ADVISORY,
                title=title,
                summary=(
                    "Statistical screening flags this metric against the field's "
                    "own history — inspect the feature values before acting."
                ),
                rationale=finding.get("detail", ""),
                evidence=[evidence_item(
                    type="feature_run", id=run_id, label="climate",
                    detail=(
                        f"{code} ({finding.get('aggregation_level')}) = {finding.get('value')} "
                        f"in {finding.get('period')}; baseline mean "
                        f"{finding.get('baseline_mean')}, z = {finding.get('z')}"
                    ),
                )],
                actions=[
                    "Open the feature-run values for this period and verify the record.",
                ],
                confidence=0.6,
                confidence_basis=(
                    f"deterministic: per-series z-score |z| >= {Z_THRESHOLD:g} "
                    f"(population σ, minimum 5 periods)"
                ),
            )
        )
    return out
