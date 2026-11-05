"""Unit: M7.5 robust rotation pure logic — scenario climate view value
sources, month coverage, per-scenario verdicts, member documents."""

from datetime import datetime, UTC
from types import SimpleNamespace

from app.robust_rotation import climate as rclimate
from app.robust_rotation import contracts as rc
from app.robust_rotation.service import _scenario_verdict
from app.rotation.problem import SeasonSpec
from datetime import date


def _row(code, status, period, scenario=None, baseline=None, agg="monthly", synthetic=False):
    return SimpleNamespace(
        feature_code=code,
        aggregation_level=agg,
        period_start=period,
        scenario_value=scenario,
        baseline_value=baseline,
        evidence_status=status,
        is_synthetic=synthetic,
    )


class TestScenarioRunView:
    def test_value_sources_recalculated_and_not_affected(self):
        rows = [
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2016, 1, 1, tzinfo=UTC), scenario=80.0, baseline=100.0),
            _row("air_temperature_mean_monthly", "not_affected",
                 datetime(2016, 1, 1, tzinfo=UTC), scenario=None, baseline=14.2),
            _row("reference_et0_total_monthly", "not_evaluated",
                 datetime(2016, 1, 1, tzinfo=UTC), scenario=None, baseline=None),
            _row("seasonal_feature", "scenario_recalculated",
                 datetime(2016, 1, 1, tzinfo=UTC), scenario=1.0, agg="seasonal"),
        ]
        view = rclimate.build_scenario_run_view(rows, is_synthetic=False)
        codes = {v.feature_code: v for v in view.values}
        # recalculated -> scenario value
        assert codes["precipitation_total_monthly"].value == 80.0
        # not_affected -> baseline value (identity, recorded)
        assert codes["air_temperature_mean_monthly"].value == 14.2
        assert view.value_sources["air_temperature_mean_monthly"] == "not_affected_baseline"
        assert view.value_sources["precipitation_total_monthly"] == "scenario_recalculated"
        # not_evaluated -> excluded (None) and recorded
        assert codes["reference_et0_total_monthly"].value is None
        assert "reference_et0_total_monthly" in view.not_evaluated_codes
        # non-monthly rows never enter the climatology
        assert "seasonal_feature" not in codes

    def test_missing_stays_missing(self):
        rows = [
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2016, 2, 1, tzinfo=UTC), scenario=None, baseline=100.0),
        ]
        view = rclimate.build_scenario_run_view(rows, is_synthetic=False)
        assert view.values[0].value is None
        assert "precipitation_total_monthly" not in view.value_sources


class TestMonthCoverage:
    SEASON = SeasonSpec(label="s", start_date=date(2016, 11, 15), end_date=date(2017, 3, 20))

    def test_required_months_wrap_years(self):
        months = rclimate.required_months(self.SEASON)
        assert months == [(2016, 11), (2016, 12), (2017, 1), (2017, 2), (2017, 3)]

    def test_gaps_detected(self):
        rows = [
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2016, 11, 1, tzinfo=UTC), scenario=10.0),
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2016, 12, 1, tzinfo=UTC), scenario=10.0),
            # Jan/Feb/Mar missing
        ]
        view = rclimate.build_scenario_run_view(rows, is_synthetic=False)
        gaps = rclimate.month_coverage_gaps(view, [self.SEASON])
        assert gaps["s"] == ["2017-01", "2017-02", "2017-03"]

    def test_no_gaps_when_all_months_present(self):
        rows = [
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2016, m, 1, tzinfo=UTC), scenario=10.0)
            for m in (11, 12)
        ] + [
            _row("precipitation_total_monthly", "scenario_recalculated",
                 datetime(2017, m, 1, tzinfo=UTC), scenario=10.0)
            for m in (1, 2, 3)
        ]
        view = rclimate.build_scenario_run_view(rows, is_synthetic=False)
        assert rclimate.month_coverage_gaps(view, [self.SEASON]) == {}

    def test_window_intersection_check(self):
        w_start = datetime(2016, 1, 1, tzinfo=UTC)
        w_end = datetime(2016, 12, 31, tzinfo=UTC)
        assert rclimate.season_months_inside_window(self.SEASON, w_start, w_end) is False
        w_start2 = datetime(2016, 10, 1, tzinfo=UTC)
        w_end2 = datetime(2017, 4, 30, tzinfo=UTC)
        assert rclimate.season_months_inside_window(self.SEASON, w_start2, w_end2) is True


class TestScenarioVerdict:
    def test_violated_check_wins(self):
        checks = [{"status": "satisfied"}, {"status": "violated"}]
        adm = [{"admissible": True}]
        assert _scenario_verdict(checks, adm) == "infeasible"

    def test_excluded_crop_is_infeasible(self):
        checks = [{"status": "satisfied"}]
        adm = [{"admissible": False, "hard_reason": "below absolute minimum"}]
        assert _scenario_verdict(checks, adm) == "infeasible"

    def test_feasible_requires_evaluated_checks(self):
        assert _scenario_verdict([{"status": "satisfied"}], []) == "feasible"
        # no evaluated checks -> not evaluable; unevaluated is never 'satisfied'
        assert _scenario_verdict([{"status": "partially_checked"}], []) == "not_evaluable"


class TestMemberDocument:
    def test_pins_are_by_value(self):
        run = SimpleNamespace(
            id="r-1", scenario_id="s-1", scenario_version=3, run_status="succeeded",
            output_checksum="abc", parent_field_state_id="fs-1",
            parent_snapshot_checksum="pk", scenario_configuration_checksum="ck",
            input_fingerprint="fp", transformation_engine_version="t1",
            feature_engine_version="f1", feature_catalog_version="c1",
        )
        doc = rc.member_document(run)
        assert doc["output_checksum"] == "abc"
        assert doc["scenario_version"] == 3
        # mutating the source afterwards must not change the pinned document
        run.output_checksum = "changed"
        assert doc["output_checksum"] == "abc"
