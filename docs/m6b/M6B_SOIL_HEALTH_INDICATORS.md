# M6B — Soil Health Indicators & Multi-Domain Assessment (`soil-health-profile-1.0.0`)

**Status:** implemented (as-built)
**Code:** `app/soil/assessment.py` (engine), `app/soil/service.py` (read models),
`src/components/croptwist/soil.tsx` (Soil tab).
**ADRs:** ADR-0026 (no composite index), ADR-0027 (comparability gate),
ADR-0028 (qualitative VOI).

---

## 1. The five domains

| Domain | Variables (from `DOMAIN_VARIABLES`) |
|---|---|
| `physical` | soil_sand_content, soil_silt_content, soil_clay_content, soil_bulk_density, soil_coarse_fragments, soil_particle_density |
| `chemical` | soil_ph, soil_electrical_conductivity, soil_available_phosphorus, soil_extractable_potassium, soil_cation_exchange_capacity, soil_total_nitrogen, soil_nitrate_n, soil_ammonium_n |
| `biological` | soil_microbial_biomass_c, soil_microbial_biomass_n, soil_respiration, soil_mineralizable_n, soil_earthworm_abundance, soil_enzyme_activity, soil_particulate_organic_matter |
| `hydrological` | soil_water_content_fc, soil_water_content_pwp |
| `organic_matter_nutrient_cycling` | soil_organic_carbon, soil_organic_matter |

The mapping is explicit and closed: a variable belongs to exactly one domain; the
assessment always emits all five domains, with empty domains shown as fully
missing.

## 2. Indicator rows (available indicators)

For each variable with history the assessment reports the LATEST row by date,
with: `variable_code`, `latest_value`, `unit`, `observed_at`,
`evidence_class`, `source_kind`, `quality_status`, `method` (from
`method_params.code`), `uncertainty`, `depth` `[top_cm, bottom_cm]`,
`interpretation_note` (descriptive context, no thresholds) and
`local_applicability` = "reference-grade — no regional confirmation; agronomist
review required for local claims". Rows with neither a value nor a result
qualifier are skipped. When ≥ 2 rows exist a `trend` block is attached (§4).

Per-domain payload: `available` rows, `missing` variable list, counts, a
data-quality note ("indicator rows keep their evidence class; mapped predictions
are listed but never mixed into measured series") and a `synthetic_flag` when any
measurement of that domain is synthetic.

## 3. Interpretation policy (no universal thresholds)

- Interpretation notes are **descriptive only** (e.g. OC: "central to soil
  function; the STOCK needs bulk density and depth — concentration alone is not
  a stock"; pH: "interpret only against method-matched references (medium +
  ratio), never a universal scale"; EC: "ECe is the standard salinity measure";
  BD: "compare only within the same basis and moisture conditions"; θFC/θWP:
  "bound the plant-available water window (FAO-56 context)").
- No numeric thresholds ship: salinity classes exist only for ECe, cited
  (FAO Soils Bulletin 62 (Abrol, Yadav & Massoud 1988), Table 4) and labelled
  indicative; pH screening against EcoCrop optima is labelled screening,
  confidence low.
- **Missing indicators are UNKNOWN** — their absence is not evidence of poor soil
  health (`missing_is_not_bad_note`).
- Biological measurements are stored with protocol metadata; nothing is simulated
  or inferred from missingness.

## 4. Comparability gate (ADR-0027)

A trend exists only when the gate passes. The gate compares method identity —
the tuple `(method_code, medium, soil_solution_ratio, bd_basis, unit)` — and the
depth support `(top_depth_cm, bottom_depth_cm)`:

| Condition | Result |
|---|---|
| fewer than 2 measurements | `comparable: false` — "fewer than two measurements — no trend" |
| method identity differs (e.g. pH water vs CaCl₂; measured vs SoilGrids) | `not_comparable` with the ADR-0023/0027 reason and the distinct key groups listed |
| depth support differs | `not_comparable` — "cross-depth trends are not computed" |
| identity + depth match | `comparable` |

A passing gate yields a `measured_change` trend: first/last (date, value, unit)
and `delta` (last − first), with the caveat "measured change over compatible
measurements; temporal association with management events is not causation".
Refused history is reported as not-comparable WITH the reason — never connected
silently.

## 5. No composite score (ADR-0026)

The result always carries `composite_score: None` and the note: "no composite
index is computed: no validated weighting methodology is available to the
platform; a transparent per-domain profile is the decision surface (ADR-0026)".
The frontend mirrors this ("soil health score" explicitly not offered). The
management-ledger association rule holds throughout: measured changes are
separated from expected mechanisms; events before a measurement are associations,
never causes.

## 6. Decision support & VOI (ADR-0028)

`data_readiness` ranks missing measurements qualitatively. Rules (checked in
order; a variable already present is never suggested):

| Variable | Trigger | Decision unblocked |
|---|---|---|
| soil_electrical_conductivity | any field without salinity evidence | salinity screening for crop choice (ECe classes; FAO Soils Bulletin 62) |
| soil_organic_carbon | concentration present without bulk density | SOC stock accounting (needs OC + BD + depth + coarse fragments) |
| soil_bulk_density | SOC stock not evaluable | SOC stock + porosity + FD-vs-ESM comparisons (one measurement, three calculations) |
| soil_water_content_fc | no water-retention evidence | measured root-zone AWC feeding the M6A water balance (replacing the texture-PTF estimate) |
| soil_water_content_pwp | no water-retention evidence | measured AWC (θFC − θWP) for the M6A water balance |
| soil_available_phosphorus | no P evidence | P availability context (extractant-specific) |
| soil_ph | no pH evidence | crop pH screening against EcoCrop optima (labelled screening) |

Policy text shipped with every response: "qualitative, decision-linked ranking
only: no sampling costs, expected benefits or statistical confidence are invented
(ADR-0028)". The `collected_note` closes the loop: newly collected measurements
enter through the sampling domain and the ranking re-evaluates automatically.

## 7. Snapshots and the read model

- `POST /fields/{id}/soil-assessments` evaluates all current measurements into an
  immutable `soil_assessment_runs` snapshot (engine + assessment versions, result
  JSONB, sha256 over `{engine, assessment, domains}`, idempotency-key support).
- `GET /fields/{id}/soil-health` returns the latest succeeded snapshot, or a
  `source: "live"` evaluation when none exists (clearly labelled, not persisted).
- The frontend Soil tab renders domain cards (available/missing, Expert mode),
  the profile explorer (depth bars, USDA badges, AWC, gap warnings), SOC and
  nutrient sections with not-evaluated lists, the lab import workspace with the
  per-row report, the readiness priorities and methodology accordions.
