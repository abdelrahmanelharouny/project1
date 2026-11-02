# M7.0 — Cross-Domain Integration Map

**Inspection date:** 2026-11-01 · **Scope:** every material dependency between the implemented domains (M1–M6A state).
**Method:** actual code paths read end-to-end; a connection is classified **Verified integration** only when a live code path *and* a test exercise it. Two tables sharing `field_id` is **not** counted as integration.

---

## 1. Dependency graph (as-built)

```
                    ┌──────────────────────── identity/tenancy (users, organizations, memberships) ───────────────────────┐
                    │            application-layer guards on every route (no RLS)                                          │
                    ▼                                                                                                       │
  farms ──1:N── fields ──1:N── field_boundary_versions                    (boundary versions referenced by NOTHING)          │
    │             │ ╲                                                                                                      │
    │             │  ╲──1:N── ingestion_jobs ──1:N── observations ──N:1── dataset_products ──N:1── data_sources              │
    │             │            (natural-key dedupe; is_synthetic; evidence_class; quality flags)     (license/attribution)  │
    │             │                                                                                                        │
    │             └──1:N── feature_runs ──1:N── feature_values                                                                │
    │                        │  (source_selection pins dataset_product id+code+version+is_synthetic;                          │
    │                        │   provenance.observation_ids ← observations [capped 400]; per-value checksum)                  │
    │                        │                                                                                                │
    │             ┌──────────┼──────────────────────────────┬─────────────────────────────┐                                   │
    │             ▼          ▼                              ▼                             ▼                                   │
    │      crop-candidates   rotation_runs ◀──1:N── rotation_strategies   water_plans        data-passport                      │
    │        (M5 read-model)   │  ▲                             │    ▲                        (per variable+product)           │
    │                          │  │                             │    │                                                            │
    │   crop_history ──────────┘  │                             │    └── farm_constraints (water_allocation_m3_per_season)           │
    │   (ids snapshotted)         │                             │        (mutable row, read at run time)                             │
    │                             │                             │                                                                    │
    │   knowledge_packs (draft/active/retired, checksum, content JSONB) ◀─ knowledge_pack_refs ─┘ (pack_id+code+version+checksum)│
    │     ├─ crops/crop_traits/crop_calendar_windows/crop_water_parameters/rotation_rules/agronomist_reviews                      │
    │     └─ knowledge_sources (citations)                                                                                        │
    └── audit_events (farm/field/boundary/knowledge writes; actor+org snapshots; org column has NO FK)                             │
```

M6B (soil health) and M6C (management) domains are absent; their only proxies are SoilGrids/farmer-CSV soil observations, knowledge traits, and two rotation criteria — shown in §2 as PROXY rows.

## 2. Connection register

Classification legend: **V** = Verified integration (code path + test) · **P** = Partial integration (code path exists, gaps documented) · **M** = Manual workflow · **N** = No integration · **U** = Unknown.

