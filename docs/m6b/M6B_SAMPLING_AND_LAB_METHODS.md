# M6B — Sampling Model & Laboratory Methods

**Status:** implemented (as-built)
**Code:** `app/soil/service.py` (write path), `app/soil/import_service.py`
(CSV import), `app/api/v1/soil.py` (endpoints), migration `0007_soil_intelligence`.
**ADRs:** ADR-0022 (dedicated soil domain), ADR-0023 (method metadata mandatory).

---

## 1. Sampling event model (`soil_sampling_events`)

One row per field sampling occasion. Fields: `field_id` (FK), `sampling_date`
(required, ISO date), `purpose`, `sampling_method` (free text, e.g.
`composite_core` / `profile_pit` / `single_core`), `sampling_depth_note`,
`management_zone` (free-text label — no spatial assumption), `gps_lat`/`gps_lon`
(CHECK-constrained to ±90/±180; validated again at the service layer),
`composite` (bool), `subsample_count`, `equipment`, `sample_handling`,
`sample_preparation`, `collected_by`, `quality_status` (CHECK vocabulary),
`notes`, `metadata` JSONB.

## 2. Samples: composite and individual

`soil_samples` rows belong to an event (`event_id`, validated to be the same
field) and carry `sample_code` (unique per field: `uq_soil_sample_code`),
`composite_parent_id` (self-FK, `SET NULL` on delete) linking individual cores to
the composite they belong to, `laboratory_id` (nullable FK — labs are
get-or-created by name from `laboratory_name`), `report_reference`,
`received_date`, `reported_date`, notes, metadata.

The API accepts composite and individual samples on the same endpoint; a child
sample with `composite_parent_id` represents one core of a composite. Parent/child
integrity is referential only — no averaging is performed automatically.

## 3. Layer model (`soil_sample_layers`)

The canonical depth-interval carrier: `sample_id` FK, `top_depth_cm`,
`bottom_depth_cm` (CHECK `top ≥ 0 AND bottom > top`), `original_depth_unit` +
`original_top` + `original_bottom` (verbatim declaration preserved),
`layer_label`, notes. Unique per sample per interval (`uq_soil_layer_interval`).
Intervals are built through `make_depth_interval`, which enforces the 300 cm
plausibility bound and refuses inverted/negative/unknown-unit depths.

## 4. Measurement rows and lab metadata

`soil_measurements` attaches one variable value to a layer (or to explicit
field-level depths for gridded rows). Method identity (ADR-0023):

- `method_id` FK to `soil_analytical_methods` and/or inline `method_params` JSONB
  (`code`, `medium`, `soil_solution_ratio`, `bd_basis`, `extractant`,
  `matric_potential_kpa`, …).
- **Mandatory method metadata** for the families `ph`, `salinity`, `nitrogen`,
  `phosphorus`, `potassium`, `cec`: a write without a method descriptor or
  `method_params` is rejected (HTTP 422), never silently defaulted.
- Method registry rows (`soil_analytical_methods`): `code` (unique per
  organization), `property_family` (CHECK: texture, bulk_density,
  water_retention, ph, salinity, carbon, nitrogen, phosphorus, potassium, cec,
  biology, other), `analytical_method`, `extraction_method`, `extractant`,
  `soil_solution_ratio`, `temperature_note`, `reporting_basis`, `reference_text`.
- Limits and qualifiers: `detection_limit`, `quantification_limit` (numeric),
  `result_qualifier` (e.g. `<`, `>`); `uncertainty_value` + `uncertainty_type`
  per row; `quality_status`; `is_synthetic`; `processing_version`; `metadata`.

pH writes are validated (`(0, 14]`, medium recorded); a partial unique index
(`uq_soil_measurement_natural_key`, `WHERE layer_id IS NULL`) deduplicates
field-attached rows on
`(field_id, variable_code, observed_at, top_depth_cm, bottom_depth_cm, source_kind, method_id)`.

## 5. CSV import contract (`POST /api/v1/soil-samples/import`)

