# P01-D — User Journey Analysis

**Method:** workflow traced through actual component code and store helpers (`src/lib/store.ts:79-87`), cross-referenced with live browser session (2026-11-13). Current state described from code; friction points cite files. Proposed journeys assume the P01-C destination structure but each improvement is independently actionable.

**Shared friction found on nearly every journey (F-0):** field context is re-selected per tab via `field-picker.tsx` in 20 tabs, while `overview.tsx:59-62` ignores the selection — the user cannot trust "which field am I looking at?" anywhere. Fix: persistent context bar (P01-C §3 C9).

---

## J1. First-time onboarding
- **Current:** register/login (`auth-gate.tsx`) → auto land on Overview → three competing entry points: header "Get started" wizard (`p3/onboarding-wizard.tsx`, 9 backend steps `app/onboarding/service.py`), Overview setup checklist (`overview.tsx:154-178`), Overview "how it works" card (`overview.tsx:228-244`). Health also shown twice more (auth-gate + footer).
- **Friction:** onboarding surface duplicated 3× with different behaviors; wizard's tour deep-links rely on tabs the user has not learned yet.
- **Proposed:** wizard is THE first-run surface (auto-opens once, dismissable); Overview checklist becomes a compact progress strip that resumes the same backend steps; "how it works" collapses into the wizard's tour. One surface, one state.

## J2. Create a farm
- **Current:** Overview quick action `openCreateFarm` (`overview.tsx:205-224`) or Farms tab dialog (`farms-fields.tsx:220`) → POST `/farms` with country/tz/currency/units.
- **Friction:** minor — two entry points is fine; form validation is toast-only (`aria-invalid` once in repo, `farms-fields.tsx:105`).
- **Proposed:** keep both entries; adopt inline field validation (ui/form.tsx already shipped, unused).

## J3. Register a field
- **Current:** Farms tab → add-field dialog with GeoJSON entry + `EXAMPLE_GEOMETRY` helper (`farms-fields.tsx:419+`) → POST `/farms/{id}/fields`; boundary versions supported.
- **Friction:** hand-pasting GeoJSON is expert-only; no map draw/edit exists (verified — no draw dependency in repo); PostGIS validation warnings surface as text.
- **Proposed:** phase 1 keep GeoJSON + example helper; P02 map-draw upgrade belongs to Map & Satellite destination (C3).

## J4. Explore field intelligence
- **Current:** pick field (per tab!) → each intelligence tab independently; digital twin (`digital-twin.tsx`) and passport (`data-passport.tsx`) are the "what do I know" surfaces but live 10+ tabs apart.
- **Friction:** intelligence is scattered across 14 tabs; cross-tab helpers exist but require learning 27 labels first (F-0, P1 problem).
- **Proposed:** Decision Center rail = the intelligence walk; context bar carries the field; passport/digital-twin reachable as contextual panels from any sub-page.

## J5. Review soil & water conditions
- **Current:** Soil tab (6 dense cards, `soil.tsx:185-709`) and Water tab (readiness + builder + history, `water.tsx`) are separate; Soil Memory is a third tab (`soil-memory.tsx`); Field State a fourth.
- **Friction:** worst terminology split in the product (Soil / Soil Memory / Field State); water plan view silently fails on fetch error (P5); empty-state CTA jumps to wrong tab (P7, `water.tsx:998`).
- **Proposed:** Crop Intelligence ▸ sub-pages Soil / Soil Memory / Irrigation; Field State moves to Decision Center (it pins scenarios); fix P5/P7 during the move.

## J6. Understand vegetation & climate
- **Current:** Satellite tab (index select, CSS monthly bars, scenes, stress) + Forecast tab (capabilities, ingest, risks). Climate chart also on Overview.
- **Friction:** satellite data never touches the map; forecast verification exists in backend but has no UI (`src/lib/api.ts:1542-1544` unwired — the only endpoint-without-UI gap found); two climate chart renderings.
- **Proposed:** Map & Satellite destination (C3): map + indices + scenes; forecast joins Crop Intelligence ▸ Climate with a visible "verify" action; retire Overview's duplicate climate chart (D2).

## J7. Generate crop recommendations
- **Current:** AI Insights tab → refresh (`POST /recommendations/refresh`, locale param) → cards by severity with evidence + feedback.
- **Friction:** labeled "AI Insights" while org analytics tab is "Insights" (nav.json collision); data-gap tabs (features/observations) are prerequisites the user discovers only through INFO recommendations.
- **Proposed:** AI Copilot destination; recommendation cards link straight into the required Data Hub sub-page ("run feature run") with correct context — removes the wrong-tab CTA class of bugs.

