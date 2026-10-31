# Milestone 3 — Focused Engineering Audit: Alternative Data Integrations

Audited: 2026-10-31 · Scope: Open-Meteo, CHIRPS v3, SoilGrids, Farmer CSV, provenance chain,
canonical contracts. Method: code review + **live probes against the actual upstream services**
(archive-api.open-meteo.com, maps.isric.org, chc.ucsb.edu docs) to verify the implementations
against their real source behaviour, not just their intended behaviour.

## Verdict summary

| Area | Verdict | Critical issues |
|---|---|---|
| Open-Meteo provider | Sound, 1 hardening gap | none critical |
| CHIRPS extractor | Sound, 2 defects | pentad calendar wrong for last pentad; subcell fields unsupported |
| SoilGrids provider | **Broken against live service** | 3 critical (coverage IDs, map param, WCS request scheme) + 1 unit bug |
| Farmer CSV | Sound, 1 gap | date-basis ambiguity |
| Provenance chain | Good | 2 schema gaps (evidence_class, ingestion_job_id not persisted on observations) |

## 1. Open-Meteo (verified live)

Confirmed against the live archive API:
- `models=era5_land` returns **null** for `precipitation_sum`, `et0_fao_evapotranspiration`,
  `wind_speed_10m_mean` and **values** only for temperature (mean/min/max) and
  `soil_moisture_0_to_7cm_mean`. `models=era5` publishes all seven. The hard-coded
  MODEL_VARIABLES matrix in the provider matches the live behaviour exactly.
- ERA5 and ERA5-Land are never silently combined: each model is a distinct `dataset_product`,
  the model is an explicit request parameter, and the response model/grid/elevation are stored
  per observation.

**Gap (hardening, fixed):** when a request mixes model-native and non-native variables, the
provider still *requested* the non-native series and relied on upstream returning nulls. If
Open-Meteo ever backfills ERA5-backed values under `era5_land`, data would be ingested under
the wrong product label — a silent ERA5/ERA5-Land mix. Fix: non-native variables are no longer
requested at all; the gap is recorded in warnings + coverage (deterministic, upstream-independent).
Temporal chunking re-verified: `_year_chunks` windows are contiguous, non-overlapping, and
calendar-aligned (regression test added).

## 2. CHIRPS v3 extractor

