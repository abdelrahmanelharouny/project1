# M6C — Test & Benchmark Report

**Suite total (fresh full run, this session): 742 tests — 0 failures,
0 errors, 1 skipped (a conditional synthetic-ingestion path), 305.9 s,
exit 0.** M6A/M6B baseline was 566; **M6C adds 176 tests.**

Frontend lint: clean (`bun run lint`, exit 0).

## 1. Test inventory by increment

| Area | Files | Count | Highlights |
|---|---|---|---|
| Increment 2 — practice knowledge | `test_management_contracts.py` (unit), `test_management_knowledge_api.py` (integration) | 15 + 9 | every claim cites a source; no numeric parameters in the pack (structural scan); two-sided trade-offs; no universal termination lead time; regional basis required; template predecessor/crop resolution; **checksum backward compatibility** (pre-M6C packs byte-identical); draft/active/retired gating; idempotent import + checksum conflict |
| Increment 3 — soil cover | `test_soil_cover_engine.py` (unit), `test_soil_cover_api.py` (integration) | 18 + 10 | hand-computed goldens (107-day crop interval; 53/26/113-day residue intervals); unknown ≠ bare; fraction>0 ⇒ protective; overlap never double-counts; longest-bare hand case; thresholds structural absence; **30 randomized partition trials**; determinism; API vocab/fraction/index validation; tenant 403 |
| Increment 4 — cover crops | `test_cover_crop_engine.py` (unit), `test_cover_crop_api.py` (integration) | 18 + 11 | **independent water golden** (uniform Kc≡1.0, 120 d, 4 mm/d ⇒ ETc 480.0 mm); missing evidence ⇒ conditional (never eligible); legume flag without trait claims nothing; rotation rules crop/family/region-scoped, reference=advisory vs confirmed=hard; **engine emits no termination dates**; eligible ⇒ all critical dimensions evaluated (property); real-KB plan (faba_bean conditional with deliberate Kc gap); reproducible checksums + idempotency; mixture ≤1 rule; cross-module: plan item ⇒ 107 timeline days |
| Increment 5 — residue | `test_residue_ledger.py` (unit), `test_residue_api.py` (integration) | 14 + 11 | hand balance (5000−4500=500); over-allocation surfaced negative, never clamped; production-unknown excluded from totals; t→kg exact; fresh→dry needs fraction (refusal otherwise); coefficient provenance gate; **no default residue ratio** (harvested product ⇒ still production-unknown); N content 36.0 kg hand case; C:N derived 33.33; **40 randomized no-silent-negative trials**; provenance link to management events; tenant 403 |
| Increment 6 — erosion | `test_erosion_screening.py` (unit), `test_erosion_api.py` (integration) | 15 + 7 | **RUSLE golden A=3.75**; partial factor set refused with names; unsourced factor refused; mixed conventions refused; **no-factors message contains no numbers** (regex); scope disclosures (no DEM / LS supplied); screening never numeric; rainfall amount ≠ erosivity; observed signs separated; alternatives cited & unranked; snapshot reproducibility; cover-linkage (3 bare observations ⇒ exposed-soil concern) |
| Increment 7 — operations | `test_operations_scheduling.py` (unit), `test_operations_api.py` (integration) | 15 + 9 | hand-checked precedence (a: Sep 1–2, b: Sep 3); same-machine non-overlap; window bounds; unscheduled reason codes incl. `no_workday_length`; transitive predecessor propagation; **nothing silently dropped** (merged entries cover every op); availability windows; infeasible names conflicts; two-tractor choice; determinism; weather/soil check labels; template generation with calendar windows (maize 2027-04-15); write-back provenance; completion link field-scoped (422 otherwise) |
| Increment 8 — management plans | `test_management_plan_api.py` | 5 | empty-field honesty (all sections present, statuses honest, checks reference gaps); populated plan (107 protective days; counts); reproducible checksums; tenant 403; feedback validation |
| Increment 9 — cross-module | `test_cross_module_integration.py` | 14 | **cover engine water ≡ direct M6A call**; residue content never leaks into M6B budgets; evidence classes survive timeline/RS paths; synthetic separation; **8-write + 4-read cross-tenant 403 sweep**; structural immutability (no PATCH/DELETE on snapshots); recomputation ⇒ new id, identical checksum |

## 2. Independent worked examples used (not implementation outputs)

- Cover water: uniform-curve ETc 480 mm (hand arithmetic; monthly totals are
  calendar-month quantities scaled by in-season fraction — documented).
- RUSLE: A = 100 × 0.25 × 1.0 × 0.3 × 0.5 = **3.75**.
- Residue: 5000 − (3000 + 1500) = 500 kg unaccounted; N 1.2 % × 3000 kg =
  36.0 kg; C 40 % ⇒ 1.2 t; C:N 40/1.2 = 33.33; 8500 kg fresh × 0.85 = 7225 kg DM.
- Cover timeline: 2026-05-01→2026-08-15 = 107 days; residue 09-10→11-01 = 53.
- Operations: precedence chain start day arithmetic (Sep 1–2 → Sep 3).

## 3. Property / metamorphic coverage

- cover timeline: 30 randomized interval sets — partition + bounds + no negatives
- residue: 40 randomized ledgers — over-allocation detection, no silent negatives
- scheduling: determinism (identical inputs → identical schedule), non-overlap, precedence
- honesty metamorphs: missing water data never yields a water-safe/eligible
  classification; increasing cover duration cannot move an engine-generated
  termination (none exists); RUSLE without factors returns no numeric estimate;
  equivalent mass units produce equivalent ledger quantities (t↔kg, fresh+fraction)

## 4. Migration tests

`test_migrations.py` exercises upgrade→downgrade→upgrade each run; the suite
rebuilds `croptwist_test` from scratch via conftest (0001→0008), so 0008's
16 tables and their CHECK constraints are validated on every run.
