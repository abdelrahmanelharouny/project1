"""Climate Forecasting & Projection endpoints (P2.B).

- GET /climate/forecast/capabilities         — verified provider capability matrix
- POST /fields/{id}/forecasts/ingest         — fetch + store forecast evidence
- GET  /fields/{id}/forecasts                — forecast window (latest issue)
- GET  /fields/{id}/forecasts/freshness      — freshness verdicts per variable
- GET  /fields/{id}/forecast-risks           — agricultural risk screening
- POST /fields/{id}/forecast-verifications   — paired forecast-observation verification
- GET  /fields/{id}/climate-projections      — stored projection records

Forecast ingestion is synchronous and idempotent (natural-key dedupe);
failures degrade to structured errors, never fabricated data. All
field-scoped endpoints are tenant-scoped through the field's farm.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate.contracts import capability_matrix
from app.climate.projections import projections_for_field
from app.climate.risk import screen_forecast_risks
from app.climate.service import (
    forecast_freshness,
    forecasts_in_window,
    persist_forecast_evidence,
)
from app.climate.verification import verify_forecasts
from app.core.database import get_db
from app.data_platform.observability import observe_latency
from app.data_platform.providers.open_meteo_forecast.provider import (
    OpenMeteoForecastProvider,
    centroid_of_geometry,
)
from app.domains.identity.service import get_field_for_principal, get_principal
from app.db import models as dbm
from app.db.models_p2 import WeatherForecast

router = APIRouter(tags=["climate"])

FORECAST_VARIABLES = [
    "air_temperature_mean",
    "air_temperature_min",
    "air_temperature_max",
    "precipitation",
    "reference_et0",
    "wind_speed_10m",
]


class ForecastIngestRequest(BaseModel):
    variables: list[str] = Field(default_factory=lambda: list(FORECAST_VARIABLES))
    model: str = "best_match"
    forecast_days: int = Field(7, ge=1, le=16)


@router.get("/climate/forecast/capabilities")
def climate_capabilities() -> dict:
    """The verified provider capability matrix: what each provider's product
    ACTUALLY supports (temporal class, horizon, resolution, licensing,
    authentication, limitations). The platform never claims a capability a
    product does not have."""
    return {
        "capability_matrix": capability_matrix(),
        "classification_vocabulary": [
            "historical_observation",
            "reanalysis",
            "short_range_forecast",
            "seasonal_forecast",
            "climate_projection",
        ],
    }


@router.post("/fields/{field_id}/forecasts/ingest")
def ingest_forecast(
    field_id: uuid.UUID,
    request: ForecastIngestRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Fetch the current forecast issue for the field and store it as
    immutable forecast evidence (issue/valid time separated). Idempotent:
    re-ingesting the same issue adds nothing."""
    field = get_field_for_principal(db, principal, field_id)
    from app.core.errors import ProviderUnavailable

    provider = OpenMeteoForecastProvider()
    centroid = centroid_of_geometry(_field_geometry_geojson(db, field.id))
    try:
        with observe_latency("forecast_ingest_seconds"):
            evidence, response_meta = provider.fetch_forecast(
                geometry_centroid=centroid,
                variables=request.variables,
                forecast_days=request.forecast_days,
                model=request.model,
            )
    except Exception as exc:
        raise ProviderUnavailable(
            "Forecast ingestion failed: the forecast provider is unreachable "
            "from this deployment. No forecast data is fabricated.",
            details=[{"reason": str(exc)}],
        ) from exc
    counts = persist_forecast_evidence(db, field.id, evidence)
    db.commit()
    return {
        "field_id": str(field.id),
        "stored": counts,
        "response_meta": response_meta,
        "note": (
            "Rows are appended per (provider, model, variable, issue, valid, "
            "horizon); historical observations are never modified."
        ),
    }


