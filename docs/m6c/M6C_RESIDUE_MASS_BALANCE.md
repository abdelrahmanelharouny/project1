# M6C — Residue Mass Balance (as-built, Increment 5)

**Status:** implemented and tested (`test_residue_ledger.py` — 14 unit tests
with hand arithmetic + 40 randomized property trials;
`test_residue_api.py` — 11 integration tests).

## 1. Ledger model

- `residue_records` — one row per field/season/crop. `produced_dm_kg` with
  `production_status ∈ {measured, farmer_reported, coefficient_estimate,
  missing}`; `coefficient_estimate` REQUIRES provenance
  (`coefficient`, `basis`, `source_reference`) — an unsourced ratio is
  rejected over HTTP (tested). `harvested_product_dm_kg` is tracked
  separately: the product and the residue are distinct quantities and the
  ledger never derives one from the other (a record with a harvested mass
  but no production claim stays `production_unknown` — tested).
- `residue_flow_events` — fates against a record:
  `retained_surface | incorporated | removed_baled | grazed | burned |
  other_loss | unknown`, each with `dm_kg` (or `fresh_kg` +
  `dry_matter_fraction`), `dm_kg_status`, optional
  `soil_management_event_id` (provenance link into the M6B ledger — tested),
  evidence class.
- `residue_quality_measurements` — C fraction, N %, C:N, lignin, per record,
  evidence-classed. Absent quality ⇒ no nutrient numbers at all.

## 2. Mass-balance contract (the acceptance core)

Per record:
`unaccounted = produced − Σ(flows)`, and:

| Situation | Ledger says | Never does |
|---|---|---|
| Σ flows ≤ produced | `balanced`, unaccounted ≥ 0 | — |
| Σ flows > produced | **`over_allocated`** with the negative unaccounted surfaced + field warning "never absorbed" | clamp, drop flows, silently rebalance |
| produced unknown | `production_unknown`, unaccounted null; flows still listed with their own statuses | treat production as zero |
| flow mass unknown | counted in `flows_with_unknown_mass`; excluded from the sum, never zero-filled | assume 0 |

Property-tested over randomized records/flows (40 trials): statuses and sums
consistent, unaccounted ≥ 0 unless `over_allocated`, deterministic output.

## 3. Units and conversions

- Canonical basis: **dry matter, kg**.
- t→kg exact (× 1000). fresh→dry requires an explicit
  `dry_matter_fraction ∈ (0, 1]` — missing fraction ⇒ refusal ("never
  assumed", tested); the converted flow's status is disclosed.
- API rejects negative masses and unknown flow types with 422.

## 4. Nutrient / carbon content — bookkeeping, not budgeting

Derived arithmetic (tested by hand: N 1.2 % × 3000 kg = **36.0 kg N**;
C 40 % → 1.2 t C input; C:N derived 40/1.2 = **33.33** when the ratio itself
is absent) is reported in `derived` with a standing note:

> inputs are NOT counted in the M6B nutrient budget (which reads its own
> `nutrient_applications` ledger) and make NO SOC-sequestration claim —
> carbon input ≠ stable SOC stock change.

This is the no-double-counting guarantee: M6B budgets are unchanged by
residue ledger contents (nothing in M6C writes nutrient applications);
consuming residue-N in a budget is an explicit, provenance-carrying step for
a future milestone/farmer workflow, out of M6C scope by design.

## 5. What is deliberately absent (red lines)

- **No universal residue coefficient / harvest index** — production arrives
  only as measured mass, a farmer figure, or a provenance-carrying
  coefficient.
- **No universal decomposition constant / C:N threshold** — quality values
  are stored; none are interpreted against a generic benchmark.
- **No automatic M6B writes** — linkage is by reference
  (`soil_management_event_id`) and by documented consumption, never by
  silently injecting rows into another domain.

## 6. API

- `POST /fields/{id}/residue-records` (status/provenance/mass consistency
  validated), `POST /residue-records/{id}/flows`,
  `POST /residue-records/{id}/quality`,
  `GET /fields/{id}/residue-ledger` — per-record ledgers, field totals
  (known-production only, with the exclusion basis string), warnings,
  method description (`residue-ledger-1.0.0`). Cross-tenant writes → 403
  (tested).
