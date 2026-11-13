# Known Limitations

Honest inventory of what the CropTwist API does **not** do. Items here are
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
  background worker pool for provider ingestion (`CROPTWIST_JOB_WORKERS`); domain run endpoints (rotation, sensitivity, robust rotation, SOC) still execute inside the request and can adopt the same pool per-domain as their UIs gain progress polling.
- **Raster processing jobs use Postgres-backed queues, not a distributed
  broker.** P05 satellite preprocessing runs through `background_jobs` +
  `raster_processing_jobs` rows and the standalone `python -m app.worker`
  process (durable rows, restart replay, graceful drain). At current scale a
  Postgres-backed queue satisfies durability and single-active-job
  idempotency; a broker (Redis/RabbitMQ/Celery) is intentionally NOT
  introduced — revisit only if multi-region fan-out or thousands of
  concurrent scene jobs are required. Workers must be deployed separately
  from the API (independently scalable); the API never runs raster work
  in-request.
- **Metrics are in-process only.** `opentelemetry-api` is pinned in
  `requirements.txt` but no exporter, collector or external metrics endpoint
  is configured. Observability today: structured logging, `x-request-id`
  correlation headers, and the health/readiness endpoints.
- No caching layer: provider probes use a small in-process TTL cache
  (`CROPTWIST_PROVIDER_PROBE_CACHE_SECONDS`); everything else reads
  PostgreSQL directly.

## Data platform

- **No weather-forecast provider.** Only the Open-Meteo *historical archive*
  (ERA5/ERA5-Land reanalysis) is implemented. Forecast APIs are not wired.
- **No climate-projection provider.** Climate scenarios cannot be built from
  projection datasets; the scenario type exists as a contract only.
- **NASA HLS connector (P04) — real adapter, live-verified discovery only.**
  Catalog discovery via NASA CMR STAC is live-verified in the sandbox (real
  HLSL30/HLSS30 scenes discovered and persisted). Authenticated asset reads
  (`/vsicurl/` COG range reads via NASA Earthdata Login) are implemented but
  NOT live-tested — no Earthdata credentials in this environment; without
  credentials the acquisition path fails loudly per scene (RasterioIOError
  surfaced in scene `acquisition_detail`), never fabricating data. Vegetation
  indices are derived per scene during acquisition (documented HLS scaling +
  Fmask masking); no agronomic conclusions in the ingestion layer.
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

## P1 AI Intelligence, Performance & Trust (known limits)

- **Narrative locale is fixed at refresh time.** The LLM narrative is a
  persisted artifact generated for the locale requested by THAT refresh
  (`?locale=ar|en`); rows keep it until the next refresh. Switching the UI
  locale does not retroactively translate existing narratives — press
  "Regenerate" (or refresh with the new locale) to rewrite them. Rules-layer
  text (titles/summaries/rationales) stays canonical English by design;
  localization happens through narratives + UI labels.
- **Evidence-quality components are heuristic, not calibrated.** A5 computes
  completeness/recency/coverage/source-reliability/data-gap components with
  documented bands; spatial resolution and cross-source agreement are
  declared `null` until such metadata reaches the evidence pack. No
  probability is manufactured anywhere.
- **Numeric-consistency validation is screening-grade.** It uses explicit
  tolerances (1.5% relative, ±0.15 z, ±1.0 percentage points) and a small
  conversion table (mm/cm/m, °C/°F, %↔fraction, kg/ha↔Mg/ha). Derived values
  the model legitimately computes from evidence (e.g. NIR minus effective
  rain) can still be flagged; the consequence is one constrained
  regeneration, then the deterministic fallback — never silent acceptance.
- **Circuit breaker and narrative cache are in-process.** Same trade-off as
  the rate limiter and job queue (single-process sandbox); multi-replica
  deployments swap the store/coordinates behind the same interfaces.
- **Streaming is intentionally not implemented** — citation validation and
  numeric consistency need the complete response before rendering
  (`mini-services/llm-bridge/README.md` documents the decision).
- **The evaluation framework verifies generator RULES, not upstream engine
  science.** Golden cases run the real generators over fixed synthetic
  contexts (62 checks, deterministic, no network). LLM-narrative criteria are
  heuristic; the optional bridge judge is supplementary and never decisive.
- **Bridge auth is off by default** (loopback-only dev). Production must set
  `BRIDGE_TOKEN` on the bridge and the same value in
  `CROPTWIST_LLM_BRIDGE_TOKEN` on the backend — see
  `mini-services/llm-bridge/README.md`.
- **Advisor answers for fields without engine runs** are honest data-gap
  reports (the model is constrained to the evidence pack, which lists only
  gaps) — an answer like "I cannot determine X, data is missing" IS the
  correct behavior, not a failure.