- Pentad calendar verified against CHC v3 documentation ("available 2 days after the end of a
  pentad — on the 2nd, 7th, 12th, 17th, 22nd and 27th"): pentads are 1-5, 6-10, 11-15, 16-20,
  21-25 and **26-end-of-month**.
- **Defect (fixed):** `_period_bounds` computed the pentad end as `start + 5 days`, producing
  e.g. Jan 26–30 instead of Jan 26–31, and Feb 26–02 instead of Feb 26–28/29. Any monthly
  aggregation that later uses `period_end` would have binned these observations wrongly.
- **Gap (fixed):** fields smaller than one 0.05° cell produce zero centre-in-polygon cells →
  structured error. Smallholder fields are the norm in the target domain. Fix: fall back to
  `all_touched` cells with an explicit `CHIRPS_SUBCELL_FIELD` warning flag and cell-coverage
  metadata (never a silent widening of support).
- Verified correct: EPSG:4326 enforcement, nodata accounting, low-coverage flag, preliminary
  flag, linear scale/offset applied to the mean.

## 3. SoilGrids provider — broken against the live service

Live probes (GetCapabilities / DescribeCoverage / real GetCoverage) showed the M3 implementation
could never have fetched a value; the registry "degraded" status was this failure being absorbed
as graceful degradation:

1. **Coverage IDs changed.** Live coverage IDs are `<family>_0-5cm_mean`, `<family>_0-5cm_Q0.05`,
   `<family>_0-5cm_Q0.5`, `<family>_0-5cm_Q0.95` (+ `_uncertainty`). The provider requested
   `soc_0-5cmQmean` / `Q005` / `Q095` → `NoSuchCoverage` (HTTP 404).
2. **Per-property map parameter required.** `maps.isric.org/mapserv` needs `map=/map/<family>.map`
   (`soc.map`, `phh2o.map`, `sand.map`, `clay.map`, `bdod.map`). Without it MapServer fails with
   `msLoadMap(): Unable to access file`. The pH family is `phh2o` (pH in water), not `phhkg`.
3. **WCS 2.0.1 Lat/Long subsets fail on the new server** ("Raster size out of range" — subsets
   are interpreted on the native axes in EPSG:152160 metres, ISRIC's custom Mollweide). The
   WCS **1.0.0** GetCoverage path (`CRS=EPSG:4326`, `RESPONSE_CRS=EPSG:4326`, `BBOX`,
   `WIDTH`/`HEIGHT` or `RESX`/`RESY`) was verified live: returns an EPSG:4326 GeoTIFF.
4. **Unit bug: soc is dg/kg on the wire.** Verified empirically: Sahara raw mean 33.2
   (→ 3.3 g/kg as dg/kg — realistic for hyper-arid sand; 33 g/kg as g/kg would be impossible),
   Nile Delta raw mean 488.6 (→ 48.9 g/kg, plausible for old irrigated delta soils; 488 g/kg
   impossible). The old code treated soc as plain g/kg → **10× overstatement**. bdod (cg/cm³,
   ÷100) and pH (×10, ÷10) conventions re-confirmed; sand/clay are plain g/kg.
5. **Spatial aggregation dilution.** Means were computed over the whole padded bbox — cells
   *outside* the field boundary contributed to "field" values, with no cell accounting. Fixed to
   mask cells against the field polygon (centre-in, `all_touched` fallback with
   `SOILGRIDS_SUBCELL_FIELD` flag), record valid/total cells + ratio, and flag < 50 % coverage
   (`SOILGRIDS_LOW_CELL_COVERAGE`) — mirroring the CHIRPS discipline.
6. Quantile labels `0.005/0.095` corrected to `0.05/0.95` (the 90 % prediction interval
   interpretation was right; the labels were wrong). Output raster CRS is now validated
   (EPSG:4326 required, structured error otherwise). Requested grid is sized to the native
   ~250 m cell (latitude-dependent degree conversion) so the server never resamples beyond
   native resolution; metadata records native CRS (EPSG:152160), reprojected output basis and
   cell coverage.

## 4. Farmer CSV import

Verified sound: strict shape, catalog validation, unit match, duplicate rejection, blank→missing
with `FARMER_BLANK`, sha256 + row provenance, `farmer_reported_record` evidence.

**Gap (fixed):** `datetime.fromisoformat` accepted full timestamps and anchored them at UTC
silently; a farmer's "2024-03-01" is a **local calendar date**. Fix: time components are now
rejected with a row-level reason; dates anchor at midnight UTC with the interpretation basis
recorded (`date_interpretation` metadata) so Milestone 4 aggregation can apply the farm
calendar explicitly instead of guessing.

## 5. Provenance propagation & schema gaps

- **Gap (fixed):** `evidence_class` exists in the canonical contract but was not persisted on
  `observations`; the passport inferred it from product metadata. Now persisted per observation
  (migration 0002) with product-metadata fallback retained for legacy rows.
- **Gap (fixed):** `ingestion_job_id` not stored on observations — the job→observation→feature
  provenance chain was untraceable. Now persisted at insert time.
- Verified correct: natural-key idempotency, per-(variable, product) passport grouping,
  product-version-aware attribution (era5_land vs era5), synthetic/real separation end-to-end.

## Disposition

All critical/high issues above were fixed and regression-tested during this audit (suite
157 → 184 at audit close; 243 after Milestone 4). The full findings were folded into
Milestone 4's implementation where relevant (e.g. the persisted evidence class now flows
into feature provenance, and window-aware source selection in feature runs).

## Regression coverage added

- Open-Meteo: non-native variables are never requested; chunk non-overlap; matrix unchanged.
- CHIRPS: pentad bounds (Jan/Feb leap/non-leap/Apr + day 26 boundary), subcell fallback.
- SoilGrids: live-shaped request assertions (map param, coverage IDs, WCS 1.0 params), soc ÷10,
  field masking with nodata accounting, subcell fallback, CRS rejection.
- CSV: timestamp rejection + date-basis metadata.
- Integration: evidence_class + ingestion_job_id persisted and surfaced in observations and
  the Data Passport.
