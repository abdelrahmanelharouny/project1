# M6C — API Contracts

All routes under `/api/v1` (management router in `app/api/v1/management.py`,
registered after soil). Conventions inherited: bearer auth, error envelope
`{error: {code, message, details, request_id}}`, tenant scoping via
field/farm membership (cross-tenant → **403**), validation → **422**,
missing → **404**. Run-creating POSTs accept `idempotency_key` and return the
existing row on replay.

## Knowledge (platform-level, auth required)
- `GET /knowledge/practices[?family=]` — active-pack practices with per-claim
  resolved citations + `evidence_coverage`
- `GET /knowledge/operation-templates[?operation_type=]`
- `GET /knowledge/packs` — counts now include `practices`,
  `operation_templates`
- `POST /knowledge/packs/import` — accepts `practices` / `operation_templates`
  sections (strict schema; unknown claim source → 422)
- `POST /knowledge/packs/{id}/activate` — lifecycle (unchanged)

## Soil cover
- `POST /fields/{id}/soil-cover/observations` — state/basis vocab, fraction
  [0,1] (never clamped), index needs type+value, RS basis forces
  `remote_sensing_estimate`
- `GET  /fields/{id}/soil-cover/observations`
- `GET  /fields/{id}/soil-cover/timeline?window_start&window_end` —
  per-day classification, metrics, thresholds (honest empty), method rules,
  evidence notes, inputs summary (≤ ~2 y per request)
- `GET  /fields/{id}/soil-cover/metrics` — metrics view of the same

## Cover crops
- `POST /fields/{id}/cover-crop-plans` — window (+optional next crop, sowing
  date, exclusions, feature_run_id) → immutable snapshot: candidates with
  status/reasons/conditions/functions/dimensions/missing_inputs, global
  gaps, warnings (SYNTHETIC, climatology-not-forecast), pack refs, checksum
- `GET  /fields/{id}/cover-crop-plans` · `GET /cover-crop-plans/{plan_id}`
- `POST /fields/{id}/cover-crop-plan-items` — adopt decision (mixture
  fractions ≤ 1; plan_run_id must belong to the field)

## Residues
- `POST /fields/{id}/residue-records` — production status/provenance/mass
  consistency (coefficient_estimate without provenance → 422; `missing` with
  a mass → 422)
- `POST /residue-records/{id}/flows` — flow type vocab; fresh→dry requires
  fraction; negative → 422
- `POST /residue-records/{id}/quality`
- `GET  /fields/{id}/residue-ledger` — per-record balance (`balanced` /
  `over_allocated` surfaced / `production_unknown`), field totals
  (known-production only), warnings, derived nutrient bookkeeping with the
  no-double-count note

## Erosion
- `POST /fields/{id}/erosion-assessments` — window, optional slope evidence,
  optional observed signs, optional RUSLE factors (complete sourced sets
  only) → snapshot: screening (concerns + observed + unknowns), rusle
  (computed/not_evaluated with named missing factors), cited alternatives,
  status separation, not_evaluated per process
- `GET  /fields/{id}/erosion-assessments` · `GET /erosion-assessments/{run_id}`
- `GET  /fields/{id}/erosion-readiness` — honest input readiness per pathway

## Operations
- `POST/GET /farms/{farm_id}/resources`
- `POST /fields/{id}/operations` (+ `depends_on` edges; optional
  `template_code` resolving against ACTIVE packs)
- `POST /fields/{id}/operations/generate` — templates → planned operations
  with calendar windows (evidence surfaced) and template precedence
- `GET  /fields/{id}/operations` (items + dependency map)
- `PATCH /operations/{id}` — status transitions; completion validates the
  linked soil-management event belongs to the field (422 otherwise)
- `POST /fields/{id}/operation-schedule-runs` — CP-SAT snapshot: every
  operation with status/reason, scheduled write-back with `schedule_run_id`,
  pending weather / manual soil checks, conflicts named on infeasible
- `GET  /operation-schedule-runs/{run_id}`
- `GET  /fields/{id}/resource-conflicts`

## Management plans
- `POST /fields/{id}/management-plans` — aggregation snapshot (all sections
  present; checks; warnings; cross-run references; checksum; idempotency)
- `GET  /fields/{id}/management-plans` · `GET /management-plans/{plan_id}`
- `POST /management-plans/{plan_id}/feedback` — farmer/agronomist/other,
  rating 1–5, accepted, comment

**No PATCH/PUT/DELETE exists on any run snapshot** (plans, cover plans,
erosion runs, schedule runs) — immutability is structural and tested.
