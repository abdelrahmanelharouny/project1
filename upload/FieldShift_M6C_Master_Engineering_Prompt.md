# FIELDSHIFT — M6C MASTER ENGINEERING PROMPT
## Field Management Intelligence: Cover Crops, Residue Management, Soil Cover, Erosion Screening & Operations Planning

**Project:** FieldShift — Global Agricultural Decision Intelligence Platform  
**Milestone:** M6C — Field Management Intelligence  
**Predecessors:** M1–M6A complete; M6B complete according to the latest implementation report  
**Execution mode:** Repository-first · scientifically grounded · incrementally implemented · independently verified  
**Scope restriction:** M6C only. Do not start M7 or unrelated roadmap modules.

---

# 0. EXECUTIVE DIRECTIVE

Build a practical, scientifically defensible **Field Management Intelligence** capability that converts crop-rotation plans, soil and water information, crop knowledge, field history, and farmer constraints into an explainable seasonal management plan.

M6C is not a generic farm ERP, a static crop calendar, or a simplistic cover-crop recommender. It must help a farmer or agronomist answer:

- When is the field likely to be without protective soil cover?
- Which management options could reduce that exposed period without creating unacceptable water, timing, pest, or operational trade-offs?
- What crop residues are available, how much is retained or removed, and what evidence supports those quantities?
- Which cover-crop candidates fit the local planting and termination windows, the following cash crop, water availability, equipment, and market or livestock needs?
- What field operations are required, in what sequence, and with which machinery and labor resources?
- Which operations conflict with one another or with crop, soil-moisture, weather, or field-access constraints?
- What erosion processes can be screened with the available evidence, and which cannot be assessed?
- Why was a practice suggested, excluded, or left unevaluated?

The key deliverable is an **explainable field management plan** connected to the existing rotation, water, soil, knowledge, and provenance systems.

## Non-negotiable principles

1. Reuse existing M1–M6B contracts and domain models; do not duplicate them.
2. Distinguish measured, farmer-reported, mapped, modeled, reference, expert-reviewed, and synthetic evidence.
3. Do not invent crop calendars, seeding rates, termination dates, residue coefficients, erosion factors, machinery capacities, labor availability, or weather forecasts.
4. Do not claim that a practice caused a measured soil or yield change from temporal association alone.
5. Do not treat a cover crop as universally beneficial: it can protect soil and recycle nutrients while also consuming water and competing with the following crop.
6. Do not turn a screening indicator into a quantitative prediction unless the selected methodology and inputs support it.
7. Do not silently relax operational or agronomic hard constraints.
8. Preserve source resolution and spatial limitations.
9. Every calculation and schedule must be reproducible and versioned.
10. The system must be allowed to return `not_evaluated`, `conditional`, `infeasible`, or `insufficient_evidence` rather than forcing a recommendation.

---

# 1. START BY INSPECTING THE REAL REPOSITORY

The previous implementation reports are context, not proof of the current working tree. Inspect the repository and verify the actual implementation before coding.

## 1.1 Required inspection

Inspect at minimum:

- Existing `app/` domain structure and application services.
- `app/water/` and M6A water contracts, methods, plans, and snapshots.
- `app/soil/` and M6B soil samples, layers, measurements, management ledger, soil assessments, and nutrient models.
- `app/knowledge/` crop traits, crop families, regional packs, evidence records, and rule applicability.
- `app/rotation/` plans, seasons, constraints, optimizer, candidate generation, and validation logic.
- M3 providers and environmental observations.
- M4 feature catalog and feature-run contracts.
- Data provenance, evidence classes, uncertainty policies, and versioning.
- Existing farm/field geometry, timezone, calendar, and tenant-isolation mechanisms.
- Frontend navigation, design system, map components, timelines, tables, offline support, and Simple/Expert modes.
- Migrations, indexes, test fixtures, API conventions, and documentation.

## 1.2 Verify baseline

Run the full backend suite, frontend lint/type checks, migration checks, and the available browser E2E path before changes. Record actual results and environment versions. Do not copy prior test counts into the new report unless freshly observed.

## 1.3 Reuse map

Produce `docs/m6c/M6C_GAP_ANALYSIS.md` with:

- Existing reusable entities and services.
- Existing management event types and whether they already cover proposed operations.
- Missing fields or relationships.
- Provider and knowledge requirements.
- Scientific assumptions that need references.
- API and UI integration points.
- Backward-compatibility risks.
- Scope boundaries and deferred items.

Do not create a second `management_events`, crop calendar, water-budget, or evidence registry if an equivalent domain already exists. Extend through additive migrations and explicit versioning.

---

# 2. M6C DOMAIN MODEL AND BOUNDARIES

M6C should contain the following cohesive capabilities. Keep them as modules within the existing architecture, not separate microservices.

## 2.1 Management Practice Knowledge

A versioned registry of practices and their requirements, intended mechanisms, evidence, risks, and regional applicability.

Examples:

- Cover cropping.
- Surface residue retention.
- Residue removal or baling.
- Residue incorporation.
- Mulching.
- Reduced tillage / strip tillage / no-till where locally appropriate.
- Contour operations.
- Strip cropping.
- Buffer strips or vegetated barriers.
- Controlled traffic where supported.
- Cover-crop termination methods.
- Field access and traffic management.

Do not represent these as universally beneficial switches. Each practice requires context, operating conditions, and trade-offs.

## 2.2 Soil Cover and Bare-Soil Window Intelligence

Represent field soil-cover status over time using available evidence:

- Living crop canopy.
- Living cover crop.
- Surface crop residue.
- Mulch or other protective cover.
- Bare or insufficiently observed surface.
- Unknown cover status.

Support both observed and modeled cover timelines. Preserve the method and evidence class. Do not infer measured percentage cover from NDVI without a validated, regionally applicable conversion model.

## 2.3 Cover-Crop Planning

Generate context-specific cover-crop candidates and compare their potential functions, establishment requirements, water use, termination needs, and compatibility with the next main crop.

## 2.4 Crop Residue and Biomass Accounting

Track residue production, harvest removal, collection, retention, incorporation, grazing, burning where legally relevant, and other documented fates. Keep dry-matter basis and nutrient/carbon content explicit.

## 2.5 Erosion and Conservation Screening

Screen relevant erosion hazards and evaluate management alternatives only within the domain supported by the selected model and evidence. Separate sheet/rill erosion, concentrated-flow/gully processes, wind erosion, streambank erosion, and sediment delivery.

## 2.6 Field Operations Planning

Convert rotation and management plans into tasks with windows, durations, precedence, machinery, labor, access, and resource constraints. Identify conflicts and unscheduled work transparently.

## 2.7 Practice Trade-off Evaluation

Compare practices across soil cover, erosion protection, water demand, nutrient cycling, crop establishment, pests/diseases, labor, machinery, costs, and market/livestock value where data exists.

## 2.8 Farmer Action Plan

Present a seasonal, editable and trackable calendar of operations, deadlines, dependencies, alerts, and reasons. Allow farmer and agronomist feedback.

---

# 3. KNOWLEDGE AND EVIDENCE MODEL

Every practice, cover crop trait, residue coefficient, operation requirement, and erosion parameter must be evidence-backed or explicitly unknown.

## 3.1 Required knowledge attributes

A knowledge record should support:

- `knowledge_code`
- `entity_type` and `entity_id`
- `attribute_code`
- `value` and `unit`
- `source_id` / `reference_id`
- publication or dataset version
- exact source location (page, table, section, formula, or dataset field when available)
- geographic applicability (country, region, agroecological zone, or geometry)
- soil/climate conditions
- crop species and cultivar applicability
- growth stage or operation stage
- validity interval
- evidence class
- uncertainty description or interval when supplied by the source
- review status
- license and attribution

## 3.2 Evidence classes

Preserve distinctions among:

- `field_measured`
- `laboratory_measured`
- `farmer_reported`
- `remote_sensing_estimate`
- `reanalysis_estimate`
- `model_estimate`
- `published_reference`
- `expert_reviewed_reference`
- `confirmed_regional`
- `synthetic_test_data`

A `published_reference` is not automatically `confirmed_regional`. A model estimate is not a field measurement. Synthetic data must never contribute to real-farm recommendations.

## 3.3 Regional applicability

Support regional knowledge packs with explicit coverage and versioning. Do not infer a regional recommendation from latitude or hemisphere alone. Crop seasons and cover-crop windows may depend on monsoon, irrigation, bimodal rainfall, elevation, local cultivar, and management system.

## 3.4 Conflicting evidence

If reputable sources disagree, store both claims and their context. Do not silently average incompatible recommendations. Provide an evidence conflict state and require expert review where the disagreement can change a decision.

---

# 4. COVER-CROP PLANNING ENGINE

This is a core M6C capability, but it must be a transparent candidate and planning engine, not a universal species ranking.

## 4.1 Cover-crop functional groups

Represent functions as evidence-backed traits, not fixed assumptions:

- Grasses / cereals: potential rapid ground cover, fibrous roots, nutrient capture, and residue production.
- Legumes: potential biological nitrogen fixation, subject to host compatibility, inoculation, biomass, growth, and management conditions.
- Brassicas and other broadleaf species: possible rooting, nutrient scavenging, biofumigation or other functions only where crop-specific evidence supports the claim.
- Mixtures: composition, seeding proportion, competitive interactions, and management complexity must be represented.

Do not infer function solely from family membership.

## 4.2 Candidate eligibility

For each field and between-crop window, evaluate:

- Locally valid sowing window.
- Time available for establishment and biomass accumulation.
- Crop duration and growth-stage development.
- Temperature and photoperiod requirements where documented.
- Frost or heat constraints where applicable.
- Soil texture, pH, salinity, drainage, and other relevant soil properties.
- Water availability and M6A demand estimates.
- Following cash-crop planting date.
- Termination method and equipment availability.
- Potential pest, disease, weed, or allelopathy concerns.
- Seed availability and local legality/invasiveness constraints where known.
- Livestock/forage value and grazing constraints if requested.
- Farmer preferences and budget.