| ID | Source → Target | DB relationship | API / service interface | Input contract | Output contract | Version refs | Provenance | Tenant | Tests | Class |
|---|---|---|---|---|---|---|---|---|---|---|
| INT-01 | fields → farms | `fields.farm_id` FK CASCADE | `POST /farms/{farm_id}/fields` | GeoJSON boundary | Field payload incl. `area_ha`, `postgis_geodesic_area_ha`, `boundary_version` | — (field is mutable identity) | audit_events on writes | membership guard | `test_farms_fields_crud.py` | **V** |
| INT-02 | observations → dataset_products → data_sources | `observations.dataset_product_id` FK RESTRICT | ingestion services | `CanonicalObservation` (UTC, missing≠zero) | rows with evidence_class, quality, is_synthetic | `dataset_products.product_version`; `observations.processing_version` | `ingestion_job_id` + metadata JSONB + file_sha256 (imports) | via field | `test_ingestion.py`, provider contracts | **V** |
| INT-03 | feature_runs → observations | **No FK.** Pinned via `source_selection` JSONB (product id+code+version+is_synthetic) + `provenance.observation_ids` per value (cap 400) | `POST /fields/{id}/feature-runs` → `app/features/service.resolve_source_selection` | period, aggregation levels, crop seasons, tz override | values with period bounds, coverage, quality, baseline_reference, provenance, per-value checksum | `feature_engine_version` `feature-engine-1.0.0`, `feature_catalog_version` `featurespec-2026.11.2-m6a` | per-value provenance JSONB; run warnings; SYNTHETIC flag | via field | `test_feature_runs.py` (never-blend :263, reproducibility :233) | **P** — observation set not fully pinned; no run-level checksum |
| INT-04 | feature_runs → crop candidates (climate bridge) | none (run id chosen at request time; latest-succeeded default) | `app/rotation/service._pick_evidence_run` (shared with water) | month-of-year climatology from values | per-candidate climate reasons + water screening estimate; `feature_run_ids` snapshotted on runs | run ids + engine versions stored | ≥90% month coverage else unevaluated; synthetic propagated into reasons | via field | `test_rotation_core.py` candidates; `test_rotation_runs.py` full run | **V** (with mutable-latest caveat) |
| INT-05 | knowledge_packs → candidates/rotation | no FK at run time; **by-value refs** `rotation_runs.knowledge_pack_refs` | `load_knowledge` reads `status='active'`; `pack_ref()` snapshot | active pack rows | candidate statuses with cited `source_refs`; criteria source_refs | `pack_version` + `checksum_sha256` per ref | citations deduped into explanations | platform-wide (not tenant) | `test_knowledge_contracts.py`, `test_rotation_runs.py:115` | **V** |
| INT-06 | crop_history → rotation_runs | no FK; `crop_history_ids` snapshot + rule lookback reads rows at run time | `POST/GET crop-history`, runs read history | farmer-reported rows (`evidence_class=farmer_reported_record`) | history-boundary constraint checks | ids snapshotted | rows immutable (no update endpoint) | via field | `test_rotation_runs.py::TestCropHistory`, tenant test :90 | **V** |
| INT-07 | water_plans → feature_runs | no FK; `feature_run_ids` JSONB + `sources[type=climate_evidence].feature_run_id` | `_pick_evidence_run` (latest-succeeded default) | monthly ET0/precip climatology | ETc/Pe/ladder results with per-month evidence | engine+methods versions + run ids | per-month `precip_evidence_missing`; SYNTHETIC banner | via field | `test_water_api.py` lifecycle | **V** (mutable-latest caveat) |
| INT-08 | water_plans → knowledge (Kc, Zr, p) | by-value refs `knowledge_pack_refs`; parameters read from active pack | `water.knowledge.water_knowledge_for_crop` | crop_code | curve or explicit gap reasons ("never guessed") | pack version + checksum in refs + plan checksum payload | per-source citations in plan `sources` | platform-wide | `test_water_core.py` (faba_bean gap), `test_water_api.py:225` | **V** |
| INT-09 | water_plans → rotation (allocation constraint) | none — **value coupling only**: rotation candidates' NIR/ETc estimates (same shared arithmetic) feed CP-SAT coefficients | `optimizer.py:363-406`; `constraints.check_water_allocation` | water_allocation_m3 (request or `farm_constraints` row) | allocation check + named infeasibility | engine versions on both sides | demand basis disclosed ("NIR" vs "ETc conservative fallback") | via field | `test_water_rotation_integration.py:163-240` | **V** |
| INT-10 | rotation_runs → water_plans | **NONE.** `water_plans` has no rotation_run_id/strategy_id column; `crop_assignments` are caller-supplied JSONB | none | — | — | — | binding is by convention (human copies crop sequence) | — | no test (nothing to test) | **N** |
| INT-11 | farm_constraints → rotation/water | mutable row read at run time (`farm_constraints.water_allocation_m3_per_season`) | read inside services | farmer-supplied numbers | allocation inputs | **no versioning, no snapshot of the row** | none (row is current-state) | via farm | indirectly via allocation tests | **P** (unversioned mutable input) |
| INT-12 | fields/boundary → observations & rasters | none (field_id only); ingestion resolves **current** boundary at fetch (`ingestion/service.py:266-275`) | map + ingestion geometry | GeoJSON (4326) | extracted values | **boundary_version NOT recorded on any result** | none for geometry | via field | geometry tests only | **P** — historical results are not pinned to the boundary they used |
| INT-13 | passport → observations+products | read-model over observations/dataset_products | `GET /fields/{id}/data-passport` | — | per-(variable,product) coverage, readiness gates, attribution | product_version + processing_version | per-entry synthetic/real identity separation | via field | `test_data_passport.py` | **V** |
| INT-14 | audit_events → writes | `audit_events` (actor_id, **organization_id no FK**, before/after JSONB) | written by farms/fields/boundary/knowledge import/activate services | action payloads | trail rows | snapshots embed current values | before/after snapshots | actor+org recorded (F-14) | implicit in CRUD tests | **V** |
| INT-15 | soil evidence → consumers (SoilGrids/farmer CSV → candidates & water PTF) | ordinary observations (`global_soil_prediction`, `farmer_reported_record`) | latest non-null value per variable read at run time | trait/observation values | pH reasons, PTF soil inputs | PTF version `saxton-rawls-2006-ptf-1.0.0` recorded in methods; SoilGrids prediction-class notes | evidence classes surfaced in outputs | via field | `test_rotation_core.py` pH evidence; `test_water_api.py` PTF/farmer | **P** — no assessment run, no measurement dates model, no layering |
| INT-16 | management domain → anything | **no tables, no code** | — | — | — | — | — | — | — | **N** (M6C not implemented) |
| INT-17 | knowledge retirement → active-set semantics | `knowledge_packs.status` lifecycle; `seed_default_packs` retires superseded versions | import/activate endpoints | pack docs | deterministic active set (F-9) | version+checksum | retirement keeps content JSONB | platform-wide | **no test for retirement path** | **P** |

## 3. What the map means for M7

1. **Pinned-by-value, not by-FK** is the platform's integration idiom (INT-03/05/06/07/08). A Field State / Scenario layer can reuse this idiom (JSONB refs + checksums) without new FK machinery — but for full reproducibility it must additionally pin the *observation set*, which today only survives capped inside per-value provenance (INT-03 gap).
2. **Rotation ↔ Water is coupled only through shared arithmetic and caller-supplied assignments** (INT-09/10). Multi-scenario rotation evaluation that also needs water results per scenario must decide whether to compute water inside the rotation run or to add an explicit plan link — currently nothing connects them.
3. **The mutable inputs that would silently change scenario replays are exactly three**: latest-succeeded feature run selection (INT-04/07), the live observation set behind a re-run (INT-03), and `farm_constraints` rows (INT-11). All three are addressable by pinning (ids + checksums) rather than redesign.
4. **Boundary versioning is a dangling dimension** (INT-12): version rows exist and are append-only, but no result records which version it used. This is the single most important schema gap for a trustworthy Field State.
5. **Soil and Management are absent domains** (INT-15 partial proxy, INT-16 none): Field State and Scenario designs must treat them as explicit `NOT_IMPLEMENTED` dimensions or gate M7 increments on M6B/M6C scope decisions.
