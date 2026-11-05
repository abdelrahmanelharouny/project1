# M7.4 — Gap Analysis (Phase 0 repository findings)

**Inspected at:** 2026-11-02, before any implementation change.

| Expected baseline (previous report) | Actually found | Verdict |
|---|---|---|
| Branch `main` @ M7.3 commit `13c31d63` | `main` @ `13c31d63` ("M7.3: environmental stress transformation & scenario execution engine …") | match |
| Working tree clean | clean (`git status --short` empty) | match |
| Migration head `0009_scenario_execution` (code + DB) | 0001→0009 chain; `alembic current` = `0009_scenario_execution (head)` | match |
| Backend tests 657 passed | 657 collected; run in chunks: 360 unit + 72 contract + 225 integration, **0 failures** | match |
| `m6b-m6c-wip` branch preserved, untouched | present; never checked out; not merged | match |
| M7.3 execution implementation present | `app/scenario_execution/` (contracts 226 L, transformations 324 L, dependency_graph 157 L, service 1043 L); 7 APIs registered; trigger-frozen runs | match |
| M7.3 docs incl. limitations + verification report | 13 documents in `docs/m7/m7_3/` incl. `M7_3_LIMITATIONS_AND_BACKLOG.md` + `M7_3_VERIFICATION_REPORT.md` | match |
| Frontend: Scenarios tab + execution workspace | `workspace.tsx` 9 tabs; `scenarios.tsx` embeds `scenario-execution.tsx`; API client + types complete | match |
| Dev DB smoke data | 1 user (demo), 3 finalized scenarios, 1 `completed_with_limitations` run, 1639 derived feature rows | match |

**Discrepancies: none.** No adaptation was required; the expected baseline was reproduced exactly.

## Reused functions (exact contracts — nothing duplicated)

- `app.scenario_execution.transformations.apply_transformations` / `transform_temperature` / `transform_precipitation` (pure, unit-gated)
- `app.scenario_execution.service._manifest_observations` (BY-VALUE manifest resolution with hard window boundaries), `_as_engine_observation`, `_run_engine_pass`
- `app.scenario_execution.dependency_graph.plan_scenario_features` / `recalculate_specs` / `FEATURE_DEPENDENCIES`
- `app.features.engine.compute_feature_drafts` + `app.features.catalog` (M4 engine + versions)
- `app.scenario_execution.contracts.canonical_value` (6-dp checksum canon), `TransformationCode`, run/evidence vocabularies
- `app.field_state.manifest.sha256_of_document`, `app.scenarios.contracts.scenario_checksum_payload` / `compute_scenario_checksum`
- `execution_service.verify_execution` (reused as an eligibility precondition)
