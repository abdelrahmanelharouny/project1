# M6C — Operations Scheduling Model (as-built, Increment 7)

**Status:** implemented and tested (`test_operations_scheduling.py` — 15 unit
tests with hand-checked golden schedules; `test_operations_api.py` — 9
integration tests).

## 1. Model

CP-SAT, **day granularity**, explicit horizon (`operation_schedule_runs`
snapshot; single OR-Tools module in `app.management.scheduling`, following
the rotation adapter's determinism contract: `num_search_workers=1`,
`random_seed=20261031`, ≤ 10 s; identical inputs → identical schedule —
tested).

| Constraint | Form |
|---|---|
| Duration | fixed days per operation (`duration_days`, or hours ÷ farmer-supplied `hours_per_workday`) |
| Windows | `start ≥ earliest_start`, `end ≤ latest_finish` (calendar windows from the crop calendar when the crop has one) |
| Precedence | finish→start (+lag) from `operation_dependencies` (template predecessors on generation; farmer-added edges allowed) |
| Resources | required type or explicit id; type-only requirements are assigned by the solver via exactly-one choice among the farm's resources of that type; per-resource `AddNoOverlap` over optional intervals |
| Availability | assigned intervals must lie inside one declared availability window (farmer-entered) |

Objective: priority-weighted earliness (higher priority ⇒ earlier), with a
deterministic operation-id tie-break.

## 2. Unscheduled work is never dropped

`prepare_operations` partitions operations into schedulable + `unscheduled`
with named reason codes — `no_duration`, `no_workday_length` (hours supplied
but `hours_per_workday` not provided — a workday length is never assumed),
`no_resource_of_type` (capacity never assumed), `unknown_resource`,
`window_too_short_for_duration`, `resource_requirement_incomplete`, and
transitively `predecessor_unschedulable`. The merged run result contains
**every** operation exactly once with a status and reason (tested), and the
solver's infeasibility names conflicts (`exclusive_resource_overdemand`,
`precedence_cycle`, or an explicit `infeasible_combination`) — never a silent
relaxation.

## 3. What is deliberately unknown (spec §8.5/8.6 red lines)

- **Weather:** the platform has no forecast provider; historical climate is
  never used as a forecast. Every scheduled entry carries
  `weather_check: "pending"`; the run's `not_evaluated` states why.
- **Soil trafficability:** no universal moisture threshold exists; entries
  carry `soil_readiness_check: "manual_required"`.
- **Durations:** templates carry none; generated operations are `planned`
  with unknown duration until the farmer supplies one (tested: a generate →
  schedule run without durations reports everything unscheduled with
  `no_duration`).

## 4. Operation generation (templates → planned operations)

`POST /fields/{id}/operations/generate` matches ACTIVE-pack templates to the
crop's category/code (crop category resolved from the ACTIVE knowledge pack),
windows from the crop's calendar window (`reference_synthesized` evidence
surfaced — maize plants 2027-04-15.. in the golden test), and precedence from
the templates' cited `typical_predecessors`. No other operation is invented
("Do not generate every possible operation for every crop" — spraying only
exists as a template the farmer can invoke manually).

## 5. Completion logging and the event ledger

`PATCH /operations/{id}` performs status transitions
(`planned|scheduled|started|completed|delayed|cancelled|blocked`).
Completion links `completed_soil_management_event_id` — validated to belong
to the same field (422 otherwise, tested) — so `soil_management_events`
remains the single agronomic event ledger and the cover timeline consumes the
completed reality (cross-module test).

## 6. API surface

`POST/GET /farms/{farm_id}/resources` · `POST /fields/{id}/operations` ·
`POST /fields/{id}/operations/generate` · `GET /fields/{id}/operations`
(with the dependency map) · `PATCH /operations/{id}` ·
`POST /fields/{id}/operation-schedule-runs` (immutable snapshot, checksum,
idempotency; scheduled entries written back to operations with
`schedule_run_id` provenance) · `GET /operation-schedule-runs/{run_id}` ·
`GET /fields/{id}/resource-conflicts` (currently scheduled same-resource
overlaps). Tenant isolation 403s tested on resources.

## 7. Known limitations (documented)

Labor is modelled as exclusive crew units (capacity-1 non-overlap) —
multi-crew `Cumulative` capacity is deferred to the research backlog; travel
times between fields are not modelled (single-field scheduling); the
solver's assignments are proposals pending the manual checks above.
