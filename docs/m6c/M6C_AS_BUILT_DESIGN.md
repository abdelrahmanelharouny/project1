# M6C — As-Built Design

**Milestone:** M6C — Field Management Intelligence
**Status:** implemented, tested and browser-verified (see `M6C_VERIFICATION_REPORT.md`)
**Engine identity:** `management-engine-1.0.0` / `management-methods-1.0.0`
(scheduling: `scheduling-engine-1.0.0`; cover timeline: `soil-cover-1.0.0`;
residue: `residue-ledger-1.0.0` — all versioned constants in
`app/management/contracts.py` / module headers).

## 1. Architecture

M6C is a set of modules inside the existing FastAPI service (no new
microservice), following the established patterns:

```
app/management/
  contracts.py      Pydantic practice/template schemas + engine vocabulary
  practices.py      active-pack practice & template read models (+citations)
  soil_cover.py     cover timeline engine (pure)
  cover_crops.py    cover-crop candidate engine (pure; wraps M6A water)
  residue.py        residue ledger engine (pure)
  erosion.py        erosion screening + conditional RUSLE (pure)
  scheduling.py     CP-SAT operations scheduler (only OR-Tools module here)
app/api/v1/management.py   all M6C REST endpoints
app/knowledge/packs/m6c_practices_pack.py   bundled practice/template pack
```

Migrations: `0008_field_management` (16 additive tables; downgrade-safe;
nothing existing altered — the M6B `soil_management_events` CHECK is
deliberately NOT extended).

## 2. Domain map (what each capability does)

| Capability | Engine module | Key honesty rule |
|---|---|---|
| Practice knowledge | pack `kp-m6c-practices` → `practice_definitions` | every claim cited; nothing confirmed_regional; two-sided trade-offs enforced at import |
| Operation templates | pack section → `operation_templates` | no durations/capacities/weights — farmer inputs only |
| Soil-cover timeline | `soil_cover.py` | unknown ≠ bare (property-tested); no NDVI→%cover; thresholds only when sourced |
| Cover-crop planning | `cover_crops.py` | missing evidence ≠ eligibility (eligible requires sowing+water+termination all evaluated); functions never inferred from family; no termination dates emitted |
| Residue ledger | `residue.py` | dry-matter; over-allocation surfaced hard; production never inferred from yield; nutrient content is bookkeeping, never a budget write |
| Erosion screening | `erosion.py` | process taxonomy declared; RUSLE only with 5 sourced factors + one unit convention; screening never numeric |
| Operations scheduling | `scheduling.py` | durations/resources farmer-entered; unscheduled work kept with reasons; weather pending; soil readiness manual |
| Management plan | aggregation endpoint | sections never dropped; every section carries status |

## 3. Reuse contracts (red line 1 compliance)

- Water for cover crops: `app.rotation.candidates.estimate_*` wrapping the
  versioned `app.water.curve` + FAO-33 — **one engine, one number**
  (equality-tested against a direct M6A call).
- Climate evidence: the rotation feature-run bridge, synthetic flag
  propagated into run warnings.
- Rotation compatibility: `rotation_rules` (reference → advisory; hard only
  at confirmed_regional).
- Management events: `soil_management_events` remains the agronomic ledger;
  M6C objects reference it (`soil_management_event_id` on residue flows and
  operation completions) — no second event domain.
- Practice/operation-template knowledge: the existing pack
  import/validate/activate workflow, extended with two new pack sections
  (backward-compatible checksum; tested).

## 4. Frontend

`src/components/fieldshift/management.tsx` — the **Management** tab (between
Soil and Data Passport) with six sub-views: Overview (plan), Cover Crops,
Soil Cover, Residue, Erosion, Operations. Simple/Expert toggle; status chips
render colour + text; SYNTHETIC warnings surface inline; long lists scroll
(`max-h-64 overflow-y-auto` in expert accordions); sticky footer preserved
(workspace layout untouched). Offline: the existing PWA shell applies; plan
data is read through the same API wrapper (no new sync semantics — viewing
cached plan responses, queued writes follow the existing idempotency-key
patterns on runs).

## 5. ADRs introduced (recorded here; ADR registry update in
`docs/implementation/DECISIONS_AND_ASSUMPTIONS.md`)

- **ADR-M6C-1** — practices & operation templates are knowledge-pack data
  materialized into relational rows (not a parallel registry).
- **ADR-M6C-2** — cover-crop species traits reuse `crop_traits` with a
  documented trait-code vocabulary (`COVER_CROP_TRAIT_CODES`); no values ship
  without sources.
- **ADR-M6C-3** — the M6B management-event ledger is the single event store;
  M6C adds planning artefacts that reference events.
- **ADR-M6C-4** — cover-crop water uses the M6A engine verbatim; cover demand
  is reported per candidate and is not silently merged into rotation
  allocation constraints.
- **ADR-M6C-5** — no erosion quantities without complete sourced factor
  sets; the platform ships no factor values and no DEM.
