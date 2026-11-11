"""Forecast-based agricultural risk screening (P2.B).

Screening translates FORECAST values into crop-relevant risk signals using
DOCUMENTED, GENERIC thresholds. Threshold provenance:

- Frost day: daily minimum temperature <= 0 degC (ETCCDI frost-day definition,
  same constant as the feature engine's `frost_days_0c`).
- Extreme heat day: daily maximum temperature >= 35 degC (ETCCDI hot-day
  definition, same constant as `hot_days_35c`).
- Heavy precipitation day: daily precipitation >= 10 mm (ETCCDI R10mm).
- Dry spell: >= 5 consecutive days with precipitation < 1 mm (WMO dry-day
  definition; 5 days is the ETCCDI consecutive-dry-day convention, more
  decision-relevant within a forecast window than the monthly maximum).
- Planting-window risk: forecast extreme heat / heavy precipitation / frost
  days overlapping a crop's documented calendar planting window (crop
  calendar windows from the knowledge base — crop-specific only where the
  KB actually documents windows).
- Harvest-window risk: same overlap logic against harvest windows.

Crop-specific thresholds (e.g. crop-specific critical temperatures) are NOT
invented here: the knowledge base currently carries no such traits, so all
thresholds are the documented generic ones with citations attached. Every
risk item carries: window, threshold, source label, observed forecast values
count, and an explicit `basis: forecast` (never mixed with observations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

RISK_SCREENING_VERSION = "forecast-risk-1.0.0"

FROST_DAY_THRESHOLD_C = 0.0
HOT_DAY_THRESHOLD_C = 35.0
HEAVY_PRECIP_MM = 10.0
DRY_SPELL_DAYS = 5
DRY_DAY_MM = 1.0


@dataclass
class RiskItem:
    risk_code: str
    severity: str  # info | advisory | recommended
    title: str
    detail: str
    window_start: datetime | None
    window_end: datetime | None
    threshold: str
    threshold_source: str
    affected_days: int
    forecast_days_total: int
    basis: str = "forecast"
    crop_context: str | None = None
    version: str = RISK_SCREENING_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_code": self.risk_code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "threshold": self.threshold,
            "threshold_source": self.threshold_source,
            "affected_days": self.affected_days,
            "forecast_days_total": self.forecast_days_total,
            "basis": self.basis,
            "crop_context": self.crop_context,
            "version": self.version,
        }


def screen_forecast_risks(
    *,
    forecast_rows: list[dict[str, Any]],
    crop_windows: list[dict[str, Any]] | None = None,
) -> list[RiskItem]:
    """Screen a forecast window for agricultural risks.

    `forecast_rows`: flat rows with {variable_code, value, valid_time} —
    VALID values only (missing rows excluded upstream).
    `crop_windows`: optional crop calendar entries
    {crop_code, window_type: planting|harvest, start_month, start_day,
    end_month, end_day} from the knowledge base.
    """
    rows = [r for r in forecast_rows if r.get("value") is not None and r.get("valid_time")]
    if not rows:
        return []
    days_total = len({r["valid_time"].date() for r in rows})

    tmax_by_day: dict[Any, float] = {}
    tmin_by_day: dict[Any, float] = {}
    precip_by_day: dict[Any, float] = {}
    for row in rows:
        day = row["valid_time"].date()
        code = row["variable_code"]
        value = float(row["value"])
        if code == "air_temperature_max":
            existing = tmax_by_day.get(day)
            tmax_by_day[day] = value if existing is None else max(existing, value)
        elif code == "air_temperature_min":
            existing = tmin_by_day.get(day)
            tmin_by_day[day] = value if existing is None else min(existing, value)
        elif code == "precipitation":
            precip_by_day[day] = precip_by_day.get(day, 0.0) + value

    risks: list[RiskItem] = []
    window_start = min(tmax_by_day.keys() | tmin_by_day.keys() | precip_by_day.keys(), default=None)
    window_end = max(tmax_by_day.keys() | tmin_by_day.keys() | precip_by_day.keys(), default=None)
    if window_start is None:
        return []

    # Frost days
    frost_days = sorted(d for d, v in tmin_by_day.items() if v <= FROST_DAY_THRESHOLD_C)
    if frost_days:
        risks.append(
            RiskItem(
                risk_code="frost_risk",
                severity="recommended" if len(frost_days) >= 2 else "advisory",
                title="Frost risk in the forecast window",
                detail=(
                    f"{len(frost_days)} forecast day(s) with minimum temperature "
                    f"<= {FROST_DAY_THRESHOLD_C:.0f} degC "
                    f"({frost_days[0].isoformat()} .. {frost_days[-1].isoformat()})."
                ),
                window_start=datetime.combine(frost_days[0], datetime.min.time()),
                window_end=datetime.combine(frost_days[-1], datetime.min.time()),
                threshold=f"tmin <= {FROST_DAY_THRESHOLD_C:.0f} degC",
                threshold_source="ETCCDI frost-day definition (features catalog frost_days_0c)",
                affected_days=len(frost_days),
                forecast_days_total=days_total,
            )
        )

    # Extreme heat days
    hot_days = sorted(d for d, v in tmax_by_day.items() if v >= HOT_DAY_THRESHOLD_C)
    if hot_days:
        risks.append(
            RiskItem(
                risk_code="extreme_heat_risk",
                severity="recommended" if len(hot_days) >= 3 else "advisory",
                title="Extreme heat in the forecast window",
                detail=(
                    f"{len(hot_days)} forecast day(s) with maximum temperature "
                    f">= {HOT_DAY_THRESHOLD_C:.0f} degC "
                    f"({hot_days[0].isoformat()} .. {hot_days[-1].isoformat()})."
                ),
                window_start=datetime.combine(hot_days[0], datetime.min.time()),
                window_end=datetime.combine(hot_days[-1], datetime.min.time()),
                threshold=f"tmax >= {HOT_DAY_THRESHOLD_C:.0f} degC",
                threshold_source="ETCCDI hot-day definition (features catalog hot_days_35c)",
                affected_days=len(hot_days),
                forecast_days_total=days_total,
            )
        )

    # Heavy precipitation
    heavy_days = sorted(d for d, v in precip_by_day.items() if v >= HEAVY_PRECIP_MM)
    if heavy_days:
        total_mm = sum(precip_by_day[d] for d in heavy_days)
        risks.append(
            RiskItem(
                risk_code="heavy_precipitation_risk",
                severity="advisory" if len(heavy_days) < 2 else "recommended",
                title="Heavy precipitation in the forecast window",
                detail=(
                    f"{len(heavy_days)} forecast day(s) with >= {HEAVY_PRECIP_MM:.0f} mm "
                    f"(total {total_mm:.1f} mm on those days)."
                ),
                window_start=datetime.combine(heavy_days[0], datetime.min.time()),
                window_end=datetime.combine(heavy_days[-1], datetime.min.time()),
                threshold=f"daily precipitation >= {HEAVY_PRECIP_MM:.0f} mm",
                threshold_source="ETCCDI R10mm",
                affected_days=len(heavy_days),
                forecast_days_total=days_total,
            )
        )

    # Dry spell (consecutive dry days within the window)
    all_days = sorted(precip_by_day.keys())
    longest_run: list[Any] = []
    current_run: list[Any] = []
    for day in all_days:
        if precip_by_day[day] < DRY_DAY_MM:
            current_run.append(day)
            if len(current_run) > len(longest_run):
                longest_run = list(current_run)
        else:
            current_run = []
    if len(longest_run) >= DRY_SPELL_DAYS:
        risks.append(
            RiskItem(
                risk_code="dry_spell_risk",
                severity="advisory",
                title="Dry spell in the forecast window",
                detail=(
                    f"{len(longest_run)} consecutive day(s) with precipitation "
                    f"< {DRY_DAY_MM:.0f} mm "
                    f"({longest_run[0].isoformat()} .. {longest_run[-1].isoformat()})."
                ),
                window_start=datetime.combine(longest_run[0], datetime.min.time()),
                window_end=datetime.combine(longest_run[-1], datetime.min.time()),
                threshold=f"{DRY_SPELL_DAYS}+ consecutive days < {DRY_DAY_MM:.0f} mm",
                threshold_source="ETCCDI consecutive-dry-day convention (WMO dry day < 1 mm)",
                affected_days=len(longest_run),
                forecast_days_total=days_total,
            )
        )

    # Crop calendar overlaps (planting / harvest window risk)
    for window in crop_windows or []:
        window_type = window.get("window_type")
        crop_code = window.get("crop_code")
        overlaps = _days_in_calendar_window(
            days=sorted(tmax_by_day.keys() | tmin_by_day.keys() | precip_by_day.keys()),
            start_month=window.get("start_month"),
            start_day=window.get("start_day"),
            end_month=window.get("end_day_month") or window.get("end_month"),
            end_day=window.get("end_day"),
        )
        if not overlaps:
            continue
        stress_days = [d for d in overlaps if d in hot_days or d in frost_days or d in heavy_days]
        if not stress_days:
            continue
        label = "planting" if window_type == "planting" else "harvest"
        risks.append(
            RiskItem(
                risk_code=f"{label}_window_risk",
                severity="recommended",
                title=f"Forecast stress inside the {crop_code} {label} window",
                detail=(
                    f"{len(stress_days)} day(s) of forecast heat/frost/heavy-rain fall "
                    f"inside the documented {crop_code} {label} window "
                    f"({overlaps[0].isoformat()} .. {overlaps[-1].isoformat()})."
                ),
                window_start=datetime.combine(stress_days[0], datetime.min.time()),
                window_end=datetime.combine(stress_days[-1], datetime.min.time()),
                threshold="overlap of crop calendar window with heat/frost/heavy-rain days",
                threshold_source="crop calendar windows (knowledge base) + ETCCDI day thresholds",
                affected_days=len(stress_days),
                forecast_days_total=days_total,
                crop_context=crop_code,
            )
        )
    severity_rank = {"recommended": 0, "advisory": 1, "info": 2}
    risks.sort(key=lambda r: severity_rank.get(r.severity, 3))
    return risks


def _days_in_calendar_window(
    *,
    days: list[Any],
    start_month: int | None,
    start_day: int | None,
    end_month: int | None,
    end_day: int | None,
) -> list[Any]:
    """MM-DD recurring window overlap with a list of dates (year-wrapping)."""
    if not (start_month and start_day and end_month and end_day):
        return []
    start_md = (start_month, start_day)
    end_md = (end_month, end_day)
    out: list[Any] = []
    for day in days:
        md = (day.month, day.day)
        if start_md <= end_md:
            inside = start_md <= md <= end_md
        else:  # wraps year end
            inside = md >= start_md or md <= end_md
        if inside:
            out.append(day)
    return out
