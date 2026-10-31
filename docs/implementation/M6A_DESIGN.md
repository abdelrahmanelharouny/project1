# M6A — Water Intelligence Engine: Design & Methodology Specification

**Status:** implemented (this document is the as-built specification)
**Engine version:** `water-engine-1.0.0` · **Methods version:** `water-methods-1.0.0`
**Related ADRs:** extends ADR-0014 (knowledge honesty), ADR-0015 (pure decision
core), ADR-0016 (candidate gating), ADR-0017 (screening ETc); introduces
ADR-0019 (water methodology layering), ADR-0020 (soil water-holding sources),
ADR-0021 (effective-rainfall methods).

---

## 1. Position in the architecture

M6A adds a **water decision layer** between the feature store (M4 evidence)
and the rotation optimizer (M5). It answers: *given this field, this crop
sequence, this climate evidence, this soil, and this farmer allocation — how
much water does the plan need, where does it come from, when does it fall
short, and how confident is each number?*

Layering (ADR-0019 — methodology ladder, each level disclosed when used):

1. **ETc layer** (always, when Kc + ET0 exist): FAO-56 single-Kc crop
   evapotranspiration. `ETc = Kc × ET0`. Provider ET0 only (ERA5 product,
   FAO-56 reference surface) — the platform computes NO local ET0 (no
   radiation/humidity evidence; backlog W-6). ET0 (reference surface) and ETc
   (crop surface) are carried as separate, labelled quantities end-to-end.
2. **Effective rainfall layer** (when precipitation evidence exists): the
   fraction of rainfall usable by the crop. Methods below; never
   "P − ET0" (that is the climatic balance feature, explicitly NOT an
   irrigation-requirement quantity).
3. **Root-zone balance layer** (only when soil water-holding inputs exist):
   FAO-56-style TAW/RAW/Dr accounting with a stress coefficient Ks. Missing
   soil inputs ⇒ this layer reports "(not evaluated)" and the plan falls back
   to the FAO-33 seasonal method (IN = ETc − Pe), which is disclosed.
4. **Irrigation requirement ladder** (explicit water-balance equations):

   ```
   net_irrigation_requirement  NIR = max(0, ETc − Pe − ΔSW)
   gross_irrigation_requirement GIR = NIR / Ea        (only when Ea exists)
   actual_applied              = farmer records (usually unknown → "unknown")
   allocation                  = farmer-supplied m³ per season (never inferred)
   ```
   `ΔSW` = soil-water contribution (root-zone depletion change + stored water
   usable in the season; from layer 3; otherwise the term is "not evaluated"
   and NIR falls back to `max(0, ETc − Pe)` with the fallback disclosed).

5. **Rotation integration**: the CP-SAT allocation constraint uses the most
   precise evaluable demand: NIR (layer 4) when evaluable, else ETc (layer 1)
   — an upper bound because NIR ≤ ETc when Pe ≥ 0 (conservative direction,
   documented in the constraint detail).

## 2. Units (hard rules)

- Depths: mm. Volumes: m³ (solver arithmetic in litres: 1 mm·m² = 1 L).
- **1 mm over 1 ha = 10 m³** (unit conversion identity, property-tested).
- θ in m³/m³. Volumetric and gravimetric soil water are never silently mixed.
- Engine outputs rounded to 4 dp (checksum-stable convention).

## 3. Effective rainfall (ADR-0021)

| Method | Formula | Source |
|---|---|---|
| `fao_aglw_1986` (default) | Pe = 0.8·P − 25 for P > 75 mm/month; Pe = 0.6·P − 10 for P ≤ 75; Pe ≥ 0 | FAO I&D Paper 33 (Brouwer & Heibloem 1986) §4.2, verified this phase incl. worked examples |
| `constant_fraction` | Pe = f·P, 0 ≤ f ≤ 1 (farmer/region-supplied) | explicit parameter, disclosed |
| none selected | Pe = "not evaluated" | honesty |

Notes: applies to MONTHLY totals (FAO-33 basis) or to daily values via the
same shape adapted per-day (`fao_aglw_1986` on daily P uses the daily form
`Pe = 0.8P − 5` / `0.6P − 3`… **NO** — unverified; the daily variant is NOT
implemented; daily precipitation is aggregated to months first, and the
method's monthly scope is disclosed). USDA-SCS is backlog W-5 (coefficients
unverified). The method, its citation, and its slope limit (FAO-33: valid for
slopes ≤ 4–5%) are returned with every value.

## 4. Soil water-holding characteristics (ADR-0020)

Required inputs for layer 3: θFC, θWP (m³/m³), Zr (m), optional p
(depletion fraction). Sources, in order of authority:

1. **farmer/lab measurement** (`direct_field_measurement` / `farmer_reported_record`) — wins.
2. **PTF estimate** (`global_soil_prediction`, `processing_version` marks the
   PTF): Saxton & Rawls 2006 (SSSAJ 70:1569–1578) applied to SoilGrids
   sand/clay (+OC→OM via van Bemmelen 1.724). Coefficients verified in two
   independent sources this phase. Validity domain enforced: sand ≤ 0.80,
   clay ≤ 0.60, OM ≤ 8% — outside the domain the estimate is REFUSED, never
   extrapolated. Disclosure: texture comes from the 0–5 cm SoilGrids layer and
   is ASSUMED representative of the root zone (single-layer extrapolation,
   backlog S-6); the estimate is soil-TEXTURE-based, not a moisture
   measurement, and is never mixed with ERA5 surface soil moisture.
