"""Soil recommendations.

Reads the soil section of the evidence pack (latest soil assessment, nutrient
budget and SOC stock runs). Nutrient deficits come from the budget's own
cumulative balance; the SOC comparison uses a disclosed screening heuristic —
the platform ships no validated local SOC reference, and the rationale says so.
"""

from __future__ import annotations

import logging
from typing import Any

from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("croptwist.recommendations.soil")

# Screening heuristic (disclosed): below this stock the profile is treated as
# carbon-depleted for ADVISORY purposes only. No regionally validated reference
# exists in the platform — the confidence is reduced accordingly.
SOC_STOCK_LOW_MG_HA = 30.0
NUTRIENTS = ("N", "P", "K")


@registry.generator("soil")
def soil_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    if ctx.section("soil") is not None:
        return []
    return [
        Recommendation(
            domain="soil",
            severity=Severity.INFO,
            title="No soil data yet — add soil measurements to unlock soil advice",
            summary=(
                "No soil assessment, nutrient budget or SOC stock run exists for "
                "this field, so soil health and fertilization stay unevaluated."
            ),
            rationale=(
                "The intelligence layer reads the latest soil assessment, nutrient "
                "budget and SOC stock runs. Without any of them, fertility, "
                "carbon and physical indicators are all data gaps."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: soil",
            )],
            actions=[
                "Import soil measurements (POST /api/v1/fields/{id}/soil/measurements).",
                "Run a soil assessment, a nutrient budget or a SOC stock run.",
            ],
            confidence=0.95,
            confidence_basis=(
                "deterministic: absence of succeeded soil_assessment_run, "
                "nutrient_budget_run and soc_stock_run rows"
            ),
        )
    ]


