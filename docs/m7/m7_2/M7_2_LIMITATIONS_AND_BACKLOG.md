# M7.2 — Limitations & Backlog

Honest record of what M7.2 deliberately does not do, what it cannot do yet, and what is
tracked for later milestones. Nothing here is hidden behavior — every item is either an
explicit M7.2 non-goal or a documented boundary.

## 1. Explicit non-goals (M7.2 spec §17 / M7.0 conditions)

| Item | Why absent | Where it lands |
|---|---|---|
| Environmental stress transformations / simulation | M7.3 scope; a valid configuration is NOT a simulated result | M7.3 (conditional GO, after M7.2) |
| Sensitivity / uncertainty analysis | M7.4 scope | M7.4 |
| Multi-scenario rotation evaluation | M7.5 scope; also needs rotation-run context choices | M7.5 |
| Robustness / decision stability | M7.6 scope | M7.6 |
| Digital Twin timeline | M7.7 scope; twin remains Level 1 (historical profile, not predictive) | M7.7 |
| Climate projections | NO-GO (M7.0 C5): no sourced/licensed dataset or methodology; type is a contract placeholder; creation rejected | M7.8 (only after C5 satisfied) |
| Weather forecasts | No real provider with issue/validity/horizon semantics; type is a placeholder | backlog until provider exists |
| Soil / Management scenario dimensions | M6B/M6C absent from this repository (M7.0 H-03); reported not_implemented everywhere | separate milestone scope, NOT within M7 |

## 2. Documented boundaries of the delivered implementation

1. **No rate limiting.** The repository has no rate-limit infrastructure; per spec §11 it was
   only required "where relevant". Tracked as platform debt (pre-existing, not introduced by
   M7.2).
2. **Scenario `name` uniqueness is not globally enforced.** Identity is the UUID; composite
   uniqueness is the field-scoped idempotency key. Renames of finalized scenarios are frozen
   by the trigger anyway.
3. **Comparison is pair-wise and definition-level.** N-way comparison tables and simulated-
   output deltas are future work (M7.3+ provides the outputs; M7.2 intentionally compares
   nothing simulated).
4. **Version chains are linearized by `_version_chain`.** A revision chain is a path; branch
   points are visible via `lineage`. Deep-forest analytics (e.g. lineage DAG visualization)
   is backlog.
5. **All-synthetic parent evidence yields `conditionally_valid`, not `invalid`.** Deliberate:
   the demo environment is synthetic by design; the requirement is disclosure (exact share +
   `all_synthetic` flag surfaced in API and UI), not a hard block. Revisit if a
   production-evidence policy is defined.
6. **Re-validation of a `valid`/`conditionally_valid` scenario is allowed** (idempotent
   re-check that appends a record); re-validation of `invalid` requires a PATCH first (edit →
   draft). Documented transition table governs.
7. **Draft edits are in-place with validation reset** — draft evolution history is not
   versioned (spec allows this: "only create a separate version table if needed"). If draft
   audit trails become a requirement, add an append-only configuration-versions table.
8. **Pre-existing frontend TypeScript debt** (M7.0 F-39 in `features.tsx`/`water.tsx`)
   remains — untouched by M7.2.
9. **Pytest terminal summary line** is still suppressed by the pre-existing benign-warning
   flood (tracked since M7.0); evidence uses exit code + collected/passed counts.
10. **Field-scoped idempotency keys** mean the same key can exist per field by design
    (cross-tenant replay is impossible — tested).

## 3. Backlog candidates surfaced by M7.2

- Scenario templates / cloning between fields of the same farm (new parent-state binding).
- Bulk validation of all drafts on a field.
- Lineage DAG visualization (currently textual ancestors/children).
- Optimistic-concurrency tokens on PATCH (currently last-write-wins within the allowed
  statuses; finalized rows are trigger-protected).
- Rate limiting middleware (platform-wide).
- Hooking scenario creation into the Field State tab UI as a cross-tab shortcut (the store
  already exposes `goToScenariosFor`).
