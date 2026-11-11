"""Vegetation stress intelligence (P2.A) — evidence-based cause context.

The foundational discipline: a vegetation index reports OBSERVED vegetation
change. Causes (heat, drought, waterlogging, nutrient issues, disease) are
INFERRED and only ever stated as hypotheses supported by explicit
environmental evidence from other evidence domains:

- Temperature context: hot-day counts / temperature z from the feature run.
- Rainfall context: precipitation z / dry-spell findings from the feature run.
- Soil moisture context: surface soil moisture feature (reanalysis — coarse).
- Water context: active deficit windows from the latest water plan.
- Growth-stage context: crop calendar windows for the field's crops — a
  decline inside a documented post-harvest window is normal, not stress.

Output contract: each signal separates `observed_change` (statistical fact
with baseline) from `possible_context` (list of {factor, evidence_ref,
relationship}) and `not_supported` (explicitly what CANNOT be claimed, e.g.
disease). Severity is a screening label (info/advisory/recommended), never a
probability.
"""

from __future__ import annotations

from typing import Any

VEGETATION_STRESS_VERSION = "veg-stress-1.0.0"

# Context factors considered (each requires actual evidence presence).
CONSIDERED_FACTORS = ("temperature", "rainfall", "soil_moisture", "water_deficit", "crop_stage")


def _month_of(finding: dict[str, Any]) -> int | None:
    period = finding.get("period") or {}
    return period.get("month")


def _decline_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        f
        for f in findings
        if f.get("kind") == "anomaly" and f.get("direction") == "below_baseline"
        or (f.get("kind") == "trend" and f.get("direction") == "declining")
    ]


def _climate_context_for_month(
    evidence: dict[str, Any],
    anomalies: list[dict[str, Any]],
    month: int | None,
) -> list[dict[str, Any]]:
    """Collect climate factor evidence relevant to the anomaly month."""
    context: list[dict[str, Any]] = []
    climate_metrics = (evidence.get("climate") or {}).get("metrics") or []
    metric_by_code: dict[str, dict[str, Any]] = {}
    for metric in climate_metrics:
        code = metric.get("code")
        if code:
            metric_by_code.setdefault(code, metric)
    for finding in anomalies:
        metric = finding.get("metric") or ""
        period = finding.get("period")
        period_month = period.get("month") if isinstance(period, dict) else None
        if month is not None and period_month not in (None, month):
            continue
        if finding.get("kind") == "anomaly" and metric.startswith("air_temperature"):
            context.append(
                {
                    "factor": "temperature",
                    "evidence_kind": "climate_anomaly",
                    "metric": metric,
                    "z": finding.get("z"),
                    "direction": finding.get("direction"),
                    "detail": finding.get("detail"),
                }
            )
        elif finding.get("kind") == "anomaly" and metric.startswith("precipitation"):
            context.append(
                {
                    "factor": "rainfall",
                    "evidence_kind": "climate_anomaly",
                    "metric": metric,
                    "z": finding.get("z"),
                    "direction": finding.get("direction"),
                    "detail": finding.get("detail"),
                }
            )
        elif finding.get("kind") == "trend" and metric.startswith("precipitation"):
            context.append(
                {
                    "factor": "rainfall",
                    "evidence_kind": "climate_trend",
                    "metric": metric,
                    "detail": finding.get("detail"),
                }
            )
    for code, metric in metric_by_code.items():
        if code == "dry_spell_max_days_monthly" and isinstance(metric.get("value"), (int, float)):
            if metric["value"] >= 14:
                context.append(
                    {
                        "factor": "rainfall",
                        "evidence_kind": "dry_spell",
                        "metric": code,
                        "value": metric["value"],
                        "unit": metric.get("unit", "days"),
                        "detail": f"Longest dry spell in the evaluated window: {metric['value']} consecutive days (<1 mm).",
                    }
                )
        if code == "hot_days_35c_count_monthly" and isinstance(metric.get("value"), (int, float)):
            if metric["value"] > 0:
                context.append(
                    {
                        "factor": "temperature",
                        "evidence_kind": "hot_days",
                        "metric": code,
                        "value": metric["value"],
                        "unit": metric.get("unit", "days"),
                        "detail": f"{metric['value']} day(s) at or above 35 degC in the evaluated window (generic WMO/ETCCDI threshold).",
                    }
                )
        if code == "soil_moisture_surface_mean_monthly" and metric.get("value") is not None:
            context.append(
                {
                    "factor": "soil_moisture",
                    "evidence_kind": "reanalysis_surface_moisture",
                    "metric": code,
                    "value": metric.get("value"),
                    "unit": metric.get("unit", "m3/m3"),
                    "detail": "Surface soil moisture (reanalysis-derived; coarse grid, not a field sensor).",
                }
            )
    return context


