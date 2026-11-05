"""Unit: operations scheduling engine (M6C Increment 7).

Spec §14.5 invariants as golden cases + properties: precedence, resource
non-overlap, capacity of windows, availability calendars, unscheduled
reporting, missing-forecast behaviour, determinism, no silent constraint
relaxation.
"""

import datetime as dt

from app.management.scheduling import (
    merge_schedule_result,
    prepare_operations,
    solve_schedule,
)

H0 = dt.date(2026, 9, 1)
H1 = dt.date(2026, 10, 31)


def _op(**kw):
    base = {
        "id": "op1",
        "title": "Operation 1",
        "priority": 3,
        "earliest_start": None,
        "latest_finish": None,
        "duration_days": 2,
        "duration_estimate_hours": None,
        "resource_requirements": [{"resource_type": "tractor"}],
    }
    base.update(kw)
    return base


def _res(**kw):
    base = {
        "id": "t1",
        "resource_type": "tractor",
        "name": "Tractor 1",
        "availability_calendar": [],
    }
    base.update(kw)
    return base


def _run(operations, dependencies=None, resources=None, hours_per_workday=None,
         horizon=(H0, H1)):
    if resources is None:
        resources = [_res()]
    prepared = prepare_operations(
        operations, dependencies or [], horizon_start=horizon[0],
        horizon_end=horizon[1], resources=resources,
        hours_per_workday=hours_per_workday,
    )
    solve = solve_schedule(prepared, dependencies or [], resources)
    return prepared, solve


class TestGoldenSchedule:
    def test_precedence_hand_checked(self):
        prepared, solve = _run(
            [_op(id="a", title="First"), _op(id="b", title="Second")],
            dependencies=[{"operation_id": "b", "depends_on_operation_id": "a",
                           "dependency_type": "finish_to_start", "lag_days": 0}],
        )
        assert solve["status"] == "scheduled"
        by_id = {a["operation_id"]: a for a in solve["assignments"]}
        a, b = by_id["a"], by_id["b"]
        # earliest possible: a on days 0-1, b starts on day 2 (earliness objective)
        assert a["scheduled_start"] == "2026-09-01"
        assert a["scheduled_end"] == "2026-09-02"
        assert b["scheduled_start"] == "2026-09-03"

    def test_same_machine_never_overlaps(self):
        prepared, solve = _run(
            [_op(id="a"), _op(id="b")],
        )
        by_id = {a["operation_id"]: a for a in solve["assignments"]}
        ends = {
            dt.date.fromisoformat(by_id["a"]["scheduled_end"]),
            dt.date.fromisoformat(by_id["b"]["scheduled_start"]),
        }
        # one starts after the other ends (day granularity, no shared day)
        a_end = dt.date.fromisoformat(by_id["a"]["scheduled_end"])
        b_start = dt.date.fromisoformat(by_id["b"]["scheduled_start"])
        b2_start = by_id["b"]
        assert b_start > a_end or dt.date.fromisoformat(by_id["a"]["scheduled_start"]) > dt.date.fromisoformat(by_id["b"]["scheduled_end"])

    def test_window_bounds_respected(self):
        prepared, solve = _run(
            [_op(id="a", earliest_start=dt.date(2026, 9, 10),
                 latest_finish=dt.date(2026, 9, 20))],
        )
        a = solve["assignments"][0]
        assert a["scheduled_start"] == "2026-09-10"  # earliest + earliness objective
        assert a["scheduled_end"] <= "2026-09-20"


