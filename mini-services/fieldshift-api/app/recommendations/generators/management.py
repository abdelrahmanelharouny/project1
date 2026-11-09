"""Management recommendations.

Reads the management section of the evidence pack: the soil-cover metrics
(trailing 365-day window over stored records) and the latest erosion
assessment run. The erosion run's own `not_evaluated` status lists exactly
which RUSLE factors are missing — naming them IS the actionable advice
(collect them), so an unevaluated screening becomes an INFO recommendation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("fieldshift.recommendations.management")

# Screening heuristic (disclosed): below this protective-cover fraction the
# field is flagged for cover improvement. No regionally validated threshold
# ships with the platform; confidence is reduced accordingly.
COVER_FRACTION_LOW = 0.5

_FACTOR_LABELS: dict[str, str] = {
    "R": "rainfall erosivity (R)",
    "K": "soil erodibility (K)",
    "LS": "slope length/steepness (LS)",
    "C": "cover-management (C)",
    "P": "support practice (P)",
}


@registry.generator("management")
def management_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    if ctx.section("management") is not None:
        return []
    return [
        Recommendation(
            domain="management",
            severity=Severity.INFO,
            title="No management data yet — record cover/management evidence to unlock advice",
            summary=(
                "No soil-cover records and no erosion assessment exist for this "
                "field, so management advice cannot be grounded."
            ),
            rationale=(
                "The intelligence layer reads soil-cover records (crop history, "
                "cover-crop items, management events, cover observations) and the "
                "latest erosion assessment run. Without any of them the "
                "management domain is a data gap."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: management",
            )],
            actions=[
                "Record a soil-cover observation or crop history for the field.",
                "Run an erosion assessment "
                "(POST /api/v1/fields/{id}/erosion-assessments).",
            ],
            confidence=0.95,
            confidence_basis=(
                "deterministic: absence of cover records and succeeded "
                "erosion_assessment_run rows"
            ),
        )
    ]


@registry.generator("management")
def erosion_factors_missing(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("management") or {}
    erosion = section.get("erosion") or {}
    if erosion.get("rusle_status") != "not_evaluated":
        return []
    missing = list(erosion.get("missing_factors") or [])
    run_id = (erosion.get("source") or {}).get("id")
    labels = ", ".join(_FACTOR_LABELS.get(f, str(f)) for f in missing) or "all factors"
    return [
        Recommendation(
            domain="management",
            severity=Severity.INFO,
            title=(
                f"Erosion model not evaluated — {len(missing) or 5} RUSLE factor(s) missing"
                if missing
                else "Erosion model not evaluated — no RUSLE factors supplied"
            ),
            summary=(
                "The RUSLE screening refuses to compute a partial product. "
                f"Collecting the missing factor(s) ({labels}) unblocks the "
                "model estimate."
            ),
            rationale=(
                f"Erosion assessment run {run_id} reports RUSLE status "
                f"'not_evaluated' with missing factors: {labels}. The engine "
                "names exactly what is absent — that list is the actionable "
                "next step (RUSLE refuses partial products by design)."
            ),
            evidence=[evidence_item(
                type="erosion_assessment_run", id=run_id, label="management",
                detail=f"rusle.status = not_evaluated; missing_factors = {missing or list(_FACTOR_LABELS)}",
            )],
            actions=[
                f"Source and record the missing factor(s): {labels}.",
                "Re-run the erosion assessment once the factors are recorded.",
            ],
            confidence=0.9,
            confidence_basis=(
                "deterministic: erosion run reports rusle.status 'not_evaluated' "
                "and names its missing factors"
            ),
        )
    ]


@registry.generator("management")
def erosion_concerns(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("management") or {}
    erosion = section.get("erosion") or {}
    concerns = erosion.get("screening_concern_count") or 0
    if not concerns:
        return []
    run_id = (erosion.get("source") or {}).get("id")
    return [
        Recommendation(
            domain="management",
            severity=Severity.ADVISORY,
            title=f"Erosion screening raised {concerns} evidence-of-concern flag(s)",
            summary=(
                "Field records show susceptibility evidence (exposed soil, slope, "
                "erodibility or erosive rainfall) — review conservation practices."
            ),
            rationale=(
                f"Erosion assessment run {run_id} raised {concerns} concern flag(s) "
                "in its qualitative screening (each flag cites the exact evidence "
                "that raised it). This is susceptibility evidence — NOT a "
                "soil-loss prediction."
            ),
            evidence=[evidence_item(
                type="erosion_assessment_run", id=run_id, label="management",
                detail=f"screening.concerns = {concerns} flag(s)",
            )],
            actions=[
                "Open the erosion assessment and read the flagged evidence.",
                "Check the conservation alternatives the run proposes for this field.",
            ],
            confidence=0.7,
            confidence_basis=(
                "deterministic: erosion-run qualitative screening concerns > 0"
            ),
        )
    ]


@registry.generator("management")
def low_soil_cover(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("management") or {}
    cover = section.get("soil_cover") or {}
    fraction = cover.get("protective_cover_fraction")
    if fraction is None or float(fraction) >= COVER_FRACTION_LOW:
        return []
    bare = cover.get("days_known_bare")
    longest = cover.get("longest_bare_interval_days")
    window = cover.get("window") or {}
    pct = round(float(fraction) * 100, 1)
    return [
        Recommendation(
            domain="management",
            severity=Severity.ADVISORY,
            title=f"Protective cover is low: {pct:g}% of the last year",
            summary=(
                "Over the trailing window the soil was protected for only "
                f"{pct:g}% of days — evaluate cover crops or residue retention "
                "to close the bare periods."
            ),
            rationale=(
                f"Soil-cover metrics over {window.get('start')} → {window.get('end')} report "
                f"{cover.get('days_protective_cover')} protected days, {bare} known-bare day(s) and "
                f"a longest bare interval of {longest} day(s) (protective fraction "
                f"{float(fraction):g} = protective / (protective + bare + unknown); "
                f"unknown days are reported separately, never merged into bare). "
                f"The {COVER_FRACTION_LOW:g} level is a screening heuristic — the platform ships "
                "no regionally validated cover threshold."
            ),
            evidence=[evidence_item(
                type="soil_cover_timeline", id=None, label="management",
                detail=(
                    f"protective_cover_fraction = {float(fraction):g} "
                    f"({cover.get('days_protective_cover')}/{cover.get('window_days')} days); "
                    f"days_known_bare = {bare}; longest_bare_interval_days = {longest}"
                ),
            )],
            actions=[
                "Plan a cover crop for the bare window "
                "(POST /api/v1/fields/{id}/cover-crop-plans).",
                "Retain residue after harvest instead of removing it.",
            ],
            confidence=0.6,
            confidence_basis=(
                f"deterministic comparison against a disclosed screening heuristic "
                f"(protective fraction < {COVER_FRACTION_LOW:g}); no validated local threshold exists"
            ),
        )
    ]
