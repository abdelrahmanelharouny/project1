# M6A Readiness Matrix — Water Knowledge Completeness

Phase-0/1 artifact of Milestone 6A (water intelligence), cited from
`app/water/knowledge.py` and `app/knowledge/packs/seed_pack_v1.py`. It
answers, per crop: **which water-planning dimensions are complete, partial,
missing or not applicable — with the citations that back every present
value.** The runtime read-model implements exactly this classification.

## Dimensions tracked per crop

| Dimension | Backed by | Notes |
| --- | --- | --- |
| Kc curve (initial/development/mid/late anchors + stage lengths) | FAO-56 ch. 6 tables | Re-verified against the FAO document during M6A Phase 0 (fetched, not transcribed from memory) |
| Rooting depth (`zr_min_m`) | FAO-56 ch. 8, Table 22 | Added in M6A (pack version 2026.11.1) |
| Depletion fraction (`p`) | FAO-56 ch. 8, Table 22 | Adjusted per crop via `adjust_p_for_etc` when ET0 differs from the table baseline |
| Effective rainfall method | FAO-56 formulation | Implemented in `app/water/effective_rainfall.py` |
| Calendar plant/harvest windows | EcoCrop (reference_synthesized) | Coarse temperate contexts; require regional calibration |

## Classification vocabulary

- **complete / source-backed** — value present with citation; usable in
  planning outputs.
- **partial** — present with gaps or scope caveats (e.g. synthesized
  calendar windows).
- **missing** — deliberately absent; downstream criteria evaluate as
  `unevaluated` (faba bean's Kc row is the standing example — its water
  budget comes out unevaluated rather than approximated).
- **not-locally-validated** — source-backed for the source's own context
  (e.g. US-scoped NRCS guidance) but not validated for the deployment
  region.
- **not applicable** — dimension meaningless for the crop/planning shape.

## Disposition / status

- The matrix is **honest about incompleteness**: a water plan computed for a
  crop with missing dimensions reports the missing inputs and the blocked
  criteria instead of substituting defaults.
- Phase-0 verification findings (Kc anchors and stage lengths re-checked
  against FAO-56 ch. 6; root depths and depletion fractions against ch. 8
  Table 22) are recorded there; the pack carries the corrected values with
  per-attribute confidence.
- What M6A did **not** add: irrigation scheduling optimization, salinity,
  snow processes, and any forecast input — no defensible source was
  transcribed, and none is simulated.