@registry.generator("soil")
def negative_nutrient_balance(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("soil") or {}
    budget = section.get("nutrient_budget") or {}
    balances = budget.get("cumulative_balance_kg_ha") or {}
    budget_id = (budget.get("source") or {}).get("id")
    out: list[Recommendation] = []
    for nutrient in NUTRIENTS:
        value = balances.get(nutrient)
        if value is None or value >= 0:
            continue
        deficit = -float(value)
        out.append(
            Recommendation(
                domain="soil",
                severity=Severity.RECOMMENDED,
                title=f"{nutrient} balance is negative: −{deficit:g} kg/ha cumulative",
                summary=(
                    f"Documented removals exceed documented {nutrient} inputs — plan a "
                    f"{nutrient} fertilization/amendment to close the deficit."
                ),
                rationale=(
                    f"Nutrient budget run {budget_id} computes a cumulative "
                    f"{nutrient} balance of {value:g} kg/ha over its evaluable seasons "
                    f"({budget.get('seasons_evaluable')} evaluable). A negative balance is an "
                    "ACCOUNTING statement over documented flows — it indicates net "
                    f"{nutrient} mining, not a measured stock change."
                ),
                evidence=[evidence_item(
                    type="nutrient_budget_run", id=budget_id, label="soil",
                    detail=(
                        f"cumulative_balance_kg_ha[{nutrient}] = {value:g} kg/ha "
                        f"over {budget.get('seasons_evaluable')} evaluable season(s)"
                    ),
                )],
                actions=[
                    f"Record planned {nutrient} applications and re-run the budget.",
                    "Cross-check high-removal seasons against actual yields.",
                ],
                confidence=0.8,
                confidence_basis=(
                    "deterministic: nutrient-budget cumulative balance < 0 kg/ha "
                    "(engine-computed from recorded flows)"
                ),
            )
        )
    return out


@registry.generator("soil")
def low_soc_stock(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    section = ctx.section("soil") or {}
    soc = section.get("soc_stock") or {}
    stock = soc.get("stock_Mg_C_ha")
    if stock is None or float(stock) >= SOC_STOCK_LOW_MG_HA:
        return []
    soc_id = (soc.get("source") or {}).get("id")
    return [
        Recommendation(
            domain="soil",
            severity=Severity.ADVISORY,
            title=f"Screened SOC stock is low: {float(stock):g} Mg C/ha",
            summary=(
                "The measured SOC stock sits below the screening heuristic — "
                "carbon-building practices (cover crops, residue retention, "
                "reduced tillage) are worth evaluating."
            ),
            rationale=(
                f"SOC stock run {soc_id} reports a profile total of {float(stock):g} Mg C/ha, "
                f"below the {SOC_STOCK_LOW_MG_HA:g} Mg C/ha screening heuristic. The platform "
                "ships NO regionally validated SOC reference — this is a coarse "
                "screening flag, not a threshold judgement."
            ),
            evidence=[evidence_item(
                type="soc_stock_run", id=soc_id, label="soil",
                detail=f"profile_total.soc_stock_mg_ha = {float(stock):g} Mg C/ha",
            )],
            actions=[
                "Evaluate cover-crop and residue-retention options for this field.",
                "Re-sample SOC on a fixed schedule to establish a trend.",
            ],
            confidence=0.55,
            confidence_basis=(
                f"deterministic comparison against a disclosed screening heuristic "
                f"({SOC_STOCK_LOW_MG_HA:g} Mg C/ha); no validated local reference exists"
            ),
        )
    ]


@registry.generator("soil")
def soil_data_collection(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """Missing indicators / unaccounted flows are INFO data-collection recs."""
    section = ctx.section("soil") or {}
    out: list[Recommendation] = []
    assessment = section.get("assessment") or {}
    assessment_id = (assessment.get("source") or {}).get("id")
    missing_domains = [
        {
            "domain": row.get("domain"),
            "missing": row.get("missing_count"),
            "available": row.get("available_count"),
        }
        for row in (assessment.get("domains") or [])
        if isinstance(row, dict) and (row.get("missing_count") or 0) > 0
    ]
    if missing_domains:
        total_missing = sum(int(d["missing"]) for d in missing_domains)
        domain_labels = ", ".join(str(d["domain"]) for d in missing_domains[:3])
        out.append(
            Recommendation(
                domain="soil",
                severity=Severity.INFO,
                title=(
                    f"{total_missing} soil indicator(s) missing across {len(missing_domains)} "
                    f"domain(s) ({domain_labels})"
                ),
                summary=(
                    "The assessment reports indicators it could not evaluate — "
                    "collecting them unlocks crop pH screening, SOC accounting "
                    "and measured water retention."
                ),
                rationale=(
                    f"Soil assessment run {assessment_id} lists {total_missing} missing "
                    "indicator(s). Missing indicators are UNKNOWN — their absence is "
                    "not evidence of poor soil health, but each one blocks a "
                    "downstream decision (decision-linked collection priorities)."
                ),
                evidence=[evidence_item(
                    type="soil_assessment_run", id=assessment_id, label="soil",
                    detail=(
                        "; ".join(
                            f"{d['domain']}: {d['available']} available, {d['missing']} missing"
                            for d in missing_domains[:3]
                        )
                    ),
                )],
                actions=[
                    "Open the soil assessment to see which variables are missing.",
                    "Prioritise measurements that unblock decisions (pH, bulk density, P).",
                ],
                confidence=0.9,
                confidence_basis=(
                    "deterministic: soil-assessment domain rows report missing_count > 0"
                ),
            )
        )
    budget = section.get("nutrient_budget") or {}
    if budget and (budget.get("seasons_evaluable") or 0) == 0:
        budget_id = (budget.get("source") or {}).get("id")
        out.append(
            Recommendation(
                domain="soil",
                severity=Severity.INFO,
                title="Nutrient budget has no evaluable seasons",
                summary=(
                    "The budget ran but no season had enough documented flows to "
                    "evaluate — record inputs (applications) and outputs (removals)."
                ),
                rationale=(
                    f"Nutrient budget run {budget_id} reports 0 evaluable seasons; "
                    "seasons without documented input/output flows are listed as "
                    "skipped, never zero-filled."
                ),
                evidence=[evidence_item(
                    type="nutrient_budget_run", id=budget_id, label="soil",
                    detail="cumulative.seasons_evaluable = 0",
                )],
                actions=[
                    "Record nutrient applications and harvest removals for a season.",
                    "Re-run the nutrient budget after recording flows.",
                ],
                confidence=0.9,
                confidence_basis="deterministic: budget cumulative reports 0 evaluable seasons",
            )
        )
    return out
