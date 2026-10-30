# API Contract — Slice 1

Base path `/api/v1`. JSON bodies, UUID ids, ISO-8601 UTC timestamps, explicit units in numeric payloads. Errors always:

```json
{
  "error": {
    "code": "INVALID_GEOMETRY",
    "message": "…actionable text…",
    "details": [{"field": "geometry", "reason": "…"}],
    "request_id": "uuid"
  }
}
```

Codes: `VALIDATION_FAILED` (422), `INVALID_GEOMETRY` (422), `UNSUPPORTED_VARIABLE` (422), `INVALID_DATE_RANGE` (422), `NOT_FOUND` (404), `UNAUTHORIZED` (401), `FORBIDDEN` (403), `CONFLICT` (409), `INTERNAL_ERROR` (500).

## Health
- `GET /api/v1/health` → `{status, service, version, environment, time}` (no auth)
- `GET /api/v1/health/ready` → `{status, database, server_version, postgis_version}` (503 if not ready)

## Auth
- `POST /auth/register` `{email, password(≥8), display_name}` → 201 `{token, token_type, expires_at, user{id,email,display_name}, organization{id,name}}` (creates personal org + owner membership)
- `POST /auth/login` `{email, password}` → 200 `{token, …, organizations[{id,role,status}]}`
- `POST /auth/logout` (Bearer) → 204 (revokes token)
- `GET /me` (Bearer) → `{user, organizations}`

## Farms (all Bearer; org-membership enforced)
- `POST /farms` `{name, country_code(2), admin_region?, timezone, currency_code(3), unit_system(metric|imperial), preferred_language}` → 201 Farm
- `GET /farms` → `{items:[Farm], total}` — Farm includes `field_count`, `total_area_ha`
- `GET /farms/{farm_id}` → Farm · `PATCH /farms/{farm_id}` partial → Farm

## Fields
- `POST /farms/{farm_id}/fields` `{name, geometry: GeoJSON Polygon|MultiPolygon (4326), change_reason?}` → 201 `{id, farm_id, name, area_ha, geometry_valid, boundary_version, data_passport_status, geometry_warnings[], geometry_repaired}`
  - Invalid geometry → 422 `INVALID_GEOMETRY` with actionable details (ring closure, bounds, self-intersection repair note, antimeridian warning…)
- `GET /farms/{farm_id}/fields` → `{items:[Field], total}`
- `GET /fields/{field_id}` → Field (`boundary_geojson`, `postgis_geodesic_area_ha` cross-check, `observation_count`, …)
- `PATCH /fields/{field_id}` `{name?}` → Field
- `POST /fields/{field_id}/boundary-versions` `{geometry, change_reason?}` → 201 (version N+1, updates current boundary — never overwrites history)
- `GET /fields/{field_id}/boundary-versions` → `{items:[{id, version_number, area_ha, change_reason, created_at, boundary_geojson}], total}`
- `GET /fields/{field_id}/map` → `{field{id,name,area_ha,boundary_version}, boundary_geojson, bbox[4], crs:"EPSG:4326", area_method:"geodesic (WGS84 ellipsoid via PyProj Geod)"}`

## Data platform
- `GET /data/catalog` → `{data_dictionary_version, variables[], sources[{provider_code, license, attribution, known_limitations, products[{product_code, product_version, temporal_resolution, coverage{start,end}, metadata}]}]}`
- `GET /data/providers/health` → `{providers[{provider_code, kind, status, details}]}`
- `GET /variables` → `{data_dictionary_version, items[]}`
- `POST /fields/{field_id}/data-jobs` `{provider_code:"synthetic", variables[], start_date, end_date, profile, seed}` → **202** job (executes inline; status `succeeded`/`failed` in response). Fail-fast 422 for unsupported variables / inverted ranges; 404 unknown provider; provider coverage errors surface as `status:"failed"` jobs with `error_summary` (Master §12).
- `GET /jobs/{job_id}` → job (tenant-checked)
- `GET /fields/{field_id}/observations?variable_code=&start=&end=&limit≤5000&offset=` → `{items:[Observation], total, limit, offset}` — each item carries unit, time_support, spatial_support, quality_status, `is_synthetic`, processing_version, metadata{generator_version, seed, profile, purpose}
- `GET /fields/{field_id}/data-passport` → DataPassport (see `docs/data_dictionary/evidence-and-quality.md`): overall_status, per-variable facts + provenance + aggregated warnings (with `occurrences`), missing_variables with reasons, analyses with status/missing_inputs/reasons, notes. **No composite score.**
- `POST /dev/seed-demo` → 200 demo token + ids (dev-only; disabled when `FIELDSHIFT_DEV_MODE=false`; synthetic data only)

## Notes
- Every response carries `x-request-id` header; the same id appears inside error envelopes.
- Pagination exists on observations (`limit/offset` + `total`); farm/field lists are small in this slice and return totals.
