# M7.0 — Frontend & User Experience Readiness

**Inspection date:** 2026-11-01 · **Scope:** all existing tabs (Features, Rotation, Water, Data Passport, plus Overview / Farms & Fields / Observations) assessed as a foundation for the six proposed M7 surfaces. Nothing was built during this inspection; §4 is a proposal only.
**Live verification this session:** every tab rendered in the browser (desktop + 390×844), zero console/page errors, no horizontal overflow at 390 px, footer sticky behavior intact (`tool-results/m70-desktop-features.png`, `tool-results/m70-mobile-390.png`).

---

## 1. Existing interface inventory (as-built)

| Tab | Component (LOC) | What it does well (reusable patterns) | Honesty behaviors already in place |
|---|---|---|---|
| Overview | `overview.tsx` (230) | stat cards, setup checklist, quick actions | DB/PostGIS status card |
| Farms & Fields | `farms-fields.tsx` (1,030) + `field-map.tsx` (110) | farm selector, field table, offline MapLibre detail, boundary-version dialog ("Boundary history is never overwritten") | geometry warnings alert; boundary version list |
| Observations | `observations.tsx` (1,179) | ingestion forms (synthetic/open-meteo), CSV + CHIRPS import tabs, coverage table, provider health dots, recharts T/P charts | per-chart provenance notes ("All plotted values are SYNTHETIC…"), quality/synthetic/provenance badges |
| Features | `features.tsx` (711) | run creation (periods, hemisphere, crop-season windows), run list, values table, run-to-run Δ comparison, catalog browser | SYNTHETIC run alert, "Not evaluated — with reasons" block, coverage %, catalog formula references |
| Rotation | `rotation.tsx` (913) | crop history, per-season candidate cards with cited reasons, optimizer card (profiles, allocation), strategy cards with criteria tables, accordions (why/constraints/evidence/limitations/validation), knowledge browser | "(not evaluated)" cells, infeasible-conflict alerts, Pareto badges, SYNTHETIC banner, checksum footer |
| Water | `water.tsx` (1,099) | readiness matrix, plan builder (seasons/crops/allocation/soil source/expert mode), stage timeline (CSS proportional bar), ladder with conversions, monthly table, deficit accordions, plan history | `(not evaluated)` ladder steps, "unknown ≠ unlimited" allocation warning, "no evidence" cells, methodology & deliberate-omissions card |
| Data Passport | `data-passport.tsx` (374) | per-variable source cards, missing-variables with reasons, analyses available/blocked with required inputs | synthetic/real entries never merged; license/attribution cards |

Shared infrastructure: `badges.tsx` (Synthetic/Quality/JobStatus/Passport badges), `field-picker.tsx` (cross-farm picker + empty states), `lib/format.ts` (units/dates/code humanization), TanStack Query hooks (`hooks/use-croptwist.ts`, ~30 typed hooks), zustand UI store with cross-tab jump actions, `lib/api.ts` (bearer header + `XTransformPort` gateway + `ApiError` envelope mapping → sonner toasts).

## 2. Can these foundations host the six proposed M7 surfaces?

| Proposed surface | Feasible with existing components? | Gaps |
|---|---|---|
| **Field Overview** (unified chronological + spatial view) | **Yes, largely** — `field-picker` + overview stat-card pattern + `field-map` + per-domain cards | no cross-domain *timeline* component exists; needs a new timeline primitive (M7.7) |
| **Historical State** (what was known at date T) | **Yes, structurally** — every domain already exposes dated artifacts (feature runs by period, water plans by seasons, boundary versions by created_at) | requires M7.1 state API; UI is then mostly composition; "as-of" picker is new |
| **Scenario Workspace** (baseline vs alternatives) | **Partial** — the rotation strategy-card grid + run selector is the closest pattern; Δ-comparison exists for feature runs | scenario list/create/compare API; side-by-side comparison component with criterion-level diffs is new |
| **Decision Comparison** (criterion-level differences & constraints) | **Yes** — rotation criteria tables + feature Δ table prove the pattern (raw + normalized + "(not evaluated)" rendering) | cross-run strategy comparison endpoint (backend) + a diff-oriented table variant |
| **Evidence Explorer** (trace values → observations → sources → methodology) | **Partially exists, scattered** — passport (per variable/source), feature provenance counts, rotation evidence accordions, water "Data provenance" + checksum accordion | no *unified* drill-down; needs a shared evidence-panel component consuming `input_refs` (API/DB doc §5.2) |
| **Digital Twin Timeline** (evolution of soil/water/crops/management) | **Partial** — all data is date-addressable; charts exist per-domain | timeline lane component; soil/management lanes will be honestly empty (M6B/M6C absent) — needs NOT_IMPLEMENTED lane states |

**Verdict:** no surface requires a rewrite; all six are compositions over proven patterns plus at most three genuinely new primitives (timeline, as-of state view, comparison-diff panel).

## 3. UX-quality review (per spec §11 checklist)

