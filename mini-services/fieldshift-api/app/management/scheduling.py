"""Operations scheduling engine (M6C Increment 7).

CP-SAT formulation over DAY granularity within an explicit horizon
(the only module in `app.management` that knows OR-Tools, mirroring the
rotation adapter's determinism contract: num_search_workers=1, fixed seed,
identical inputs → identical schedule, tested).

HONESTY CONTRACT (spec §8):

- Durations are farmer/sourced inputs. An operation without a usable duration
  is NEVER scheduled — it lands in `unscheduled` with reason `no_duration`
  (hours are converted only with a farmer-supplied `hours_per_workday`; a
  missing workday length is never assumed).
- Resources are farmer-entered. A required resource type with no matching
  resource ⇒ `no_resource_of_type`. Capacity/availability gaps are reported,
  never defaulted.
- Weather and soil conditions are NOT evaluated: the platform has no forecast
  provider and no universal trafficability threshold. Every scheduled
  operation carries `weather_check: pending` and `soil_readiness_check:
  manual_required` (spec §8.5/8.6).
- Every operation appears in the result with a status + reason — nothing is
  silently dropped to make the calendar look clean.
- Infeasibility names the conflicting operations; hard constraints are never
  relaxed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

SCHEDULING_ENGINE_VERSION = "scheduling-engine-1.0.0"
SCHEDULING_METHODS_VERSION = "scheduling-methods-1.0.0"

EXCLUSIVE_RESOURCE_TYPES = frozenset(
    {"tractor", "implement", "seeder", "sprayer", "harvester", "baler",
     "irrigation_equipment", "contractor", "labor_crew", "transport"}
)


def _day_index(day: dt.date, horizon_start: dt.date) -> int:
    return (day - horizon_start).days


def prepare_operations(
    operations: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    *,
    horizon_start: dt.date,
    horizon_end: dt.date,
    resources: list[dict[str, Any]],
    hours_per_workday: float | None,
) -> dict[str, Any]:
    """Split operations into schedulable + unscheduled with named reasons.

    Pure function. `operations` carry: id, title, priority, earliest_start,
    latest_finish, duration_days?, duration_estimate_hours?,
    resource_requirements [{resource_type, resource_id?}].
    """
    unscheduled: list[dict[str, Any]] = []
    schedulable: list[dict[str, Any]] = []
    resource_ids = {str(r["id"]) for r in resources}

    for op in operations:
        reasons: list[dict[str, Any]] = []
        duration_days: float | None = op.get("duration_days")
        if duration_days is None:
            hours = op.get("duration_estimate_hours")
            if hours is not None and hours_per_workday:
                duration_days = float(hours) / hours_per_workday
            elif hours is not None:
                reasons.append(
                    {
                        "code": "no_workday_length",
                        "message": "duration supplied in hours but "
                        "hours_per_workday was not provided for this run — a "
                        "workday length is never assumed",
                    }
                )
            else:
                reasons.append(
                    {
                        "code": "no_duration",
                        "message": "no duration estimate supplied (farmer/"
                        "resource inputs only — the engine invents none)",
                    }
                )

        # resource requirements must resolve against the farm registry
        resolved_reqs: list[dict[str, Any]] = []
        for req in op.get("resource_requirements") or []:
            rtype = req.get("resource_type")
            rid = req.get("resource_id")
            if rid is not None:
                if str(rid) not in resource_ids:
                    reasons.append(
                        {
                            "code": "unknown_resource",
                            "message": f"required resource {rid} is not in the "
                            "farm registry",
                        }
                    )
                    continue
                resolved_reqs.append({**req, "resource_id": str(rid)})
            elif rtype:
                if rtype not in EXCLUSIVE_RESOURCE_TYPES:
                    reasons.append(
                        {
                            "code": "unknown_resource_type",
                            "message": f"unknown resource type '{rtype}'",
                        }
                    )
                    continue
                if not any(r["resource_type"] == rtype for r in resources):
                    reasons.append(
                        {
                            "code": "no_resource_of_type",
                            "message": f"no '{rtype}' in the farm registry — "
                            "capacity is never assumed",
                        }
                    )
                    continue
                resolved_reqs.append({**req})
            else:
                reasons.append(
                    {
                        "code": "resource_requirement_incomplete",
                        "message": "a resource requirement needs a type or an id",
                    }
                )

        earliest = op.get("earliest_start")
        latest = op.get("latest_finish")
        if duration_days is not None:
            lo = _day_index(_as_date(earliest), horizon_start) if earliest else 0
            hi = (
                _day_index(_as_date(latest), horizon_start)
                if latest
                else _day_index(horizon_end, horizon_start)
            )
            span = hi - lo + 1
            if span < duration_days:
                reasons.append(
                    {
                        "code": "window_too_short_for_duration",
                        "message": f"window of {span} day(s) cannot fit a "
                        f"{duration_days:g}-day operation",
                    }
                )
        if reasons:
            unscheduled.append({"operation_id": op["id"], "title": op.get("title"), "reasons": reasons})
        else:
            schedulable.append(
                {
                    **op,
                    "duration_days": float(duration_days),
                    "resolved_requirements": resolved_reqs,
                }
            )

    # predecessor unschedulable ⇒ successor unschedulable (transitively)
    deps_by_op: dict[str, list[str]] = {}
    for dep in dependencies:
        deps_by_op.setdefault(str(dep["operation_id"]), []).append(
            str(dep["depends_on_operation_id"])
        )
    unschedulable_ids = {u["operation_id"] for u in unscheduled}
    changed = True
    schedulable_ids = {str(op["id"]) for op in schedulable}
    while changed:
        changed = False
        for op_id in list(schedulable_ids):
            for pred in deps_by_op.get(op_id, []):
                if pred in unschedulable_ids:
                    schedulable_ids.discard(op_id)
                    unschedulable_ids.add(op_id)
                    unscheduled.append(
                        {
                            "operation_id": op_id,
                            "title": next(
                                (o.get("title") for o in operations if str(o["id"]) == op_id), None
                            ),
                            "reasons": [
                                {
                                    "code": "predecessor_unschedulable",
                                    "message": f"predecessor {pred} could not be "
                                    "scheduled — hard precedence is never relaxed",
                                }
                            ],
                        }
                    )
                    changed = True
    schedulable = [op for op in schedulable if str(op["id"]) in schedulable_ids]

    return {
        "schedulable": schedulable,
        "unscheduled": unscheduled,
        "horizon": [horizon_start.isoformat(), horizon_end.isoformat()],
    }


def solve_schedule(
    prepared: dict[str, Any],
    dependencies: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    """CP-SAT day scheduling with precedence + per-resource non-overlap.

    Deterministic (single worker, fixed seed). Returns assignments for the
    schedulable set plus solver status; the caller merges `unscheduled` back.
    """
    from ortools.sat.python import cp_model

    ops = prepared["schedulable"]
    horizon_start = dt.date.fromisoformat(prepared["horizon"][0])
    horizon_end = dt.date.fromisoformat(prepared["horizon"][1])
    horizon_days = (horizon_end - horizon_start).days + 1

    if not ops:
        return {
            "status": "no_schedulable_operations",
            "assignments": [],
            "solver_status": "none",
        }

    model = cp_model.CpModel()
    horizon = model.NewConstant(horizon_days)

    starts: dict[str, Any] = {}
    ends: dict[str, Any] = {}
    intervals: dict[str, Any] = {}
    for op in ops:
        oid = str(op["id"])
        dur = max(1, int(round(op["duration_days"])))
        lo = _day_index(_as_date(op["earliest_start"]), horizon_start) if op.get("earliest_start") else 0
        hi = (
            _day_index(_as_date(op["latest_finish"]), horizon_start)
            if op.get("latest_finish")
            else horizon_days - 1
        )
        lo = max(0, lo)
        hi = min(horizon_days - 1, hi)
        start = model.NewIntVar(lo, hi, f"start_{oid}")
        end = model.NewIntVar(lo + dur, min(horizon_days, hi + dur), f"end_{oid}")
        model.Add(start + dur == end)
        model.Add(end <= horizon)
        starts[oid] = start
        ends[oid] = end
        intervals[oid] = (model.NewIntervalVar(start, dur, end, f"iv_{oid}"), dur)

    # precedence (finish_to_start default; lag days)
    op_ids = {str(op["id"]) for op in ops}
    for dep in dependencies:
        oid, pred = str(dep["operation_id"]), str(dep["depends_on_operation_id"])
        if oid in op_ids and pred in op_ids and dep.get("dependency_type", "finish_to_start") == "finish_to_start":
            model.Add(starts[oid] >= ends[pred] + int(dep.get("lag_days", 0)))

    # resource assignment: for each requirement with a type (no fixed id),
    # exactly-one candidate resource; NoOverlap per concrete resource.
    resources_by_type: dict[str, list[dict[str, Any]]] = {}
    for r in resources:
        if r["resource_type"] in EXCLUSIVE_RESOURCE_TYPES:
            resources_by_type.setdefault(r["resource_type"], []).append(r)

    resource_of: dict[str, dict[str, Any]] = {}
    for op in ops:
        oid = str(op["id"])
        for req in op["resolved_requirements"]:
            rtype, rid = req.get("resource_type"), req.get("resource_id")
            candidates = (
                [r for r in resources_by_type.get(rtype, []) if str(r["id"]) == rid]
                if rid
                else resources_by_type.get(rtype, [])
            )
            if rid:
                resource_of.setdefault(oid, {})[rtype] = rid
                continue
            lits = {}
            for r in candidates:
                rid = str(r["id"])
                lits[rid] = model.NewBoolVar(f"assign_{oid}_{rtype}_{rid}")
            model.AddExactlyOne(lits.values())
            # availability windows per candidate: if assigned to the resource,
            # the interval must fit inside one declared availability window
            for r in candidates:
                rid = str(r["id"])
                lit = lits[rid]
                windows = r.get("availability_calendar") or []
                if windows:
                    in_window_lits = []
                    for w in windows:
                        w_start = _day_index(_as_date(w["from"]), horizon_start)
                        w_end = _day_index(_as_date(w["to"]), horizon_start)
                        in_window = model.NewBoolVar(f"in_{oid}_{rid}_{w_start}")
                        # in_window=true ⇒ interval lies inside this window
                        model.Add(starts[oid] >= w_start).OnlyEnforceIf(in_window)
                        model.Add(ends[oid] <= w_end).OnlyEnforceIf(in_window)
                        in_window_lits.append(in_window)
                    # assigned ⇒ inside at least one declared window
                    model.AddBoolOr(in_window_lits).OnlyEnforceIf(lit)
            resource_of.setdefault(oid, {})[rtype] = lits  # type: ignore[assignment]

    # NoOverlap per concrete resource over the assigned optional intervals
    per_resource: dict[str, list[Any]] = {}
    for op in ops:
        oid = str(op["id"])
        iv, _dur = intervals[oid]
        for rtype, req_resource in resource_of.get(oid, {}).items():
            if isinstance(req_resource, str):
                per_resource.setdefault(req_resource, []).append(iv)
            else:
                for rid, lit in req_resource.items():
                    opt = model.NewOptionalIntervalVar(
                        starts[oid], intervals[oid][1], ends[oid], lit, f"niv_{oid}_{rid}"
                    )
                    per_resource.setdefault(rid, []).append(opt)
    for rid, ivs in per_resource.items():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # objective: priority-weighted earliness (deterministic tie-break by op id)
    objective_terms = []
    for op in sorted(ops, key=lambda o: str(o["id"])):
        weight = max(1, int(op.get("priority", 3)))
        objective_terms.append(weight * starts[str(op["id"])])
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 20261031
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        return {
            "status": "infeasible",
            "assignments": [],
            "solver_status": "INFEASIBLE",
            "conflicts": _named_conflicts(ops, dependencies, resources),
        }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "solver_failed",
            "assignments": [],
            "solver_status": solver.StatusName(status),
        }

    assignments = []
    for op in sorted(ops, key=lambda o: str(o["id"])):
        oid = str(op["id"])
        start_day = solver.Value(starts[oid])
        end_day = solver.Value(ends[oid])
        assigned: dict[str, str] = {}
        for rtype, req_resource in resource_of.get(oid, {}).items():
            if isinstance(req_resource, str):
                assigned[rtype] = req_resource
            else:
                for rid, lit in req_resource.items():
                    if solver.Value(lit):
                        assigned[rtype] = rid
        assignments.append(
            {
                "operation_id": oid,
                "scheduled_start": (horizon_start + dt.timedelta(days=start_day)).isoformat(),
                "scheduled_end": (horizon_start + dt.timedelta(days=end_day - 1)).isoformat(),
                "assigned_resources": assigned,
                "duration_days": intervals[oid][1],
            }
        )
    return {
        "status": "scheduled",
        "assignments": assignments,
        "solver_status": solver.StatusName(status),
    }


def _named_conflicts(
    ops: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Human-readable explanations for infeasibility (best effort, structural)."""
    conflicts: list[dict[str, Any]] = []
    # same exclusive resource demanded by operations with too-short windows
    by_resource: dict[str, list[dict[str, Any]]] = {}
    for op in ops:
        for req in op["resolved_requirements"]:
            rid = req.get("resource_id")
            if rid:
                by_resource.setdefault(str(rid), []).append(op)
    for rid, group in by_resource.items():
        if len(group) > 1:
            window = min(
                (op.get("latest_finish") or "9999-12-31") for op in group
            )
            conflicts.append(
                {
                    "code": "exclusive_resource_overdemand",
                    "resource_id": rid,
                    "operations": [op["id"] for op in group],
                    "message": f"{len(group)} operations require resource {rid} "
                    "exclusively; their windows do not allow a non-overlapping "
                    "sequence.",
                }
            )
    # precedence cycles
    graph = {str(op["id"]): [] for op in ops}
    for dep in dependencies:
        a, b = str(dep["operation_id"]), str(dep["depends_on_operation_id"])
        if a in graph and b in graph:
            graph[a].append(b)
    cycle = _find_cycle(graph)
    if cycle:
        conflicts.append(
            {
                "code": "precedence_cycle",
                "operations": cycle,
                "message": "operations form a precedence cycle — no schedule "
                "can satisfy it.",
            }
        )
    if not conflicts:
        conflicts.append(
            {
                "code": "infeasible_combination",
                "operations": [op["id"] for op in ops],
                "message": "the combination of windows, precedence and resource "
                "constraints admits no schedule.",
            }
        )
    return conflicts


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    seen: set[str] = set()
    done: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in done:
            return None
        if node in seen:
            return stack[stack.index(node):]
        seen.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            found = visit(nxt)
            if found:
                return found
        stack.pop()
        done.add(node)
        return None

    for node in graph:
        found = visit(node)
        if found:
            return found
    return None


