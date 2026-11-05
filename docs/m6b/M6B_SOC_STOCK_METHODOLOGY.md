# M6B — SOC Stock Methodology (`soc-stock-1.0.0`)

**Status:** implemented (as-built)
**Code:** `app/soil/soc.py` (pure engine), `app/api/v1/soil.py` (run endpoint),
`app/soil/layers.py` (interval validation).
**ADR:** ADR-0024 (layer-wise stocks refused when incomplete; FD vs ESM
method-aware; single coarse-fragment correction).

---

## 1. Formula and dimensional derivation

```
SOC_layer [Mg C/ha] = OC [g C/kg fine earth] × BD_fine [g/cm³]
                      × (1 − vCF [m³/m³]) × d [cm] × 0.1
```

Derivation (independent of the implementation, stated in the module and
property-tested):

```
mass fine earth per cm²  = BD_fine × d                 [g/cm²]
carbon per cm²           = (OC/1000) × BD_fine × d      [g C/cm²]
carbon per ha            = × 10⁸ cm²/ha                 [g C/ha]
megagrams                = ÷ 10⁶ g/Mg
⇒ OC × BD_fine × d × 10⁸ / (1000 × 10⁶) = OC × BD × d × 0.1   [Mg C/ha]
```

Coarse fragments remove soil volume, hence the `(1 − vCF)` factor — applied
EXACTLY ONCE (§3). This is the FAO GSOC MRV convention; the dimensional identity
was verified analytically during the gap analysis (§8) and against hand-computed
golden values (see `M6B_TEST_AND_BENCHMARK_REPORT.md`).

## 2. Layer-wise computation and refusals

`layer_soc_stock` returns either a stock (rounded 6 dp) or `None` with an explicit
`not_evaluated_reason`. Refusal table:

| Condition | Result |
|---|---|
| OC missing | refused — "OC concentration missing — stock refused" |
| bulk density missing | refused — no assumed density (the 2.65 g/cm³ porosity assumption is NOT reused here) |
| `bd_basis` missing or unknown (`whole_soil`/`fine_earth` are the only values) | refused |
| OC negative, BD outside (0, 2.65) | refused |
| `whole_soil` BD without vCF | refused — the single correction needs the coarse-fragment fraction |
| vCF outside [0, 1) | refused |
| `fine_earth` BD **with** vCF supplied | refused — double correction is a hard error, not a warning |

The refusal reason travels into the run result's `not_evaluated` list; a missing
input never becomes a zero stock.

## 3. Bulk-density basis and the single-correction rule

- `whole_soil` BD → the `(1 − vCF)` correction converts to a fine-earth basis
  inside the formula (`correction_note: "vCF applied once"`).
- `fine_earth` BD → correction is 1.0; supplying vCF as well is refused
  ("fine-earth bulk density must NOT be coarse-fragment corrected again").
- Basis mixing across a profile is a validation concern per layer; the engine
  evaluates each layer on its declared basis and records the basis in
  `inputs_used` for auditability.

## 4. Profile aggregation (contiguity, gaps, overlaps)

`profile_soc_stock`:

