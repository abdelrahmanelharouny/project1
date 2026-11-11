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
from app.recommendations.evidence_quality import (
    assess_evidence_quality,
    evidence_backed_confidence,
)
from app.recommendations.registry import RecommendationContext, registry

logger = logging.getLogger("croptwist.recommendations.climate")

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
            confidence_kind="deterministic_rule",
            confidence_basis=(
                "deterministic: absence of a succeeded feature_run row for the "
                "field is a verifiable fact — the constant states trigger "
                "certainty, not statistical calibration"
            ),
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
    quality = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
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
            confidence=evidence_backed_confidence(quality),
            confidence_kind="evidence_quality",
            confidence_basis=(
                f"heuristic threshold (engine metric {metric.get('code')} >= "
                f"{DRY_SPELL_ADVISORY_DAYS} days) screened over evidence of "
                f"documented quality — NOT a calibrated probability: "
                f"{quality.get('summary')}"
            ),
            evidence_quality=quality,
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
    quality = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
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
            confidence=evidence_backed_confidence(quality),
            confidence_kind="evidence_quality",
            confidence_basis=(
                f"heuristic threshold (engine metric {metric.get('code')} >= "
                f"{HOT_DAYS_ADVISORY_COUNT} days) screened over evidence of "
                f"documented quality — NOT a calibrated probability: "
                f"{quality.get('summary')}"
            ),
            evidence_quality=quality,
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
    quality = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
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
            confidence=evidence_backed_confidence(quality),
            confidence_kind="evidence_quality",
            confidence_basis=(
                f"engine z-feature |{metric.get('code')}| >= {PRECIP_Z_STRONG:g} "
                f"screened over evidence of documented quality — NOT a "
                f"calibrated probability: {quality.get('summary')}"
            ),
            evidence_quality=quality,
        )
    ]


@registry.generator("climate")
def statistical_anomaly_advisories(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """One advisory per statistically unusual metric (top |z| first)."""
    out: list[Recommendation] = []
    section = ctx.section("climate") or {}
    run_id = (section.get("source") or {}).get("id")
    quality = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
    covered_prefixes = ("dry_spell_max_days", "hot_days_35c_count", "precipitation_anomaly_z")
    for finding in ctx.anomalies:
        if len(out) >= MAX_ANOMALY_RECS:
            break
        code = str(finding.get("metric", ""))
        if any(code.startswith(p) for p in covered_prefixes):
            continue  # already covered by the dedicated rules above
        if finding.get("kind") not in ("anomaly", "trend"):
            continue  # seasonal_variation / insufficient_baseline are not advice triggers
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
                confidence=evidence_backed_confidence(quality),
                confidence_kind="evidence_quality",
                confidence_basis=(
                    f"z-score screening |z| >= {Z_THRESHOLD:g} over the same-month "
                    f"baseline (population σ) — NOT a calibrated probability: "
                    f"{quality.get('summary')}"
                ),
                evidence_quality=quality,
            )
        )
    return out


@registry.generator("climate")
def forecast_risk_advisories(db, field, ctx: RecommendationContext) -> list[Recommendation]:
    """P2.B: convert the forecast risk screening into recommendations.

    Reads the LIVE forecast window (weather_forecasts — never blended into
    observations). When no forecast has been ingested the generator emits
    nothing: forecast absence is a data gap reported by the forecast surface,
    not a fabricated advisory. Thresholds are the documented generic ETCCDI/
    WMO definitions reused by the risk screener (no crop-specific critical
    thresholds are invented)."""
    from datetime import UTC, datetime, timedelta

    from app.climate.risk import screen_forecast_risks
    from app.climate.service import forecasts_in_window
    from app.db.models_p2 import WeatherForecast
    from sqlalchemy import func, select as _select

    try:
        count = db.scalar(
            _select(func.count(WeatherForecast.id)).where(WeatherForecast.field_id == field.id)
        )
        if (count or 0) == 0:
            return []
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC) + timedelta(days=16)
        flat_rows: list[dict[str, Any]] = []
        for vcode in ("air_temperature_max", "air_temperature_min", "precipitation"):
            rows = forecasts_in_window(db, field.id, variable_code=vcode, start=start, end=end)
            flat_rows.extend(
                {"variable_code": vcode, "value": r.value, "valid_time": r.valid_time}
                for r in rows
            )
        crop_windows = _climate_crop_windows(db, field.id)
        risks = screen_forecast_risks(forecast_rows=flat_rows, crop_windows=crop_windows)
    except Exception as exc:  # noqa: BLE001 — forecast hiccups never break the refresh
        logger.warning("forecast risk screening skipped: %s", exc)
        return []

    quality = assess_evidence_quality(ctx, "climate", expected_sections=("climate",))
    out: list[Recommendation] = []
    severity_map = {
        "info": Severity.INFO,
        "advisory": Severity.ADVISORY,
        "recommended": Severity.RECOMMENDED,
        "required": Severity.REQUIRED,
    }
    for risk in risks[:3]:
        out.append(
            Recommendation(
                domain="climate",
                severity=severity_map.get(risk.severity, Severity.ADVISORY),
                title=risk.title,
                summary=risk.detail,
                rationale=(
                    f"Screening of the CURRENT FORECAST window (issue/valid-time "
                    f"separated, never mixed with observations) against the "
                    f"documented threshold: {risk.threshold} ({risk.threshold_source}). "
                    f"{risk.affected_days} of {risk.forecast_days_total} forecast day(s) "
                    f"are affected. Basis: {risk.basis}."
                ),
                evidence=[evidence_item(
                    type="weather_forecast", id=None, label="climate",
                    detail=(
                        f"Forecast window {risk.window_start} .. {risk.window_end}; "
                        f"threshold {risk.threshold} ({risk.threshold_source})"
                    ),
                )],
                actions=[{
                    "title": "Check the forecast timeline before field operations",
                    "detail": "Horizon-resolved values and freshness are on the Climate Forecasting tab.",
                }],
                confidence=evidence_backed_confidence(quality),
                confidence_kind="evidence_quality",
                confidence_basis=(
                    "Deterministic threshold screening over a single-model "
                    f"forecast whose skill degrades with horizon; {quality.get('summary')}"
                ),
                evidence_quality=quality,
            )
        )
    return out


def _climate_crop_windows(db, field) -> list[dict[str, Any]]:
    """Crop calendar windows (MM-DD) for the crops that grew on this field."""
    from app.db import models as dbm
    from sqlalchemy import select as _select

    history = list(
        db.scalars(_select(dbm.CropHistory).where(dbm.CropHistory.field_id == field.id))
    )
    crop_ids = [h.crop_id for h in history if h.crop_id is not None]
    if not crop_ids:
        return []
    windows = list(
        db.scalars(
            _select(dbm.CropCalendarWindow).where(dbm.CropCalendarWindow.crop_id.in_(crop_ids))
        )
    )
    out: list[dict[str, Any]] = []
    for w in windows:
        for window_type, raw_start, raw_end in (
            ("planting", w.planting_start, w.planting_end),
            ("harvest", w.harvest_start, w.harvest_end),
        ):
            if not raw_start or not raw_end:
                continue
            try:
                sm, sd = int(raw_start.split("-")[0]), int(raw_start.split("-")[1])
                em, ed = int(raw_end.split("-")[0]), int(raw_end.split("-")[1])
            except (ValueError, AttributeError):
                continue
            out.append(
                {
                    "crop_code": None,
                    "window_type": window_type,
                    "start_month": sm,
                    "start_day": sd,
                    "end_month": em,
                    "end_day": ed,
                }
            )
    return out