Return candidate classes:

- `eligible`
- `conditional`
- `excluded`
- `not_evaluated`

Every condition and exclusion must be explained. Missing evidence must not become eligibility.

## 4.3 Water competition and termination

Integrate with M6A, not a parallel water model.

Evaluate potential cover-crop water use and the following crop's establishment risk only when appropriate Kc, crop-stage, water-balance, and calendar inputs are available.

Termination must be represented as a decision with:

- Target termination window.
- Method.
- Required machinery or labor.
- Time needed before next crop operations.
- Water implications.
- Biomass/residue implications.
- Regrowth or seed-set risk where relevant.
- Evidence and regional applicability.

Do not hardcode a universal termination lead time (for example, a fixed number of days before planting). Such timing is species-, climate-, soil-, method-, and crop-system-dependent.

## 4.4 Cover-crop output

For each candidate return:

- Species / cultivar or mixture identity.
- Intended function(s).
- Eligibility status.
- Planting window and its evidence.
- Establishment requirements.
- Expected duration only if supported.
- Water-demand profile or explicit missing-data status.
- Termination options and constraints.
- Following-crop compatibility.
- Benefits, trade-offs, and risks.
- Knowledge coverage and missing inputs.
- References and version identifiers.

Do not generate an agronomic recommendation when the minimum regional crop calendar or critical water/termination knowledge is absent. Return a research candidate or unevaluated option instead.

---

# 5. SOIL COVER AND BARE-SOIL WINDOW ENGINE

## 5.1 Temporal representation

Build an interval-based field cover timeline. Track:

- Main crop establishment and harvest.
- Cover-crop establishment and termination.
- Residue deposition and removal.
- Mulch events.
- Tillage or disturbance events.
- Remote-sensing cover observations when available.
- Farmer-observed cover measurements.
- Unknown intervals.

## 5.2 Coverage measures

Calculate transparent metrics such as:

- Number of days with known living cover.
- Number of days with known residue cover.
- Number of days with known bare surface.
- Unknown observation days.
- Longest observed uncovered interval.
- Fraction of the planning window with evidence of protective cover.
- Seasonal cover timeline.

Do not label all missing observations as bare soil. Use `unknown` where the status is not observed or inferable.

## 5.3 Cover thresholds

Do not apply a universal “safe cover percentage” or minimum cover threshold to every region and conservation standard.

Thresholds must be sourced, versioned, and scoped to the applicable practice standard or regional objective. If no threshold is applicable, report the actual cover metrics without pass/fail classification.

## 5.4 Spatial cover

If remote sensing is introduced or already available, distinguish:

- Vegetation index.
- Estimated fractional vegetation cover.
- Measured ground cover.
- Residue cover.
- Total protective cover.

NDVI alone cannot distinguish all forms of residue and green vegetation. Do not equate NDVI with percentage soil cover without a validated model and appropriate sensor/time conditions.

---

# 6. CROP RESIDUE AND BIOMASS MANAGEMENT ENGINE

## 6.1 Residue mass accounting

Represent residue flows on a dry-matter basis whenever possible:

- Above-ground biomass produced.
- Harvested product.
- Residue generated.
- Residue retained on surface.
- Residue incorporated.
- Residue removed or baled.
- Residue grazed.
- Residue burned or otherwise lost where relevant and legally recorded.
- Unknown/unaccounted fraction.

Use mass-balance checks. Never allow negative residue availability. Do not infer residue biomass from grain yield unless a crop-, cultivar-, environment-, and management-appropriate harvest-index or residue-to-product relationship is sourced and versioned.

## 6.2 Residue properties

Support where evidence exists:

- Dry matter.
- Carbon fraction.
- Nitrogen concentration.
- C:N ratio.
- Lignin or quality indicators where relevant.
- Particle size and orientation if relevant to cover/erosion modeling.
- Decomposition method and conditions.

Do not use one universal decomposition constant or C:N threshold across residues and climates.

## 6.3 Residue management trade-offs

Evaluate documented implications for:

- Surface protection.
- Soil organic carbon inputs.
- Nutrient recycling.
- Water infiltration and evaporation.
- Seedbed and planting interference.
- Pest/disease carryover.
- Livestock feed value.
- Bioenergy or market value.
- Removal costs and machinery.

Do not assume residue retention is always optimal. Balance soil protection and nutrient cycling against feed, fuel, market, and operational requirements. Surface cover benefits and removal risks must be interpreted in the field and regional context.

## 6.4 Integrate with M6B

Reuse M6B management events, nutrient budgets, and soil profile contracts. Record residue events so that subsequent nutrient accounting and soil-carbon analyses can consume them with provenance.

A residue input is not automatically equivalent to stable soil organic carbon sequestration. Keep carbon input, decomposition, and SOC stock change conceptually separate.

---

# 7. EROSION AND CONSERVATION RISK INTELLIGENCE

This area requires strict model applicability controls.

