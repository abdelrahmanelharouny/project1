"""Commercial intelligence & business analytics (P3 W4).

HONESTY CONTRACT (P3 §6.2 / §16.6): every metric carries explicit
PROVENANCE — one of:
  observed       measured platform data (observations, records)
  model_derived  computed by a documented formula from observed inputs
  simulated      synthetic fixture data (always labelled elsewhere)
  missing        the platform does not hold the required data

No yield, profit or productivity value is EVER invented. Financial metrics
are computed ONLY from user-supplied cost assumptions combined with measured
volumes, and always echo their assumptions back.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CropHistory, Farm, Field, Observation
from app.db.models_ai import AIRecommendation, AIRecommendationFeedback
from app.domains.identity.service import Principal

PROVENANCE_OBSERVED = "observed"
PROVENANCE_MODEL = "model_derived"
PROVENANCE_SIMULATED = "simulated"
PROVENANCE_MISSING = "missing"


def _metric(
    key: str,
    label: str,
    value: float | int | None,
    unit: str,
    provenance: str,
    *,
    source: str,
    period_from: date | None = None,
    period_to: date | None = None,
    note: str | None = None,
    breakdown: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "provenance": provenance if value is not None else PROVENANCE_MISSING,
        "source": source,
        "period": {"from": period_from.isoformat() if period_from else None,
                   "to": period_to.isoformat() if period_to else None},
        "note": note,
        **({"breakdown": breakdown} if breakdown else {}),
    }


def _org_fields(db: Session, organization_id: uuid.UUID) -> list[tuple[Farm, Field]]:
    rows = db.execute(
        select(Farm, Field)
        .join(Field, Field.farm_id == Farm.id)
        .where(Farm.organization_id == organization_id)
        .order_by(Farm.name, Field.name)
    ).all()
    return [(farm, field) for farm, field in rows]


# ------------------------------------------------------- executive dashboard
def executive_dashboard(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    farm_id: uuid.UUID | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    """Organization-level executive dashboard (P3 §6.1).

    Every metric is real data with provenance; unavailable metrics report
    `missing` with an explanation instead of a fabricated number.
    """
    principal.require_member_of(organization_id)
    now = datetime.now(UTC)
    pairs = _org_fields(db, organization_id)
    if farm_id is not None:
        pairs = [(f, fl) for f, fl in pairs if f.id == farm_id]
        if not pairs:
            from app.core.errors import NotFound

            raise NotFound("Farm not found in this organization.")
    farm_ids = {f.id for f, _ in pairs}
    field_ids = [fl.id for _, fl in pairs]

    total_area_ha = float(sum(fl.area_ha for _, fl in pairs)) if pairs else 0.0
    distinct_farms = len({f.id for f, _ in pairs})

    # Crop distribution from ACTUAL crop history (observed/farmer records).
    crop_conditions = [CropHistory.field_id.in_(field_ids)] if field_ids else []
    if season:
        crop_conditions.append(CropHistory.season_label == season)
    crop_rows = (
        db.execute(
            select(CropHistory.crop_label, func.count())
            .where(*crop_conditions)
            .group_by(CropHistory.crop_label)
        ).all()
        if crop_conditions
        else []
    )
    crop_distribution = [
        {"crop": label, "cycles": int(count)} for label, count in crop_rows
    ] or None

    # Active crop cycles: sowing happened, harvest not yet recorded.
    active_cycles = int(
        db.scalar(
            select(func.count())
            .select_from(CropHistory)
            .where(
                *crop_conditions,
                CropHistory.sowing_date.is_not(None),
                CropHistory.harvest_date.is_(None),
            )
        )
        or 0
    ) if crop_conditions else 0

    # Recommendation activity (org's fields only).
    rec_total = active_recs = 0
    rec_by_domain: dict[str, int] = {}
    if field_ids:
        rec_total = int(
            db.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(AIRecommendation.field_id.in_(field_ids))
            )
            or 0
        )
        active_recs = int(
            db.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(
                    AIRecommendation.field_id.in_(field_ids),
                    AIRecommendation.status == "active",
                )
            )
            or 0
        )
        domain_rows = db.execute(
            select(AIRecommendation.domain, func.count())
            .where(
                AIRecommendation.field_id.in_(field_ids),
                AIRecommendation.status == "active",
            )
            .group_by(AIRecommendation.domain)
        ).all()
        rec_by_domain = {domain: int(n) for domain, n in domain_rows}

    # Data freshness per key variable family (observed).
    freshness = _data_freshness(db, field_ids, now)

    # Adoption from the P1 feedback lifecycle (observed behaviour — NOT
    # agronomic correctness).
    adoption = _adoption(db, field_ids)

    return {
        "organization_id": str(organization_id),
        "filters": {
            "farm_id": str(farm_id) if farm_id else None,
            "season": season,
        },
        "generated_at": now.isoformat(),
        "metrics": [
            _metric(
                "farm_count", "Farms", distinct_farms or None, "count",
                PROVENANCE_OBSERVED, source="farms table",
            ),
            _metric(
                "field_count", "Fields", len(field_ids) or None, "count",
                PROVENANCE_OBSERVED, source="fields table",
            ),
            _metric(
                "total_area_ha", "Total area", round(total_area_ha, 2) or None, "ha",
                PROVENANCE_OBSERVED, source="fields.area_ha",
                note="Field geometry-derived registered area.",
            ),
            _metric(
                "active_crop_cycles", "Active crop cycles", active_cycles or None, "count",
                PROVENANCE_OBSERVED, source="crop_history",
                note="Sowing recorded, harvest pending.",
            ),
        ],
        "crop_distribution": crop_distribution,
        "recommendations": {
            "total_ever": rec_total or None,
            "active": active_recs or None,
            "active_by_domain": rec_by_domain or None,
            "provenance": PROVENANCE_OBSERVED,
        },
        "adoption": adoption,
        "data_freshness": freshness,
        "farm_ids": [str(x) for x in farm_ids],
        "farm_count_total": len(farm_ids),
    }


def _data_freshness(db: Session, field_ids: list[uuid.UUID], now: datetime) -> dict[str, Any]:
    """Freshness of key observation families; staleness is explicit."""
    if not field_ids:
        return {"provenance": PROVENANCE_MISSING, "variables": []}
    variables = ["precipitation", "air_temperature_max", "soil_moisture", "ndvi"]
    out = []
    for vcode in variables:
        last = db.scalar(
            select(func.max(Observation.observed_at)).where(
                Observation.field_id.in_(field_ids), Observation.variable_code == vcode
            )
        )
        count = int(
            db.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.field_id.in_(field_ids), Observation.variable_code == vcode)
            )
            or 0
        )
        if last is None:
            out.append({
                "variable": vcode, "observations": 0, "last_observed_at": None,
                "age_days": None, "status": "missing",
                "provenance": PROVENANCE_MISSING,
                "note": "No observations ingested for this variable.",
            })
            continue
        age_days = (now - last).total_seconds() / 86400
        out.append({
            "variable": vcode,
            "observations": count,
            "last_observed_at": last.isoformat(),
            "age_days": round(age_days, 1),
            "status": "fresh" if age_days <= 3 else ("stale" if age_days <= 14 else "very_stale"),
            "provenance": PROVENANCE_OBSERVED,
        })
    return {"variables": out}


def _adoption(db: Session, field_ids: list[uuid.UUID]) -> dict[str, Any]:
    if not field_ids:
        return {"provenance": PROVENANCE_MISSING, "note": "No recommendation feedback recorded."}
    rows = db.execute(
        select(AIRecommendationFeedback.state, func.count())
        .where(AIRecommendationFeedback.field_id.in_(field_ids))
        .group_by(AIRecommendationFeedback.state)
    ).all()
    if not rows:
        return {"provenance": PROVENANCE_MISSING,
                "note": "No recommendation feedback recorded yet."}
    by_state = {state: int(n) for state, n in rows}
    accepted = by_state.get("accepted", 0) + by_state.get("implemented", 0)
    total = sum(by_state.values())
    return {
        "provenance": PROVENANCE_OBSERVED,
        "by_state": by_state,
        "acceptance_rate": round(accepted / total, 4) if total else None,
        "note": (
            "Acceptance rate reflects user behaviour, NOT agronomic "
            "correctness (P1 A12 honesty rule)."
        ),
    }


# ---------------------------------------------------- farm performance analytics
def farm_performance(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    farm_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Per-farm analytics over a period with field comparison (P3 §6.2)."""
    principal.require_member_of(organization_id)
    farm = db.get(Farm, farm_id)
    if farm is None or farm.organization_id != organization_id:
        from app.core.errors import NotFound

        raise NotFound("Farm not found in this organization.")
    fields = list(db.scalars(select(Field).where(Field.farm_id == farm_id)).all())
    field_ids = [f.id for f in fields]

    field_rows = []
    for field in fields:
        obs_count = int(
            db.scalar(
                select(func.count())
                .select_from(Observation)
                .where(
                    Observation.field_id == field.id,
                    Observation.observed_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC),
                    Observation.observed_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC),
                )
            )
            or 0
        )
        active_recs = int(
            db.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(AIRecommendation.field_id == field.id, AIRecommendation.status == "active")
            )
            or 0
        )
        cycles = int(
            db.scalar(
                select(func.count())
                .select_from(CropHistory)
                .where(
                    CropHistory.field_id == field.id,
                    CropHistory.sowing_date >= date_from,
                    CropHistory.sowing_date <= date_to,
                )
            )
            or 0
        )
        field_rows.append(
            {
                "field_id": str(field.id),
                "name": field.name,
                "area_ha": round(field.area_ha, 2),
                "observations_in_period": obs_count,
                "active_recommendations": active_recs,
                "crop_cycles_started_in_period": cycles,
            }
        )

    obs_total = int(
        db.scalar(
            select(func.count())
            .select_from(Observation)
            .where(
                Observation.field_id.in_(field_ids) if field_ids else False,
                Observation.observed_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC),
                Observation.observed_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC),
            )
        )
        or 0
    ) if field_ids else 0
    expected_min = len(fields) * max(1, (date_to - date_from).days // 30)
    coverage = min(1.0, obs_total / expected_min) if expected_min else None

    return {
        "farm_id": str(farm_id),
        "farm_name": farm.name,
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "fields": field_rows,
        "metrics": [
            _metric(
                "observations_in_period", "Observations ingested",
                obs_total or None, "count", PROVENANCE_OBSERVED,
                source="observations",
            ),
            _metric(
                "data_coverage", "Estimated data coverage",
                round(coverage, 4) if coverage is not None else None, "ratio",
                PROVENANCE_MODEL,
                source="observations vs. monthly minimum expectation",
                note="Model-derived coverage heuristic: observed count vs. one "
                     "observation per variable per field per month floor. NOT a "
                     "quality certification.",
            ),
        ],
        "water_usage": _water_usage(db, field_ids, date_from, date_to),
    }


def _water_usage(
    db: Session, field_ids: list[uuid.UUID], date_from: date, date_to: date
) -> dict[str, Any]:
    """Water volumes from measured precipitation observations; irrigation
    metering is NOT implemented platform-wide, so irrigation volume is
    reported as missing unless observations exist."""
    if not field_ids:
        return {"provenance": PROVENANCE_MISSING, "note": "No fields."}
    # precipitation is in mm over area → m³ estimate (model-derived)
    rows = db.execute(
        select(Observation.field_id, func.sum(Observation.value))
        .where(
            Observation.field_id.in_(field_ids),
            Observation.variable_code == "precipitation",
            Observation.unit.in_(("mm", "kg/m^2")),
            Observation.observed_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC),
            Observation.observed_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=UTC),
        )
        .group_by(Observation.field_id)
    ).all()
    areas = {
        f.id: f.area_ha for f in db.scalars(select(Field).where(Field.id.in_(field_ids))).all()
    }
    per_field = []
    total_m3 = 0.0
    for field_id, mm_sum in rows:
        if mm_sum is None or field_id not in areas:
            continue
        # 1 mm over 1 ha = 10 m³
        m3 = float(mm_sum) * 10.0 * areas[field_id]
        total_m3 += m3
        per_field.append({"field_id": str(field_id), "precip_mm": round(float(mm_sum), 1),
                          "volume_m3": round(m3, 1)})
    return {
        "precipitation": (
            {
                "provenance": PROVENANCE_MODEL,
                "total_volume_m3": round(total_m3, 1),
                "per_field": per_field,
                "source": "precipitation observations × registered area "
                          "(1 mm over 1 ha = 10 m³)",
                "note": "Effective-rainfall adjustment is NOT applied here; "
                        "use the water intelligence module for agronomic "
                        "effective rainfall.",
            }
            if rows
            else {"provenance": PROVENANCE_MISSING,
                  "note": "No precipitation observations in this period."}
        ),
        "irrigation": {
            "provenance": PROVENANCE_MISSING,
            "note": "Irrigation volumes are not metered by the platform yet; "
                    "add an irrigation provider or import records to enable "
                    "this metric.",
        },
    }


