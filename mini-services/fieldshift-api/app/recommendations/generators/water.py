"""Water recommendations.

Reads the water section of the evidence pack (latest succeeded water plan).
The plan already contains the numbers (NIR/GIR mm, deficit windows with dates
and Dr depths, allocation shortfall volumes) — these generators only compare
and explain them.
"""

from __future__ import annotations

import logging
from typing import Any

from app.recommendations.contracts import Recommendation, Severity, evidence_item
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("fieldshift.recommendations.water")

# A root-zone stress window of at least this many days escalates the timing
# advisory to `recommended` (documented screening heuristic).
LONG_STRESS_WINDOW_DAYS = 10


@registry.generator("water")
def water_data_gap(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    if ctx.section("water") is not None:
        return []
    return [
        Recommendation(
            domain="water",
            severity=Severity.INFO,
            title="No water plan yet — run a water plan to unlock irrigation advice",
            summary=(
                "This field has no succeeded water plan, so net/gross irrigation "
                "requirements and deficit windows are unknown."
            ),
            rationale=(
                "The intelligence layer reads the latest succeeded water plan for "
                "irrigation evidence. Without one, seasonal NIR/GIR, allocation "
                "coverage and root-zone stress windows all stay unevaluated."
            ),
            evidence=[evidence_item(
                type="data_gap", id=None, label="data_gaps",
                detail="domains with no engine outputs: water",
            )],
            actions=[
                "Create a water plan for this field "
                "(POST /api/v1/fields/{id}/water-plans).",
            ],
            confidence=0.95,
            confidence_basis="deterministic: absence of a succeeded water_plan row for the field",
        )
    ]


@registry.generator("water")
def allocation_shortfall(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """NIR exceeding the water allocation is a REQUIRED-severity shortfall."""
    section = ctx.section("water") or {}
    allocation = section.get("water_allocation_m3")
    if allocation is None:
        return []
    plan_id = (section.get("source") or {}).get("id")
    nir_mm = section.get("nir_mm")
    gir_mm = section.get("gir_mm")
    volumes = _shortfall_volumes(ctx)
    if volumes is None:
        return []
    deficit_m3, ratio = volumes
    rec_evidence = [evidence_item(
        type="water_plan", id=plan_id, label="water",
        detail=(
            f"net irrigation requirement {nir_mm if nir_mm is not None else 'n/a'} mm "
            f"(gross {gir_mm if gir_mm is not None else 'n/a'} mm) vs allocation "
            f"{allocation:,.0f} m³ → shortfall {deficit_m3:,.0f} m³ "
            f"({round(ratio * 100, 1):g}% of allocation)"
        ),
    )]
    return [
        Recommendation(
            domain="water",
            severity=Severity.REQUIRED,
            title=(
                f"Water allocation shortfall: NIR needs {deficit_m3:,.0f} m³ more than allocated"
            ),
            summary=(
                "The plan's irrigation requirement exceeds the available allocation — "
                "resolve the shortfall before the season (priority crop, extra "
                "allocation, or acreage adjustment)."
            ),
            rationale=(
                f"The latest water plan evaluates a season net irrigation requirement of "
                f"{nir_mm if nir_mm is not None else 'n/a'} mm over the field area against an allocation of "
                f"{allocation:,.0f} m³; the engine records an allocation status of 'deficit' "
                f"with a shortfall of {deficit_m3:,.0f} m³. This is the engine's own "
                "allocation check — the shortfall is binding, not advisory."
            ),
            evidence=rec_evidence,
            actions=[
                "Request additional allocation or renegotiate the seasonal quota.",
                "Prioritise irrigation to the most water-responsive crop/season.",
                "Re-run the water plan with the adjusted allocation to confirm coverage.",
            ],
            confidence=0.9,
            confidence_basis=(
                "deterministic: water-plan allocation check status 'deficit' "
                "(engine-computed shortfall volume)"
            ),
        )
    ]


def _shortfall_volumes(ctx: RecommendationContext) -> tuple[float, float] | None:
    """(deficit_m3, nir_m3/allocation) from the allocation shortfall window."""
    plan = ctx.section("water") or {}
    if plan.get("allocation_status") != "deficit":
        return None
    window = plan.get("first_deficit_window") or {}
    if window.get("kind") != "allocation_shortfall":
        return None
    deficit_m3 = window.get("deficit_m3")
    allocation = plan.get("water_allocation_m3")
    if deficit_m3 is None or allocation in (None, 0):
        return None
    nir_m3 = float(deficit_m3) + float(allocation)
    return float(deficit_m3), nir_m3 / float(allocation)


@registry.generator("water")
def stress_window_timing(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """Root-zone stress windows → irrigation timing advice with mm numbers."""
    section = ctx.section("water") or {}
    plan = ctx.evidence.get("water") or {}
    count = plan.get("deficit_window_count") or 0
    first = plan.get("first_deficit_window") or {}
    if not count or first.get("kind") != "root_zone_stress":
        return []
    plan_id = (section.get("source") or {}).get("id")
    nir_mm = section.get("nir_mm")
    days = first.get("days")
    max_dr = first.get("max_dr_mm")
    long_window = isinstance(days, (int, float)) and days >= LONG_STRESS_WINDOW_DAYS
    severity = Severity.RECOMMENDED if long_window else Severity.ADVISORY
    window_label = (
        f"{first.get('start_date')} → {first.get('end_date')}"
        if first.get("start_date") and first.get("end_date")
        else "the recorded window"
    )
    return [
        Recommendation(
            domain="water",
            severity=severity,
            title=(
                f"{count} root-zone stress window(s) — irrigate ahead of {window_label}"
                if count == 1
                else f"{count} root-zone stress windows — first opens {first.get('start_date')}"
            ),
            summary=(
                "The daily water balance shows the root zone depleting beyond the "
                "readily-available water threshold — time irrigation before these "
                "windows, not after visible stress."
            ),
            rationale=(
                f"The latest water plan records {count} root-zone stress window(s) "
                f"(Dr > RAW); the first runs {window_label} for {days if days is not None else 'n/a'} days "
                f"peaking at {max_dr if max_dr is not None else 'n/a'} mm depletion. Season totals: "
                f"NIR {nir_mm if nir_mm is not None else 'not evaluable'} mm. The windows come from the "
                "plan's daily balance — no new simulation is performed here."
            ),
            evidence=[evidence_item(
                type="water_plan", id=plan_id, label="water",
                detail=(
                    f"deficit_windows = {count}; first root-zone window {window_label} "
                    f"({days if days is not None else 'n/a'} days, max Dr {max_dr if max_dr is not None else 'n/a'} mm)"
                ),
            )],
            actions=[
                f"Schedule irrigation to close the deficit before {first.get('start_date')}.",
                "Check the plan's month-by-month balance for the cheapest timing.",
            ],
            confidence=0.8 if not long_window else 0.85,
            confidence_basis=(
                "deterministic: water-plan daily balance reports Dr > RAW windows "
                f"(escalated to recommended at >= {LONG_STRESS_WINDOW_DAYS}-day windows)"
            ),
        )
    ]