## 7.1 Erosion process taxonomy

Keep distinct:

- Sheet/interrill erosion.
- Rill erosion.
- Ephemeral gully erosion.
- Classical gully erosion.
- Wind erosion.
- Streambank/channel erosion.
- Deposition and sediment delivery.

A model designed for rainfall-driven sheet and rill erosion must not be presented as estimating all erosion processes.

## 7.2 Terrain and hydrology inputs

Potential inputs include:

- Slope and aspect.
- Slope length / flow path.
- Curvature.
- Flow accumulation.
- Convergent areas.
- Soil erodibility properties.
- Rainfall erosivity.
- Infiltration/runoff evidence.
- Surface cover and residue.
- Crop sequence and tillage operations.
- Conservation support practices.

Do not calculate slope length from a DEM using a naive straight-line distance. Flow routing, concentrated flow, terraces, and deposition boundaries matter.

## 7.3 RUSLE/RUSLE2 adapter policy

If RUSLE/RUSLE2 is implemented or integrated, treat it as a model-specific pathway for rainfall-driven sheet and rill erosion within its supported assumptions.

The familiar USLE structure is:

`A = R × K × LS × C × P`

However:

- Factor units and definitions must follow the selected RUSLE version and regional parameter set.
- Do not combine factor values from incompatible unit systems.
- Do not use US-specific NRCS factor databases as global defaults.
- Do not invent R, K, C, or P values.
- Do not assume DEM resolution guarantees accurate slope-length estimation.
- Do not label the result as watershed sediment yield.
- Do not claim coverage of ephemeral gullies, classical gullies, wind erosion, or channel erosion unless a separate validated model supports them.

Where inputs or regional factors are missing, return `screening_only` or `not_evaluated`, with a clear reason.

## 7.4 Erosion risk screening

A qualitative screening pathway may identify evidence of concern from slope, soil, rainfall, cover, and management records. It must remain a screening result, not a numeric soil-loss prediction.

Keep these outputs separate:

- Evidence of erosion susceptibility.
- Model-estimated sheet/rill soil loss.
- Field-observed erosion signs.
- Unknown erosion status.

## 7.5 Management alternatives

Compare practices such as:

- Maintain surface residues.
- Establish cover crops.
- Adjust tillage timing or intensity.
- Contour-aligned operations.
- Strip cropping.
- Vegetated barriers/buffer strips.
- Field traffic management.

Only evaluate a practice quantitatively if the model has appropriate parameters and local applicability. Otherwise provide a sourced qualitative mechanism and identify local design requirements.

---

# 8. FIELD OPERATIONS AND RESOURCE SCHEDULING ENGINE

This is a practical differentiator: FieldShift should help turn a rotation plan into an executable sequence of farm operations.

## 8.1 Operation templates

Support configurable templates for relevant operations, for example:

- Residue chopping or spreading.
- Tillage or seedbed preparation.
- Soil sampling.
- Cover-crop seeding.
- Main-crop planting.
- Fertilizer/manure application.
- Irrigation operations.
- Cover-crop termination.
- Spraying where legally and operationally relevant.
- Harvest.
- Residue baling/removal.
- Post-harvest field preparation.

Operations must be derived from the actual crop/management plan and regional operation templates. Do not generate every possible operation for every crop.

## 8.2 Operation data model

Each operation should support:

- Operation type.
- Field or management-zone scope.
- Related crop and season.
- Earliest start and latest finish.
- Preferred window.
- Duration or workload estimate.
- Area or quantity.
- Required machinery.
- Required implement.
- Labor skill/capacity.
- Fuel/material requirements where recorded.
- Predecessor and successor tasks.
- Soil condition restrictions.
- Weather restrictions.
- Access/trafficability restrictions.
- Completion state.
- Evidence and source of the operation template.

Keep planned, scheduled, started, completed, delayed, cancelled, and blocked states distinct.

## 8.3 Resource registry

Support optional farmer-provided records for:

- Tractors.
- Implements.
- Seeders.
- Sprayers.
- Harvesters.
- Balers.
- Irrigation equipment.
- Contractors.
- Labor crews.
- Storage and transport capacity.

Include availability calendar, capacity, compatibility, working width, field efficiency where known, and maintenance/unavailability periods.

Do not assume resource capacity or machine speed if not supplied or sourced.

## 8.4 Scheduling model

Use an appropriate scheduling formulation, potentially OR-Tools CP-SAT interval variables, only after inspecting existing optimization abstractions.

Support:

- Precedence constraints.
- Non-overlap constraints for exclusive resources.
- Resource capacity constraints.
- Operation windows.
- Labor availability.
- Machinery availability.
- Field access constraints.
- Setup/travel time where data exists.
- Weather and soil condition windows where actual forecasts/measurements and valid thresholds exist.
- Priority levels and farmer-selected objectives.

Do not present a schedule as guaranteed executable when weather forecasts, machinery availability, or field conditions are unknown.

## 8.5 Soil trafficability and compaction risk