Multipart upload (`file`) + optional `mapping` Form field (JSON mapping spec).
Pure parsing/validation lives in `parse_soil_lab_csv`; the endpoint persists in
per-row savepoints so one rejected row cannot poison the batch.

### 5.1 Mapping spec

- No spec (or a spec without `columns`) → built-in template **`canonical_lab_v1`**
  (canonical column names).
- A `columns` object maps template columns → canonical fields. Canonical targets:
  `sample_code`, `top_depth`, `bottom_depth`, `depth_unit`, `observed_at`,
  `variable_code`, `value`, `unit`, `detection_limit`, `result_qualifier`,
  `method_code`. Unknown targets are refused; the required targets are
  `sample_code`, `top_depth`, `bottom_depth`, `variable_code`, `value`.
- Unknown CSV columns (outside the mapping plus the reserved passthrough
  `notes`, `laboratory_name`, `report_reference`) produce a report WARNING, not
  a failure.
- The endpoint additionally requires `default_field_id` in the mapping spec
  (the field the samples belong to); per-sample field binding arrives with
  multi-field templates.

### 5.2 Row validation

| Check | Behaviour |
|---|---|
| `sample_code`, `variable_code`, depths, `observed_at` present | required; missing → row rejected |
| `variable_code` in the canonical dictionary | unknown → row rejected |
| depth sanity | `make_depth_interval` rules (0 ≤ top < bottom ≤ 300 cm; cm/mm/m) |
| value parsing | plain numbers parse; blanks / `NA` / `N/A` / `NULL` / `ND` / `-` → value None (recorded missing, never zero) |
| detection limits | `<0.05` → `value=None`, `detection_limit=0.05`, `qualifier='<'` (same shape for `>`); unparseable → rejected |
| unit normalization | DECLARED conversions only (table below); no declared conversion → row rejected, never guessed |
| dates | `YYYY-MM-DD`, `YYYY/MM/DD`, `DD.MM.YYYY`, `DD/MM/YYYY` |
| duplicates | natural key (sample, variable, top, bottom, date, method) — duplicate row rejected |

Declared unit conversions (`UNIT_CONVERSIONS`): `%`→`g/kg` ×10; `ppm`→`mg/kg` ×1;
`kg/dm3`→`g/cm3` ×1; `mS/cm`→`dS/m` ×1; `cmolc/kg`→`cmol(+)/kg` ×1; identities
for `g/kg`, `mg/kg`, `g/cm3`, `dS/m`, `vol%`, `pH`. If the unit cell is absent the
canonical unit is assumed and recorded.

### 5.3 Report and idempotency

The `ImportReport` carries: `template`, `file_sha256`, `rows_total`, `imported`,
`rejected`, `warnings_count`, per-row results (`row_number`, `status`
`imported|rejected|warning`, `sample_code`, `message`, `measurement_id`) and
`idempotency_key = "soil-lab:" + sha256[:16]`. Re-importing the same file content
is a no-op by checksum (the endpoint returns `already_imported` when an
`IngestionJob` with the same idempotency key exists).

Import-created rows are stamped `evidence_class='direct_field_measurement'`
(`farmer_reported_record` when the mapping spec sets `"farmer_reported": true`),
`spatial_support_type='lab_sample'`, `source_kind='lab_analysis'`; a minimal
sampling event (`purpose='laboratory analysis'`, `sampling_method='import'`,
`composite=true`) and sample/layer rows are created on demand, with the file
sha256 in their metadata for provenance.

### 5.4 Deliberately out of scope

PDF/image laboratory-report extraction is NOT implemented — unverified OCR is
never accepted as a validated laboratory measurement (see
`M6B_RESEARCH_BACKLOG.md`).

## 6. Relation to the rest of the engine

- Measurements feed the profile read model (`build_profile`: layer grouping +
  overlap/gap integrity block), the derived indicators
  (`derive_texture_and_awc`: per-layer USDA class and AWC with refusals), the
  SOC/nutrient/assessment engines and the VOI ranking.
- Newly collected measurements enter through the same sampling domain — closing
  the loop announced by `GET /fields/{id}/soil-data-readiness`.
