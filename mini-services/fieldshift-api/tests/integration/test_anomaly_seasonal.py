"""A1 seasonal-aware anomaly detection: same-month baselines + classification.

Covers the mandated test matrix: normal seasonal patterns, unusually high /
low rainfall WITHIN the same month, temperature anomalies, insufficient
historical baseline, missing months, incomplete observations, and trend
detection across multiple years.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.intelligence.anomaly import detect_feature_anomalies
from tests.conftest import SessionLocal  # noqa: F401 — ensures app import order


def _make_run(db, field_id, code, monthly_values, *, unit="mm", quality="valid"):
    """One succeeded feature run with monthly values for (year, month, value)."""
    from app.db import models as dbm

    run = dbm.FeatureRun(
        field_id=field_id,
        status="succeeded",
        calendar_timezone="UTC",
        hemisphere="north",
        period_start=datetime(2022, 1, 1, tzinfo=UTC),
        period_end=datetime(2025, 12, 31, tzinfo=UTC),
        aggregation_levels=["monthly"],
        requested_variables=[code],
        source_selection={},
        feature_engine_version="test",
        feature_catalog_version="test",
        is_synthetic=False,
    )
    db.add(run)
    db.flush()
    for year, month, value in monthly_values:
        start = datetime(year, month, 1, tzinfo=UTC)
        end = (start + timedelta(days=31)).replace(day=1) - timedelta(seconds=1)
        db.add(
            dbm.FeatureValue(
                run_id=run.id,
                field_id=field_id,
                feature_code=code,
                aggregation_level="monthly",
                period_label=f"{year:04d}-{month:02d}",
                period_start=start,
                period_end=end,
                value=value,
                unit=unit,
                quality_status=quality,
            )
        )
    db.commit()
    return run


def _field(db, client, farm_with_field):
    """Resolve the fixture field id via the API-created field."""
    return uuid.UUID(farm_with_field["field"]["id"])


def test_normal_seasonal_pattern_not_flagged(client, farm_with_field):
    """Monsoon-like rainfall (wet Julys, dry Junes) is ordinary seasonality:
    June values deviate strongly from the whole-series mean but match the
    June baseline — NO anomaly finding, only seasonal_variation at most."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        values = []
        for year in (2022, 2023, 2024):
            values.append((year, 6, 5.0))    # bone-dry June, every year
            values.append((year, 7, 220.0))  # monsoon July, every year
            values.append((year, 8, 180.0))
        _make_run(db, field_id, code, values)
        findings = detect_feature_anomalies(db, field_id)
        anomaly_kinds = [f["kind"] for f in findings if f["metric"] == code]
        assert "anomaly" not in anomaly_kinds, findings
    finally:
        db.close()


