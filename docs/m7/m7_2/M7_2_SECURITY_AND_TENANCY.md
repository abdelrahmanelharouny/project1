# M7.2 — Security & Tenancy

**Status:** implemented and tested (`tests/integration/test_scenarios.py::TestSecurityAndTenancy`)

## 1. Tenancy model

The platform's tenant rule: every resource access is authorized against the requesting user's
active organization memberships. Scenarios inherit it through the **field**:

```
scenario.field_id → fields.farm_id → farms.organization_id ⇄ Principal.memberships
```

`get_field_for_principal` is called at every reference boundary:

- `POST /fields/{field_id}/scenarios` — the target field is tenant-scoped;
- `GET/PATCH/DELETE … /scenarios/{id}` and every action route — the scenario's own field is
  re-scoped (`_get_scenario_scoped`);
- `GET …/compare?against=` — **both** sides are scoped independently;
- `GET /fields/{field_id}/scenarios` — the field is scoped.

Client-supplied tenant/ownership claims are never trusted; there is no tenant field in any
scenario payload accepted from clients.

## 2. Review checklist (spec §13) — status

| Item | Status / mechanism |
|---|---|
| Tenant-scoped ownership resolution | ✅ server-side via identity service; membership check on every boundary |
| Cross-tenant parent snapshot references | ✅ parent state must belong to the same (already-scoped) field → 422 `PARENT_STATE_MISMATCH`; the pure engine additionally rejects cross-tenant parents (`parent_state_cross_tenant`) |
| Cross-tenant scenario access | ✅ 403/404 platform convention; tested |
| Scenario ID enumeration | ✅ random UUID → 404 |
| Composite uniqueness | ✅ partial unique `(field_id, idempotency_key)`; PK id; no global-unique name enforced (documented) |
| Concurrent finalization | ✅ service transition check + DB trigger backstop; double-finalize → 409 (tested) |
| Idempotency replay | ✅ field-scoped; cross-tenant replay impossible (tested); replay returns the same row |
| Checksum verification | ✅ `GET /scenarios/{id}/verify` recomputes from stored content; parent state checksum re-checked; latest validation record must match the current configuration checksum |
| Immutable update attempts | ✅ 409 `SCENARIO_IMMUTABLE` at the service; DB trigger rejects even raw SQL (tested) |
| Delete restrictions | ✅ drafts only, and only without children (RESTRICT FKs + service check); finalized/archived → archive route |
| Audit actor identity | ✅ `created_by` recorded on scenarios and validation records from the authenticated principal |
| Snapshot retention | ✅ parent Field States are RESTRICT-protected from scenario references; archived scenarios remain retrievable + checksum-verifiable |

## 3. Evidence-integrity security rules

- Hypothetical inputs are structurally pinned to `status: "hypothetical"` (Pydantic Literal +
  engine check) — a user assumption can never be presented as an observed event.
- Historical observations are never altered by scenario operations (regression-tested: the
  parent state, including its manifest hash, is byte-identical after scenario creation).
- Synthetic parent evidence is disclosed with exact shares; it never silently counts as
  measured evidence.
- Climate/forecast rows cannot exist as executable capabilities (creation rejected + DB CHECK);
  no forecast-derived evidence can be produced.

## 4. Known boundaries (honest)

- No rate limiting (no infrastructure in the repository — tracked in the backlog doc).
- `created_by` is provenance only (excluded from checksums by design).
- The `Forbidden` (403) vs `NotFound` (404) split follows the existing identity service
  convention; both outcomes leak no resource detail.