1. **Overlaps refuse the total** (`SocStockError`: "layer depth intervals overlap
   — profile aggregation refused (never deduplicated silently)").
2. Each layer is evaluated independently; evaluated layers are summed into the
   profile total **only over complete coverage**.
3. The total block records `coverage_cm`, `covered_thickness_cm` and
   `contiguous`; when evaluated layers are not contiguous a warning states that
   "the total covers the measured intervals only; gaps are NOT interpolated".
   Gaps are listed verbatim in the result.
4. Layers whose inputs are mapped predictions (`is_prediction`) are flagged with
   a warning: "uses mapped (SoilGrids-style) inputs — prediction, not a field
   measurement".

Golden hand-checks: `20 × 1.3 × 0.9 × 20 × 0.1 = 46.8 Mg C/ha` (whole-soil BD
1.3, vCF 0.1, 0–20 cm) and `15 × 1.25 × 10 × 0.1 = 18.75 Mg C/ha` (fine-earth).

## 5. Fixed-depth (FD) comparison

`fixed_depth_comparison(baseline, follow_up)`:

- Layers are matched by identical `(top_cm, bottom_cm)`; the comparison runs over
  the COMMON depth support only. Duplicate intervals within one profile are an
  error; no common interval ⇒ `not_evaluated`.
- Both profiles must be internally complete over the common support — otherwise
  `not_evaluated` with the combined refusal list (no partial FD claims).
- Output: baseline/follow-up stocks, `delta_mg_ha`, common depths.
- **BD-change caveat:** when any common layer's bulk density differs between
  events, a caveat is emitted — "a fixed-depth stock difference can reflect soil
  mass redistribution, not only carbon change (equivalent-soil-mass comparison
  refines this when the required data exist)".

## 6. Equivalent-soil-mass (ESM) comparison

`equivalent_soil_mass_comparison` is implemented ONLY with the data it requires —
no partial ESM:

- Refused (`not_evaluated` with `missing_inputs` list) unless BOTH events carry,
  for every common layer: bulk density + basis, OC, and coarse fragments when the
  whole-soil basis is used (fine-earth masses are needed).
- Method: cumulative fine-earth mass profiles — layer mass
  `BD_fine × d × 100` [Mg/ha] (100 = 10⁸ cm²/ha ÷ 10⁶ g/Mg) — and cumulative SOC
  curves; the follow-up's total fine-earth mass is matched on the baseline curve
  with linear-within-layer interpolation of the baseline stock.
- Refused when the follow-up mass exceeds the baseline's covered mass (the
  reference depth cannot be matched from these layers).
- Output: `reference_mass_mg_ha`, both stocks at equivalent mass, `delta_mg_ha`,
  and the method note.

Two-layer golden scenario (baseline 0–10 cm OC 20/BD 1.4, 10–30 cm OC 10/BD 1.3;
follow-up BD 1.2/1.25): fixed depth gives 54.0 → 49.0 (Δ −5.0, BD-driven); ESM
matches at reference mass 3700 Mg/ha where the baseline curve holds 51.0, giving
Δ −2.0 — the mass correction removes the spurious 3 Mg/ha of "loss".

## 7. Uncertainty treatment (as built)

`LayerStockInput` accepts `oc_uncertainty_g_kg` and `bd_uncertainty_g_cm3`
(1σ measurement uncertainty). `soc-stock-1.0.0` **records** these fields but does
not propagate them into confidence intervals — layer stocks are point estimates.
The honest comparison machinery (refusals, caveats) is the shipped uncertainty
handling; propagation arithmetic is open (see `M6B_RESEARCH_BACKLOG.md`).

## 8. SoilGrids caveat (F-8 label)

- Mapped inputs keep `evidence_class='global_soil_prediction'`; the write path
  refuses `soilgrids_profile` rows claiming any measured evidence class, and the
  run warns per prediction layer.
- The SoilGrids provider's uncertainty figure is the mean of per-pixel Q05–Q95
  half-widths — explicitly NOT a field-level 90% prediction interval (deepening
  F-8). Aggregating pixel quantiles into a field PI would need a spatial error
  covariance model (backlog S-1); M6B reports such aggregation as **unavailable**
  and never averages-and-relabels.

## 9. Run snapshots and checksum

`POST /fields/{id}/soc-stock-runs` persists an immutable `soc_stock_runs` row:
`comparison_mode` (`single_profile` | `fixed_depth` | `equivalent_soil_mass`,
CHECK-constrained), `baseline_run_id` for comparisons, engine/methods versions,
full `result` JSONB, `warnings`, `not_evaluated`, `request_parameters`,
`idempotency_key` (partial-unique per field) and
`checksum_sha256 = sha256(canonical JSON of {engine, methods, profile_total, layers})`
— deterministic and reproducible (property-tested).