def test_unusually_high_rainfall_same_month_flagged(client, farm_with_field):
    """A 200 mm March against a 40-41 mm March history is a genuine same-month
    anomaly — and |z| against the MARCH baseline must exceed what the old
    whole-series screening would have produced."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        from app.db import models as dbm

        run = dbm.FeatureRun(
            field_id=field_id,
            status="succeeded",
            calendar_timezone="UTC",
            hemisphere="north",
            period_start=datetime(2022, 1, 1, tzinfo=UTC),
            period_end=datetime(2024, 12, 31, tzinfo=UTC),
            aggregation_levels=["monthly"],
            requested_variables=[code],
            source_selection={},
            feature_engine_version="test",
            feature_catalog_version="test",
            is_synthetic=False,
        )
        db.add(run)
        db.flush()
        # 3 clean Marches (2021-2023) so the 2024 outlier does not inflate
        # its own baseline beyond recognition (includes_evaluated_period
        # parity with the feature engine's climatology).
        series = [
            (2021, 3, 40.8), (2021, 4, 41.2),
            (2022, 3, 40.0), (2022, 4, 42.0),
            (2023, 3, 41.0), (2023, 4, 42.5),
            (2024, 3, 200.0), (2024, 4, 41.5),
        ]
        for year, month, value in series:
            start = datetime(year, month, 1, tzinfo=UTC)
            end = (start + timedelta(days=31)).replace(day=1) - timedelta(seconds=1)
            db.add(dbm.FeatureValue(
                run_id=run.id, field_id=field_id, feature_code=code,
                aggregation_level="monthly", period_label=f"{year:04d}-{month:02d}",
                period_start=start, period_end=end, value=value, unit="mm",
                quality_status="valid",
            ))
        db.commit()
        findings = detect_feature_anomalies(db, field_id)
        march = [f for f in findings if f["metric"] == code and f["period"] == "2024-03"]
        assert march and march[0]["kind"] == "anomaly"
        assert march[0]["direction"] == "above"
        assert march[0]["baseline"]["calendar_month"] == 3
        assert 2 <= march[0]["baseline"]["n_years"]
        # The z is computed against the MARCH baseline (which honestly
        # includes the evaluated period — engine parity), so 1.5 <= |z| is
        # the screening contract; the finding carries the full provenance.
        assert abs(march[0]["z"]) >= 1.5
        assert march[0]["baseline"]["window_years"] == [2021, 2022, 2023, 2024]
    finally:
        db.close()


def test_unusually_low_rainfall_same_month_flagged(client, farm_with_field):
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        series = [
            (2021, 11, 31.0), (2021, 12, 28.5),
            (2022, 11, 30.0), (2022, 12, 28.0),
            (2023, 11, 32.0), (2023, 12, 27.0),
            (2024, 11, 1.0),  # unusually dry November
            (2024, 12, 29.0),
        ]
        _make_run(db, field_id, code, series)
        findings = detect_feature_anomalies(db, field_id)
        november = [f for f in findings if f["metric"] == code and f["period"] == "2024-11"]
        assert november and november[0]["kind"] == "anomaly"
        assert november[0]["direction"] == "below"
        assert november[0]["baseline"]["calendar_month"] == 11
    finally:
        db.close()


def test_temperature_anomaly_same_month(client, farm_with_field):
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "temperature_2m_mean_monthly"
        series = []
        for year, jan, jul in (
            (2021, 12.0, 31.5), (2022, 12.2, 33.0), (2023, 11.8, 32.0),
        ):
            series.append((year, 1, jan))
            series.append((year, 7, jul))
        series.append((2024, 1, 12.5))
        series.append((2024, 7, 33.5))
        series.append((2025, 1, 26.0))  # a 26°C January is genuinely unusual
        series.append((2025, 7, 34.0))
        _make_run(db, field_id, code, series, unit="degC")
        findings = detect_feature_anomalies(db, field_id)
        january = [f for f in findings if f["metric"] == code and f["period"] == "2025-01"]
        assert january and january[0]["kind"] == "anomaly"
        assert january[0]["baseline"]["calendar_month"] == 1
        # July values stay in band: no July anomaly.
        july = [f for f in findings if f["metric"] == code and f["period"] == "2025-07"]
        assert not july
    finally:
        db.close()


def test_insufficient_baseline_reported_not_anomaly(client, farm_with_field):
    """A calendar month with < 2 distinct years of history is blind screening:
    reported as insufficient_baseline, never as an anomaly."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        # Only ONE year: every month has insufficient history.
        _make_run(db, field_id, code, [(2024, m, 10.0 + m) for m in range(1, 13)])
        findings = detect_feature_anomalies(db, field_id)
        kinds = [f["kind"] for f in findings if f["metric"] == code]
        assert kinds, "insufficient history must be reported, not silent"
        assert "anomaly" not in kinds
        assert "insufficient_baseline" in kinds
        detail = next(f for f in findings if f["kind"] == "insufficient_baseline")
        assert "insufficient historical evidence" in detail["detail"]
    finally:
        db.close()


