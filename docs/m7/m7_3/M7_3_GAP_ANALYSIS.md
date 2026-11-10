# M7.3 — Phase 0 Gap Analysis (Baseline Inspection)

**Milestone:** M7.3 — Environmental Stress Transformation & Scenario-derived Feature Engine
**Inspection date:** 2025-11-02 (sandbox session)
**Inspector protocol:** repository-first — every claim below was verified against the working tree, not taken from prior reports.

---

## 1. Repository identity at inspection

| Item | Verified value | M7.3 spec claim | Verdict |
|---|---|---|---|
| Branch | `main` | `main` | ✅ match |
| HEAD commit | `8f0ca8f` ("M7.2: documentation set …") | `8f0ca8f` | ✅ match |
| Migration head | `0008_scenario_domain` (linear 0001→0008 after baseline restore) | `0008_scenario_domain` | ✅ match after repair (see §3) |
| Test suite | **581 collected; 580 passing + 1 environmental failure** | 581 passing | ⚠️ 1 network-dependent failure (see §5) |
| Working tree | contained a large **uncommitted, incomplete M6B/M6C workstream** | "clean at M7.2 completion" | ❌ mismatch — repaired (see §2) |

The spec's "historical baseline references" matched the **committed** state exactly. The working tree, however, had drifted.

## 2. Working-tree drift: uncommitted M6B/M6C workstream (material finding)

The working tree contained an **uncommitted and incomplete** Soil (M6B) + Field Management (M6C) implementation:

- Untracked: `app/soil/`, `app/management/`, `app/api/v1/soil.py`, `app/api/v1/management.py`,
  migrations `0007_soil_intelligence.py` + `0008_field_management.py`, 17 soil/management test files,
  `docs/m6b/`, `docs/m6c/`, frontend `soil.tsx` / `management.tsx`.
- Mode-only (no content) modifications to M7.0/M7.1/M7.2 docs and M7.1/M7.2 sources.
- **Defect A — branched migration history:** the M6B/M6C migrations reused revision numbers 0007/0008 with
  `down_revision = 0006_water_intelligence`, creating two heads next to M7.1/M7.2's
  `0007_field_state_foundation → 0008_scenario_domain`. `alembic upgrade head` failed
  ("Multiple head revisions are present"); the dev server could not start.
- **Defect B — unwired routers:** `soil.py` / `management.py` were never included in `app/api/v1/router.py`;
  every soil/management/cover-crop/erosion/operations/residue endpoint returned 404.
- **Defect C — contract drift:** 12 unit failures in `test_management_contracts.py`
  (practice-pack schema rejects `practices` / `operation_templates` fields).
- Net effect: **~102 failing tests** in the working tree (12 unit + ~90 integration) versus the spec's declared 581-passing baseline.

**Disposition (preservation, not destruction):** the entire uncommitted workstream was committed verbatim to a side
branch **`m6b-m6c-wip` @ `c6e533d`** (including a diagnostic merge migration `0009_merge_domain_branches` that was
created during inspection to unblock the dev server). `main` was restored to the committed M7.2 baseline.
M7.3 proceeds from `main`. The M6B/M6C workstream remains available for future resumption and is **not** part of
M7.3 scope ("M6B and M6C are not present … preserve that limitation").

## 3. Baseline repair steps performed (main)

1. `git checkout -b m6b-m6c-wip && git add -A && git commit` (preservation commit above).
2. `git checkout main` → tree clean at `8f0ca8f`.
3. Recreated the wiped sandbox runtime: `.venv` (requirements.txt), PostgreSQL+PostGIS into `db/pgenv`
   (micromamba, fresh package cache — the git-tracked cache had symlink corruption after the sandbox reset),
   `initdb -U postgres --auth=trust` into `db/pgdata`, cluster on port 5433.
4. Fresh `alembic upgrade head` on database `croptwist` → `0008_scenario_domain` (single head, linear chain). ✅
5. Demo seed `POST /api/v1/dev/seed-demo` → healthy. `/api/v1/health` → ok.

## 4. Verified reusable components (M7.3 will build on these — inspected, not assumed)