Only evaluate trafficability if the system has defensible inputs and a valid method, such as soil moisture/consistency, texture, machine axle load, tire pressure, and relevant field/soil parameters.

Do not invent a universal soil-moisture threshold for machinery entry.

When the required inputs are missing, display a manual field-readiness check rather than an automatic pass.

## 8.6 Weather windows

Historical climate data is not a weather forecast.

Do not use climate normals as if they were next-week forecasts.

Allow forecast information only through an explicit forecast provider or farmer-entered forecast. Record forecast issue time, valid time, provider, uncertainty, and expiration.

If no forecast exists, schedule within agronomic date windows and clearly label weather checks as pending.

## 8.7 Schedule explanations

For every unscheduled or delayed task, explain the cause:

- No available machine.
- Labor conflict.
- Predecessor incomplete.
- Outside sowing/harvest window.
- Water allocation conflict.
- Weather information missing.
- Soil trafficability unevaluated.
- Required agronomic knowledge missing.

Never silently drop a task to produce a visually clean calendar.

---

# 9. PRACTICE TRADE-OFF AND DECISION ENGINE

Compare management alternatives across multiple dimensions:

- Soil cover duration.
- Surface residue availability.
- Erosion susceptibility or modelled sheet/rill soil loss, if supported.
- Water demand and following-crop water risk.
- Nutrient cycling.
- Soil organic matter input potential.
- Crop establishment and termination risk.
- Pest/disease concerns.
- Labor and machinery demand.
- Cost and revenue where evidence exists.
- Forage/livestock value where relevant.

Separate hard constraints from soft objectives.

Generate candidate plans such as:

- Baseline farmer practice.
- Residue-retention-oriented plan.
- Cover-crop-oriented plan.
- Water-conserving cover/termination plan.
- Erosion-control-oriented plan.
- Balanced management plan.

Do not preselect a plan as globally best. Use Pareto-aware comparison and display trade-offs. Preserve unevaluated criteria and distinguish evidence coverage from outcome confidence.

---

# 10. DATA MODEL AND DATABASE DESIGN

Inspect current M6A/M6B tables and reuse existing management events, crop plans, soil samples, water plans, and provenance structures.

Potential logical entities, to be adapted rather than blindly copied:

- `practice_definitions`
- `practice_knowledge_records`
- `practice_evidence_links`
- `soil_cover_observations`
- `cover_crop_plans`
- `cover_crop_plan_items`
- `cover_crop_establishment_events`
- `cover_crop_termination_events`
- `crop_residue_records`
- `residue_flow_events`
- `residue_quality_measurements`
- `erosion_assessment_runs`
- `erosion_model_parameters`
- `erosion_assessment_results`
- `operation_templates`
- `field_operations`
- `operation_dependencies`
- `farm_resources`
- `resource_availability`
- `operation_schedule_runs`
- `scheduled_operations`
- `schedule_conflicts`
- `management_plan_snapshots`

Required properties:

- UUID primary keys.
- Tenant and farm/field scoping.
- Explicit geometry/management-zone relationship where relevant.
- Timezone-aware timestamps.
- Canonical units plus preservation of original units.
- Evidence class and source lineage.
- Knowledge and algorithm version.
- Immutable run snapshots.
- Audit actor and timestamps.
- Idempotent imports/jobs where applicable.

Use relational columns for core domain fields. JSONB may hold flexible source-specific metadata but must not replace structured, queryable fields.

Provide additive, downgrade-safe migrations consistent with project conventions.

---

# 11. API CONTRACTS

Follow existing `/api/v1/` patterns, tenant isolation, pagination, validation, error shape, idempotency, and background job conventions.

Candidate route groups (adjust to existing API architecture):

## Soil cover

- `GET /fields/{field_id}/soil-cover/timeline`
- `POST /fields/{field_id}/soil-cover/observations`
- `GET /fields/{field_id}/bare-soil-windows`

## Cover crops

- `GET /fields/{field_id}/cover-crop-candidates`
- `POST /fields/{field_id}/cover-crop-plans`
- `GET /cover-crop-plans/{plan_id}`
- `POST /cover-crop-plans/{plan_id}/evaluate`

## Residues

- `POST /fields/{field_id}/residue-assessments`
- `POST /fields/{field_id}/residue-events`
- `GET /fields/{field_id}/residue-ledger`

## Erosion

- `POST /fields/{field_id}/erosion-assessments`
- `GET /erosion-assessments/{run_id}`
- `GET /fields/{field_id}/conservation-options`

## Operations

- `GET /fields/{field_id}/operation-templates`
- `POST /fields/{field_id}/operations`
- `GET /fields/{field_id}/operations`
- `POST /fields/{field_id}/operation-schedule-runs`
- `GET /operation-schedule-runs/{run_id}`
- `GET /fields/{field_id}/resource-conflicts`

## Management plans

- `POST /fields/{field_id}/management-plans`
- `GET /fields/{field_id}/management-plans`
- `GET /management-plans/{plan_id}`
- `POST /management-plans/{plan_id}/feedback`