def _water_deficit_context(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    water = evidence.get("water") or {}
    windows = water.get("deficit_windows") or []
    context: list[dict[str, Any]] = []
    for window in windows:
        context.append(
            {
                "factor": "water_deficit",
                "evidence_kind": "water_plan_deficit_window",
                "detail": (
                    f"Documented root-zone deficit window {window.get('start','?')} to "
                    f"{window.get('end','?')} from the latest water plan."
                ),
            }
        )
    return context


def _stage_context(evidence: dict[str, Any], month: int | None) -> list[dict[str, Any]]:
    rotation = evidence.get("rotation") or {}
    assignment = rotation.get("assignment") or {}
    crops = assignment.get("crops") or []
    context: list[dict[str, Any]] = []
    for crop in crops:
        windows = (crop.get("calendar_windows") or [])
        for window in windows:
            harvest_month = window.get("harvest_month")
            if month is not None and harvest_month == month:
                context.append(
                    {
                        "factor": "crop_stage",
                        "evidence_kind": "crop_calendar_harvest_window",
                        "crop": crop.get("crop_code"),
                        "detail": (
                            f"Calendar month {month} falls in a documented harvest window "
                            f"for {crop.get('crop_code')}; vegetation decline here is "
                            "consistent with harvest, not necessarily stress."
                        ),
                    }
                )
    return context


def build_stress_signals(
    *,
    index: str,
    findings: list[dict[str, Any]],
    evidence: dict[str, Any],
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build stress signals from vegetation findings + cross-domain evidence.

    Each signal: observed_change (the statistical finding), possible_context
    (factors WITH evidence), not_supported (explicit non-claims), severity.
    A finding with no supporting context yields possible_context=[] and keeps
    the honest "cause unknown" posture.
    """
    signals: list[dict[str, Any]] = []
    for finding in _decline_findings(findings):
        if finding.get("context") == "seasonal_dormancy_or_harvest":
            continue
        month = _month_of(finding)
        context = []
        context.extend(_climate_context_for_month(evidence, anomalies, month))
        context.extend(_water_deficit_context(evidence))
        context.extend(_stage_context(evidence, month))
        # Severity: screening label tied to evidence breadth — NOT a probability.
        factor_count = len({c["factor"] for c in context if c["factor"] != "crop_stage"})
        if factor_count >= 2:
            severity = "recommended"
        elif factor_count == 1:
            severity = "advisory"
        else:
            severity = "info"
        not_supported = ["disease or pest diagnosis", "nutrient deficiency diagnosis"]
        if not context:
            not_supported.append("any specific cause (no corroborating environmental evidence)")
        signals.append(
            {
                "index": index,
                "observed_change": {
                    "kind": finding.get("kind"),
                    "period": finding.get("period"),
                    "value": finding.get("value"),
                    "z": finding.get("z"),
                    "slope_per_year": finding.get("slope_per_year"),
                    "detail": finding.get("detail"),
                    "baseline": finding.get("baseline"),
                },
                "possible_context": context,
                "not_supported": not_supported,
                "severity": severity,
                "version": VEGETATION_STRESS_VERSION,
            }
        )
    return signals
