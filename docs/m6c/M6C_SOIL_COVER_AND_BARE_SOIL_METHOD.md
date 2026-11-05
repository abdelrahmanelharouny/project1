# M6C — Soil Cover & Bare-Soil Method (as-built, Increment 3)

**Status:** implemented and tested (`test_soil_cover_engine.py` — 18 unit tests
with hand-computed golden values + 30 randomized property trials;
`test_soil_cover_api.py` — 10 integration tests).

## 1. What the engine does

`app/management/soil_cover.py` builds a deterministic, day-level cover
timeline for an explicit window from the evidence that exists — nothing else:

| Input source | Produces | Evidence class |
|---|---|---|
| `crop_history` (sowing+harvest dates) | `living_main_crop` intervals | row's `evidence_class` (farmer_reported_record by default) |
| `cover_crop_plan_items` (sowing→termination) | `living_cover_crop` intervals | row's `evidence_class` |
| `soil_management_events` `residue_retention` | `surface_residue` interval, open until the next `residue_removal`/`tillage` event or window end (openness disclosed) | farmer_reported_record |
| `soil_management_events` `soil_amendment{mulch:true}` | `mulch` interval (same open/close rule) | farmer_reported_record |
| `soil_cover_observations` | dated state + optional measured fraction / RS index | row's `evidence_class` (`remote_sensing_estimate` enforced for index rows) |

## 2. Day classification (the honest core)

For each day in the window:

1. `protective` — any of `living_main_crop | living_cover_crop |
   surface_residue | mulch` applies, OR an observation reports a measured
   `cover_fraction > 0`.
2. `bare` — otherwise, an explicit bare observation (state `bare` or measured
   `cover_fraction == 0`).
3. `unknown` — otherwise. **Unknown is the absence of evidence, never bare.**

Invariant (property-tested over randomized interval sets):
`protective + bare + unknown == window_days`, counts never negative, fraction
∈ [0, 1], timeline dates bounded by the window.

Golden hand-arithmetic cases: maize 2026-05-01→2026-08-15 = **107** protective
days; residue opened 2026-09-10, removed 2026-11-01 = **53** residue days;
tillage closing = **26**; open-at-window-end = **113** with an explicit
`residue_interval_open_at_window_end` evidence note.

## 3. What is deliberately NOT done

- **No universal cover threshold / pass-fail.** The response carries a
  `thresholds: {applicable: [], note: …}` section; metrics ship without
  verdicts. Thresholds can only arrive as versioned, region-scoped knowledge
  (spec §5.3). Structural test asserts no day and no metric key carries a
  verdict beyond the three evidence states.
- **No NDVI → % cover conversion.** Index readings are stored with
  `index_type` + `index_value` + provider metadata and
  `evidence_class=remote_sensing_estimate`; the timeline displays them as
  evidence, never as a cover percentage (no validated regional model exists).
- **No assumptions from single-endpoint crops.** A crop history row with a
  sowing date but no harvest date contributes nothing (never an assumed
  interval).
- **No inferred residue fates.** After a tillage/removal event the field is
  `unknown` until the next evidence — an event *ends* a state; it does not
  invent the next one.

## 4. Metrics

`days_protective_cover`, `days_known_bare`, `days_unknown`,
`protective_cover_fraction` (= protective / total, with the basis string
explaining unknown is separated, never merged into bare),
`longest_bare_interval_days` + interval dates (only from known-bare days),
`state_day_counts` per state, `month_breakdown` (local calendar months,
partition-consistent), `window_days`.

## 5. API

- `POST /fields/{id}/soil-cover/observations` — validated CRUD
  (state/basis vocab; fraction ∈ [0,1] rejected outside, never clamped; index
  needs type+value together; `remote_sensing_index` basis forces
  `remote_sensing_estimate` evidence).
- `GET /fields/{id}/soil-cover/observations` — last 365 rows.
- `GET /fields/{id}/soil-cover/timeline?window_start&window_end` — full
  timeline + metrics + method description + thresholds + inputs summary
  (≤ ~2 years per request).
- `GET /fields/{id}/soil-cover/metrics` — the same computation, metrics view.
- All routes use `get_field_for_principal` (cross-tenant → 403, tested).

## 6. Timezone note

The timeline is computed over **local calendar dates** (the same basis as
`crop_history` and the management ledger), so no UTC/day-boundary conversion
is involved in interval math. Farm timezone and hemisphere remain relevant for
seasonal breakdowns in the management plan layer (Increment 8), which reuses
`app.features.calendar`.
