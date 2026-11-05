"""Unit: soil-cover timeline engine (M6C Increment 3).

Golden cases use hand arithmetic; property tests enforce the honesty
invariants (spec §14.2): unknown ≠ bare, counts partition the window,
overlap never double-counts protective days, intervals never leak outside
the window.
"""

import datetime as dt
import random

import pytest

from app.management.soil_cover import build_cover_timeline


def _window(year=2026):
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


def _run(**overrides):
    base = dict(
        window_start=_window()[0],
        window_end=_window()[1],
        crop_history=[],
        cover_crop_items=[],
        management_events=[],
        cover_observations=[],
    )
    base.update(overrides)
    return build_cover_timeline(**base)


def _count(result, classification):
    return sum(1 for d in result["timeline"] if d["classification"] == classification)


class TestGoldenIntervals:
    def test_crop_history_interval_hand_arithmetic(self):
        result = _run(
            crop_history=[
                {
                    "id": "c1",
                    "crop_label": "maize",
                    "sowing_date": dt.date(2026, 5, 1),
                    "harvest_date": dt.date(2026, 8, 15),
                    "evidence_class": "farmer_reported_record",
                }
            ]
        )
        # May 1 .. Aug 15 inclusive = 31-1+1 + 30+31+31+15 = 107 days
        assert _count(result, "protective") == 107
        assert result["metrics"]["state_day_counts"]["living_main_crop"] == 107
        assert _count(result, "unknown") == 365 - 107
        assert _count(result, "bare") == 0

    def test_one_endpoint_is_not_enough(self):
        """A crop with only a sowing date cannot produce an interval — the
        missing harvest date stays a gap (never assumed)."""
        result = _run(
            crop_history=[
                {"id": "c1", "crop_label": "maize", "sowing_date": dt.date(2026, 5, 1), "harvest_date": None}
            ]
        )
        assert _count(result, "protective") == 0
        assert _count(result, "unknown") == 365

    def test_residue_opened_by_event_closed_by_removal(self):
        result = _run(
            management_events=[
                {"id": "e1", "event_date": dt.date(2026, 9, 10), "event_type": "residue_retention", "title": "left stubble", "details": {}},
                {"id": "e2", "event_date": dt.date(2026, 11, 1), "event_type": "residue_removal", "title": "baled", "details": {}},
            ]
        )
        # Sep 10 .. Nov 1 inclusive = 21+31+1 = 53 days
        assert result["metrics"]["state_day_counts"]["surface_residue"] == 53
        assert _count(result, "protective") == 53

    def test_residue_open_at_window_end_disclosed(self):
        result = _run(
            management_events=[
                {"id": "e1", "event_date": dt.date(2026, 9, 10), "event_type": "residue_retention", "title": None, "details": {}}
            ]
        )
        # Sep 10 .. Dec 31 = 21+31+30+31 = 113 days
        assert result["metrics"]["state_day_counts"]["surface_residue"] == 113
        assert any(n["note"] == "residue_interval_open_at_window_end" for n in result["evidence_notes"])

    def test_tillage_closes_residue(self):
        result = _run(
            management_events=[
                {"id": "e1", "event_date": dt.date(2026, 9, 10), "event_type": "residue_retention", "title": None, "details": {}},
                {"id": "e2", "event_date": dt.date(2026, 10, 5), "event_type": "tillage", "title": None, "details": {}},
            ]
        )
        # Sep 10 .. Oct 5 = 21+5 = 26 days of residue; afterwards unknown (not bare)
        assert result["metrics"]["state_day_counts"]["surface_residue"] == 26
        assert _count(result, "bare") == 0

    def test_cover_item_interval(self):
        result = _run(
            cover_crop_items=[
                {
                    "id": "cc1",
                    "crop_label": "faba_bean",
                    "intended_sowing_start": dt.date(2026, 10, 1),
                    "intended_termination_window_start": dt.date(2026, 12, 15),
                    "evidence_class": "farmer_reported_record",
                }
            ]
        )
        # Oct 1 .. Dec 15 = 31+30+15 = 76 days
        assert result["metrics"]["state_day_counts"]["living_cover_crop"] == 76


class TestUnknownVsBare:
    def test_no_evidence_means_unknown_not_bare(self):
        result = _run()
        assert _count(result, "unknown") == 365
        assert _count(result, "bare") == 0
        assert result["metrics"]["days_known_bare"] == 0

    def test_explicit_bare_observation_only_marks_that_day(self):
        result = _run(
            cover_observations=[
                {"id": "o1", "observed_date": dt.date(2026, 3, 15), "cover_state": "bare", "cover_fraction": None}
            ]
        )
        assert _count(result, "bare") == 1
        day = next(d for d in result["timeline"] if d["date"] == "2026-03-15")
        assert day["classification"] == "bare"
        # neighbours stay unknown
        before = next(d for d in result["timeline"] if d["date"] == "2026-03-14")
        assert before["classification"] == "unknown"

    def test_fraction_zero_is_bare_evidence_state_unknown(self):
        result = _run(
            cover_observations=[
                {"id": "o1", "observed_date": dt.date(2026, 3, 15), "cover_state": "unknown", "cover_fraction": 0.0}
            ]
        )
        assert _count(result, "bare") == 1

    def test_fraction_positive_counts_protective_even_state_unknown(self):
        result = _run(
            cover_observations=[
                {"id": "o1", "observed_date": dt.date(2026, 3, 15), "cover_state": "unknown", "cover_fraction": 0.42}
            ]
        )
        assert _count(result, "protective") == 1
        day = next(d for d in result["timeline"] if d["date"] == "2026-03-15")
        assert day["classification"] == "protective"

    def test_unknown_state_without_fraction_stays_unknown(self):
        result = _run(
            cover_observations=[
                {"id": "o1", "observed_date": dt.date(2026, 3, 15), "cover_state": "unknown", "cover_fraction": None}
            ]
        )
        assert _count(result, "unknown") == 365