Every response must expose status semantics, assumptions, missing data, provenance, and version identifiers where relevant.

---

# 12. FRONTEND AND FARMER EXPERIENCE

Create a dedicated **Management** tab or workspace consistent with the current FieldShift design system.

## 12.1 Management Overview

Show:

- Current crop/rotation context.
- Next key operations.
- Upcoming management windows.
- Known bare-soil periods.
- Cover-crop plan status.
- Residue status.
- Resource conflicts.
- Unresolved agronomic checks.

## 12.2 Cover Crop Studio

Provide:

- Candidate list with eligibility state.
- Functional traits.
- Sowing and termination windows.
- Water trade-offs from M6A.
- Following-crop compatibility.
- Evidence and limitations.
- Side-by-side comparison.

## 12.3 Soil Cover Timeline

Show crop canopy, cover crop, residue, bare/unknown intervals, and management events as separate tracks. Use patterns/labels as well as colors so the interface remains accessible.

## 12.4 Residue Ledger

Show residue production, harvest export, retention, incorporation, removal, grazing, and unknown flows. Clearly indicate dry-matter basis and estimated versus measured values.

## 12.5 Erosion & Conservation Workspace

Display the assessed erosion process, model/method, input coverage, and limitations. Keep screening results separate from quantitative model outputs.

## 12.6 Operations Calendar

Provide calendar and timeline views with:

- Planned operations.
- Dependencies.
- Machinery/labor assignments.
- Conflicts.
- Blocked/unscheduled tasks.
- Farmer override and confirmation.
- Actual completion logging.

## 12.7 Simple and Expert modes

Simple Mode should communicate practical actions and important risks in farmer-friendly language.

Expert Mode should reveal model details, parameters, sources, units, geometry, uncertainty, and constraints.

Do not hide a critical limitation in Simple Mode.

## 12.8 Offline behavior

Reuse the existing PWA/IndexedDB synchronization pattern. Allow users to view cached plans and record field operations offline. Use idempotent synchronization and conflict handling. Do not overwrite concurrent edits silently.

---

# 13. SECURITY, AUDIT AND RELIABILITY

- Enforce tenant isolation for every new entity and query.
- Scope idempotency keys by tenant and operation as appropriate.
- Record the actor for user-created and system-generated changes.
- Audit changes to operation schedules and management plans.
- Keep historical plan snapshots immutable.
- Validate GeoJSON and spatial extents.
- Limit upload sizes and validate file formats.
- Avoid storing sensitive personal data in free-text logs.
- Apply authorization to agronomist review and farmer actions.
- Do not expose another tenant's resource availability, field geometry, or farm records.
- Make background jobs retry-safe and idempotent.

---

# 14. TESTING AND SCIENTIFIC BENCHMARKS

Do not set an arbitrary target test count. Build tests from the actual domain invariants and reference cases.

## 14.1 Cover-crop tests

- Regional sowing-window validity.
- Establishment-window duration.
- Growth duration and following-crop timing.
- Missing crop traits.
- Water-competition behavior.
- Termination method/equipment compatibility.
- Invasive/legal restriction handling where knowledge exists.
- Mixture composition and percentages.
- Evidence and provenance preservation.

## 14.2 Soil-cover timeline tests

- Crop harvest and establishment intervals.
- Residue deposition/removal events.
- Unknown versus bare distinction.
- Overlapping cover sources.
- Missing observations.
- Calendar timezone boundaries.
- Cover-duration calculations.
- Sourced threshold applicability.

## 14.3 Residue accounting tests

- Dry-matter unit conversion.
- Mass conservation.
- Harvest-product versus residue distinction.
- Retained/removed/incorporated/grazed flows.
- Missing residue production coefficients.
- No negative residue balance.
- Nutrient and carbon linkage to M6B without double counting.

## 14.4 Erosion tests

- RUSLE factor unit compatibility.
- Missing factor refusal.
- Local parameter-set validation.
- DEM/resolution limitations.
- Slope and flow path geometry.
- RUSLE domain restrictions.
- Gully/wind/channel process separation.
- Screening versus modeled result semantics.

## 14.5 Scheduling tests

- Operation precedence.
- Resource non-overlap.
- Capacity constraints.
- Availability calendars.
- Duration calculations.
- Unscheduled task reporting.
- Missing forecast behavior.
- Soil trafficability unknown behavior.
- No silent hard-constraint relaxation.
- Deterministic run reproduction.

## 14.6 Cross-module tests

- M5 crop rotation plans supply correct season/crop context.
- M6A water estimates are reused, not recalculated inconsistently.
- M6B residue and nutrient ledgers receive correct events.
- Evidence classes survive every calculation.
- Synthetic and real records remain separate.
- Tenant isolation and authorization remain intact.
- Versioned snapshots are immutable.

Use independent worked examples where available. Do not calculate expected test values by calling the same implementation under test.

## 14.7 Property-based and metamorphic tests

Examples:

