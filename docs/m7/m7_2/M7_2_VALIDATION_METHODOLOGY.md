# M7.2 — Validation Methodology

**Status:** implemented (`app/scenarios/validation.py` — pure; rules version
`scenario-validation-rules-1.0`)

## 1. Independence

The engine imports nothing from FastAPI, SQLAlchemy or the ORM models. It consumes two plain
dataclass views and returns a plain result document:

- `ScenarioView` — scenario_type, configuration, parent pins, period;
- `ParentStateView` — field/organization ids, status, checksum, boundary version +
  boundary-record existence, period, timezone, domain availability, manifest observation
  counts (total and synthetic).

The service (`validate_scenario`) builds the views from tenant-scoped reads and persists an
immutable `scenario_validation_records` row plus the `validation_summary` copy. This keeps the
engine unit-testable without HTTP/DB and the API thin.

## 2. Result vocabulary (spec §8)

`valid · invalid · conditionally_valid · unsupported · not_implemented · missing_reference ·
incompatible_period · insufficient_parent_evidence`

Lifecycle mapping: `valid→VALID`; `conditionally_valid`, `insufficient_parent_evidence` →
`CONDITIONALLY_VALID`; `invalid`, `missing_reference`, `incompatible_period` → `INVALID`;
`unsupported`, `not_implemented` → `UNSUPPORTED`.

## 3. Checks performed (order matters — first blocking verdict wins)

1. **Parent reference exists** → else `missing_reference` (+ missing input
   `parent_field_state_id`).
2. **Tenant boundary** — parent organization must equal the requesting organization → else
   `invalid` with `parent_state_cross_tenant` (defense in depth; the API already resolves
   ownership server-side and never trusts client claims).
3. **Scenario type capability** — unimplemented/unknown types → `not_implemented` with the
   honest reason (unreachable via the API, which rejects them at creation).
4. **Parent state integrity** — status must be `succeeded`; parent checksum must be present
   and match the scenario's pinned copy (`parent_snapshot_checksum_mismatch`); pinned boundary
   version must match the parent (`parent_boundary_version_mismatch`).
5. **Boundary record (H-01 continuity)** — the parent's boundary version must exist in the
   append-only boundary history → else `insufficient_parent_evidence`.
6. **Temporal compatibility** — scenario period vs parent period overlap fraction: 0 →
   `incompatible_period` (incompatible windows are never merged); <1 → `conditionally_valid`
   with the fraction recorded (partial cover).
7. **Assumption honesty** — hypothetical types must carry
   `assumption_metadata.status = 'hypothetical'`; a historical observed scenario must NOT
   carry adjustments/assumption metadata.
8. **Real vs synthetic evidence** — if the parent's manifest contains synthetic observations:
   `conditionally_valid` + finding with the exact share (`synthetic_share`,
   `all_synthetic`); an all-synthetic parent is loudly disclosed ("ALL evidence is synthetic")
   but stays `conditionally_valid` — the platform's demo profile is synthetic by design, and
   the requirement is that synthetic data remains *visibly* synthetic, which this finding
   guarantees (it is also surfaced in the UI).
9. **Parent dimension availability** — every implemented dimension
   (`environmental`, `water`, `rotation`, `crop_history`) with status ≠ `available` degrades a
   `valid` verdict to `conditionally_valid` and is listed in `unsupported_dimensions` with its
   status and reason.
10. **Structurally unavailable domains** — soil, management, climate projection, weather
    forecast are ALWAYS appended to `unsupported_dimensions` with their fixed reasons (C3/C5)
    and an `info` finding records this.

## 4. Findings

Each finding: `{code, severity, message, ...detail}`. Severity ladder: `error` (drives an
invalid/blocking verdict), `warning` (degrades to conditionally_valid), `info` (recorded
limitation). The result document embeds the rule version and the configuration checksum that
was validated — a validation verdict is meaningful only for that exact checksum.

## 5. What validation NEVER implies

- That the scenario has been executed (nothing executes in M7.2).
- That any simulated/predicted output exists (M7.3 absent).
- That the parent's data is real (synthetic evidence is disclosed, never conflated).
- That a hypothetical assumption is an observed event or a forecast.
- That the Digital Twin is predictive (Level 1 — Historical Digital Profile).

The API response carries this note explicitly on every validation call.
