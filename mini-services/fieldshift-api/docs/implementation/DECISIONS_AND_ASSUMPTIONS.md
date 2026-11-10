# Decisions and Assumptions (ADR index)

Authoritative record of the architectural decisions and standing assumptions
behind the CropTwist API. Each entry names the code that implements it, so
this document cannot silently drift: if the code changes, update the entry.

## Decisions

- **ADR-0001 — Modular monolith.** One FastAPI service (`app.main:app`) with
  domain packages under `app/` (identity, farms_fields, data_platform,
  features, knowledge, rotation, water, field_state, scenarios, soil,
  management, scenario_execution, sensitivity, robust_rotation, decision,
  digital_twin). Routers live in `app/api/v1/` and are aggregated by
  `router.py`. No inter-service network calls inside the backend.
- **ADR-0002 — Configuration via environment.** All settings are read by
  pydantic-settings (`app/core/config.py`, prefix `CROPTWIST_`, optional
  `.env` in the API working directory). No secrets in code or images; a
  committed `.env` is intentionally absent — `.env.example` documents every
  variable. Unknown `CROPTWIST_*` variables are ignored (`extra="ignore"`),
  which lets deployments pre-provision reserved settings.
- **ADR-0003 — PostgreSQL + PostGIS only.** The platform requires PostGIS
  (boundary geometry, geodesic area, spatial queries). There is no SQLite
  fallback; `GET /api/v1/health/ready` fails when the extension is missing.
- **ADR-0004 — Small, auditable auth.** Passwords: PBKDF2-HMAC-SHA256 with a
  per-user random salt (`app/core/security.py`); the iteration count is
  embedded in every stored hash, so raising
  `CROPTWIST_PASSWORD_PBKDF2_ITERATIONS` (default 600,000) keeps old hashes
  verifiable. Access tokens: 256-bit opaque tokens stored as SHA-256 hashes.
  Refresh tokens rotate on every use; reuse of a rotated token revokes the
  whole token family. Account lockout after repeated failures; per-IP
  sliding-window rate limit on auth endpoints.
- **ADR-0005..0013 — Milestone-scoped decisions** (observation contracts,
  ingestion idempotency, passport readiness, feature-engine catalog,
  water/soil/management methodology) are recorded in the milestone documents
  under `docs/` alongside the code that implements them.
- **ADR-0014 — Knowledge honesty contract.** Knowledge packs
  (`app/knowledge/packs/`) carry per-attribute source citations and
  `validation_status`. Values transcribed from published tables are
  `"reference"`; only agronomist review upgrades them. Deliberate gaps stay
  gaps (see `docs/implementation/M5_GAP_ANALYSIS.md`).
- **ADR-0015/0016/0017 — Deterministic optimization.** OR-Tools CP-SAT with
  `num_search_workers=1`, a recorded seed and sorted iteration order:
  identical inputs produce identical plans. Hard constraints are registered
  as solver assumptions so infeasibility maps back to named constraints
  (never silent relaxation). Reported criteria are recomputed post-hoc by
  `app/rotation/objectives.py`; the solver objective is a steering device
  only.
- **ADR-0018 — Knowledge model.** Packs are platform-level, versioned and
  checksummed; `status` (`draft`/`active`/`retired`) governs whether a pack
  feeds candidate generation (`app/db/models.py`, `KnowledgePack`).
- **ADR-0024 — SOC stock arithmetic.** The FAO GSOC-convention layer stock
  formula is implemented once in `app/soil/soc.py` with explicit bulk-density
  basis handling and single coarse-fragment correction (see
  `docs/m6b/M6B_GAP_ANALYSIS.md` §8).

## Assumptions

- **Tenant isolation is enforced at the service layer.** Every farm/field/
  data route resolves the principal from the bearer token and authorizes
  against organization membership (`app/domains/identity/service.py`).
- **Missing data is never zero-filled.** Absent observations propagate as
  `NULL`/`not_evaluated` through features, scenarios and reports.
- **Determinism over cleverness.** Runs (scenario executions, sensitivity
  analyses, robust evaluations, decision documents) are pure recomputations
  over pinned inputs, persisted with SHA-256 checksums and method versions,
  and expose `/verify` endpoints.
- **Runs execute inline.** Scenario executions, sensitivity analyses and
  robust runs are computed synchronously inside the request. An async mode
  ships for provider ingestion behind `CROPTWIST_JOB_WORKERS` (documented in
  `.env.example`).
- **Dev conveniences are gated.** `CROPTWIST_DEV_MODE` (default false)
  enables the demo seed endpoint and auto-verified registration; it must be
  false in production.
- **Sandbox deployment scripts are sandbox-specific.** `scripts/ensure_db.py`
  boots a user-space conda-forge PostgreSQL cluster; production uses managed
  PostgreSQL (see `docs/architecture/deployment.md`).