@router.get("/fields/{field_id}/forecasts")
def field_forecasts(
    field_id: uuid.UUID,
    variable_code: str = Query("air_temperature_max"),
    days: int = Query(16, ge=1, le=30),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Forecast rows from the latest issue within the window, with the
    freshness verdict and explicit forecast-vs-history labeling."""
    field = get_field_for_principal(db, principal, field_id)
    start = datetime.now(UTC) - timedelta(days=1)
    end = datetime.now(UTC) + timedelta(days=days)
    rows = forecasts_in_window(
        db, field.id, variable_code=variable_code, start=start, end=end
    )
    freshness = forecast_freshness(db, field.id, variable_code)
    return {
        "field_id": str(field.id),
        "variable_code": variable_code,
        "basis": "forecast",
        "freshness": freshness.model_dump(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "values": [
            {
                "valid_time": r.valid_time.isoformat(),
                "issued_at": r.issued_at.isoformat(),
                "horizon_hours": r.horizon_hours,
                "value": r.value,
                "unit": r.unit,
                "model_id": r.model_id,
                "is_synthetic": r.is_synthetic,
            }
            for r in rows
        ],
    }


@router.get("/fields/{field_id}/forecast-risks")
def field_forecast_risks(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Screen the current forecast window for agricultural risks (extreme
    heat, frost, heavy precipitation, dry spells, planting/harvest window
    overlaps) using documented generic thresholds."""
    field = get_field_for_principal(db, principal, field_id)
    start = datetime.now(UTC) - timedelta(days=1)
    end = datetime.now(UTC) + timedelta(days=16)
    flat_rows: list[dict[str, Any]] = []
    for vcode in ("air_temperature_max", "air_temperature_min", "precipitation"):
        rows = forecasts_in_window(db, field.id, variable_code=vcode, start=start, end=end)
        flat_rows.extend(
            {"variable_code": vcode, "value": r.value, "valid_time": r.valid_time} for r in rows
        )
    crop_windows = _crop_calendar_windows(db, field.id)
    risks = screen_forecast_risks(forecast_rows=flat_rows, crop_windows=crop_windows)
    return {
        "field_id": str(field.id),
        "basis": "forecast",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "risks": [r.as_dict() for r in risks],
        "limitations": [
            "Thresholds are documented GENERIC definitions (ETCCDI/WMO); the "
            "knowledge base carries no crop-specific critical temperatures, "
            "so none are invented here.",
            "Risks derive from a deterministic single-model forecast whose "
            "skill degrades with horizon.",
        ],
    }


@router.post("/fields/{field_id}/forecast-verifications")
def field_forecast_verification(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Verify archived forecasts against later observations (bias/MAE/RMSE
    per horizon bucket). Runs only on actual paired data; reports
    limitations when pairing is impossible."""
    field = get_field_for_principal(db, principal, field_id)
    return verify_forecasts(db, field.id)


@router.get("/fields/{field_id}/climate-projections")
def field_climate_projections(
    field_id: uuid.UUID,
    scenario_id: str | None = Query(None),
    variable_code: str | None = Query(None),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Stored climate projection records (scenario/model/ensemble identity
    preserved). The CMIP6 adapter is a seam in this deployment — the
    response states that honestly instead of pretending data exists."""
    field = get_field_for_principal(db, principal, field_id)
    records = projections_for_field(
        db, field.id, scenario_id=scenario_id, variable_code=variable_code
    )
    return {
        "field_id": str(field.id),
        "records": records,
        "adapter_status": "blocked_pending_credentials",
        "note": (
            "No CMIP6 dataset is wired in this deployment; records may exist "
            "only from explicitly labelled synthetic fixtures. Projections "
            "are never deterministic future weather."
        ),
    }


# ------------------------------------------------------------------ helpers
def _field_geometry_geojson(db: Session, field_id: uuid.UUID) -> dict[str, Any]:
    from sqlalchemy import text as _text

    row = db.execute(
        _text("SELECT ST_AsGeoJSON(boundary) AS geojson FROM fields WHERE id = :id"),
        {"id": str(field_id)},
    ).first()
    if row is None or row.geojson is None:
        from app.core.errors import NotFound

        raise NotFound("Field boundary not found.", details=[{"field_id": str(field_id)}])
    import json as _json

    return _json.loads(row.geojson)


def _crop_calendar_windows(db: Session, field_id: uuid.UUID) -> list[dict[str, Any]]:
    """Crop calendar windows (planting/harvest, MM-DD) for the crops that
    actually grew on this field, from the knowledge base."""
    from app.db.models import CropCalendarWindow, CropHistory

    history = list(db.scalars(select(CropHistory).where(CropHistory.field_id == field_id)))
    crop_ids = [h.crop_id for h in history if h.crop_id is not None]
    if not crop_ids:
        return []
    crops = {
        c.id: c for c in db.scalars(select(dbm.Crop).where(dbm.Crop.id.in_(crop_ids)))
    }
    windows = list(
        db.scalars(select(CropCalendarWindow).where(CropCalendarWindow.crop_id.in_(crop_ids)))
    )
    out: list[dict[str, Any]] = []
    for window in windows:
        crop = crops.get(window.crop_id)
        crop_code = getattr(crop, "code", None) or (crop.crop_code if crop else None)
        for window_type, raw_start, raw_end in (
            ("planting", window.planting_start, window.planting_end),
            ("harvest", window.harvest_start, window.harvest_end),
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
                    "crop_code": crop_code,
                    "window_type": window_type,
                    "start_month": sm,
                    "start_day": sd,
                    "end_month": em,
                    "end_day": ed,
                }
            )
    return out
