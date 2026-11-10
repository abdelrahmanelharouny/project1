# M7.3 — Frontend Scenario Execution Workspace

**Component:** `src/components/croptwist/scenario-execution.tsx` (new), wired into the existing
**Scenarios** tab (`scenarios.tsx`). API client: `src/lib/api.ts` (7 new functions); types: `src/lib/types.ts`.

---

## 1. Where it lives

The Scenario Workspace tab gains an **Execute scenario (M7.3)** section inside every scenario card whose
type can ever execute (`user_defined_stress`, `historical_perturbation`); reference-only
(`historical_observed`) and contract-only types keep the M7.2 presentation. The section is present for
non-finalized drafts too, with a disabled Execute button and an explanatory tooltip — honest unavailability
instead of a hidden feature.

## 2. A. Execute Scenario

- **Execute** button — enabled only for `finalized` + executable type. Anything else is disabled with a
  tooltip ("Only finalized stress/perturbation scenarios can execute").
- Execution is synchronous; the section then lists runs with a refresh button.
- Blocked configurations surface the API's structured findings (422 `SCENARIO_EXECUTION_BLOCKED`) as an
  error alert naming the offending dimension and reason.

## 3. B. Transformation Preview

Before execution, the exact parameters are shown from the canonical configuration, e.g.:

> 🧪 Hypothetical assumptions to apply (never observed data)
> `Temperature: +2.0 °C` `Precipitation: ×0.80`

`water_allocation_multiplier` renders as `Irrigation allocation: ×0.7`; unsupported dimensions
(`precipitation_delta_mm`, timing shifts) render as days/mm entries — execution will refuse them with an
explicit reason if attempted.

## 4. C. Execution Progress & Status

Per run: `RunStatusBadge` with the five honest states — `queued`, `running`, `succeeded`,
`completed_with_limitations`, `failed` — plus a failure alert carrying `error_summary`. (Execution is
synchronous, so `queued`/`running` are transient; the vocabulary matches the backend contract and future
async reuse.) Runs show completion time, transformed-observation count and feature-row count.

## 5. D. Baseline vs Scenario

`RunDetail → Baseline vs scenario` loads the comparison document and renders a filterable table
(`max-h-96 overflow-auto` with sticky header, custom-scrollbar friendly):

| Column | Content |
|---|---|
| Feature | name + code; excluded rows show their reason inline |
| Level / period | aggregation level + period label |
| Baseline / Scenario | values (recalculated rows only) |
| Δ | absolute difference |
| Δ % | **only when the API provided it** — withheld when the baseline is zero or the comparison is invalid |
| Evidence | `scenario-derived` / `not affected` / `not evaluated` badges |

Filters: All / Scenario-derived / Not evaluated / Not affected. A footnote states that scenario values are
hypothetical, never observations. No simulation charts exist anywhere in the workspace.

## 6. E. Evidence Explorer

`RunDetail → Evidence explorer` loads the first 100 derived observations:

- source linkage (`source_observation_id`), baseline value, transformed value, unit,
- exact transformation (`temperature_delta_c {"delta_c": 2.0}` …),
- period, and an evidence badge — `hypothetical` (amber, flask icon) or `synthetic` (fuchsia).

Run metadata always shows: output checksum, input fingerprint, engine versions, feature-spec version,
calendar window/timezone and the parent snapshot checksum.

## 7. F. Unsupported Capabilities

- The tab's **Platform scenario capabilities** panel (M7.2) continues to show climate-projection /
  weather-forecast / soil / management as explicit unavailable states with verbatim reasons.
- Per run, the **Limitations & disclosures** box lists all warnings, and a collapsible
  **Not evaluated (n) — with reasons** list itemizes every excluded feature (ET0-safety text included).
  Unsupported ET0 transformations are therefore visible on every temperature run — never silently absent.
- No simulated yield prediction or unsupported crop-impact visualization exists.

## 8. Verification

`Verify checksums` renders the four-way verification result (output checksum, definition checksum, parent
intact, manifest pinned) with pass/fail icons and the verification note.

## 9. Layout & responsiveness

- Desktop (≥ sm): metadata grids go 2–3 columns; tables scroll horizontally inside their card.
- Mobile (390 px): single-column stacking, `min-w-0` + `break-all` on hashes/ids, `min-h-9/8` touch targets
  (≥ 44 px effective for primary actions), tables inside `overflow-auto` containers — no horizontal page
  overflow (verified in the browser E2E).
- The workspace footer remains the app's sticky footer (`mt-auto`), unaffected by this component.
