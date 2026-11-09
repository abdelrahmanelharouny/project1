# M6B Gap Analysis — Soil Intelligence

Recorded at Milestone 6B (soil intelligence) and cited from the SOC stock
engine (`app/soil/soc.py`). It records what soil science the platform can
defend, what it refuses to claim, and why.

## What M6B implements

- Soil profiles, sampling events, samples and per-layer measurements
  (`app/db/models_m6bc_m7.py`, `app/soil/`).
- SOC stock accounting (see §8 below), nutrient budgets (products,
  applications, removals), and soil health assessment over physical,
  chemical and biological indicators.
- Import paths for laboratory data with unit and basis validation
  (`app/soil/import_service.py`, `app/soil/layers.py`).

## §8 — SOC layer stock identity (the dimensional audit)

The FAO GSOC MRV-convention layer stock implemented in `app/soil/soc.py`:

```
SOC_layer [Mg C/ha] = OC [g C/kg fine earth] × BD_fine [g/cm³]
                      × (1 − vCF [m³/m³]) × d [cm] × 0.1
```

Derivation, checked analytically and property-tested:

```
mass fine earth per cm²  = BD_fine × d                    [g/cm²]
carbon per cm²           = (OC/1000) × BD_fine × d        [g C/cm²]
carbon per ha            = × 10⁸ cm²/ha                   [g C/ha]
Mg C                     = ÷ 10⁶
⇒ OC × BD × d × 10⁸ / (1000 × 10⁶) = OC × BD × d × 0.1  [Mg C/ha]
```

Coarse fragments remove soil volume exactly once via `(1 − vCF)`.

## Hard rules enforced in code

- Every layer needs OC + BD + thickness (and vCF unless both are explicitly
  declared absent-from-basis). A missing input makes **that layer's** stock
  `not_evaluated`; it is never zero-filled.
- Bulk-density basis (`whole_soil` vs `fine_earth`) is explicit per layer.
  The `(1 − vCF)` correction is applied exactly once: whole-soil BD gets it;
  fine-earth BD must not be corrected again — double correction is a hard
  error.
- Profile totals sum only contiguous, non-overlapping coverage; gaps are
  reported and totals are labelled by their covered depth.
- Fixed-depth vs equivalent-soil-mass comparisons are method-aware: ESM is
  refused without the required per-layer masses (no partial ESM claims).
- SoilGrids-derived inputs keep the F-8 prediction label; a field-level 90%
  prediction interval aggregated from pixel quantiles remains unavailable
  and is reported as such.

## Remaining gaps (unchanged)

- No process-based SOC turnover model (no RothC/CENTURY dynamics) — stock
  accounting only.
- No greenhouse-gas flux estimation.
- Nutrient budgets use handbooks/removal tables as reference knowledge;
  region-specific fertilizer recommendations are out of scope until
  region-validated packs exist.