- A task requiring one exclusive machine cannot overlap another task assigned to the same machine.
- A schedule must respect every hard precedence constraint.
- A residue ledger cannot have a negative physical mass balance.
- A missing cover observation must not become a bare-soil observation.
- Increasing a cover-crop duration must not silently move termination outside the following crop's permissible window.
- Missing water data must not produce a water-safe classification.
- A RUSLE assessment without required factors must not return a numeric soil-loss estimate.
- Equivalent unit representations must produce equivalent physical quantities.

Ensure tests reflect the model assumptions and do not encode unsupported universal agronomic rules.

---

# 15. IMPLEMENTATION SEQUENCE

Implement M6C in small, independently verifiable increments.

## Increment 1 — M6C readiness and domain design

- Inspect repository and baseline.
- Reuse map.
- Define practice ontology.
- Define soil-cover temporal model.
- Define residue flow model.
- Define operation/resource model.
- Document scientific references and applicability.

Acceptance: approved as-built gap analysis, domain map, and contracts before major coding.

## Increment 2 — Management knowledge and provenance

- Practice definitions.
- Regional applicability.
- Evidence references.
- Versioning and licensing.
- Candidate trait schemas.

Acceptance: no unsupported practice is silently treated as validated.

## Increment 3 — Soil cover and bare-soil timeline

- Management event mapping.
- Cover observation ingestion.
- Interval construction.
- Bare/unknown distinction.
- Cover metrics.

Acceptance: timeline can be reconstructed from versioned events and observations.

## Increment 4 — Cover-crop candidate and planning engine

- Candidate eligibility.
- Sowing and termination windows.
- Water integration.
- Following-crop constraints.
- Trade-off explanations.

Acceptance: candidates are classified and explained without fabricated traits.

## Increment 5 — Residue and biomass ledger

- Dry-matter mass flows.
- Residue quality.
- Retention/removal/incorporation.
- M6B nutrient linkage.
- Soil cover linkage.

Acceptance: mass balance checks and no double counting.

## Increment 6 — Erosion and conservation screening

- Process taxonomy.
- Terrain/data readiness.
- Optional RUSLE2-compatible adapter only if valid inputs and parameters exist.
- Qualitative screening where appropriate.
- Conservation alternative comparison.

Acceptance: no unsupported erosion quantity or universal risk label.

## Increment 7 — Operations and resource scheduling

- Operation templates.
- Machinery/labor registry.
- Precedence graph.
- Scheduling solver.
- Conflict explanation.
- Actual completion tracking.

Acceptance: schedules respect constraints and explain unscheduled work.

## Increment 8 — Management plan and frontend

- Management overview.
- Cover-crop studio.
- Cover timeline.
- Residue ledger.
- Erosion workspace.
- Operations calendar.
- Simple/Expert modes.
- Offline integration.

Acceptance: complete user journey works in the browser.

## Increment 9 — Cross-module integration and hardening

- M5 rotation integration.
- M6A water integration.
- M6B soil/nutrient integration.
- Security and tenant tests.
- Performance review.
- Regression tests.
- Documentation and browser verification.

Acceptance: M6C functionality works end-to-end without regressions to M1–M6B.

---

# 16. REQUIRED DOCUMENTATION

Create `docs/m6c/` containing at least:

- `M6C_GAP_ANALYSIS.md`
- `M6C_AS_BUILT_DESIGN.md`
- `M6C_PRACTICE_KNOWLEDGE_MODEL.md`
- `M6C_COVER_CROP_METHODOLOGY.md`
- `M6C_SOIL_COVER_AND_BARE_SOIL_METHOD.md`
- `M6C_RESIDUE_MASS_BALANCE.md`
- `M6C_EROSION_SCREENING_AND_MODEL_SCOPE.md`
- `M6C_OPERATIONS_SCHEDULING_MODEL.md`
- `M6C_DATA_DICTIONARY.md`
- `M6C_DATABASE_AND_MIGRATION_DESIGN.md`
- `M6C_API_CONTRACTS.md`
- `M6C_UNCERTAINTY_AND_EVIDENCE_POLICY.md`
- `M6C_TEST_AND_BENCHMARK_REPORT.md`
- `M6C_RESEARCH_BACKLOG.md`
- `M6C_VERIFICATION_REPORT.md`

Update existing implementation status, README, test matrix, data dictionary, ADR registry, and API docs.

Every document must describe actual implemented behavior, not intended future behavior.

---

# 17. ACCEPTANCE CRITERIA AND EXIT GATES

M6C may be marked complete only when all applicable gates pass:

1. Repository baseline freshly verified.
2. No duplicate soil, water, crop, management, or provenance domain was introduced.
3. Practice knowledge is versioned, sourced, and regionally scoped.
4. Soil-cover timeline distinguishes covered, bare, and unknown intervals.
5. Cover-crop candidates preserve eligibility, conditionality, exclusion, and unevaluated states.
6. Water competition and termination trade-offs integrate with M6A where supported.
7. Residue accounting is mass-consistent and dry-matter aware.
8. Nutrient and carbon linkages do not double-count flows.
9. Erosion output distinguishes screening from model-derived soil-loss estimates.
10. RUSLE/RUSLE2 use is restricted to supported erosion processes and valid parameter sets.
11. Field operation schedules preserve dependencies and resource constraints.
12. Unknown forecasts, machine capacity, labor availability, and field trafficability remain unknown.
13. Every unscheduled operation has a reason.
14. Provenance and uncertainty survive all new pipelines.
15. Tenant isolation, idempotency, and audit semantics are verified.
16. APIs and frontend work end-to-end.
17. Offline changes synchronize without silent overwrite.
18. Full regression, lint/type checks, migrations, and browser E2E pass.
19. Scientific assumptions and remaining gaps are documented.
20. No M7 work has started.

External field validation must not be claimed unless it actually occurred.

---

# 18. SCIENTIFIC REFERENCE STARTING POINTS

Use primary, official, or technically authoritative references. Verify the actual document, version, scope, and applicability before encoding any value or rule.

## Soil cover and conservation agriculture

1. FAO — Soil Organic Cover in Conservation Agriculture:  
   https://www.fao.org/conservation-agriculture/in-practice/soil-organic-cover/en/

2. FAO — Conservation Agriculture principles:  
   https://www.fao.org/conservation-agriculture/en/

3. FAO — How to Practice Conservation Agriculture:  
   https://www.fao.org/agriculture/crops/thematic-sitemap/theme/spi/scpi-home/managing-ecosystems/conservation-agriculture/ca-how/en/

## Cover crop planning and termination

4. USDA NRCS — Cover Crop Conservation Practice Standard (Code 340):  
   https://www.nrcs.usda.gov/resources/guides-and-instructions/cover-crop-ac-340-conservation-practice-standard

5. USDA NRCS — Cover Crop Termination technical sheet:  
   https://www.nrcs.usda.gov/sites/default/files/2025-04/Cover_Crop_Termination-FS_0.pdf

6. USDA NRCS — Cover Crops for Soil Health:  
   https://www.nrcs.usda.gov/conservation-basics/soil/soil-health/cover-crops-for-soil-health

7. NC State Extension — Soil Moisture Challenge for Cover Crops:  
   https://covercrops.ces.ncsu.edu/soil-moisture-challenge/

## Residue management

8. USDA NRCS — Harvesting Crop Residue:  
   https://www.nrcs.usda.gov/sites/default/files/2024-10/HarvestingCropResidueOctober2016.pdf

9. USDA NRCS — National Agronomy Manual, Water Management / residue effects:  
   https://directives.nrcs.usda.gov/sites/default/files2/1719337255/National%20Agronomy%20Manual.pdf

## Erosion processes and modeling

10. USDA NRCS — RUSLE2 technology and scope:  
    https://www.nrcs.usda.gov/resources/tech-tools/water-erosion-rusle2

11. USDA NRCS — RUSLE2 Handbook:  
    https://www.nrcs.usda.gov/sites/default/files/2022-10/RUSLE2%20Handbook_0.pdf

12. USDA ARS — RUSLE2 definitions:  
    https://www.ars.usda.gov/southeast-area/oxford-ms/national-sedimentation-laboratory/watershed-physical-processes-research/research/rusle2/revised-universal-soil-loss-equation-2-rusle2-definitions/

13. FAO — Revised Universal Soil Loss Equation:  
    https://www.fao.org/land-water/land/land-governance-and-planning/land-resources-planning-toolbox/detail/revised-universal-soil-loss-equation/en

14. USDA NRCS — National Agronomy Manual, Water Erosion:  
    https://www.nrcs.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf

## Operations scheduling

15. ASABE — Scheduling of Robotics or Machinery Operations in Agricultural Fields: A Review (2024):  
    https://elibrary.asabe.org/abstract.asp?aid=54815&redir=&redirType=&t=3

Treat these as starting points, not blanket authorization to apply regional standards globally. Record source version, regional applicability, and relevant sections.

---

# 19. STRICT EXECUTION RULES FOR GLM

- Inspect actual code before planning changes.
- Do not claim completion based on documentation alone.
- Do not replace real data with synthetic data in production pathways.
- Do not invent cover-crop species parameters or planting windows.
- Do not apply universal termination lead times.
- Do not assume residue-to-grain ratios or harvest indices.
- Do not equate residue mass with soil organic carbon sequestration.
- Do not assume cover crops always conserve water.
- Do not equate NDVI with measured soil cover.
- Do not use RUSLE2 to represent all erosion processes.
- Do not use US-specific erosion factor databases as global defaults.
- Do not treat historical climate as a weather forecast.
- Do not assume machinery/labor availability.
- Do not silently remove unscheduled or conflicting operations.
- Do not turn missing evidence into zero, false, safe, or eligible.
- Do not claim causal practice impacts from observational association.
- Do not start M7 or other unrelated roadmap modules.

For each increment: inspect → specify → implement → test → document → browser verify where relevant.

At the end, provide a concise but evidence-rich report listing actual code changes, migrations, tests, browser checks, scientific references, unresolved limitations, and the exact completion status of each acceptance gate.