class TestUnscheduledHonesty:
    def test_no_duration_unscheduled_with_reason(self):
        prepared, solve = _run([_op(id="a", duration_days=None,
                                    duration_estimate_hours=None)])
        assert solve["status"] == "no_schedulable_operations"
        assert prepared["unscheduled"][0]["reasons"][0]["code"] == "no_duration"

    def test_hours_without_workday_length_refused(self):
        prepared, _ = _run([_op(id="a", duration_days=None,
                                duration_estimate_hours=8.0)])
        assert prepared["unscheduled"][0]["reasons"][0]["code"] == "no_workday_length"

    def test_hours_with_workday_length_convert(self):
        prepared, solve = _run(
            [_op(id="a", duration_days=None, duration_estimate_hours=16.0)],
            hours_per_workday=8.0,
        )
        assert prepared["schedulable"][0]["duration_days"] == 2.0
        assert solve["status"] == "scheduled"

    def test_no_resource_of_type(self):
        prepared, _ = _run([_op(id="a")], resources=[])
        assert any(
            r["code"] == "no_resource_of_type" for r in prepared["unscheduled"][0]["reasons"]
        )

    def test_window_too_short(self):
        prepared, _ = _run(
            [_op(id="a", duration_days=10,
                 earliest_start=dt.date(2026, 9, 20), latest_finish=dt.date(2026, 9, 25))]
        )
        assert any(
            r["code"] == "window_too_short_for_duration"
            for r in prepared["unscheduled"][0]["reasons"]
        )

    def test_predecessor_unschedulable_propagates(self):
        prepared, _ = _run(
            [_op(id="a", duration_days=None), _op(id="b")],
            dependencies=[{"operation_id": "b", "depends_on_operation_id": "a",
                           "dependency_type": "finish_to_start", "lag_days": 0}],
        )
        codes = {u["operation_id"]: [r["code"] for r in u["reasons"]]
                 for u in prepared["unscheduled"]}
        assert "no_duration" in codes["a"]
        assert "predecessor_unschedulable" in codes["b"]

    def test_nothing_silently_dropped(self):
        """Every operation appears in the merged result with a status."""
        operations = [_op(id="a"), _op(id="b", duration_days=None),
                      _op(id="c", resource_requirements=[{"resource_type": "harvester"}])]
        prepared = prepare_operations(
            operations, [], horizon_start=H0, horizon_end=H1,
            resources=[_res()], hours_per_workday=None,
        )
        solve = solve_schedule(prepared, [], [_res()])
        merged = merge_schedule_result(prepared, solve, operations)
        entry_ids = {e["operation_id"] for e in merged["entries"]}
        assert entry_ids == {"a", "b", "c"}
        statuses = {e["operation_id"]: e["status"] for e in merged["entries"]}
        assert statuses["a"] == "scheduled"
        assert statuses["b"] == "unscheduled"
        assert statuses["c"] == "unscheduled"
        assert merged["entries"][1]["reason"]


class TestAvailabilityAndInfeasibility:
    def test_availability_window_respected(self):
        prepared, solve = _run(
            [_op(id="a", earliest_start=dt.date(2026, 9, 1))],
            resources=[_res(availability_calendar=[
                {"from": "2026-09-10", "to": "2026-09-30"}])],
        )
        a = solve["assignments"][0]
        assert a["scheduled_start"] >= "2026-09-10"
        assert a["scheduled_end"] <= "2026-09-30"

    def test_infeasible_names_conflicts(self):
        # two 10-day operations on ONE tractor, both must finish by day 10
        prepared, solve = _run(
            [_op(id="a", duration_days=10,
                 earliest_start=dt.date(2026, 9, 1), latest_finish=dt.date(2026, 9, 10)),
             _op(id="b", duration_days=10,
                 earliest_start=dt.date(2026, 9, 1), latest_finish=dt.date(2026, 9, 10))],
        )
        assert solve["status"] == "infeasible"
        assert solve["conflicts"], "infeasibility must name its conflicts"
        assert any(c["code"] in ("exclusive_resource_overdemand", "infeasible_combination")
                   for c in solve["conflicts"])

    def test_resource_choice_when_type_only(self):
        prepared, solve = _run(
            [_op(id="a"), _op(id="b")],
            resources=[_res(id="t1"), _res(id="t2", name="Tractor 2")],
        )
        by_id = {a["operation_id"]: a for a in solve["assignments"]}
        # both scheduled; may share the window only on different machines
        if by_id["a"]["scheduled_start"] <= by_id["b"]["scheduled_end"] and \
           by_id["b"]["scheduled_start"] <= by_id["a"]["scheduled_end"]:
            assert by_id["a"]["assigned_resources"]["tractor"] != \
                   by_id["b"]["assigned_resources"]["tractor"]


class TestDeterminismAndChecks:
    def test_identical_inputs_identical_schedule(self):
        kwargs = dict(
            operations=[_op(id="a"), _op(id="b", priority=1),
                        _op(id="c", resource_requirements=[{"resource_type": "tractor"}])],
            dependencies=[{"operation_id": "c", "depends_on_operation_id": "a",
                           "dependency_type": "finish_to_start", "lag_days": 1}],
        )
        prepared = prepare_operations(
            kwargs["operations"], kwargs["dependencies"], horizon_start=H0,
            horizon_end=H1, resources=[_res()], hours_per_workday=None,
        )
        s1 = solve_schedule(prepared, kwargs["dependencies"], [_res()])
        s2 = solve_schedule(prepared, kwargs["dependencies"], [_res()])
        assert s1 == s2

    def test_weather_and_soil_checks_pending(self):
        prepared, solve = _run([_op(id="a")])
        merged = merge_schedule_result(prepared, solve, [_op(id="a")])
        entry = merged["entries"][0]
        assert entry["weather_check"] == "pending"
        assert entry["soil_readiness_check"] == "manual_required"
