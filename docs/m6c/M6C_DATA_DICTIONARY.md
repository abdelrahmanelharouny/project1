# M6C — Data Dictionary

Canonical vocabularies introduced by M6C (all enforced by CHECK constraints
or Pydantic schemas; single source of truth in
`app/db/models.py` + `app/management/contracts.py`).

## Cover states (`soil_cover_observations.cover_state`)
`living_main_crop · living_cover_crop · surface_residue · mulch · bare ·
unknown · mixed`

## Cover measurement bases
`visual_estimate · line_point_transect · canopy_scope · quadrat ·
remote_sensing_index · unknown`

## Candidate eligibility (cover crops)
`eligible · conditional · excluded · not_evaluated`

## Cover-crop trait codes (values only with sources; ADR-M6C-2)
`cover_establishment_speed, cover_growth_duration_days,
cover_sowing_window_note, cover_frost_tolerance, cover_water_use_note,
cover_termination_methods, cover_seeding_rate, cover_seed_availability_note,
cover_invasiveness_risk, cover_forage_value_note,
cover_biomass_potential_note, cover_n_scavenging_note`

## Residue
- basis: `dry_matter` (canonical) · `fresh_weight` (requires supplied
  dry-matter fraction to convert)
- production_status: `measured · farmer_reported · coefficient_estimate`
  (requires provenance) `· missing`
- flow_type: `retained_surface · incorporated · removed_baled · grazed ·
  burned · other_loss · unknown`
- dm_kg_status: `measured · farmer_reported · estimated · unknown`
- balance status: `balanced · over_allocated · production_unknown`
- quality fields: `carbon_fraction` (%), `nitrogen_pct` (%), `cn_ratio`,
  `lignin_pct` — all optional, evidence-classed

## Erosion
- processes: `sheet_interrill · rill · ephemeral_gully · classical_gully ·
  wind · streambank · sediment_delivery`
- assessment kinds: `qualitative_screening` (never numeric) ·
  `screening_only` (RUSLE-family, sheet/rill only)
- RUSLE factor envelope: `{value, source_reference, region_scope,
  unit_convention}` × {R, K, LS, C, P}; unit conventions: `us_customary ·
  metric_si` (mixing refused)
- slope classes: `flat · gentle · moderate · steep · unknown`

## Operations
- statuses: `planned · scheduled · started · completed · delayed ·
  cancelled · blocked` (scheduler also reports `unscheduled` per run)
- dependency types: `finish_to_start · start_to_start · finish_to_finish`
  (finish_to_start is the scheduled type)
- resource types: `tractor · implement · seeder · sprayer · harvester ·
  baler · irrigation_equipment · contractor · labor_crew · storage ·
  transport · other`
- unscheduled reason codes: `no_duration, no_workday_length,
  no_resource_of_type, unknown_resource, unknown_resource_type,
  window_too_short_for_duration, resource_requirement_incomplete,
  predecessor_unschedulable`
- checks: `weather_check = pending` · `soil_readiness_check =
  manual_required` (always, until real forecast/trafficability evidence
  exists)

## Practices
- families: `cover_crop · residue · tillage · soil_cover ·
  erosion_control · traffic · termination`
- claim kinds: mechanisms / requirements (kind: seed·equipment·labor·
  knowledge·window·other) / trade-offs (direction: positive·negative·
  context_dependent) / risks / regional_applicability (region_code or
  agroecological_zone + declared basis)
- trade-off dimensions: `soil_cover, erosion_protection, water_demand,
  nutrient_cycling, soil_organic_matter, crop_establishment,
  pests_diseases, labor, machinery, cost, revenue, forage_value`
- validation vocabulary: inherited from M5 (`reference ·
  locally_validated · confirmed_regional · retired`)

## Management plan sections (result JSONB)
`season_context · soil_cover · cover_crop · residue · erosion · operations ·
practice_guidance · water · checks` — every section present with `status ∈
{evaluated, not_evaluated}` + message when unevaluated; checks are
`{code, severity: warning|info, message}`.
