# GLOBAL_SPATIAL_AND_CALENDAR_AUDIT.md — Phase G

## 1. Coordinate reference systems and area

- Storage: `Geometry(MULTIPOLYGON, 4326)` with PostGIS spatial index; inputs
  restricted to GeoJSON WGS84 (CRS84 semantics), other CRS rejected rather
  than silently reprojected (rasters: explicit EPSG:4326 enforcement, e.g.
  CHIRPS/SoilGrids upload paths).
- Area: PyProj WGS84 geodesic (`Geod.geometry_area_perimeter`) on
  orientation-normalised rings, cross-checked against PostGIS geography area
  (<0.5% divergence, tested). Equal-area projection is NOT needed for area
  itself (geodesic is the reference); it becomes relevant for area-weighted
  raster statistics on cells whose geodesic area varies with latitude — the
  F-13 weighting uses the lon/lat cell-geometry intersection ratio, which is
  an acceptable local approximation documented here (on 0.05° cells the
  planar-vs-geodesic cell-area ratio varies <0.2% for latitudes <60°).

## 2. Geometry edge cases

| Case | Behaviour | Test |
|---|---|---|
| Bowtie (self-intersection) | repaired with warning, valid result | U12 |
| Open / short rings, non-numeric coords, point geometry | structured 422 | U5–U9 |
| Antimeridian-spanning ring | WARNING (span > 180°) — user must re-wrap explicitly; no silent re-labelling | U13 |
| MultiPolygon | both parts stored, area summed geodesically | U2 |
| High-latitude fields | geodesic area correct (cos-law); equator vs 60°N sanity | U14–U16 |
| Degenerate / oversized | <1 m² rejected; >5,000,000 ha rejected (unit guard) | U11, I-validation |

Limitation (documented): the antimeridian warning is honest but requires user
action; automatic longitude re-wrapping is backlog G-1.

## 3. Raster/vector intersection

### 3.1 CHIRPS (5.566 km cells) — deepening F-13
- Selection: cell-centre-in-polygon; **field mean = fractional pixel-AREA
  weighted** over valid cells (weights = intersection-area/cell-area,
  renormalized over valid cells; nodata excluded, never biasing weights).
- Sub-grid fields (no centre inside): all-touched fallback with
  `CHIRPS_SUBCELL_FIELD` — explicitly "may represent the surrounding grid
  cell rather than a field-specific measurement" (verbatim in flag text).
- Nodata accounting + `CHIRPS_LOW_CELL_COVERAGE` (<50% valid).
- Numeric verification: 2-cell raster (0 mm fully covered, 20 mm 75% covered)
  → weighted 8.571 vs unweighted 10.0 (test).

### 3.2 SoilGrids (250 m cells)
- Centre-inclusion mean per property across mean/Q0.05/Q0.95 coverages;
  same sub-grid fallback and low-coverage flags.
- **Area weighting investigated and deliberately not applied**: at 250 m the
  fraction of CropTwist-scale fields spanning ≤2 cells is small, the
  all-touched fallback already discloses the widening, and per-quantile
  weighting would triple the intersection work for a marginal correction.
  Revisit if sub-hectare field support becomes a requirement (backlog G-2).
- Edge effects: the WCS bbox is padded by one cell; cells fully outside the
  field cannot enter the mean (mask-based); raster edge truncation is covered
  by the field-overlap error ("does not overlap any cell" → structured
  warning, no value).

### 3.3 Missing spatial coverage
- No raster overlap / all-nodata → structured errors, never fabricated values.
- Grid-cell support is recorded per observation (`spatial_support_type`,
  resolution_m) and surfaced in the passport — a field-level claim is never
  made for grid-derived values.

## 4. Regional time zones and crop calendars

- Feature calendar: farm timezone (IANA) explicit on every run; midpoint
  local-day assignment; DST boundaries tested (Cairo summer); offset
  invariance property-tested; monthly/season bounds computed in UTC from
  local boundaries.
- Hemisphere: only a season LABEL swap (DJF↔JJA, MAM↔SON) for meteorological
  aggregation — never used to infer crop calendars. Rotation seasons are
  explicit user windows; knowledge-base calendar windows are region- and
  hemisphere-scoped rows with validation status; a crop without a window for
  the field's hemisphere is **unevaluated**, not excluded.
- Tropical/equatorial seasonality: supported only through explicit windows
  today (the seed pack has none equatorial); regional knowledge packs are the
  intended carrier (backlog C-4).