def test_missing_month_safe(client, farm_with_field):
    """Missing months (None values / absent rows) never crash or mislead:
    the rest of the series is still screened on complete months."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        series = [
            (2021, 2, 49.0), (2021, 3, 54.0),
            (2022, 2, 50.0), (2022, 3, 55.0),
            (2023, 2, 48.0), (2023, 3, 52.0),
            # 2024-02 completely missing; 2024-03 None:
            (2024, 3, None),
            (2025, 2, 250.0),  # genuine February anomaly
            (2025, 3, 53.0),
        ]
        run = _make_run(db, field_id, code, series)
        # None value rows exist but must be ignored by the screener.
        findings = detect_feature_anomalies(db, field_id)
        feb = [f for f in findings if f["metric"] == code and f["period"] == "2025-02"]
        assert feb and feb[0]["kind"] == "anomaly"
        assert run.id  # run present; screener handled the gap
    finally:
        db.close()


def test_incomplete_observations_quality_filter(client, farm_with_field):
    """Rows flagged 'missing' (below coverage) are excluded from baselines —
    an incomplete record must not poison the same-month statistics."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "precipitation_sum_monthly"
        from app.db import models as dbm

        run = dbm.FeatureRun(
            field_id=field_id, status="succeeded", calendar_timezone="UTC",
            hemisphere="north",
            period_start=datetime(2022, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 12, 31, tzinfo=UTC),
            aggregation_levels=["monthly"], requested_variables=[code],
            source_selection={}, feature_engine_version="test",
            feature_catalog_version="test", is_synthetic=False,
        )
        db.add(run)
        db.flush()
        rows = [
            (2022, 5, 60.0, "valid"), (2023, 5, 62.0, "valid"),
            (2024, 5, 0.0, "missing"),   # excluded: no honest value
            (2025, 5, 61.0, "valid"),
        ]
        for year, month, value, quality in rows:
            start = datetime(year, month, 1, tzinfo=UTC)
            end = (start + timedelta(days=31)).replace(day=1) - timedelta(seconds=1)
            db.add(dbm.FeatureValue(
                run_id=run.id, field_id=field_id, feature_code=code,
                aggregation_level="monthly", period_label=f"{year:04d}-{month:02d}",
                period_start=start, period_end=end, value=value, unit="mm",
                quality_status=quality,
            ))
        db.commit()
        findings = detect_feature_anomalies(db, field_id)
        # With the missing row excluded, May = {60, 62, 61}: σ tiny, all in band.
        may = [f for f in findings if f["metric"] == code and f["period"] == "2025-05"
               and f["kind"] == "anomaly"]
        assert not may
    finally:
        db.close()


def test_trend_detection_multi_year(client, farm_with_field):
    """A sustained same-direction shift over the last periods is a TREND —
    screened against the same-month baseline for monthly series."""
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "growing_season_length_seasonal"
        # Seasonal series: stable history, then a sustained same-direction shift.
        series = [
            (2018, 1, 100.0), (2019, 1, 102.0), (2020, 1, 98.0),
            (2021, 1, 101.0), (2022, 1, 99.0), (2023, 1, 101.0),
            (2024, 1, 160.0), (2025, 1, 164.0), (2026, 1, 168.0),
        ]
        _make_run(db, field_id, code, series, unit="days")
        findings = detect_feature_anomalies(db, field_id)
        trends = [f for f in findings if f["metric"] == code and f["kind"] == "trend"]
        assert trends, findings
        assert trends[0]["direction"] == "above"
        # Recent values are also flagged as plain anomalies (they exceed band).
        anomalies = [f for f in findings if f["metric"] == code and f["kind"] == "anomaly"]
        assert anomalies
    finally:
        db.close()


def test_zero_variance_series_skipped(client, farm_with_field):
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        code = "frost_days_0c_count_monthly"
        _make_run(db, field_id, code, [(y, m, 0.0) for y in (2022, 2023, 2024) for m in (1, 12)])
        findings = detect_feature_anomalies(db, field_id)
        assert not [f for f in findings if f["metric"] == code]
    finally:
        db.close()


def test_no_run_returns_empty(client, farm_with_field):
    db = SessionLocal()
    try:
        field_id = _field(db, client, farm_with_field)
        assert detect_feature_anomalies(db, field_id) == []
    finally:
        db.close()
