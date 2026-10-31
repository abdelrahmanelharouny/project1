# Milestone 5 — Implementation Gap Analysis (2026-10-31)

Fact base: full repository inspection (models, features engine, passport, APIs,
tests, frontend) + regression suite re-run on a freshly rebuilt sandbox
(PostgreSQL 16.10 + PostGIS 3.5.0 re-initialized, API venv recreated with
`ortools==9.14.6206` added) — **243/244 tests state confirmed: 243 passed**.

## What already exists (verified)

| Capability | Where | Usable by M5 |
|---|---|---|
| Canonical observations w/ evidence_class + provenance | `observations`, providers | candidate-gen climate/soil evidence |
| Versioned feature catalog + reproducible runs (M4) | `feature_definitions`, `feature_runs`, `feature_values` | season climate aggregates (P, Tmean, Tmax, hot days, ET0) w/ coverage + synthetic flag |
| Data Passport honest readiness | `app/passport/service.py` | rotation rule must become **dynamic** |
| `farm_constraints` table (code/value/hard flag/source) | models | water allocation, equipment, market exclusions |
| OR-Tools 9.14.6206 installed | `.venv` | CP-SAT adapter |
| Frontend transport/hooks/tabs | `src/lib/api.ts`, hooks, workspace | new "Rotation" tab reuses field picker, badges, job pattern |

## Gaps

- **G1 Knowledge foundation** — no crops/families/varieties/traits/calendars/
  water-parameter tables, no knowledge sources, no pack versioning or import
  workflow (Master §17.5, §17.13).
- **G2 Rotation relationship knowledge** — no rules (breaks, host–pathogen,
  succession) with region scope + validation status.
- **G3 Crop history** — no `crop_history` (Master §17.8); baseline rotation
  cannot be reconstructed.
- **G4 Farmer preferences** — no `farmer_preferences` (Master §17.7); custom
  strategy weights have nowhere to live.
- **G5 Candidate generation** — nothing evaluates crops per season with
  eligible / conditionally eligible / excluded / unevaluated semantics.
- **G6 Constraint model + optimizer** — no solver-independent constraint layer,
  no CP-SAT adapter, no run persistence/snapshots.
- **G7 Pareto evaluation** — nothing.
- **G8 Explainability** — nothing criterion-level.
- **G9 Passport staleness** — `rotation_optimization` lists `feature_runs` and
  `constraint_solver` as "later milestone"; after M4/M5 these exist. The rule
  must query reality, and the test asserting `constraint_solver` missing must be
  updated to the new honest semantics.
- **G10 APIs/UI** — no knowledge or rotation endpoints, no UI.

## Honesty decisions for the seed knowledge pack

1. Only attributes with a citable published source are shipped:
   - **FAO-56 (Allen et al. 1998)** — Kc single values (Table 11/12), stage
     lengths, total duration, effective rooting depth (Table 22).
   - **FAO EcoCrop** — coarse ecological amplitude (temperature, precipitation,
     pH) stored as ranges with explicit low/high + confidence.
   - **Agrios (2005), Plant Pathology 5th ed.** — host–pathogen rationale for
     rotation breaks (soilborne pathogens persist; related hosts share them).
   - **Herridge, Peoples & Boddey (2008), Plant and Soil 311:1–18** — legume
     biological N fixation.
2. Digitization honesty: pack values are `validation_status="reference"`,
   `confidence` carried per trait, `digitization_note` on the pack — a
   reviewed/local-validated state can only be reached through the review
   workflow, never claimed by import.
3. Missing attributes stay absent: e.g. no invented drought-tolerance scores;
   faba bean ships **without** Kc values (water criteria → unevaluated, never
   guessed).
4. Rotation rules ship as **reference knowledge** (`validation_status="reference"`).
   Hard rotation-break constraints bind ONLY for rules with
   `validation_status="confirmed_regional"` — the seed pack deliberately has
   none; tests cover the confirmed case with a fixture. The UI states this.
