# M6B — API Contracts (`/api/v1/` soil endpoints)

**Status:** implemented (as-built)
**Code:** `app/api/v1/soil.py`; auth via `get_principal`; every field-scoped
endpoint resolves the field through `get_field_for_principal` (tenant isolation).

---

## 1. Conventions

- **Tenant isolation:** every field-scoped route (and every run-detail route via
  the run's `field_id`) passes through `get_field_for_principal`; a principal
  from another organization gets **403** (integration-tested).
- **Content:** JSON request/response bodies; the CSV import is multipart.
- **Status codes:** 201 on creation; 200 otherwise; 404 unknown/foreign ids;
  422 `ValidationFailed` (honest refusals carry the reason in
  `error.message`/`details`).
- **Idempotency:** run-creation endpoints accept `idempotency_key`; a repeated
  key returns the ORIGINAL run (per-field partial-unique index).
- **Run snapshots are immutable** with `checksum_sha256`; re-running creates a
  new row.

## 2. Endpoint inventory

| # | Method & path | Purpose |
|---|---|---|
| 1 | GET `/soil/methods` | versioned methodology catalog |
| 2 | POST `/fields/{id}/soil-sampling-events` | create sampling event (201) |
| 3 | GET `/fields/{id}/soil-sampling-events` | list (latest 100, date desc) |
| 4 | POST `/fields/{id}/soil-samples` | create sample / composite core link (201) |
| 5 | GET `/fields/{id}/soil-samples` | list (latest 100) |
| 6 | POST `/soil-samples/import` | laboratory CSV import (multipart + mapping Form) |
| 7 | POST `/fields/{id}/soil-measurements` | record one measurement (201) |
| 8 | GET `/fields/{id}/soil-profile` | depth-explicit profile read model |
| 9 | GET `/fields/{id}/soil-indicators` | per-layer derived texture/AWC |
| 10 | POST `/fields/{id}/soc-stock-runs` | SOC stock run (immutable snapshot, 201) |
| 11 | GET `/fields/{id}/soc-stock-runs` | list runs (latest 50) |
| 12 | GET `/soc-stock-runs/{id}` | run detail (tenant-checked) |
| 13 | POST `/fields/{id}/nutrient-products` | product registry row (201) |
| 14 | POST `/fields/{id}/nutrient-applications` | documented input flow (201) |
| 15 | POST `/fields/{id}/nutrient-removals` | documented output flow (201) |
| 16 | POST `/fields/{id}/nutrient-budget-runs` | N/P/K budget run (201) |
| 17 | GET `/nutrient-budget-runs/{id}` | budget run detail |
| 18 | POST `/fields/{id}/soil-management-events` | ledger event (201) |
| 19 | GET `/fields/{id}/soil-management-events` | ledger list (latest 100) |
| 20 | POST `/fields/{id}/soil-assessments` | assessment snapshot (201) |
| 21 | GET `/soil-assessments/{id}` | assessment detail |
| 22 | GET `/fields/{id}/soil-health` | latest assessment (snapshot or live) |
| 23 | GET `/fields/{id}/soil-data-readiness` | qualitative VOI ranking |

## 3. Key request/response shapes (abridged)

**GET /soil/methods** → `{soil_engine_version, methods_version, texture_classifier{version, system, source, silt_derivation, tolerance}, conversions{p2o5_to_p{factor, derivation, version}, k2o_to_k{…}, oc_to_om{factor 1.724, method}}, salinity_classes[{range_ds_m, class, citation, applies_to}], assessment_policy{version, composite_index: null, note}, variables[26]}`.

**POST soil-sampling-events** ← `{sampling_date (required), purpose?,
sampling_method?, management_zone?, gps_lat?/gps_lon? (validated), composite?,
subsample_count?, equipment?, sample_handling?, sample_preparation?, collected_by?,
quality_status?, notes?, metadata?}` → `{id, field_id, sampling_date}`.
GPS outside ±90/±180 → 422.

**POST soil-samples** ← `{event_id (required, must belong to the field),
sample_code (required, unique per field), composite_parent_id?, laboratory_name?
(get-or-create), report_reference?, received_date?, reported_date?, notes?,
metadata?}` → `{id, sample_code, event_id}`.

**POST soil-samples/import** ← multipart `file` (CSV) + optional `mapping`
(JSON: `columns` map, `default_field_id` REQUIRED by the endpoint, optional
`farmer_reported`, `template`). → `{status: imported|already_imported, report
{template, file_sha256, rows_total, imported, rejected, warnings, rows[…],
idempotency_key}, created_samples, created_measurements, errors[≤20]}`.
Re-import of identical content is a no-op by checksum.

**POST soil-measurements** ← `{variable_code (dictionary member), value?, unit?,
layer_id? OR top_depth_cm+bottom_depth_cm, evidence_class?
(default farmer_reported_record), source_kind?, method? {code, property_family,
extractant, soil_solution_ratio, …} OR method_params?, detection_limit?,
quantification_limit?, result_qualifier?, uncertainty_value?/uncertainty_type?,
quality_status?, is_synthetic?, observed_at (required), processing_version?,
metadata?}` → full measurement payload. 422 when: unknown variable; chemical
family without method metadata (ADR-0023); pH outside (0,14] or missing medium;
`soilgrids_profile` without `global_soil_prediction`; invalid depths.

**GET soil-profile** → `{field_id, engine_version, layers[{top_cm, bottom_cm,
source_kinds, evidence_classes, measurements[payloads], sample_id?}],
integrity{overlaps, gaps[{from_cm, to_cm, gap_cm}], coverage_cm, note}}`.
Measurements limited to the latest 500 rows (date desc, then depth).

**GET soil-indicators** → `{engine_version, layers[{top_cm, bottom_cm,
texture{class, sand/silt/clay_pct, silt_basis, classifier_version} |
{status: not_evaluated, reason}, awc{awc_m3_m3, awc_mm, fc/pwp_potential_kpa} |
{status: not_evaluated, reason}}], note}`.

**POST soc-stock-runs** ← `{label?, layers[{top_depth, bottom_depth,
depth_unit?, oc_g_kg?, bulk_density_g_cm3?, bd_basis?
(whole_soil|fine_earth), coarse_fragment_vol_fraction?, evidence_class?,
is_prediction?, source_refs?}], comparison_mode? (single_profile|fixed_depth|
equivalent_soil_mass), baseline_run_id? (required for comparison modes),
sample_ids?, request_parameters?, idempotency_key?}` → run payload
`{id, field_id, status, label, comparison_mode, engine_version,
methods_version, warnings, not_evaluated, checksum_sha256, error_summary?,
result{formula, layers[…], profile_total{soc_stock_mg_ha, coverage_cm,
covered_thickness_cm, contiguous, reason?}, not_evaluated, gaps, warnings,
comparison?{…}}}`. Unknown comparison mode → 422; foreign baseline → 404.

**POST nutrient-products** ← `{name (required), product_type?
(fertilizer|manure|compost|organic_amendment|other), n_pct?/p_pct?/k_pct?,
reporting_basis (elemental|oxide — required choice), dry_matter_fraction?,
moisture_basis?, availability_notes?, source_reference?, metadata?}` →
`{id, name, reporting_basis}`.

**POST nutrient-applications** ← `{season_label (required),
application_date (required), input_kind (8 CHECK kinds), product_id? OR
n_kg/p_kg/k_kg + reporting_basis, applied_mass_kg (required, ≥ 0), area_ha
(required, > 0), availability_fraction? (REQUIRED for
manure/compost/organic_amendment — 422 otherwise), availability_basis?,
application_method?, moisture_basis?, evidence_class?, is_synthetic?,
source_reference?, notes?}` → `{id, season_label, input_kind, n_kg, p_kg, k_kg,
reporting_basis, area_ha}` (product-derived masses computed from the grade;
oxide grades keep the declared form — the budget engine converts).

**POST nutrient-removals** ← `{season_label (required), removal_date?, crop_code?,
output_kind? (harvested_product|crop_residue|other_biomass), biomass_kg
(required, ≥ 0), dry_matter_fraction?, moisture_basis (as_harvested|dry_matter;
default as_harvested), n/p/k_concentration_g_kg? (AT LEAST ONE required — 422
"yield alone is never a removal estimate"), concentration_basis?,
concentration_source?, evidence_class?, is_synthetic?, notes?, metadata?}` →
`{id, season_label, output_kind, biomass_kg, moisture_basis, concentrations}`.

**POST nutrient-budget-runs** ← `{seasons [≥1 required], area_ha? (default
field.area_ha), label?, request_parameters?, idempotency_key?}` → run payload
with `result{seasons[{season_label, overall, balance{N,P,K{inputs_kg_ha,
outputs_kg_ha, balance_kg_ha, status}}, nue, inputs[], outputs[],
missing_flows, warnings, interpretation_note}], cumulative{seasons_total,
seasons_evaluable, seasons_skipped, cumulative_balance_kg_ha, note},
engine_version, methods_version, reference_library_note}`.

**POST soil-management-events** ← `{event_date (required), event_type (12 CHECK
types: planting, harvest, fertilizer_application, manure_application,
compost_application, residue_retention, residue_removal, tillage,
cover_crop_termination, irrigation, soil_amendment, other), title?, details?,
nutrient_application_id?, notes?}` → `{id, event_type, event_date}`.
Unknown type → 422.

**POST soil-assessments** ← `{label?, request_parameters?, idempotency_key?}` →
assessment payload `{id, field_id, status, label, engine_version,
checksum_sha256, result{field_id, assessment_version, engine_version,
methods_version, domains[5 × {domain, available[…], missing[…], counts,
data_quality_note, synthetic_flag}], composite_score: null, composite_note,
missing_is_not_bad_note}}`.

**GET soil-health** → `{source: snapshot|live, assessment_id? , result}` —
latest succeeded snapshot, else a live (unpersisted) evaluation, labelled.

**GET soil-data-readiness** → `{priorities[{variable_code, trigger,
decision_unblocked, priority_basis}], collected_note, policy, engine_version}`.

## 4. Honesty-status vocabulary (as used in responses)

| Status | Where | Meaning |
|---|---|---|
| `evaluated` | SOC layers, budget balance rows, comparisons | computed from complete documented inputs |
| `not_evaluated` | SOC layers, comparisons, run `not_evaluated` lists | refused with an explicit reason (missing inputs) |
| `not_supplied` | per-nutrient status on individual flows | that nutrient was not documented for the flow |
| `not_evaluable` | budget overall/per-nutrient balance | no usable documented flow on either side |
| `partial` | budget overall | documented flows exist; missing flows (incl. all loss terms) are LISTED, never zero |
| `refused` | validation errors (HTTP 422) | the write/engine rejects the request with the reason |

## 5. Errors

`ValidationFailed` → 422 with `{error: {message, details[{field, reason?}]}}`;
`NotFound` → 404; cross-tenant access → 403. Run failures are recorded on the
run row (`status='failed'`, `error_summary`) and re-raised, so the ledger keeps
the failed attempt without a fabricated result.
