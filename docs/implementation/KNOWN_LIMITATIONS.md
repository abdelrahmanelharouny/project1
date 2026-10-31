# Known Limitations

Honest record of what this slice does NOT do. Nothing here is claimed to work.

## Data and providers

1. **Synthetic fixtures are fixtures.** The synthetic provider's profiles are invented shapes — zero agronomic validity, always `is_synthetic=true`. Real sources now exist alongside (item 2) but the fixture rule is unchanged.
2. **Real providers connected in Milestone 3** — Open-Meteo archive (ERA5-Land/ERA5, live-verified), CHIRPS v3 upload+extract, SoilGrids WCS (optional), farmer CSV. Remaining gaps: **no NASA connectors** (intentional, Master rule 8); **no FAO GAEZ / crop-calendar imports yet**; **no live SoilGrids/WCS data in the sandbox verification** (mocked contract tests + graceful degradation verified; the sandbox could not complete a real WCS round-trip); **CHIRPS has no bulk download pipeline** (operator supplies GeoTIFFs); Open-Meteo uses the field **centroid cell only** (no within-field gradient); SoilGrids ingests **0-5 cm only** until Milestone 4 adds depth-aware soil history.
3. **Minimal raster pipeline**: CHIRPS extraction does nodata masks + pixel-coverage accounting for uploaded single-band GeoTIFFs only. No raster asset storage, resampling metadata, or multi-band/time-series raster handling yet.
4. **No unit conversion engine yet**: observations are stored in the catalog unit they arrive in; the versioned conversion registry arrives with the variable registry (Milestone 4).
5. **No soil sample intake**: `soil_analysis` is honestly reported blocked.

## Intelligence

6. **No features, no water balance, no rotation optimization, no stress testing.** The Data Passport blocks these analyses with explicit missing-input lists instead of simulating them.
7. Passport "valid coverage" thresholds (0.8) are engineering defaults for the readiness rules, not agronomic requirements.

## Security and operations

8. **Password hashing iterations are lowered for sandbox CPUs** (120k PBKDF2 vs. OWASP-recommended ≥600k for production); token TTL is 12 h; no refresh-token rotation yet.
9. **No rate limiting** on exposed endpoints; no file upload scanning (no uploads exist).
10. **CORS is disabled by default** (same-origin only via gateway). Production must set `FIELDSHIFT_CORS_ALLOW_ORIGINS` to approved origins.
11. **No background worker queue**: ingestion executes inline within the request (jobs remain 202-shaped, so the contract survives moving to workers).
12. **In-memory metrics counters** are per-process; durable observability comes from structured logs + job tables.

## Frontend

13. **No PWA/offline mode** yet; no i18n/RTL yet (architecture-ready, English only).
14. The map is a fully offline boundary preview (dark background, no basemap tiles) because the sandbox cannot guarantee third-party tile availability. Production should add a self-hosted or licensed basemap.
15. GeoJSON is entered via paste/example; there is no interactive polygon drawing yet.

## Engineering

16. `next dev` runs in **webpack mode** (not Turbopack) because Turbopack compile workers caused OOM kills in the 4 GB sandbox. Revisit when the deployment environment has more memory.
17. The maplibre worker file is copied to `public/` and wired via `setWorkerUrl` because webpack dev does not resolve MapLibre's ESM worker URL.
18. The conda-forge PostgreSQL cluster is a dev convenience; backups, monitoring, and least-privilege credentials are production tasks.
19. No CI pipeline configuration yet (tests run locally; `docs/implementation/TEST_MATRIX.md` records exact commands and outcomes).

## Explicitly out of scope (per spec)

- Any real-world agricultural recommendation, yield guarantee, or prescription.
- Any use of synthetic observations as evidence for agronomic conclusions.
