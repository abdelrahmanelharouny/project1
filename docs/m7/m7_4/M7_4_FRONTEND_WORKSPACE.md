# M7.4 — Frontend Workspace

**Component:** `src/components/fieldshift/sensitivity.tsx`
**Navigation:** new workspace tab **"Sensitivity"** (icon: `LineChart`), placed
after **Scenarios**.

---

## 1. Information architecture

```
Sensitivity tab
├── Field picker (reuses FieldPicker)
├── Scenario selector   (finalized + executable scenarios of the field)
├── Execution selector  (result-bearing runs of the scenario; shows status,
│                        ΔT/M_p reference values, output checksum short form)
└── Analysis workspace
    ├── Step 1 — Define: per-explorable-parameter bounds + points
    │            (bounded inputs showing the reference value; guardrails
    │            mirrored client-side), optional joint-grid toggle with
    │            per-axis resolution
    ├── Step 2 — Run: POST (idempotent) with loading state; failed analyses
    │            show error_summary + reproduction mismatches
    ├── Step 3 — Results
    │   ├── Reference reproduction card (reproduced / compared / matched)
    │   ├── Envelope & response table (per parameter × feature × period:
    │   │     reference, envelope, range, slope + units + validity,
    │   │     direction, classification badge, elasticity or its honest
    │   │     unavailable reason) with filters (parameter, feature,
    │   │     aggregation, classification)
    │   ├── Response chart (per selected feature: evaluated values vs
    │   │     parameter, reference marker; pure SVG, no chart lib needed)
    │   ├── Joint grid card (axes, min/max/range, direction, interaction
    │   │     contrast labelled "finite-grid interaction contrast")
    │   ├── Uncertainty registry (grouped by category, status badges,
    │   │     user_facing_explanation verbatim)
    │   ├── Warnings & not-analysed features (inherited reasons, verbatim)
    │   └── Verify button (POST verify; five flags rendered with ShieldCheck)
    └── Analysis history list (previous analyses of the run)
```

## 2. Honesty rules rendered (binding)

- Every number panel carries the disclosure: hypothetical scenario-derived
  features; the envelope is **"explored parameter-range envelope — a
  deterministic sensitivity result, not a confidence or probability
  interval"**.
- Parameters not configured in the source execution are shown as
  `not applicable` with the API's reason — never hidden, never editable.
- Classification badges use the API's vocabulary verbatim
  (`threshold_suspected` etc.).
- Elasticity shown only when `status == "available"`; otherwise the structured
  reason is printed.
- No chart or text anywhere suggests probabilities, forecasts, yield impact,
  or climate projections.

## 3. Browser journey (verification script)

1. Open workspace → Sensitivity tab.
2. Pick field → pick finalized stress scenario → pick its completed run.
3. Define ΔT bounds [−2, 6] with 9 points (single-parameter source: M_p shown
   not applicable) → Run analysis.
4. Verify: reproduction card all-match; OAT table shows slope 1.0 for monthly
   mean temperature; envelope correct; classification badges sensible.
5. Switch to a both-parameter scenario run; request bounds for both + joint
   grid; verify interaction contrast card (0.0 / approximately additive) and
   grid summaries.
6. Open the uncertainty registry; confirm status badges and explanations
   render; confirm no composite score appears.
7. Click Verify — all flags render green.
8. Reload — analysis history restores; clicking a past analysis reopens its
   results (persistence).
9. Mobile width (390px): layout stacks, tables scroll horizontally, no
   overflow.
