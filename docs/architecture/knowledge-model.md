# Knowledge Model & Rotation Intelligence (Milestone 5)

Architecture doc. Normative rules live in `DECISIONS_AND_ASSUMPTIONS.md`
(ADR-0014..0018); the honesty protocol in `M5_GAP_ANALYSIS.md`.

## Module boundaries (extends docs/architecture/module-boundaries.md)

```
api/v1 ──► knowledge ──► db (models)            api/v1 ──► rotation ──► rotation core
              │                                               │
              └─ pack import validates + persists             ├─ context.py maps ORM → dataclasses
                                                              ├─ candidates.py (pure)
knowledge ──► data (packs bundled under app/knowledge/packs/) ├─ constraints.py (pure)
                                                              ├─ optimizer.py (ortools only)
rotation core (candidates/constraints/objectives/optimizer/   ├─ objectives.py (pure)
explain) NEVER imports FastAPI, SQLAlchemy or db models       └─ explain.py (pure)
```

- `app/knowledge/` — pack model, import/validation workflow, read services.
- `app/rotation/` — pure decision core + one service module that maps DB ↔
  dataclasses and persists runs. The core modules are unit-testable without PG.

## Data model (migration 0004_knowledge_rotation)

Platform-level (not tenant-scoped): `knowledge_packs`, `knowledge_sources`,
`crop_families`, `crops`, `crop_varieties`, `crop_traits`,
`crop_calendar_windows`, `crop_water_parameters`, `rotation_rules`.

Tenant-scoped: `crop_history` (field), `farmer_preferences` (farm),
`rotation_runs` + `rotation_strategies` (field).

Key semantics:

- `crop_traits`: row per (crop or variety, trait_code, region, management
  context, growth stage) — CHECK constraint: exactly one of crop/variety set.
  `value_numeric` XOR `value_text`; optional `value_low/value_high` ranges;
  `evidence_class`, `confidence` (high/moderate/low/unknown),
  `validation_status` (reference / locally_validated / confirmed_regional /
  retired), `valid_from/valid_to`, source FK, pack FK.
- `rotation_rules`: structured JSONB `rule_definition`
  (`{predecessor:{crop|family}, successor:{crop|family}, min_break_seasons,
  mechanism, severity}`), `applies_to_regions` (empty = global),
  `validation_status` — hard enforcement ONLY at `confirmed_regional`.
- `crop_calendar_windows`: `planting_start/end`, `harvest_start/end` as MM-DD,
  `hemisphere`, `region_code`, season_code, source FK, validation status.
- `rotation_runs`: full reproducibility snapshot — planning seasons, strategy
  profiles, water allocation, knowledge-pack versions+checksums, feature-run
  ids, crop-history ids, engine/solver versions, seed, solver status, wall
  time, infeasibility details, warnings.
- `rotation_strategies`: per-strategy assignment, weights, criteria
  (raw/normalized/weights/availability), constraint checks, Pareto position,
  explanation blocks, sha256 checksum.

## Trait vocabulary (seed pack v1, `kp-seed-2026.11`)

| trait_code | unit | source |
|---|---|---|
| stage_init/dev/mid/late_days | d | FAO-56 Table 11 |
| duration_days_total | d | FAO-56 Table 11 |
| kc_initial / kc_mid / kc_end | – | FAO-56 Table 11 (single Kc) |
| root_depth_effective_m | m | FAO-56 Table 22 |
| temp_min_abs_degC, temp_opt_min/max_degC | degC | FAO EcoCrop (range + confidence) |
| precip_min/max_annual_mm | mm | FAO EcoCrop |
| ph_opt_min/max | pH | FAO EcoCrop |
| n_fixation_capacity | kg N/ha/season (order) | Herridge et al. 2008 |

Absence is intentional: crops without a verified value simply have no row
(e.g. faba bean has no Kc rows → its water criteria are unevaluated).

## Rotation rules (seed pack v1)

All rules are `validation_status="reference"` with explicit mechanism text and
citations (Agrios 2005 for host–pathogen breaks; extension-level agronomy for
succession monotony). **None are regionally confirmed** — the hard
rotation-break constraint therefore binds on nothing in the seed pack; the
solver machinery is exercised by a confirmed-regional fixture in tests.

## Strategy profiles (M5.5)

`water_priority`, `soil_health_priority`, `balanced`, `economic_priority`,
`custom` (weights supplied per run / farmer_preferences). Criteria:
water_requirement_mm, soil_health_index, economic_margin_index (farmer-supplied
only), crop_family_diversity, climate_resilience_index, erosion_reduction_index,
cover_crop_opportunity. Each criterion documents its derivation and availability.