## J8. Run crop-rotation scenarios
- **Current:** Rotation tab (optimize) → Field State (snapshot) → Scenarios (create/validate/finalize) → Execution sub-workflow (`scenario-execution.tsx`) → derived data.
- **Friction:** 4 tabs across the strip for one logical chain; each re-presents run ids; ordering is implicit.
- **Proposed:** Decision Center rail orders the chain visually: State ▸ Scenario ▸ Execute ▸ Analyze ▸ Decide ▸ Audit; chain progress indicator on the rail.

## J9. Compare alternatives
- **Current:** Sensitivity (tornado/curves) → Robust Plan (regret analysis) → Decisions (documents) — three tabs, each re-selecting executions (`sensitivity.tsx:58`, `robust-plan.tsx:223-238`).
- **Friction:** repeated artifact selection; verify buttons duplicated 5×; no side-by-side scenario diff visualization (charts audit: no comparison view exists).
- **Proposed:** shared execution-picker component within Decision Center; verify stays once at the source, elsewhere links; P02 adds a scenario diff chart.

## J10. Review AI explanations
- **Current:** advisor chat inside AI Insights (`ai-insights.tsx:845+`); multi-session; citations validated; engine-mode honest.
- **Friction:** advisor buried at tab #14 of 27; narrative locale fixed at refresh (known limitation, needs "Regenerate" after locale switch).
- **Proposed:** AI Copilot destination makes the advisor first-class; add locale-aware narrative hint when UI locale ≠ narrative locale.

## J11. Generate reports
- **Current:** Reports tab (P3) → create (10 types × 3 formats × en/ar) → queued → scheduler executes → download; plus a separate client-side CSV/JSON export button in 5 other tabs.
- **Friction:** two export systems with no cross-links (D5); expired artifacts only discoverable via status badge; recurrence UI limited to weekly/monthly though backend accepts 1–365 days.
- **Proposed:** Reports & Analytics destination unifies both: "quick export" (client CSV) contextual on data views, "formal reports" (server jobs) in the library; expose arbitrary intervals; expiry notice on rows.

## J12. Manage subscriptions & organizations
- **Current:** Billing tab (plans, lifecycle, sandbox pay) + Team tab (orgs, members, invitations, ownership transfer, activity, preferences) + Developer tab (keys, webhooks).
- **Friction:** admin surfaces sit between scientific tabs; preferences has no real home (section inside team-tab, `p3/team-tab.tsx:1162-1179`); non-admin users discover 403s at click-time (server enforces `org_admin+`, `app/api/v1/billing.py:43`); org creation duplicated (team tab vs onboarding wizard).
- **Proposed:** Workspace & Settings destination with role-aware sub-page rail (hide what your role cannot act on — visibility only; server remains authority); one org-creation component reused by wizard and team.

---

## Journey friction summary (ranked)

| Rank | Friction | Evidence | Fix target |
|---|---|---|---|
| 1 | Field context not persistent/trusted | `field-picker.tsx` ×20 tabs; `overview.tsx:59-62` | context bar (C9) |
| 2 | 27-tab strip hides the workflow spine | measured 3,263px/3,047px strips | destinations (C1–C7) |
| 3 | Wrong-tab empty-state CTAs | `features.tsx:573`, `rotation.tsx:867`, `water.tsx:998` | C1/C2 + redirect map |
| 4 | Scenario chain spread over 4–5 tabs with duplicated verify | inventory §4.1 | C4 chain rail |
| 5 | Terminology collisions & jargon | nav.json:15,32; tab labels | C5/C6 renames |
| 6 | Silent water-plan failure + mislabeled retry | `water.tsx:976`; `overview.tsx:96-98` | P5/P6 fixes |
| 7 | Onboarding 3× duplication | wizard vs checklist vs how-it-works | J1 proposal |
| 8 | Two export systems | `export-button.tsx` vs `p3/reports-tab.tsx` | J11 proposal |
| 9 | Back-button never returns to previous tab | `workspace.tsx:159` router.replace | evaluate push-mode during shell rebuild |
| 10 | Forecast verification capability invisible | `api.ts:1542-1544` unwired | J6 proposal |