3. **absent** ⇒ layer 3 unevaluated (FAO-33 fallback, disclosed).

Derived (FAO-56 ch. 8): `TAW = 1000·(θFC − θWP)·Zr` mm; `RAW = p·TAW`;
`Dr` recurrence (mm): `Dr,i = min(TAW, max(0, Dr,i−1 − (Pe,i + I,i) + ETc,i))`
(simplified daily form: runoff/percolation handled by the effective-rainfall
method upstream and by the TAW cap; capillary rise and groundwater are not
modelled — disclosed). Stress: `Ks = (TAW − Dr)/(TAW − RAW)` when Dr > RAW
else 1 (FAO-56 Eq. 84); reported only when p exists. Zr default: midpoint of
the pack's FAO-56 Table 22 range with disclosure; p: pack value adjusted by
`p + 0.04·(5 − ETc)` when ETc-mean exists (verified footnote 2).

## 5. Seasonal planning (Phase 5)

`plan_rotation_water` produces, per season (and per assigned crop):

- stage windows (init/dev/mid/late from pack stage lengths) and per-stage
  Kc-mean, ETc, Pe, Dr at stage end, NIR;
- monthly timeline: ET0, Kc-mean, ETc, P, Pe, NIR, Dr;
- seasonal totals: ET0, ETc, P, Pe, ΔSW, NIR, GIR (when Ea), allocation
  coverage; deficit windows (periods where Dr > RAW, and/or NIR > allocation
  share);
- explicit ladder of the 7 quantities (Phase 4 list) with "(not evaluated)"
  where inputs are missing — e.g. economics-style honesty for water;
- assumptions + methodology block (which Pe method, which soil source, Zr
  choice, sowing-date assumption) and the source refs for every knowledge
  parameter;
- **unknown allocation is never unlimited**: when no allocation is supplied
  the allocation row is "unknown" and no feasibility claim is made;
- sha256 plan checksum over (inputs, methods, versions, values).

## 6. Rotation integration (Phase 6)

- `CandidateAssessment.net_irrigation_requirement_mm` added (None when not
  evaluable, with reasons).
- Optimizer allocation coefficients use NIR when evaluable for the season's
  crop; else the ETc screening value with detail text "demand basis: ETc
  screening (net irrigation requirement not evaluable — precipitation/soil
  evidence missing); ETc is a conservative upper bound of irrigation need".
- Infeasibility conflict labels name `water_allocation` per season (unchanged
  semantics; already verified).
- Crops with neither estimate are held out of allocation-constrained runs
  (unchanged, ADR-0016).

## 7. Knowledge model additions (Phase 1)

Seed pack `kp-seed-2026.11.1` (additive, checksummed, verified during Phase 0):
- `stress_depletion_fraction_p` trait for 10 crops (FAO-56 T22; e.g. maize
  0.55, cotton 0.65, onion 0.30) + faba_bean Zr 0.5–0.7 m and p 0.45
  (**faba keeps NO Kc — deliberate gap stays**);
- Zr corrections (barley 1.0–1.5, dry_bean 0.6–0.9, cotton 1.0–1.7);
- digitization note updated with the Phase-0 verification provenance;
- superseded pack version `kp-seed-2026.11.0` is retired at bootstrap
  (lifecycle transition; content/checksum preserved — history not rewritten).

`app/water/` versioned surfaces: `water-engine-1.0.0`, methods catalog
(`water-methods-1.0.0`) exposing every Pe method, efficiency class, soil
source and its citation via `GET /api/v1/water/methods`.

## 8. Feature catalog additions

`featurespec-2026.11.2-m6a` (additive): `reference_et0_total_daily`
(identity, coverage 1.0), `reference_et0_total_seasonal` (0.9),
`reference_et0_total_crop_season` (0.8). Effective rainfall / ETc / Dr are
NOT feature-engine features — they are decision-layer quantities computed by
the versioned water engine (they need knowledge + methods, not just data).

## 9. Persistence

Migration `0006_water_intelligence`: table `water_plans` (id, field_id,
status, seasons JSONB, methods JSONB, soil_inputs JSONB, result JSONB,
warnings JSONB, not_evaluated JSONB, engine_version, feature_run_id,
water_engine_version, methods_version, checksum_sha256, created_by,
created_at/updated_at). Plans are immutable snapshots (like rotation
strategies); re-running creates a new row. NUMERIC-friendly accumulation:
values are stored as JSON numbers rounded 4 dp; the float8 policy note
(backlog B-9) is superseded for water plans by storing the ledger arithmetic
as exact integer-litre conversions inside the result payload
(`volume_m3` fields carry both mm and exact m³ via 1 mm·ha = 10 m³).

## 10. Honesty contract (inherits all deepening rules)

Missing ≠ zero; partial ET0 refuses the estimate (F-07 generalized: a missing
MONTH refuses the monthly cell and the seasonal total only aggregates
labelled months — totals under missing months are marked under-count, and
ETc/NIR refuse when any season month lacks ET0); no composite confidence;
synthetic banners; "≈ + assumptions"; P−ET0 never an irrigation requirement;
surface moisture never a root-zone claim; unknown allocation ≠ unlimited;
synthetic evidence never validates agronomic claims.