def merge_schedule_result(
    prepared: dict[str, Any],
    solve: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge solver assignments with the unscheduled set — every operation
    appears exactly once with a status and a reason where unscheduled."""
    by_id = {str(op["id"]): op for op in operations}
    entries: list[dict[str, Any]] = []
    scheduled_ids = set()
    for a in solve.get("assignments", []):
        oid = a["operation_id"]
        scheduled_ids.add(oid)
        op = by_id[oid]
        entries.append(
            {
                "operation_id": oid,
                "title": op.get("title"),
                "status": "scheduled",
                "scheduled_start": a["scheduled_start"],
                "scheduled_end": a["scheduled_end"],
                "assigned_resources": a["assigned_resources"],
                "weather_check": "pending",
                "soil_readiness_check": "manual_required",
                "reason": None,
            }
        )
    for u in prepared["unscheduled"]:
        entries.append(
            {
                "operation_id": u["operation_id"],
                "title": u.get("title"),
                "status": "unscheduled",
                "scheduled_start": None,
                "scheduled_end": None,
                "assigned_resources": {},
                "weather_check": "pending",
                "soil_readiness_check": "manual_required",
                "reason": "; ".join(r["message"] for r in u["reasons"]),
                "reason_codes": [r["code"] for r in u["reasons"]],
            }
        )
    # any operation not covered (e.g. infeasible run) keeps its planned state
    for op in operations:
        oid = str(op["id"])
        if oid not in scheduled_ids and not any(e["operation_id"] == oid for e in entries):
            entries.append(
                {
                    "operation_id": oid,
                    "title": op.get("title"),
                    "status": "unscheduled",
                    "scheduled_start": None,
                    "scheduled_end": None,
                    "assigned_resources": {},
                    "weather_check": "pending",
                    "soil_readiness_check": "manual_required",
                    "reason": "the scheduling run " + (
                        "was infeasible" if solve.get("status") == "infeasible"
                        else "did not place this operation"
                    ),
                }
            )
    return {
        "solver": {k: solve[k] for k in ("status", "solver_status") if k in solve},
        "conflicts": solve.get("conflicts", []),
        "entries": sorted(entries, key=lambda e: (e["scheduled_start"] or "9999-12-31", str(e["operation_id"]))),
    }


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
