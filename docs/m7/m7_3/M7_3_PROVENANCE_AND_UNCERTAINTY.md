# M7.3 — Provenance, Evidence & Uncertainty

**Status:** Implemented in the derived tables + run payload; disclosed end-to-end in the API and UI.

---

## 1. The derivation chain (every transformed value)

```
Dataset product (source registry)
  → Observation row (evidence_class, is_synthetic, quality, uncertainty)
    → Field State snapshot (verbatim observation manifest + manifest SHA-256)   [M7.1]
      → Scenario definition (canonical configuration + checksum)                [M7.2]
        → Scenario execution run (engine versions + input fingerprint)
          → scenario_derived_observations row
              source_observation_id        — exact parent observation
              dataset_product_id           — exact source product
              baseline_value               — the value the observation carried
              transformed_value            — the deterministic transform output
              transformation_code/parameter — e.g. temperature_delta_c {delta_c: 2.0}
              evidence_class               — scenario_derived_transformed | synthetic_test
              source_evidence_class        — the source's own class, preserved
              is_synthetic / quality_status — carried through
            → scenario_derived_features row
                baseline_value / scenario_value / difference / difference_percent
                feature_specification_version
                uncertainty_metadata.{source_uncertainty, transformation_assumption,
                                      missing_evidence_note, provenance, baseline_reference}
```

Run-level provenance: `parent_field_state_id`, `parent_snapshot_checksum`, `scenario_configuration_checksum`,
`input_fingerprint`, `source_observation_manifest` (+ SHA-256), `execution_configuration`, all three engine
versions, `output_checksum`.

## 2. Evidence classification (M7.3 spec §10)

The M7.2 `EvidenceClassification` enum stays frozen (its CHECK constraints bind scenario definitions). The
execution layer adds its own vocabulary:

| Class | Meaning | Where |
|---|---|---|
| `observed_source` | the source observation came from an observed/reanalysis product | run provenance / source class passthrough |
| `scenario_derived_transformed` | a deterministic transformation of an observed source value — **hypothetical** | every derived observation row |
| `synthetic_test` | the source observation was synthetic — stays visible as synthetic | every derived observation row (source `is_synthetic` flag) |
| `scenario_recalculated` | feature genuinely recomputed from transformed values | derived feature rows |
| `not_affected` | source variables untouched by the configured transformations — reported with reason | derived feature rows |
| `not_evaluated` | ET0 safety / engine limitation — reported with reason | derived feature rows + run `not_evaluated_reasons` |

Rules enforced (and tested):

- A scenario-derived temperature or rainfall value is **never** labelled an original observed value — the
  derived row carries the derived class, and the source's class travels beside it.
- Synthetic source ⇒ derived row is `synthetic_test` ⇒ the run emits a `SYNTHETIC SOURCE` warning with the
  exact share. Synthetic and real evidence remain explicitly distinct end-to-end.
- User-defined assumptions (the delta/multiplier themselves) are classified `user_defined_hypothetical`
  inside every feature row's `transformation_assumption` metadata.

## 3. Uncertainty model (honest by construction)

Four distinct uncertainty sources are separated, and only the defensible ones are quantified:

1. **Source data uncertainty** — the observation's own `uncertainty_value`/`uncertainty_type` travels
   unchanged into the engine (which propagates standard-error for means) and is echoed in each derived
   feature row (`source_uncertainty`).
2. **Transformation assumption uncertainty** — the delta/multiplier is a user-defined hypothetical choice.
   The transformations are deterministic: they add **no numerical uncertainty** to the source data. This is
   stated explicitly in every feature row (`transformation_assumption.note`), never expressed as a fabricated
   confidence number.
3. **Calculation uncertainty** — the engine's own coverage/quality machinery (standard errors for means,
   coverage ratios, n_input/n_missing) operates identically in both passes and is stored per derived feature.
4. **Missing evidence** — features that could not be evaluated are reported `not_evaluated` / `not_affected`
   with reasons; missing observations stay missing in derived rows (NULL, never zero).

**If no defensible quantitative uncertainty calculation exists, the limitation is reported instead of
generating a numeric confidence value** — implemented verbatim (`missing_evidence_note` on every derived
feature row; disclosure warning on every run).

## 4. What M7.3 does not claim

- Deterministic transformations do **not** reduce the uncertainty of the original dataset.
- Transformed values are **not** observations of the real world and never enter `observations`.
- Baseline-versus-scenario differences quantify the *sensitivity of features to the stated assumptions* —
  nothing more. They are never presented as forecasts, projections, or expected future conditions.
- No crop-yield, crop-survival, irrigation-demand or water-plan claim is produced anywhere in the execution
  path (water/rotation engines are not invoked).
