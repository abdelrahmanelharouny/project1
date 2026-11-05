# M6C — Practice Knowledge Model (as-built, Increment 2)

**Status:** implemented and tested (24 unit+integration tests; see
`M6C_TEST_AND_BENCHMARK_REPORT.md` for counts).

## 1. Where practice knowledge lives

Practices and operation templates are **knowledge-pack data** (ADR-M6C-1):
a pack payload carries `practices: [...]` and `operation_templates: [...]`
sections; import validates and materializes them into relational rows
(`practice_definitions`, `operation_templates`) exactly like crops/rules.
Consequences (all enforced in code):

- Lifecycle: rows belong to their pack; only ACTIVE packs feed read models
  and engines. Draft packs are inert; retired packs are history. Verified by
  `test_draft_practices_are_inert_until_activated`.
- Versioning: `(pack_code, pack_version)` unique + whole-pack checksum.
  Re-import is idempotent; a different checksum under the same version is a
  422 conflict (`test_import_idempotent_and_checksum_conflict`).
- Licensing/attribution: pack-level (license_name, attribution_text,
  license_notes, digitization_note), per-source citation rows with
  publisher/title/url/license/citation_text.
- Backward compatibility: `pack_checksum` omits empty M6C sections, so
  pre-M6C pack checksums are byte-stable
  (`test_checksum_ignores_empty_m6c_sections`,
  `test_pre_m6c_pack_reimport_is_idempotent`).

## 2. Practice schema (app/management/contracts.py)

```
PracticeDefinitionIn
  practice_code, practice_family ∈ {cover_crop, residue, tillage, soil_cover,
                                    erosion_control, traffic, termination}
  name, description, validation_status ∈ M5 vocabulary (reference | …)
  mechanisms[]            {mechanism_code, text, source_key, evidence_class,
                           confidence, conditions}
  requirements[]          {requirement_code, kind: seed|equipment|labor|
                           knowledge|window|other, text, source_key, …}
  trade_offs[]            {dimension ∈ 12 dimensions, direction:
                           positive|negative|context_dependent, text, …}
  risks[]                 {risk_code, text, source_key, …}
  regional_applicability[] {region_code | agroecological_zone, basis,
                            source_key, validation_status}
```

Import-time rejections (acceptance: *no unsupported practice is silently
treated as validated*):

- a claim without a resolvable `source_key` → whole pack rejected
- unknown `trade_offs[].dimension` → rejected (typo would hide a dimension)
- a practice with neither mechanisms nor trade-offs → schema-rejected
- regional applicability without region/zone + declared basis → rejected
  (latitude/hemisphere alone is not a regional basis)
- operation-template predecessor referencing an unknown template → rejected
- explicit crop scoping referencing non-pack crops → rejected

## 3. Two-sidedness and numeric bans (red lines 3/5)

- Every bundled practice carries ≥ 1 `negative` or `context_dependent`
  trade-off (`test_every_practice_is_two_sided`).
- The bundled pack is **numeric-free**: no seeding rates, termination lead
  times, machinery capacities, cover thresholds or erosion factors.
  `test_practices_pack_contains_no_numeric_parameters` scans claims; the
  termination practice additionally asserts no "days/weeks before" phrasing
  (`test_cover_termination_has_no_fixed_lead_time`).
- Nothing ships `confirmed_regional`; upgrade paths go through the existing
  `agronomist_reviews` workflow (unchanged from M5).

## 4. Bundled pack `kp-m6c-practices-2026.11.1`

12 practices: cover_cropping · residue_retention · residue_removal_baling ·
residue_incorporation · mulching · reduced_tillage · contour_operations ·
strip_cropping · vegetated_buffer · controlled_traffic ·
cover_termination_planning · field_access_management.

12 operation templates (op_harvest, op_residue_chop_spread,
op_residue_baling, op_soil_sampling, op_tillage_seedbed, op_cover_seeding,
op_cover_termination, op_main_planting, op_fertilizer_application,
op_irrigation, op_spraying, op_post_harvest_prep) — each with cited
predecessor rationale where a cycle order exists; **no durations, no
capacities, no thresholds** (red line: resources are farmer-entered).

Sources (all fetched/read during Increment 1; see gap analysis §11):
FAO CA principles / soil-organic-cover / how-to pages; USDA NRCS Cover Crop
Standard (Ac.) 340; NRCS Cover Crop Termination fact sheet (2025); NRCS
Harvesting Crop Residue (2016); NRCS National Agronomy Manual (water erosion);
NRCS/ARS RUSLE2 scope pages; ASABE 2024 machinery-scheduling review.
US-scoped applicability is declared explicitly on NRCS-derived practices.

## 5. Read models & API

- `GET /api/v1/knowledge/practices[?family=]` — active-pack practices with
  every claim's resolved citation plus `evidence_coverage`
  (`claim_counts`, `claims_cited`, `trade_off_dimensions_covered`) — a
  transparency metric, never a confidence score (M5 convention).
- `GET /api/v1/knowledge/operation-templates[?operation_type=]` — same
  conventions for templates.
- `GET /api/v1/knowledge/packs` — counts now include `practices` and
  `operation_templates`.
- Read model code: `app/management/practices.py` (deterministic ordering by
  pack_version → pack_code → code, mirroring deepening F-09).

## 6. Cover-crop trait vocabulary (for Increments 4's engine)

`app.management.contracts.COVER_CROP_TRAIT_CODES` documents the trait codes a
cover-crop species may carry (`cover_establishment_speed`,
`cover_growth_duration_days`, `cover_termination_methods`,
`cover_seeding_rate`, …). **The bundled pack ships no values for these** —
regional packs must bring them with sources; the candidate engine (Increment
4) treats missing traits as unevaluated dimensions.