class TestOverlap:
    def test_crop_and_residue_overlap_both_states_once_protective(self):
        result = _run(
            crop_history=[
                {"id": "c1", "crop_label": "maize", "sowing_date": dt.date(2026, 5, 1), "harvest_date": dt.date(2026, 8, 15)}
            ],
            management_events=[
                {"id": "e1", "event_date": dt.date(2026, 9, 10), "event_type": "residue_retention", "title": None, "details": {}}
            ],
        )
        assert result["metrics"]["state_day_counts"]["living_main_crop"] == 107
        assert result["metrics"]["state_day_counts"]["surface_residue"] == 113
        assert _count(result, "protective") == 107 + 113  # disjoint in time

    def test_overlapping_intervals_dont_double_count_days(self):
        result = _run(
            crop_history=[
                {"id": "c1", "crop_label": "maize", "sowing_date": dt.date(2026, 5, 1), "harvest_date": dt.date(2026, 8, 15)}
            ],
            cover_crop_items=[
                {
                    "id": "cc1",
                    "crop_label": "faba_bean",
                    "intended_sowing_start": dt.date(2026, 7, 1),
                    "intended_termination_window_start": dt.date(2026, 9, 30),
                }
            ],
        )
        # overlap Jul 1 .. Aug 15 counted once as protective
        assert _count(result, "protective") == 107 + (46 - 46) + (16 + 30)  # 153
        day = next(d for d in result["timeline"] if d["date"] == "2026-07-15")
        assert day["classification"] == "protective"

    def test_longest_bare_interval_hand_computed(self):
        result = _run(
            cover_observations=[
                {"id": "o1", "observed_date": dt.date(2026, 2, 1), "cover_state": "bare"},
                {"id": "o2", "observed_date": dt.date(2026, 2, 2), "cover_state": "bare"},
                {"id": "o3", "observed_date": dt.date(2026, 2, 3), "cover_state": "bare"},
                {"id": "o4", "observed_date": dt.date(2026, 6, 1), "cover_state": "bare"},
                {"id": "o5", "observed_date": dt.date(2026, 6, 2), "cover_state": "bare"},
            ]
        )
        assert result["metrics"]["longest_bare_interval_days"] == 3
        assert result["metrics"]["longest_bare_interval"] == ["2026-02-01", "2026-02-03"]


class TestThresholdsAndMethod:
    def test_no_threshold_means_no_pass_fail(self):
        result = _run(
            crop_history=[
                {"id": "c1", "crop_label": "maize", "sowing_date": dt.date(2026, 5, 1), "harvest_date": dt.date(2026, 8, 15)}
            ]
        )
        assert result["thresholds"]["applicable"] == []
        # no day or metric carries a pass/fail verdict: classifications are
        # limited to the three evidence states, and the metrics dict adds no
        # verdict field.
        classifications = {d["classification"] for d in result["timeline"]}
        assert classifications <= {"protective", "bare", "unknown"}
        allowed_metric_keys = {
            "window_days", "days_protective_cover", "days_known_bare",
            "days_unknown", "protective_cover_fraction",
            "protective_fraction_basis", "longest_bare_interval_days",
            "longest_bare_interval", "state_day_counts", "month_breakdown",
        }
        assert set(result["metrics"].keys()) == allowed_metric_keys

    def test_month_breakdown_sums_to_window(self):
        result = _run()
        total = sum(
            b["protective"] + b["bare"] + b["unknown"] for b in result["metrics"]["month_breakdown"]
        )
        assert total == 365


class TestProperties:
    def test_partition_and_bounds_randomized(self):
        rng = random.Random(20261031)
        for trial in range(30):
            start = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randint(0, 60))
            end = start + dt.timedelta(days=rng.randint(30, 200))
            crops = []
            for k in range(rng.randint(0, 3)):
                s = start + dt.timedelta(days=rng.randint(0, 90))
                e = s + dt.timedelta(days=rng.randint(0, 120))
                crops.append({"id": f"c{k}", "crop_label": "x", "sowing_date": s, "harvest_date": e})
            events = []
            for k in range(rng.randint(0, 3)):
                d = start + dt.timedelta(days=rng.randint(0, 120))
                events.append({"id": f"e{k}", "event_date": d, "event_type": rng.choice(["residue_retention", "residue_removal", "tillage"]), "title": None, "details": {}})
            result = build_cover_timeline(
                window_start=start,
                window_end=end,
                crop_history=crops,
                cover_crop_items=[],
                management_events=events,
                cover_observations=[],
            )
            m = result["metrics"]
            total = (end - start).days + 1
            assert m["days_protective_cover"] + m["days_known_bare"] + m["days_unknown"] == total
            assert 0 <= m["protective_cover_fraction"] <= 1
            assert m["longest_bare_interval_days"] <= total
            # timeline dates within window
            assert result["timeline"][0]["date"] == start.isoformat()
            assert result["timeline"][-1]["date"] == end.isoformat()

    def test_determinism_same_inputs_same_output(self):
        kwargs = dict(
            crop_history=[{"id": "c1", "crop_label": "maize", "sowing_date": dt.date(2026, 5, 1), "harvest_date": dt.date(2026, 8, 15)}],
            management_events=[{"id": "e1", "event_date": dt.date(2026, 9, 10), "event_type": "residue_retention", "title": None, "details": {}}],
        )
        r1 = _run(**kwargs)
        r2 = _run(**kwargs)
        assert r1 == r2
