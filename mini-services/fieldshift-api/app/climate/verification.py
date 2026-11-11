"""Forecast verification: archived forecasts vs later observations (P2.B).

Only runs when PAIRED data exists — a forecast row (issued before the valid
time) and an observation of the same variable for the same valid day. Metrics
(bias, MAE, RMSE) follow standard definitions over the paired sample:

    bias = mean(forecast - observed)
    MAE  = mean(|forecast - observed|)
    RMSE = sqrt(mean((forecast - observed)^2))

Units are the variable's catalog unit; metrics are reported per horizon
bucket (0-24h / 24-72h / 72-168h / 168h+) because skill degrades with
horizon and a single blended number would hide that. No verification is
fabricated when pairing is impossible; the result reports pair counts and
limitations.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate.service import horizon_bucket
from app.db.models import Observation
from app.db.models_p2 import ForecastVerification, WeatherForecast

FORECAST_VERIFICATION_VERSION = "forecast-verification-1.0.0"

# Observations are daily with observed_at at 00:00 UTC (providers anchor
# days that way); forecast valid_time for daily values is 00:00 UTC too.
# Pairing tolerance: same calendar UTC day.
_VERIFICATION_VARIABLES = (
    "air_temperature_mean",
    "air_temperature_max",
    "air_temperature_min",
    "precipitation",
    "reference_et0",
)


def _day_key(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%d")


def verify_forecasts(
    db: Session,
    field_id: Any,
    *,
    variable_codes: list[str] | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Pair archived forecasts with observations and compute verification.

    Returns {verifications: [...], pairs_by_variable: {...}, limitations:
    [...]} — verifications are also persisted (idempotent by natural key).
    """
    wanted = [v for v in (variable_codes or list(_VERIFICATION_VARIABLES))]
    limitations: list[str] = []
    results: list[dict[str, Any]] = []

    forecast_rows = list(
        db.scalars(
            select(WeatherForecast)
            .where(
                WeatherForecast.field_id == field_id,
                WeatherForecast.value.isnot(None),
            )
            .order_by(WeatherForecast.valid_time.asc())
        )
    )
    if window_start:
        forecast_rows = [r for r in forecast_rows if r.valid_time >= window_start]
    if window_end:
        forecast_rows = [r for r in forecast_rows if r.valid_time <= window_end]

    obs_rows = list(
        db.scalars(
            select(Observation).where(
                Observation.field_id == field_id,
                Observation.value.isnot(None),
            )
        )
    )
    obs_by_day: dict[tuple[str, str], tuple[float, str]] = {}
    for obs in obs_rows:
        if obs.variable_code not in _VERIFICATION_VARIABLES:
            continue
        if obs.observed_at is None:
            continue
        key = (obs.variable_code, _day_key(obs.observed_at))
        obs_by_day.setdefault(key, (float(obs.value), obs.unit or ""))

    pairs_total = 0
    for vcode in wanted:
        grouped: dict[str, list[WeatherForecast]] = {}
        for row in forecast_rows:
            if row.variable_code != vcode:
                continue
            grouped.setdefault(horizon_bucket(row.horizon_hours), []).append(row)
        if not grouped:
            continue
        for bucket, rows in sorted(grouped.items()):
            diffs: list[float] = []
            for row in rows:
                # Pair only forecasts ISSUED BEFORE their valid time.
                if row.issued_at >= row.valid_time:
                    continue
                key = (vcode, _day_key(row.valid_time))
                if key not in obs_by_day:
                    continue
                observed, _unit = obs_by_day[key]
                # Observation must post-date the issue to be a true "later
                # observation" (verification honesty).
                obs_row = None
                for obs in obs_rows:
                    if (
                        obs.variable_code == vcode
                        and obs.observed_at is not None
                        and _day_key(obs.observed_at) == key[1]
                    ):
                        obs_row = obs
                        break
                if obs_row and obs_row.ingestion_job_id is None and obs.observed_at < row.issued_at:
                    continue
                diffs.append(float(row.value) - observed)
            if not diffs:
                continue
            n = len(diffs)
            bias = sum(diffs) / n
            mae = sum(abs(d) for d in diffs) / n
            rmse = math.sqrt(sum(d * d for d in diffs) / n)
            pairs_total += n
            results.append(
                {
                    "variable_code": vcode,
                    "horizon_bucket_hours": bucket,
                    "pair_count": n,
                    "bias": round(bias, 4),
                    "mae": round(mae, 4),
                    "rmse": round(rmse, 4),
                }
            )

    if pairs_total == 0:
        limitations.append(
            "No paired forecast-observation data exists yet. Verification "
            "requires forecasts to be ingested and the corresponding days to "
            "later appear as observations. No metrics are fabricated."
        )

    persisted = 0
    for item in results:
        payload = {
            "variable_code": item["variable_code"],
            "horizon_bucket_hours": item["horizon_bucket_hours"],
            "pair_count": item["pair_count"],
            "bias": item["bias"],
            "mae": item["mae"],
            "rmse": item["rmse"],
        }
        checksum = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        window_start_eff = window_start or (datetime.now(UTC) - timedelta(days=365))
        window_end_eff = window_end or datetime.now(UTC)
        existing = db.scalar(
            select(ForecastVerification.id).where(
                ForecastVerification.field_id == field_id,
                ForecastVerification.provider_code == "open_meteo_forecast",
                ForecastVerification.variable_code == item["variable_code"],
                ForecastVerification.horizon_bucket_hours == item["horizon_bucket_hours"],
                ForecastVerification.window_start == window_start_eff,
                ForecastVerification.window_end == window_end_eff,
            )
        )
        if existing is None:
            db.add(
                ForecastVerification(
                    field_id=field_id,
                    provider_code="open_meteo_forecast",
                    variable_code=item["variable_code"],
                    horizon_bucket_hours=item["horizon_bucket_hours"],
                    pair_count=item["pair_count"],
                    bias=item["bias"],
                    mae=item["mae"],
                    rmse=item["rmse"],
                    window_start=window_start_eff,
                    window_end=window_end_eff,
                    metric_version=FORECAST_VERIFICATION_VERSION,
                    checksum_sha256=checksum,
                )
            )
            persisted += 1
    db.flush()
    return {
        "verifications": results,
        "pairs_total": pairs_total,
        "persisted": persisted,
        "limitations": limitations,
        "version": FORECAST_VERIFICATION_VERSION,
    }
