# AGRONOMIC_KNOWLEDGE_AUDIT.md — Phase D (state of the knowledge system post-deepening)

## 1. Knowledge model (as-built)

Every attribute row carries: source FK (publisher/title/year/citation text),
evidence class, confidence enum, validation status
(`reference`/`locally_validated`/`confirmed_regional`/`retired`), region code,
optional management context and growth stage, unit, notes — pack-versioned
with content checksum. Species vs cultivar: `crop_traits` rows may attach to
`crops` XOR `crop_varieties` (DB-enforced XOR; variety-level Kc is modelled
but intentionally unresolved in the read slice and skipped, never merged into
species rows). Multiple values per trait under different contexts are
first-class (`code@region` keys; conflicts within one context rejected at
import). Pack lifecycle: draft → active → retired; drafts are inert; imports
are idempotent by (code, version) with checksum-conflict detection.

## 2. Crop taxonomy

Scientific name, common names, family (botanical, with scientific name),
genus/species via scientific_name, lifecycle type, crop category, legume and
cover-crop-capable flags. Cultivars exist as a table but the seed pack ships
none — "avoid merging varieties with materially different duration/water
response" is enforced structurally (variety rows) rather than by data (none
sourced yet; backlog K-5).

## 3. Phenology and development

Present: `duration_days_total`, FAO-56 stage lengths (init/dev/mid/late) for
10/11 crops, planting windows (hemisphere/region-scoped, evidence-classed,
13 windows declared `reference_synthesized`).
NOT present and NOT invented: GDD/base temperatures, photoperiod response,
vernalization, upper development temperature, phenological uncertainty —
these require crop-science sources not in the pack's source set
(backlog K-1). One universal duration is assumed per species today; regional
durations must arrive as region-scoped trait rows (structure ready).

## 4. Crop water physiology (FAO-56)

- `ETc = Kc × ET0` implemented as the ADR-0017 screening estimate: single-Kc
  curve reconstructed from the three sourced anchors (linear ramps), monthly
  ET0 climatology, sowing at season start — ALL assumptions returned with the
  estimate and displayed.
- Post-deepening guarantees: anchor vocabulary {initial, mid, late} enforced;
  incomplete anchor sets rejected at import (F-5); partial ET0 coverage
  refuses the estimate instead of under-reporting (F-7); zero-fill of missing
  anchors impossible at load (F-5).
- Dual-Kc, wetting-frequency/local-climate Kc adjustments, stage water
  sensitivity, root-zone extraction dynamics: correctly NOT implemented
  (require the M7 daily water balance); documented in the estimate caveat.

## 5. Nitrogen fixation and nutrient cycling

Present: `n_fixation_capacity_kg_ha` (Herridge et al. 2008) for the three
grain legumes; `is_legume` flag drives the soil-health composite. The
composite counts legume presence — it does NOT credit a fixed N contribution
to the following crop. Grain N export vs residue N vs net balance require
biomass/residue data the platform does not ingest (backlog K-2). A legume
never receives automatic positive N credit beyond the flag-based descriptor,
and the descriptor's semantics are stated in the criterion derivation.

## 6. Soil compatibility (species level, evidence-backed)

pH optima (EcoCrop ranges, low/high) evaluated against field soil pH with the
evidence class surfaced ("a 0–5 cm model prediction is not a lab measurement").
Outside-optimum → CONDITIONAL with citation, never silent exclusion. Salinity
tolerance, texture preferences, drainage/waterlogging sensitivity, compaction:
NOT in the pack (no verifiable source transcription available in this
sandbox) — backlog K-3 (FAO-29 ECe table is the identified source).

## 7. Residues and cover crops

`is_cover_crop_capable` + cover_crop_opportunity criterion (fraction of
seasons with legume/cover-capable crop). NOT claimed: residue quantities,
C:N ratios, decomposition dynamics, biomass — the erosion criterion is a
clearly-labelled soil-cover PROXY (duration/season-length). "A cover crop
always improves the next crop" is NOT assumed anywhere; cover-crop water
competition cannot be evaluated without the M7 water balance (backlog K-2).

## 8. Pest and disease knowledge

Rotation rules are structured (predecessor/successor as crop OR family,
min_break_seasons ≥ 1, mechanism text, region list, severity, source,
validation status). Family-scoped rules exist only where the cited mechanism
justifies them (Agrios soilborne-persistence rationale); region gating means
rules scoped elsewhere never apply; hard binding requires `confirmed_regional`
— the seed pack deliberately ships ZERO confirmed rules, so nothing binds
until a regional agronomist confirms (the UI states this; tests enforce it).
Host–pathogen structure exists (`host_pathogen` rule type) but species-level
pathogen entities (alternative hosts, survival structures, per-pathogen
break durations) are not modelled yet (backlog K-4).

## 9. Knowledge provenance completeness (exit criterion 3/5)

Every seed trait, Kc row, calendar window and rule carries source + citation +
evidence class + confidence (tests: `test_every_seed_trait_carries_source_and_citation`,
`test_every_seed_kc_row_has_source_and_confidence`). Crop detail API surfaces
citations. Deliberate gaps stay gaps (faba bean Kc; no drought/heat scores).
What remains unverified is explicit: all values are `reference` — regional
validation is pending by design, tracked in the validation workflow
(agronomist_reviews table exists; review UI is a later-milestone item).
