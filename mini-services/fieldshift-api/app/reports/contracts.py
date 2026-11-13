"""Reports & exports domain (P3 W5): type registry, formats, statuses.

This module is the machine-readable contract for the reports feature:

- ``REPORT_TYPES`` — every report the platform can produce, with the data
  dependencies it declares and its default sections. Report generation is
  HONEST (same rule as app/analytics): a section whose data is unavailable
  is rendered with ``provenance: "missing"`` and an explanatory note — the
  platform never fabricates agronomic or financial values.
- ``REPORT_FORMATS`` — output formats, mirroring the DB check constraint
  ``ck_report_format`` on ``report_jobs``.
- ``REPORT_STATUSES`` — job lifecycle values, mirroring ``ck_report_status``
  EXACTLY as the model defines them (queued/running/succeeded/failed/expired).
- ``REPORT_LOCALES`` — mirroring ``ck_report_locale``.
- Retention policy constants (``settings.report_retention_days`` is the
  default window; jobs carry their own ``retention_until`` timestamp).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.config import settings

# ----------------------------------------------------------------- formats
# Mirrors ck_report_format on report_jobs (app/db/models_p3.py).
REPORT_FORMATS: tuple[str, ...] = ("pdf", "xlsx", "csv")

# ---------------------------------------------------------------- statuses
# Mirrors ck_report_status on report_jobs EXACTLY (queued — not "pending";
# succeeded — not "completed"). Never invent other values.
REPORT_STATUS_QUEUED = "queued"
REPORT_STATUS_RUNNING = "running"
REPORT_STATUS_SUCCEEDED = "succeeded"
REPORT_STATUS_FAILED = "failed"
REPORT_STATUS_EXPIRED = "expired"
REPORT_STATUSES: tuple[str, ...] = (
    REPORT_STATUS_QUEUED,
    REPORT_STATUS_RUNNING,
    REPORT_STATUS_SUCCEEDED,
    REPORT_STATUS_FAILED,
    REPORT_STATUS_EXPIRED,
)

# ----------------------------------------------------------------- locales
# Mirrors ck_report_locale on report_jobs.
REPORT_LOCALES: tuple[str, ...] = ("en", "ar")

# -------------------------------------------------------------- provenance
# Same provenance vocabulary as app/analytics/service.py.
PROVENANCE_OBSERVED = "observed"
PROVENANCE_MODEL = "model_derived"
PROVENANCE_SIMULATED = "simulated"
PROVENANCE_MISSING = "missing"
PROVENANCE_VALUES: tuple[str, ...] = (
    PROVENANCE_OBSERVED,
    PROVENANCE_MODEL,
    PROVENANCE_SIMULATED,
    PROVENANCE_MISSING,
)

# ---------------------------------------------------------------- retention
# Default retention window for generated artifacts (downloadable period).
# Jobs store their own `retention_until`; this default is applied at
# completion time and can be tightened per-plan via history entitlements
# later without changing callers.
REPORT_RETENTION_DAYS_DEFAULT: int = settings.report_retention_days
# Failed jobs (no artifact) are purge-eligible after the same window.
FAILED_JOB_RETENTION_DAYS: int = REPORT_RETENTION_DAYS_DEFAULT
# Guard against absurd schedules.
MIN_INTERVAL_DAYS: int = 1
MAX_INTERVAL_DAYS: int = 365


def retention_until_for(now: datetime, days: int | None = None) -> datetime:
    """Downloadable-until timestamp for an artifact completed at `now`."""
    window = days if days is not None else REPORT_RETENTION_DAYS_DEFAULT
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now + timedelta(days=max(1, int(window)))


def default_date_range(today: date | None = None) -> tuple[date, date]:
    """Default reporting window: the trailing 30 days (inclusive)."""
    end = today or datetime.now(UTC).date()
    return end - timedelta(days=29), end


@dataclass(frozen=True)
class ReportTypeSpec:
    """One report type in the registry."""

    key: str
    title_en: str
    title_ar: str
    description: str
    requires: tuple[str, ...] = field(default=())
    default_sections: tuple[str, ...] = field(default=())
    # Section whose table becomes the flat CSV export when present.
    primary_section: str | None = None


SECTION_KEYS: tuple[str, ...] = (
    "overview",
    "field_breakdown",
    "crop_cycles",
    "water",
    "soil",
    "recommendations",
    "seasonality",
    "risk",
    "data_quality",
    # P07 — satellite / spatial / environmental intelligence sections
    "data_availability",
    "satellite",
    "spatial",
    "environmental",
    "methodology",
)

REPORT_TYPES: dict[str, ReportTypeSpec] = {
    spec.key: spec
    for spec in (
        ReportTypeSpec(
            key="farm_performance",
            title_en="Farm performance",
            title_ar="أداء المزرعة",
            description=(
                "Per-field activity over the selected period: observations "
                "ingested, active recommendations, crop cycles started, and "
                "precipitation-derived water volumes."
            ),
            requires=("farm", "observations", "crop_history", "recommendations"),
            default_sections=("overview", "field_breakdown", "water", "data_quality"),
            primary_section="field_breakdown",
        ),
        ReportTypeSpec(
            key="field_analysis",
            title_en="Field analysis",
            title_ar="تحليل الحقل",
            description=(
                "Single-field deep dive: observation coverage by variable, "
                "crop history, and active recommendations."
            ),
            requires=("field", "observations", "crop_history", "recommendations"),
            default_sections=("overview", "seasonality", "crop_cycles", "recommendations"),
            primary_section="seasonality",
        ),
        ReportTypeSpec(
            key="soil_health",
            title_en="Soil health",
            title_ar="صحة التربة",
            description=(
                "Soil laboratory measurements and profile summary for the "
                "selected scope. Rendered from measured samples only."
            ),
            requires=("farm_or_field", "soil_measurements"),
            default_sections=("overview", "soil"),
            primary_section="soil",
        ),
        ReportTypeSpec(
            key="water",
            title_en="Water intelligence",
            title_ar="ذكاء المياه",
            description=(
                "Water plans and precipitation-derived volumes for the "
                "scope. Irrigation metering is reported as missing unless "
                "a provider supplies it."
            ),
            requires=("farm_or_field", "water_plans", "observations"),
            default_sections=("overview", "water"),
            primary_section="water",
        ),
        ReportTypeSpec(
            key="rotation",
            title_en="Rotation history",
            title_ar="سجل الدورة الزراعية",
            description=(
                "Crop cycles recorded for the scope: crop, sowing/harvest "
                "dates and season labels from farmer records."
            ),
            requires=("farm_or_field", "crop_history"),
            default_sections=("overview", "crop_cycles"),
            primary_section="crop_cycles",
        ),
        ReportTypeSpec(
            key="seasonal",
            title_en="Seasonal summary",
            title_ar="الملخص الموسمي",
            description=(
                "Month-by-month observation totals (precipitation, "
                "temperature, NDVI) across the selected period."
            ),
            requires=("farm_or_field", "observations"),
            default_sections=("overview", "seasonality"),
            primary_section="seasonality",
        ),
        ReportTypeSpec(
            key="environmental_risk",
            title_en="Environmental risk exposure",
            title_ar="المخاطر البيئية",
            description=(
                "Data-driven exposure view: observation freshness, synthetic "
                "data share, and coverage gaps. Explicitly NOT an agronomic "
                "risk certification."
            ),
            requires=("farm_or_field", "observations"),
            default_sections=("overview", "risk", "data_quality"),
            primary_section="data_quality",
        ),
        ReportTypeSpec(
            key="recommendations",
            title_en="Recommendations digest",
            title_ar="ملخص التوصيات",
            description=(
                "Active AI recommendations for the scope with domain, "
                "severity and confidence, plus feedback adoption state."
            ),
            requires=("farm_or_field", "recommendations"),
            default_sections=("overview", "recommendations"),
            primary_section="recommendations",
        ),
        ReportTypeSpec(
            key="org_executive",
            title_en="Executive summary",
            title_ar="الملخص التنفيذي",
            description=(
                "Organization-level dashboard: farms, fields, area, crop "
                "distribution, recommendation activity and data freshness."
            ),
            requires=("organization", "farms", "observations"),
            default_sections=("overview", "field_breakdown", "data_quality"),
            primary_section="field_breakdown",
        ),
        ReportTypeSpec(
            key="custom_range",
            title_en="Custom period report",
            title_ar="تقرير فترة مخصصة",
            description=(
                "Generic best-effort report over an arbitrary date range: "
                "scope overview, observation totals and active "
                "recommendations."
            ),
            requires=("farm_or_field_or_org", "observations"),
            default_sections=("overview", "field_breakdown", "recommendations"),
            primary_section="field_breakdown",
        ),
        # ------------------------------------------------- P07 report types
        ReportTypeSpec(
            key="field_intelligence",
            title_en="Field intelligence report",
            title_ar="تقرير ذكاء الحقل",
            description=(
                "Comprehensive single-field report: data availability and "
                "observation coverage, satellite acquisition history, "
                "vegetation index history, spatial variation and statistical "
                "zones, quality-gated anomaly signals, environmental "
                "context, water/soil indicators, active recommendation "
                "evidence, limitations and a methodology/source appendix. "
                "Generated only from actual authorized platform data; "
                "insufficient evidence is stated, never filled."
            ),
            requires=("field", "observations"),
            default_sections=(
                "overview",
                "data_availability",
                "satellite",
                "spatial",
                "environmental",
                "water",
                "soil",
                "recommendations",
                "methodology",
            ),
            primary_section="satellite",
        ),
        ReportTypeSpec(
            key="satellite_vegetation",
            title_en="Satellite & vegetation report",
            title_ar="تقرير الأقمار الصناعية والغطاء النباتي",
            description=(
                "Satellite-focused field report: scene acquisition history "
                "with provenance, per-index zonal statistics, statistical "
                "zones, coverage gaps and data quality."
            ),
            requires=("field", "observations"),
            default_sections=(
                "overview",
                "satellite",
                "spatial",
                "seasonality",
                "data_quality",
            ),
            primary_section="satellite",
        ),
        ReportTypeSpec(
            key="spatial_anomalies",
            title_en="Spatial anomaly report",
            title_ar="تقرير الشذوذ المكاني",
            description=(
                "Quality-gated spatial anomaly signals for the scope with "
                "their thresholds, confidence, supporting measurements and "
                "environmental context. Signals are explicitly NOT "
                "diagnoses; insufficient-evidence cases are listed."
            ),
            requires=("farm_or_field", "observations"),
            default_sections=(
                "overview",
                "spatial",
                "environmental",
                "data_quality",
            ),
            primary_section="spatial",
        ),
    )
}


def get_report_type(key: str) -> ReportTypeSpec:
    """Registry lookup raising ValueError for unknown keys (service maps to
    ValidationFailed)."""
    spec = REPORT_TYPES.get(key)
    if spec is None:
        raise ValueError(f"Unknown report type '{key}'.")
    return spec


# ------------------------------------------------- normalized payload schema
def make_section(
    heading: str,
    *,
    prose: str | None = None,
    table: dict[str, Any] | None = None,
    kpis: list[dict[str, Any]] | None = None,
    provenance: str = PROVENANCE_OBSERVED,
    note: str | None = None,
) -> dict[str, Any]:
    """One normalized report section (schema shared with renderers)."""
    return {
        "heading": heading,
        "prose": prose,
        "table": table,  # {"columns": [...], "rows": [[...]], "units": [...]|None}
        "kpis": kpis or [],  # [{"label","value","unit","provenance"}]
        "provenance": provenance,
        "note": note,
    }


def missing_section(heading: str, reason: str) -> dict[str, Any]:
    """A section that could not be gathered — rendered honestly as missing."""
    return make_section(
        heading,
        prose=reason,
        provenance=PROVENANCE_MISSING,
        note=reason,
    )


def make_table(
    columns: list[str], rows: list[list[Any]], units: list[str | None] | None = None
) -> dict[str, Any]:
    """Normalized table block: column headers, stringified rows, units."""
    return {
        "columns": [str(c) for c in columns],
        "rows": [[("" if v is None else v) for v in row] for row in rows],
        "units": units,
    }


def make_kpi(
    label: str,
    value: Any,
    unit: str,
    provenance: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Normalized KPI block. `value=None` renders as the missing marker."""
    return {
        "label": label,
        "value": value,
        "unit": unit,
        "provenance": provenance if value is not None else PROVENANCE_MISSING,
        "note": note,
    }