| Component | Location (verified) | Relevance to M7.3 |
|---|---|---|
| Scenario taxonomy + strict config contracts | `app/scenarios/contracts.py` | `AdjustmentSet` defines `temperature_delta_c` ([-20, +20] °C) and `precipitation_multiplier` ([0, 3]); `SCENARIO_CONFIG_SCHEMA_VERSION = "scenario-config-1.0"`; canonical serialization + SHA-256 via `sha256_of_document`. M7.3 transformations consume exactly these dimensions. |
| Scenario lifecycle / validation / lineage / compare | `app/scenarios/service.py` (1142 lines), `app/scenarios/validation.py` | `finalize_scenario`, `_resolve_parent_state` (tenant-safe), `compute_scenario_checksum`, `verify_scenario`; lifecycle `FINALIZED` is the execution gate. |
| Field State snapshots | `app/field_state/service.py`, `contracts.py`, `models.FieldState` | Immutable parent reference: `parent_snapshot_checksum`, `boundary_version`, verbatim `observation_manifest` + `observation_manifest_sha256`, `domain_availability` (soil/management `not_implemented`). |
| Observation manifest | `app/field_state/manifest.py` | `build_manifest`, `manifest_entry`, canonical JSON + SHA-256 — reused for the execution's derived-input manifest. |
| Feature engine (M4) | `app/features/engine.py::compute_feature_drafts(observations=[dict], specs, tz, hemisphere, window, levels, crop_seasons, engine_version, definition_version)` | **The recalculation path.** Accepts plain observation dicts — transformed observations can be fed without touching the `observations` table. Strategies: `daily_passthrough`, `accumulation`, `mean`, `count_days`, `dry_spell_max`, `difference`, `anomaly`, `anomaly_z`, `cv_across_years`. Daily-first: `build_daily_series` excludes non-`daily` time supports (counted, never mixed). |
| Feature catalog | `app/features/catalog.py`, `FEATURE_CATALOG_VERSION = "featurespec-2026.11.2-m6a"` | `required_variables` / `aggregation_levels` / thresholds are data — the M7.3 dependency registry is **derived from this catalog**, not duplicated. |
| DB models | `app/db/models.py` (`Scenario`, `ScenarioValidationRecord`, `FeatureRun`, `FeatureValue`, `Observation`) | Table/trigger/index idioms to follow for the execution tables. |
| API conventions | `app/api/v1/scenarios.py`, `field_states.py` | Router registration, structured errors, tenant resolution via `get_field_for_principal` / principal deps, idempotency-key replay. |
| Immutability trigger idiom | migration `0008_scenario_domain` (`enforce_scenario_immutability`) | Pattern for freezing succeeded execution runs at the database level. |

## 5. Intended-interface mismatches found (and resolutions)

| # | Mismatch | Resolution in M7.3 |
|---|---|---|
| 1 | Spec assumes a runnable baseline; working tree had ~102 failing tests | Repaired by restoring committed M7.2 baseline (see §2). Baseline re-verified: **581 collected, 580 pass, 1 env failure**. |
| 2 | `test_data_passport.py::test_same_variable_from_two_sources_gets_two_entries` fails because the upstream Open-Meteo archive answers "The service is overloaded" (network-dependent integration test; open-meteo reachable but degraded) | Classified **environmental**, not a code regression. Will be retried before final verification; documented in the verification report either way. |
| 3 | M7.2 `AdjustmentSet` also contains `precipitation_delta_mm`, `water_allocation_multiplier`, `seasonal_timing_shift_days`, `rainfall_period_shift_days` — M7.3 supports only temperature delta + precipitation multiplier | Execution eligibility rules (see EXECUTION_ARCHITECTURE): unsupported dimensions **block execution** with explicit `unsupported_transformation` findings, except `water_allocation_multiplier`, which the M7.3 spec §2 allows to ride along as a resource-constraint context assumption (never a transformed weather observation). |
| 4 | M7.2 `EvidenceClassification` has 3 values (observed / hypothetical / not_available); M7.3 §10 needs a scenario-derived class + synthetic-test distinction | The execution layer defines its own versioned evidence vocabulary (`scenario_derived_transformed`, plus source-class passthrough and `is_synthetic` flags) — the M7.2 enum is NOT extended, so existing contracts and CHECK constraints stay frozen. |
| 5 | Engine is daily-first (monthly/pentadal sources are excluded from daily series by design) | Transformation layer transforms observations at their **native support**; scenario feature recalculation covers the daily-source feature set the engine actually supports; monthly/pentad-source features are recorded `not_evaluated` with an explicit engine-limitation reason (documented in VARIABLE_COMPATIBILITY). |
| 6 | ET0: `reference_et0` is an observed input variable; no humidity/radiation/wind-based recalculation exists | All ET0-dependent features (`reference_et0_total_*`, `water_balance_p_minus_et0_monthly`) are excluded from scenario feature sets and reported `not_evaluated` — baseline ET0 is never reused as scenario-derived ET0 (spec §7). |
| 7 | Sandbox reset wiped `.venv`, `db/pgenv`, `db/pgdata` | Recreated (§3). One-time environment repair, no repo changes required. |

## 6. Decisions inherited from inspection

- Execution gate: **only `finalized` scenarios** execute (finalization freezes the definition and checksum; a
  `conditionally_valid` verdict is carried inside `validation_summary` of the finalized row). This satisfies
  M7.3 §8 without executing mutable definitions.
- Baseline features for comparison are recomputed **in-process from the parent manifest's original
  observations** over the scenario window (same engine/catalog version as the scenario pass) — the parent
  `feature_runs` rows are never modified.
- New tables are separate derived structures (`scenario_execution_runs`, `scenario_derived_observations`,
  `scenario_derived_features`); nothing scenario-derived is inserted into `observations` / `feature_runs`.
- Migration `0009_scenario_execution` extends the linear chain on `main` (the merge migration exists only on
  the `m6b-m6c-wip` branch, where the branch topology lives).

## 7. Verdict

**GO for M7.3 implementation** on `main` @ `8f0ca8f` after the repairs documented above. All interfaces the
M7.3 spec depends on (scenario contracts, field state pins, manifest, feature engine, API idioms) are present,
versioned, and verified in the tree.
