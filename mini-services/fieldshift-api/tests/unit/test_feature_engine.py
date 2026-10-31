"""Unit tests: feature calendar basis and the deterministic feature engine.

Pure functions, no database. Observation dicts mimic the normalized rows the
run service feeds the engine (UTC-anchored daily periods like Open-Meteo, the
CSV importer and the synthetic provider produce).
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.features import calendar as fscal
from app.features.catalog import FEATURE_CATALOG
from app.features.engine import build_daily_series, compute_feature_drafts

CAIRO = ZoneInfo("Africa/Cairo")
NEW_YORK = ZoneInfo("America/New_York")


def utc_day_obs(variable: str, day: datetime, value: float | None, **extra):
    """A UTC-anchored daily observation like every M3 provider emits."""
    if day.tzinfo is None:
        day = day.replace(tzinfo=UTC)
    day = day.astimezone(UTC)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "id": extra.pop("id", f"obs-{variable}-{start.date().isoformat()}"),
        "variable_code": variable,
        "value": value,
        "unit": "mm",
        "quality_status": "missing" if value is None else "valid",
        "observed_at": start,
        "period_start": start,
        "period_end": start + timedelta(days=1) - timedelta(seconds=1),
        "time_support": "daily",
        "is_synthetic": False,
        "processing_version": "test-v1",
        "evidence_class": "reanalysis_model_estimate",
        "dataset_product_id": "prod-1",
        **extra,
    }


def month_days(year: int, month: int) -> list[datetime]:
    nxt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    start = datetime(year, month, 1)
    days = []
    while start < nxt:
        days.append(start)
        start += timedelta(days=1)
    return days


def spec(code: str):
    return FEATURE_CATALOG[code]


def local_month_window(year: int, month: int, tz: ZoneInfo):
    """Mimic the run service: windows are LOCAL calendar dates."""
    start = datetime(year, month, 1, tzinfo=tz).astimezone(UTC)
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=tz)
    end = nxt.astimezone(UTC) - timedelta(seconds=1)
    return start, end


def local_range_window(start_d, end_d, tz: ZoneInfo):
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz).astimezone(UTC)
    end = (
        datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz) + timedelta(days=1)
    ).astimezone(UTC) - timedelta(seconds=1)
    return start, end


def run_levels(levels):
    return levels


# ----------------------------------------------------------------- calendar
class TestCalendarBasis:
    def test_local_day_bounds_cairo(self):
        s, e = fscal.day_bounds_utc(fscal.date(2024, 1, 15), CAIRO)
        assert s.hour == 22 and s.minute == 0  # UTC+2 winter
        assert (e - s).total_seconds() == 86400

    def test_local_day_bounds_cairo_summer_dst(self):
        s, _ = fscal.day_bounds_utc(fscal.date(2024, 7, 15), CAIRO)
        assert s.hour == 21  # UTC+3 DST

    def test_assign_local_date_utc_day_cairo_same_date(self):
        d = datetime(2024, 3, 1, tzinfo=UTC)
        got = fscal.assign_local_date(d, d + timedelta(days=1) - timedelta(seconds=1), CAIRO)
        assert got == fscal.date(2024, 3, 1)

    def test_assign_local_date_utc_midnight_days_stay_on_date(self):
        """UTC-midnight-anchored daily data (all M3 providers) maps to the same
        local calendar date for any standard offset — the midpoint is 12:00 UTC,
        which lands inside local date D for |offset| <= 12h."""
        d = datetime(2024, 3, 1, tzinfo=UTC)
        end = d + timedelta(days=1) - timedelta(seconds=1)
        assert fscal.assign_local_date(d, end, CAIRO) == fscal.date(2024, 3, 1)
        assert fscal.assign_local_date(d, end, NEW_YORK) == fscal.date(2024, 3, 1)

    def test_assign_local_date_extreme_offset_shifts(self):
        """A NEW YORK-local-midnight-anchored day (Feb 29 05:00Z - Mar 1 04:59Z)
        stays on Feb 29 for New York and Cairo (offset difference < 12 h), but
        the midpoint (16:59:59.5Z) already falls on Mar 1 in Auckland (+13) —
        the calendar basis genuinely decides the bucket for extreme offsets."""
        start = datetime(2024, 2, 29, 5, 0, tzinfo=UTC)  # NY local midnight Feb 29
        end = start + timedelta(days=1) - timedelta(seconds=1)
        auckland = ZoneInfo("Pacific/Auckland")
        assert fscal.assign_local_date(start, end, NEW_YORK) == fscal.date(2024, 2, 29)
        assert fscal.assign_local_date(start, end, CAIRO) == fscal.date(2024, 2, 29)
        assert fscal.assign_local_date(start, end, auckland) == fscal.date(2024, 3, 1)

    def test_month_bounds_utc(self):
        s, e = fscal.month_bounds_utc(2024, 3, CAIRO)
        assert s == datetime(2024, 2, 29, 22, 0, tzinfo=UTC)
        assert e == datetime(2024, 3, 31, 22, 0, tzinfo=UTC)

    def test_season_label_djf_year_wrap(self):
        assert fscal.season_label(fscal.date(2024, 1, 15)) == "2023-DJF"
        assert fscal.season_label(fscal.date(2023, 12, 31)) == "2023-DJF"
        assert fscal.season_label(fscal.date(2024, 7, 15)) == "2024-JJA"

    def test_southern_hemisphere_swap(self):
        assert fscal.season_of(fscal.date(2024, 7, 15), "south") == "DJF"
        assert fscal.season_of(fscal.date(2024, 1, 15), "south") == "JJA"

    def test_resolve_timezone_rejects_unknown(self):
        with pytest.raises(ValueError):
            fscal.resolve_timezone("Mars/Olympus")


# ------------------------------------------------------------------- engine
class TestDailyPassthrough:
    def test_daily_values_and_missing(self):
        obs = [
            utc_day_obs("precipitation", datetime(2024, 3, 1, tzinfo=UTC), 5.0),
            utc_day_obs("precipitation", datetime(2024, 3, 2, tzinfo=UTC), None),
            utc_day_obs("precipitation", datetime(2024, 3, 3, tzinfo=UTC), 1.5),
        ]
        drafts, _, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_daily")],
            tz=CAIRO,
            hemisphere="north",
            window_start=datetime(2024, 3, 1, tzinfo=UTC),
            window_end=datetime(2024, 3, 3, 23, 59, 59, tzinfo=UTC),
            aggregation_levels=["daily"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        by_label = {d.period_label: d for d in drafts}
        assert by_label["2024-03-01"].value == 5.0
        assert by_label["2024-03-01"].quality_status == "valid"
        assert by_label["2024-03-02"].value is None
        assert by_label["2024-03-02"].quality_status == "missing"  # never zero
        assert by_label["2024-03-03"].value == 1.5
        # provenance links to the source observation
        assert by_label["2024-03-01"].provenance["observation_count"] == 1
        assert by_label["2024-03-01"].provenance["checksum"]


class TestMonthlyAggregation:
    def _monthly(self, obs, code="precipitation_total_monthly", year=2024, month=3):
        w_start, w_end = local_month_window(year, month, CAIRO)
        drafts, _, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec(code)],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        return [d for d in drafts if d.period_label == f"{year:04d}-{month:02d}"]

    def test_accumulation_full_month(self):
        obs = [utc_day_obs("precipitation", d, 2.0) for d in month_days(2024, 3)]
        drafts = self._monthly(obs)
        assert len(drafts) == 1
        d = drafts[0]
        assert d.period_label == "2024-03"
        assert d.value == pytest.approx(2.0 * 31, abs=0.01)
        assert d.quality_status == "valid"
        assert d.coverage_ratio == 1.0
        assert d.n_input == 31 and d.n_missing == 0

    def test_accumulation_missing_days_never_zero_filled(self):
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 2.0) for d in days[:28]]  # last 3 missing
        d = self._monthly(obs)[0]
        assert d.value == pytest.approx(2.0 * 28, abs=0.01)
        assert d.quality_status == "partial"
        assert d.coverage_ratio == pytest.approx(28 / 31, abs=0.001)

    def test_accumulation_below_coverage_minimum_is_null_not_scaled(self):
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 2.0) for d in days[:26]]  # 26/31 = 0.839 < 0.9
        d = self._monthly(obs)[0]
        assert d.value is None
        assert d.quality_status == "insufficient_coverage"
        assert "never treated as zero" in d.provenance["reason"]
        assert d.coverage_ratio == pytest.approx(26 / 31, abs=0.001)

    def test_mean_carries_standard_error(self):
        days = month_days(2024, 3)
        values = [float(i % 4) for i in range(len(days))]
        obs = [utc_day_obs("air_temperature_mean", d, v) for d, v in zip(days, values)]
        for o in obs:
            o["unit"] = "degC"
        d = self._monthly(obs, "air_temperature_mean_monthly")[0]
        assert d.unit == "degC"
        assert d.value == pytest.approx(sum(values) / len(values), abs=0.01)
        assert d.uncertainty_type == "standard_error_of_mean"
        assert d.uncertainty_value is not None and d.uncertainty_value > 0

    def test_hot_days_count(self):
        days = month_days(2024, 7)
        values = [36.0 if i % 2 == 0 else 30.0 for i in range(len(days))]
        obs = [utc_day_obs("air_temperature_max", d, v) for d, v in zip(days, values)]
        for o in obs:
            o["unit"] = "degC"
        d = self._monthly(obs, "hot_days_35c_count_monthly", year=2024, month=7)[0]
        assert d.unit == "days"
        assert d.value == pytest.approx(16, abs=0.01)
        assert d.quality_status == "valid"

    def test_dry_spell_missing_interrupts_never_assumed_dry(self):
        # Mar 1-7: dry, dry, MISSING, dry, dry, dry, wet — then all-wet tail
        values = {1: 0.0, 2: 0.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 5.0}
        obs = [
            utc_day_obs("precipitation", datetime(2024, 3, day, tzinfo=UTC), values.get(day))
            for day in range(1, 8)
        ] + [
            # wet tail so the longest spell is the interrupted Mar 4-6 run
            utc_day_obs("precipitation", datetime(2024, 3, day, tzinfo=UTC), 2.0)
            for day in range(8, 32)
        ]
        d = self._monthly(obs, "dry_spell_max_days_monthly")[0]
        # gap on Mar 3 interrupts: max spell = Mar 4-6 (3), not 5
        assert d.value == pytest.approx(3.0, abs=0.01)
        assert d.quality_status == "partial"

    def test_temporal_resolutions_never_mixed(self):
        """A monthly product observation must not join daily-bucket totals."""
        monthly_obs = utc_day_obs("precipitation", datetime(2024, 3, 15, tzinfo=UTC), 999.0)
        monthly_obs["time_support"] = "monthly"
        monthly_obs["id"] = "obs-monthly-1"
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 1.0) for d in days]
        w_start, w_end = local_month_window(2024, 3, CAIRO)
        drafts, _, warnings = compute_feature_drafts(
            observations=obs + [monthly_obs],
            specs=[spec("precipitation_total_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        march = [d for d in drafts if d.period_label == "2024-03"][0]
        assert march.value == pytest.approx(31.0, abs=0.01)  # 999 not summed
        assert any("time_support 'monthly'" in w and "excluded" in w for w in warnings)


class TestTimezoneAssignment:
    def test_local_midnight_observation_binned_by_farm_timezone(self):
        """A NEW YORK-local-midnight-anchored daily record (Feb 29 05:00Z -
        Mar 1 04:59Z) is binned into February in New York but March in
        Auckland (+13) — the run's calendar basis decides the bucket,
        explicitly and deterministically."""
        obs = [
            {
                "id": "obs-ny-midnight",
                "variable_code": "precipitation",
                "value": 10.0,
                "unit": "mm",
                "quality_status": "valid",
                "observed_at": datetime(2024, 2, 29, 19, 0, tzinfo=UTC),
                "period_start": datetime(2024, 2, 29, 19, 0, tzinfo=UTC),
                "period_end": datetime(2024, 3, 1, 4, 59, 59, tzinfo=UTC),
                "time_support": "daily",
                "is_synthetic": False,
                "processing_version": "test-v1",
                "evidence_class": "farmer_reported_record",
                "dataset_product_id": "prod-1",
            }
        ]
        auckland = ZoneInfo("Pacific/Auckland")
        for tz, expected_month, other_month in (
            (NEW_YORK, "2024-02", "2024-03"),
            (auckland, "2024-03", "2024-02"),
        ):
            drafts, _, _ = compute_feature_drafts(
                observations=obs,
                specs=[spec("precipitation_total_monthly")],
                tz=tz,
                hemisphere="north",
                window_start=datetime(2024, 1, 1, tzinfo=UTC),
                window_end=datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC),
                aggregation_levels=["monthly"],
                crop_seasons=[],
                engine_version="test-engine",
                definition_version="test-spec",
            )
            by_label = {d.period_label: d for d in drafts}
            # the single observation lands in exactly one local month bucket
            assert by_label[expected_month].n_input == 1, tz
            assert by_label[other_month].n_input == 0, tz
            # and it can never satisfy the monthly coverage minimum alone
            assert by_label[expected_month].quality_status == "insufficient_coverage"
            assert by_label[expected_month].value is None


class TestBaselinesAndAnomalies:
    def _six_years_january_precip(self, years=(2018, 2019, 2020, 2021, 2022, 2023)):
        obs = []
        totals = {2018: 40.0, 2019: 60.0, 2020: 50.0, 2021: 45.0, 2022: 55.0, 2023: 100.0}
        for year in years:
            for day in range(1, 32):
                obs.append(
                    utc_day_obs(
                        "precipitation",
                        datetime(year, 1, day, tzinfo=UTC),
                        totals.get(year, 50.0) / 31.0,
                    )
                )
        return obs, totals

    def test_anomaly_against_baseline(self):
        obs, totals = self._six_years_january_precip()
        drafts, not_evaluated, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_monthly"), spec("precipitation_anomaly_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=datetime(2018, 1, 1, tzinfo=UTC),
            window_end=datetime(2023, 1, 31, 23, 59, 59, tzinfo=UTC),
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        anomalies = {
            d.period_label: d for d in drafts if d.feature_code == "precipitation_anomaly_monthly"
        }
        anomaly = anomalies["2023-01"]
        assert anomaly.quality_status == "valid"
        # baseline climatology = mean of ALL Januaries in the window (40,60,50,45,55,100)
        assert anomaly.value == pytest.approx(100.0 - 58.3333, abs=0.5)
        baseline = anomaly.baseline_reference
        assert baseline["n_years"] == 6
        assert baseline["calendar_month"] == 1
        assert pytest.approx(baseline["mean"], abs=0.5) == 58.3333
        assert anomaly.provenance["baseline"] == baseline

    def test_anomaly_z_standardized(self):
        obs, totals = self._six_years_january_precip()
        drafts, _, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_monthly"), spec("precipitation_anomaly_z_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=datetime(2018, 1, 1, tzinfo=UTC),
            window_end=datetime(2023, 1, 31, 23, 59, 59, tzinfo=UTC),
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        anomalies = [d for d in drafts if d.feature_code == "precipitation_anomaly_z_monthly"]
        by_label = {d.period_label: d for d in anomalies}
        z = by_label["2023-01"]
        assert z.quality_status == "valid"
        assert z.value > 0  # wettest year above baseline
        assert z.unit == "sd"

    def test_anomaly_not_evaluated_below_min_years(self):
        obs, _ = self._six_years_january_precip(years=(2021, 2022, 2023))
        drafts, not_evaluated, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_monthly"), spec("precipitation_anomaly_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=datetime(2021, 1, 1, tzinfo=UTC),
            window_end=datetime(2023, 1, 31, 23, 59, 59, tzinfo=UTC),
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        anomalies = [d for d in drafts if d.feature_code == "precipitation_anomaly_monthly"]
        assert anomalies, "anomaly drafts are emitted but flagged"
        assert all(d.value is None and d.quality_status == "not_evaluated" for d in anomalies)
        assert any("5 distinct years" in r for r in not_evaluated.values())


class TestSeasonalAndCV:
    def test_seasonal_total_and_cv(self):
        obs = []
        jja_totals = {2018: 30.0, 2019: 40.0, 2020: 50.0, 2021: 60.0, 2022: 70.0}
        for year, total in jja_totals.items():
            for month in (6, 7, 8):
                n_days = 30 if month == 6 else 31
                for day in range(1, n_days + 1):
                    obs.append(
                        utc_day_obs("precipitation", datetime(year, month, day, tzinfo=UTC), total / 92.0)
                    )
        w_start, w_end = local_range_window(date(2018, 1, 1), date(2022, 12, 31), CAIRO)
        drafts, not_evaluated, _ = compute_feature_drafts(
            observations=obs,
            specs=[
                spec("precipitation_total_seasonal"),
                spec("precipitation_variability_cv_seasonal"),
            ],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["seasonal"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        seasonal = {d.period_label: d for d in drafts if d.feature_code == "precipitation_total_seasonal"}
        assert seasonal["2018-JJA"].value == pytest.approx(30.0, abs=0.5)
        # season bounds are LOCAL: June 1 in Cairo
        assert seasonal["2018-JJA"].period_start.astimezone(CAIRO).month == 6
        assert seasonal["2018-JJA"].quality_status == "valid"
        cvs = {d.period_label: d for d in drafts if d.feature_code == "precipitation_variability_cv_seasonal"}
        assert set(cvs) == {f"{y}-JJA" for y in jja_totals}
        for label, d in cvs.items():
            assert d.quality_status == "valid"
            baseline = d.provenance["baseline"]
            assert baseline["n_years"] == 5
        # CV is one number per season across years — same value for every year label
        vals = {round(d.value, 6) for d in cvs.values()}
        assert len(vals) == 1

    def test_cv_not_evaluated_with_few_years(self):
        # one full JJA season — seasonal total valid, but CV needs >= 5 seasons
        obs = [
            utc_day_obs("precipitation", datetime(2021, month, day, tzinfo=UTC), 1.0)
            for month in (6, 7, 8)
            for day in range(1, (30 if month != 7 else 31) + 1)
        ]
        w_start, w_end = local_range_window(date(2021, 1, 1), date(2021, 12, 31), CAIRO)
        drafts, not_evaluated, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_seasonal"), spec("precipitation_variability_cv_seasonal")],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["seasonal"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        cvs = [d for d in drafts if d.feature_code == "precipitation_variability_cv_seasonal"]
        assert cvs and all(d.value is None and d.quality_status == "not_evaluated" for d in cvs)
        assert any("5 distinct years" in r for r in not_evaluated.values())


class TestDifferenceAndCropSeason:
    def test_p_minus_et0(self):
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 2.0) for d in days]
        obs += [utc_day_obs("reference_et0", d, 3.0) for d in days]
        w_start, w_end = local_month_window(2024, 3, CAIRO)
        drafts, _, _ = compute_feature_drafts(
            observations=obs,
            specs=[
                spec("precipitation_total_monthly"),
                spec("reference_et0_total_monthly"),
                spec("water_balance_p_minus_et0_monthly"),
            ],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        wb = [d for d in drafts if d.feature_code == "water_balance_p_minus_et0_monthly"]
        assert len(wb) == 1
        assert wb[0].value == pytest.approx(2.0 * 31 - 3.0 * 31, abs=0.05)
        assert wb[0].provenance["derived_from"]["left"]["value"] == pytest.approx(62.0, abs=0.1)

    def test_p_minus_et0_without_et0_not_evaluated(self):
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 2.0) for d in days]
        w_start, w_end = local_month_window(2024, 3, CAIRO)
        drafts, not_evaluated, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_monthly"), spec("water_balance_p_minus_et0_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        wb = [d for d in drafts if d.feature_code == "water_balance_p_minus_et0_monthly"]
        assert wb and all(d.value is None and d.quality_status == "not_evaluated" for d in wb)
        assert any("ET0" in r for r in not_evaluated.values())

    def test_crop_season_window(self):
        obs = [
            utc_day_obs("precipitation", datetime(2024, 5, day, tzinfo=UTC), 1.0)
            for day in range(1, 32)
        ]
        w_start, w_end = local_range_window(date(2024, 5, 1), date(2024, 5, 31), CAIRO)
        cs_start, cs_end = local_range_window(date(2024, 5, 10), date(2024, 5, 20), CAIRO)
        drafts, _, _ = compute_feature_drafts(
            observations=obs,
            specs=[spec("precipitation_total_crop_season")],
            tz=CAIRO,
            hemisphere="north",
            window_start=w_start,
            window_end=w_end,
            aggregation_levels=["crop_season"],
            crop_seasons=[
                {"label": "maize_2024", "start": cs_start, "end": cs_end}
            ],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        assert len(drafts) == 1
        d = drafts[0]
        assert d.period_label == "maize_2024"
        assert d.value == pytest.approx(11.0, abs=0.01)
        assert d.provenance["crop_season_window"]["label"] == "maize_2024"
        assert "user_supplied_window" in d.provenance["crop_season_window"]["source"]


class TestReproducibility:
    def test_identical_inputs_identical_checksums(self):
        days = month_days(2024, 3)
        obs = [utc_day_obs("precipitation", d, 1.0 + (i % 3)) for i, d in enumerate(days)]
        kwargs = dict(
            observations=obs,
            specs=[spec("precipitation_total_monthly"), spec("dry_spell_max_days_monthly")],
            tz=CAIRO,
            hemisphere="north",
            window_start=local_month_window(2024, 3, CAIRO)[0],
            window_end=local_month_window(2024, 3, CAIRO)[1],
            aggregation_levels=["monthly"],
            crop_seasons=[],
            engine_version="test-engine",
            definition_version="test-spec",
        )
        drafts_a, _, _ = compute_feature_drafts(**kwargs)
        drafts_b, _, _ = compute_feature_drafts(**kwargs)
        for a, b in zip(drafts_a, drafts_b):
            assert a.provenance["checksum"] == b.provenance["checksum"]
            assert a.value == b.value


class TestDuplicateAssignment:
    def test_duplicate_local_day_collapsed_deterministically(self):
        obs = [utc_day_obs("precipitation", datetime(2024, 3, 1, tzinfo=UTC), 5.0)]
        dup = utc_day_obs("precipitation", datetime(2024, 3, 1, tzinfo=UTC), 9.0)
        dup["id"] = "obs-dup"
        series = build_daily_series(obs + [dup], "precipitation", CAIRO)
        assert len(series.cells) == 1
        assert series.cells[fscal.date(2024, 3, 1)].value == 5.0  # earliest wins
        assert series.duplicate_assignments == 1
