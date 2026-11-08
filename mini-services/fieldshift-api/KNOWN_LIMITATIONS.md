# Known Limitations

Honest inventory of what the FieldShift API does **not** do. Items here are
gaps by design or by priority — not hidden defects. Where a future direction
exists it is named; nothing in this list is simulated elsewhere in the code.

## Identity and authorization

- **RBAC enforcement is being rolled out.** The four roles (`viewer <
  agronomist < manager < owner`) and the gate helpers
  (`require_org_role`, `require_farm_role`) exist in
  `app/domains/identity/service.py` and are enforced on farms, fields,
  rotation, management, scenario executions, sensitivity and robust rotation
  routes. Several other routers still authorize membership only, without the
  role gate; wiring the role check through every router is in progress.
- Password reset and email verification issue single-use tokens but have
  **no delivery channel**: plaintext tokens are handed to the caller /
  returned in the response for sandbox use. An out-of-band mailer is not
  implemented.

## Execution model and observability

- **Runs execute inline.** Scenario executions (M7.3), sensitivity analyses
  (M7.4), robust rotations (M7.5) and decision documents (M7.6) are computed
  synchronously inside the HTTP request. Long scenario sets are bounded by
  documented caps (e.g. `MAX_SCENARIO_SET_SIZE = 5`), but there is no job
  queue yet. An async mode is being added behind the reserved
  background worker pool for provider ingestion (`FIELDSHIFT_JOB_WORKERS`); domain run endpoints (rotation, sensitivity, robust rotation, SOC) still execute inside the request and can adopt the same pool per-domain as their UIs gain progress polling.
- **Metrics are in-process only.** `opentelemetry-api` is pinned in
  `requirements.txt` but no exporter, collector or external metrics endpoint
  is configured. Observability today: structured logging, `x-request-id`
  correlation headers, and the health/readiness endpoints.
- No caching layer: provider probes use a small in-process TTL cache
  (`FIELDSHIFT_PROVIDER_PROBE_CACHE_SECONDS`); everything else reads
  PostgreSQL directly.

## Data platform

- **No weather-forecast provider.** Only the Open-Meteo *historical archive*
  (ERA5/ERA5-Land reanalysis) is implemented. Forecast APIs are not wired.
- **No climate-projection provider.** Climate scenarios cannot be built from
  projection datasets; the scenario type exists as a contract only.
- **No satellite / NASA connectors.** The adapter seam exists in the
  provider registry, but no satellite product is ingested.
- CHIRPS support is limited to local GeoTIFF extraction (`extractor.py`);
  there is no live CHIRPS API client.
- Provider availability probes and timeouts are best-effort; a provider being
  unreachable marks datasets stale rather than blocking the API.

## Scenarios and analytics

- **Soil and management scenario dimensions are not implemented.** M7.3
  transformations cover uniform temperature shifts and precipitation
  scaling only. `climate_projection` and `weather_forecast` scenario types
  are **rejected** at validation with structured findings (they are
  contract-only in M7.2; no real forecast/projection evidence exists).
- Scenario reference ET0 is never recalculated; scenario water estimates are
  structurally unavailable and farmer water allocations are rejected in
  robust runs rather than silently dropped (see
  `docs/m7/m7_5/M7_5_ROBUST_METHOD.md`).
- Knowledge values are `validation_status="reference"` until agronomist
  review; hard rotation-break constraints bind on nothing until
  region-validated rules exist.
- No composite scores, probabilities, yield predictions or universal
  recommendations are produced anywhere — by design (M7.6 discipline).

## Deployment and operations

- The sandbox deployment scripts (`scripts/ensure_db.py`,
  `scripts/daemonize.py`, `scripts/start-stack.sh` at the repo root) are
  **sandbox-specific**: they boot a user-space conda-forge PostgreSQL
  cluster and daemonize processes to survive sandbox process reaping.
  Production must use a managed PostgreSQL + PostGIS and a real process
  manager (see `docs/architecture/deployment.md`).
- `next.config.ts` hardcodes the `/api/v1` rewrite fallback to
  `http://127.0.0.1:3030`, which only works when web and API share a host.
  Behind the Caddy gateway this does not matter; in a compose network it
  does (documented in the compose files).
- Single-database, single-region. No replication, point-in-time recovery
  config, or backup automation ships with the repository.
