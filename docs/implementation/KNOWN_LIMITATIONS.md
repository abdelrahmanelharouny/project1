# Known Limitations

Honest record of what this slice does NOT do. Nothing here is claimed to work.

## Data and providers

1. **Only the synthetic provider exists.** No real environmental data source is connected yet. The synthetic provider's profiles are invented fixture shapes — they carry zero agronomic validity and must never be interpreted as climate.
2. **No NASA connectors** (intentional per Master rule 8). No Open-Meteo, CHIRPS, SoilGrids or GAEZ yet (Milestone 3).
3. **No raster pipeline**: no raster assets, nodata masks, resampling metadata, or pixel-coverage accounting. `spatial_resolution_m` is None for synthetic observations because the generator is field-resolved by construction.
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