| Aspect | Current state | Evidence | M7 note |
|---|---|---|---|
| Component reuse | high — badges/pickers/format/api shared everywhere | §1 | extend, don't fork |
| Navigation complexity | 7 tabs + zustand cross-tab jumps; flat structure holds | `workspace.tsx:23-31,148-188` | 7→9 tabs (add States, Scenarios) still manageable; keep tab strip scroll pattern |
| Data consistency across tabs | consistent field scoping; each tab re-fetches via TanStack Query with invalidation on mutation | hooks/use-croptwist.ts | state/scenario APIs must follow same query-key conventions |
| Responsive layout | mobile-first Tailwind: stacked headers (`flex-col sm:flex-row`), 2-col mobile grids, `overflow-x-auto` tables with min-widths, scrollable tab strip | §1 components | verified 390 px this session: no overflow |
| Mobile behavior | footer `mt-auto` + safe-area inset; tab strip scrolls; no horizontal overflow | `workspace.tsx:36,157-158` + live check | keep for new tabs |
| Accessibility | semantic tablist/panels (Radix), labeled inputs, alt-free decorative SVGs; **no dedicated audit done this session** | component structure | run an a11y pass before M7.7 (low risk, Radix base) |
| Chart semantics | units in titles (°C, mm); per-series provenance notes; empty states explain what to ingest | `observations.tsx:458-465,785-835` | timeline must carry per-lane provenance + evidence class |
| Unit display | `formatArea`, mm/m³ conversions on the water ladder, unit columns on feature values | `lib/format.ts`, water/features | scenario comparisons must state per-scenario units/basis |
| Missing-data messaging | strongest platform property: "(not evaluated)", "— obs" (F-17 fix), "no evidence" cells, blocked-analyses with reasons | across tabs | reuse verbatim; never add a generic completeness score (Field State doc §4) |
| Synthetic-data labels | `SyntheticBadge` + amber SYNTHETIC banners + workspace-level promise | `badges.tsx:8-22`, `workspace.tsx:40` | scenario types need analogous new badges (F-14) |
| Long-running task feedback | job footers with status badge + counts + warnings; relies on inline-completion (202 responses usually already terminal) | `observations.tsx:167` (JobFooter) | **biggest UX gap for M7.5**: multi-scenario batches may exceed inline latency → needs progress/cancel UI once worker exists (API doc F-29) |

## 4. Interface architecture proposal (for M7, not implemented)

```
workspace.tsx
├── existing 7 tabs (unchanged)
├── NEW "Field State" tab (M7.1/M7.7)
│   ├── FieldPicker (reuse)
│   ├── StateAsOfPicker (new: date/period + state list w/ checksums)
│   ├── StateSummary (evidence/quality dimension chips — per-dimension, no generic score)
│   └── StateTimeline (new primitive: chronological lanes per domain; empty lanes labelled NOT_IMPLEMENTED for soil/management)
├── NEW "Scenarios" tab (M7.2+)
│   ├── ScenarioList (type badge: OBSERVED / PERTURBED / STRESS / PROJECTION / FORECAST / MANAGEMENT — never interchangeable)
│   ├── ScenarioBuilder (adjustment config forms w/ physical-consistency validation client+server)
│   └── ScenarioCompare (new diff panel: baseline vs scenario criterion table, constraint outcomes, evidence deltas)
└── cross-cutting
    ├── EvidencePanel (new shared drill-down consuming input_refs: value → run → observations → source/license)
    └── badges.tsx += ScenarioTypeBadge, EvidenceClassBadge, StalenessBadge
```

Design rules carried over (non-negotiable, already institutionalized): SYNTHETIC/assumption labelling per scenario type; "(not evaluated)" instead of blanks or zeros; no generic completeness score; checksums displayed at every artifact; long-running tasks must show progress + cancel once backend support exists; every new surface mobile-first with the same footer contract.

## 5. Findings register

| ID | Severity | Area | Current | Expected | Impact | Blocks M7? |
|---|---|---|---|---|---|---|
| F-35 | Medium | UX | no long-running task UX (progress/cancel) | needed for M7.5 scenario batches | UX debt; depends on backend F-29 | No |
| F-36 | Low | UX | no a11y audit on record | run axe/lint-a11y pass pre-M7.7 | quality | No |
| F-37 | Low | Tooling | no `tsc --noEmit` script | add typecheck script | CI safety | No |
| F-38 | Low | UX | frontend `JobStatus` type omits `cancelled`/`retrying` | align type with backend enums | minor | No |
| F-39 | Medium | UX | no cross-run comparison surface (backend endpoint also missing) | needed for Decision Comparison | composition + backend work (M7.5) | No |

## 6. Readiness verdict

| Capability | Status |
|---|---|
| Hosting the six M7 surfaces | **READY_WITH_LIMITATIONS** (3 new primitives; no rewrite) |
| Honesty/labelling infrastructure | **READY** (best-in-class already; extend with scenario-type badges) |
| Responsive/mobile | **READY** (verified live at 390 px this session) |
| Long-running task UX | **NOT_IMPLEMENTED** (blocked on backend worker, F-29/F-35) |
| Evidence traceability UI | **PARTIAL** (scattered per-domain; unify via EvidencePanel + input_refs) |