# ------------------------------------------------------- commercial metrics
def commercial_metrics(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    farm_id: uuid.UUID,
    date_from: date,
    date_to: date,
    water_price_per_m3: float | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """Financial metrics ONLY where defensible (P3 §6.3).

    - Water cost: measured precipitation-derived volume × USER-SUPPLIED
      price → model_derived, assumptions echoed.
    - Cost per hectare / profit / yield: the platform holds no measured
      input costs → reported as MISSING. Never fabricated.
    """
    perf = farm_performance(
        db, principal,
        organization_id=organization_id, farm_id=farm_id,
        date_from=date_from, date_to=date_to,
    )
    water = perf["water_usage"]["precipitation"]
    volume_m3 = water.get("total_volume_m3") if water.get("provenance") == PROVENANCE_MODEL else None

    water_cost = None
    if volume_m3 is not None and water_price_per_m3 is not None:
        if water_price_per_m3 < 0:
            from app.core.errors import ValidationFailed

            raise ValidationFailed("water_price_per_m3 must be non-negative.")
        water_cost = round(volume_m3 * water_price_per_m3, 2)

    assumptions = {
        "water_price_per_m3": water_price_per_m3,
        "currency": currency,
        "volume_source": "precipitation observations × registered area",
    }
    return {
        "farm_id": str(farm_id),
        "period": perf["period"],
        "metrics": [
            _metric(
                "water_volume_m3", "Water volume (precipitation)",
                volume_m3, "m3",
                PROVENANCE_MODEL if volume_m3 is not None else PROVENANCE_MISSING,
                source=assumptions["volume_source"],
                note="Effective rainfall NOT deducted.",
            ),
            _metric(
                "water_cost", "Water cost",
                water_cost, currency,
                PROVENANCE_MODEL if water_cost is not None else PROVENANCE_MISSING,
                source="user-supplied price × measured volume",
                note=None if water_cost is not None else
                "Requires measured volume AND a user-supplied water price.",
            ),
            _metric(
                "cost_per_hectare", "Cost per hectare",
                None, currency, PROVENANCE_MISSING,
                source="not available",
                note="The platform does not record input costs. Import cost "
                     "records to enable this metric; values are never "
                     "estimated here.",
            ),
            _metric(
                "yield", "Yield",
                None, "t/ha", PROVENANCE_MISSING,
                source="not available",
                note="No measured yield data is recorded by the platform.",
            ),
        ],
        "assumptions": assumptions,
        "honesty_note": (
            "Every financial figure above states its source, unit, period and "
            "assumptions. Missing data is reported as missing — the platform "
            "never manufactures financial benefits (P3 §6.3)."
        ),
    }


# ---------------------------------------------------------------- benchmarks
def benchmark(
    db: Session,
    principal: Principal,
    *,
    organization_id: uuid.UUID,
    scope: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Farm-vs-farm / field-vs-field comparison INSIDE the organization.

    Only compatible units/periods are compared; cross-organization
    anonymized aggregates are architecture-ready but NOT implemented (no
    cross-tenant data path exists — documented in KNOWN_LIMITATIONS).
    """
    principal.require_member_of(organization_id)
    if scope not in ("farm", "field"):
        from app.core.errors import ValidationFailed

        raise ValidationFailed("scope must be 'farm' or 'field'.")
    if scope == "farm":
        farms = list(db.scalars(select(Farm).where(Farm.organization_id == organization_id)).all())
        entries = []
        for farm in farms:
            fields = list(db.scalars(select(Field).where(Field.farm_id == farm.id)).all())
            field_ids = [f.id for f in fields]
            recs = int(
                db.scalar(
                    select(func.count())
                    .select_from(AIRecommendation)
                    .where(
                        AIRecommendation.field_id.in_(field_ids) if field_ids else False,
                        AIRecommendation.status == "active",
                    )
                )
                or 0
            ) if field_ids else 0
            entries.append(
                {
                    "id": str(farm.id),
                    "name": farm.name,
                    "area_ha": round(sum(f.area_ha for f in fields), 2),
                    "field_count": len(fields),
                    "active_recommendations": recs,
                }
            )
        return {
            "scope": "farm",
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "metric_definitions": {
                "area_ha": "sum of registered field areas (observed)",
                "field_count": "registered fields (observed)",
                "active_recommendations": "active recommendation rows (observed)",
            },
            "compatibility_note": (
                "Only like-for-like metric definitions are compared. "
                "Different farms may have different data coverage — compare "
                "coverage before comparing values."
            ),
            "entries": entries,
            "cross_org_anonymized": {
                "provenance": PROVENANCE_MISSING,
                "note": "Not implemented: cross-organization aggregates "
                        "require a dedicated anonymization pipeline. No "
                        "other organization's data is ever accessible.",
            },
        }
    # field scope
    rows = _org_fields(db, organization_id)
    entries = []
    for farm, field in rows:
        recs = int(
            db.scalar(
                select(func.count())
                .select_from(AIRecommendation)
                .where(AIRecommendation.field_id == field.id, AIRecommendation.status == "active")
            )
            or 0
        )
        entries.append(
            {
                "id": str(field.id),
                "name": field.name,
                "farm": farm.name,
                "area_ha": round(field.area_ha, 2),
                "active_recommendations": recs,
            }
        )
    return {
        "scope": "field",
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "metric_definitions": {
            "area_ha": "registered field area (observed)",
            "active_recommendations": "active recommendation rows (observed)",
        },
        "entries": entries,
        "cross_org_anonymized": {
            "provenance": PROVENANCE_MISSING,
            "note": "Not implemented (see above).",
        },
    }
