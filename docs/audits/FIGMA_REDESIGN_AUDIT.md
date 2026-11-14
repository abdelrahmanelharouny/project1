# CropTwist Figma redesign audit

**Date:** 2026-11-14<br>
**Repository:** `https://github.com/abdelrahmanelharouny/project1`<br>
**Figma reference:** [Untitled (Copy) — FieldShift design board](https://www.figma.com/design/T614Zo8hWuEbNgM4cEhpzg/Untitled--Copy-?node-id=3-3&t=diAJIa3pneiEOnie-1)<br>
**Implementation branch:** `feature/croptwist-ui-ux-redesign`<br>
**Base commit:** `38f8891696f6c27e79e25ddf65b33549f4a51397` (`feature/ai-complete-integration`)

## 1. Figma access and inspected evidence

The public Figma URL opens the canvas in a view-only state. The file is titled “Untitled (Copy)” and the visible board is labeled “FieldShift — Data, Planning & Decision Intelligence.” The board canvas is visible at 40–61% zoom; Figma indicates that sign-in is required to inspect, edit, or comment. The board’s accessibility/screen-reader view is disabled. Consequently, visual structure and copy in the visible frames can be read, but exact Figma measurements, token names, font metadata, component properties, and prototype transitions are not available from this view.

The captured canvas showed a Data Intelligence feature view and two Agricultural Planning screens. A third group is referenced in the board’s navigation, but a dedicated Decision Intelligence frame was not legible in the accessible canvas capture. Mobile-specific frames were not visible in the inspected viewport; responsive behavior must therefore preserve CropTwist’s existing mobile interactions and be verified in the implementation rather than inferred from unseen Figma frames.

### Visible frame inventory

| Group/frame | Observed content | Confidence / limits |
|---|---|---|
| **Group A — Data Intelligence** | Feature-availability/specification view. A compact availability matrix is paired with a feature-specification panel for date range, source reference, and calculation status. An empty state reads “No calculated features yet” and offers “Review observations”; a compact “Back to module” action is visible in the panel. | The frame is visible in the upper portion of the board. Smaller labels and exact dimensions are only partly legible at the available zoom; a direct Data Passport link is not verified from the capture. |
| **B1 — Crop Rotation Overview** | Shared sidebar and top bar; workspace/farm context; field and period selectors; “Edit rotation” action; a note to confirm evidence before committing; an explicit demo-workspace / no-connected-measurements notice; illustrative crop-sequence cards; and a field crop-history table. | Screen title, hierarchy, labels, disclaimer, and panel pattern are visible. The board presents illustrative/demo records, not measured farm data. |
| **B2 — Rotation Planner** | Same navigation shell, breadcrumb/search/farm context, “Simple / Expert” control, field/period inputs, “Save rotation” action, seasonal crop-selection cards, rotation-draft details, planning notes, and a “Review before saving” section. A disclaimer states the draft is illustrative and not an approved agronomic plan. | Form structure and key copy are visible; some small helper labels are not reliably readable. |
| **Group C — Decision Intelligence** | The sidebar group and item labels “Scenarios,” “Sensitivity,” “Robust Plan,” “Decisions,” and “Digital Twin” are visible in the shared shell. | Dedicated Group C frames were not inspected at readable scale in this view, so no frame-specific layout or interaction is asserted. Use the existing CropTwist Decision Center contracts until the frames can be inspected more fully. |

### Shared visual language

The observed screens use a deep charcoal/forest-green canvas, slightly lighter green-tinted panels, thin restrained green separators, pale high-contrast text, muted secondary copy, and mint-green primary actions. The interface is compact and data-dense: small section labels, grouped panels, restrained radii, tables/forms, and muted status banners take priority over decoration. A left navigation rail groups Workspace, Land & Data, Agricultural Planning, and Decision Intelligence; the top bar includes workspace search, help/notifications, a user identity, and a farm selector. No large decorative imagery was visible in the inspected screens.

Approximate implementation tokens (visually estimated, not exported from Figma):

| Role | Starting value | Intent |
|---|---:|---|
| Main canvas | `#0D1714` | Quiet, dark forest-charcoal workspace |
| Primary surface | `#13211B` | Dense cards and panels one step above the canvas |
| Raised surface | `#192B23` | Selected/hovered rows and nested data regions |
| Divider/border | `#294035` | Thin green-tinted separators, not bright outlines |
| Primary text | `#DDE8E1` | Soft pale text with readable contrast |
| Secondary text | `#93A99B` | Muted labels and supporting metadata |
| Primary action | `#87DDA7` | Mint action with dark foreground |

The font family and exact values are not specified by the view-only canvas; CropTwist’s existing Geist typography is retained unless later inspectable evidence justifies a change. Status colors remain semantic and distinct; they are not replaced by the mint brand color.

## 2. Existing CropTwist product structure

The selected code base already implements a single Next.js workspace route backed by `src/components/croptwist/workspace.tsx`. Navigation state is synchronized through the URL contract `/?tab=<id>&sub=<sub>&farm=<id>&field=<id>&fieldName=<name>`. `src/lib/navigation.ts` defines nine canonical destinations, their sub-pages, legacy tab redirects, and aliases; `tests/frontend/navigation.test.ts` protects much of that routing contract. The visual redesign should therefore change the shell and presentation without replacing the route/store/API model.

| CropTwist destination | Existing implementation and Figma relationship | Main invariants to preserve |
|---|---|---|
| **Overview** (`overview`) | `overview.tsx` renders farm/field summaries, health status, a selected field’s climate view, explore/quick actions, and a create-first-farm state. No one-to-one Figma Overview frame was verified. | Farm/field selection precedence, query keys, climate time windows, real-data/no-data semantics, and action callbacks. |
| **Farms & Fields** (`farms`) | `farms-fields.tsx` provides farm/field selection, CRUD, field map and boundary history, and export. | API contracts, mutation invalidation, field context, GeoJSON warnings/repair state, export shape, and tenant enforcement by the server. |
| **Data Hub** (`datahub`) | `observations.tsx`, `features.tsx`, `data-passport.tsx`, `adaptive-evidence.tsx`, and `satellite-scenes.tsx` cover observations, calculated features, provenance/passport, evidence workflows, and scene catalog/acquisition. Group A is the closest Figma match. | Field-scoped queries, polling, provenance and synthetic labels, unavailable reasons, and the scene page’s explicit rule not to display unverified vegetation-index values. |
| **Crop Intelligence** (`cropintel`) | `rotation-overview.tsx` now renders B1 at `/?tab=cropintel&sub=rotation-overview`; `RotationPlanner` renders B2 at `/?tab=cropintel&sub=rotation-planner`. `rotation.tsx`, `water.tsx`, `soil.tsx`, the management sub-pages, `forecast.tsx`, and `soil-memory.tsx` remain mounted. | All original sub-page IDs/aliases, field-context behavior, evidence/null/status contracts, Simple/Expert state, exports, and agronomic constraints remain. The original `cropintel:rotation` optimizer and `cropintel:plan` management plan were not repurposed. |
| **Map & Satellite** (`geo`) | `navigation/map-satellite-pane.tsx`, `farm-map.tsx`, `map/layer-manager.tsx`, `satellite.tsx`, and P07 hooks/types provide the map, layer catalog, raster overlays, temporal controls, point sampling, statistical zones, and satellite summary. | MapLibre lifecycle, source/layer IDs and order, asset/scene/version resolution, same-origin tile access, field switching, provenance, and honest unavailable/error states. |
| **Decision Center** (`decisions`) | Existing sub-pages include field state, scenarios, sensitivity, robust planning, decision documents, failure lab, portfolio, and digital twin. The sidebar vocabulary aligns with the visible Group C labels, but dedicated Group C layouts were not verified. | `?tab=decisions&sub=documents` is distinct from bare `decisions`; preserve typed server results, evidence states, query keys, and avoid invented scores/probabilities. |
| **AI Copilot** (`copilot`) | `ai-insights.tsx`, `ai-copilot.tsx`, API helpers and hooks implement field-scoped conversations, streaming, evidence, limitations, feedback consent, and provider state. No matching Figma frame was verified. | Payload/SSE contracts, field scope, abort/thread lifecycle, consent/disclaimer, server-side identity/tenant checks, and provider privacy. |
| **Reports & Analytics** (`reports`) | Reports, analytics hub, insights, and exports cover report generation/library/scheduling and analytical panels. No matching Figma frame was verified. | URL/query parameters, report state/polling/download behavior, applied filters, provenance/no-data states, and responsive data views. |
| **Workspace & Settings** (`settings`) | Team/organization, billing, developer, preferences, notifications, and onboarding are implemented in existing components. No matching Figma frame was verified. | Role/entitlement rules, current organization-selection behavior, destructive confirmations, one-time secrets, authentication, and localized settings routes. |

A read-only, parallel source audit was completed for all nine destinations. The existing destination views are mostly white/stone surfaces with emerald accents, while the Figma reference uses dark forest/charcoal surfaces and mint actions. The audit found useful dense tables/panels and substantial data/API behavior already present; it did not find evidence that a Figma frame name alone guarantees a backend capability. Do not combine or relocate capabilities solely because the design board groups them visually.

## 3. Repository and branch baseline

The actual source repository is the public GitHub repository named by the user, `abdelrahmanelharouny/project1`. Before implementation, the remote branch inventory showed `main` at `998f7a5885e4ee0c9defe28671736560fb1b8762`, `feature/gis-spatial-analytics` at `324486e863de19b65d34786be2590732368c449d` (open PR #1), `fix/ci-baseline-alembic-bun` at `a3c617a939686396b921ee45379c0dc8e448f9be` (open PR #3), `feature/ai-complete-integration` at `38f8891696f6c27e79e25ddf65b33549f4a51397`, and `integration/cropshift-control` at `759a094bc5c895b6e2042f9a2654179889a6f423`.

The redesign branch was created locally as a separate worktree from the exact AI integration tip `38f8891696f6c27e79e25ddf65b33549f4a51397`. This is intentionally not a `main` base: the AI branch contains the real nine-destination product shell, API clients, AI Copilot/orchestration interfaces, and an initial GIS commit (`0ed6039`), while the control branch is documentation-only and the GIS branch does not contain the later AI work. The selected base is the most complete available UI/API foundation for this requested redesign; its GitHub CI was not green, so this is not a release-readiness claim.

The GIS branch contains three later GIS commits after the shared `0ed6039` base and changes map/data-processing UI and API files. Those GIS changes are not included in the redesign base and must be reconciled deliberately before any integration; the redesign must not alter the GIS source branch or GIS algorithms. The AI source branch and `app/db/models_ai.py` are likewise out of scope for edits. The separate `/home/ubuntu/fieldshift` scaffold and Figma notes are preserved and are not the implementation repository. At branch creation, the audit worktree remained clean on `main`; the new redesign worktree was separate.

## 4. Implementation guidance and risks

1. Keep CropTwist branding; “FieldShift” is a reference board label, not permission to rename the product or transfer its demo records.
2. Treat Figma sample values as illustrative. The visible board explicitly labels the workspace as demo and warns that plans/geometry are illustrative or not measured. Any fixtures in CropTwist must be labeled as sample/demo; do not present them as actual farms, satellite observations, weather, or recommendations.
3. Build the shared shell and design tokens around the existing nine-destination route model. Preserve keyboard/mobile navigation and all deep links rather than replacing URL state.
4. Prefer presentation-only modules/adapters around existing hooks, typed responses, and API services. Preserve authenticated same-origin calls, tenant boundaries, entitlements, status/error semantics, provenance, and no-data behavior.
5. Global styling has a broad blast radius: `globals.css` records the current light-only styling decision and many destination components use hard-coded stone/emerald utilities. Restyle through controlled shared tokens/classes and check map, charts, semantic statuses, dialogs, and RTL contrast rather than blindly inverting every color.
6. The visible Figma canvas does not provide inspectable spacing values, font metadata, all Group C layouts, or mobile frames. Keep those limitations explicit and use CropTwist’s established responsive, localization, accessibility, and API behavior as the source of truth where Figma evidence is absent.
7. Existing client contracts do not independently verify backend authorization, live endpoint availability, provider readiness, or production data. An incomplete endpoint must produce an honest unavailable state; continue with other destinations rather than fabricating a capability.

## 5. Implementation and visual QA status

Implemented so far on `feature/croptwist-ui-ux-redesign`:

- Central dark forest/charcoal tokens, semantic color mapping, shared card/form/table styling, and a CropTwist-branded desktop sidebar with all nine destinations and nested routes.
- Responsive mobile navigation with 44px targets, onboarding access, compact locale selector, command-palette/share access, and a right-opening RTL sheet.
- Data Hub Features now displays the Figma-referenced “No calculated features yet” state, a real navigation action to observations, and explicit loading, error, retry, and catalog-empty states. All displayed feature data remains API-backed; no feature metrics or operational status are fabricated.
- HTTPS Preview session cookies use `Secure; HttpOnly; SameSite=None`, while plain-HTTP local sessions remain `SameSite=Lax`; logout clears them with matching attributes.
- Added the B1 Crop Rotation Overview and B2 Rotation Planner as additive subpages. Overview filters and exports backend-returned crop-history records with source/evidence context and honest loading/error/empty states; Planner reuses existing season/candidate/optimizer operations and explicitly labels its output analysis-only. No illustrative sequence, save, or approval state is fabricated.
- Replaced the starter external ChatGLM favicon and “First vertical slice” metadata with a local CropTwist sprout SVG and factual product description.

Validation evidence: `npx --yes --package bun@1.4.4 bun test tests/frontend` passes **146 tests**; `bun run lint`, `bun x tsc --noEmit`, and the Next.js production build pass. All locale JSON parses, and en/ar keys match for destinations (33), rotation (119), and features (79). `public/manus-routes.json` contains 12 unique states. The root, both new Crop Rotation deep links, the manifest, and local logo each returned HTTP 200 on the local development server.

Chromium screenshots of the actual unauthenticated sign-in page were captured at 1440×900, 390×844, and 360×800. The sign-in card fits all three widths without horizontal overflow. Evidence files: [1440px sign-in](/home/ubuntu/project1-ui-ux/docs/audits/visual/crop-login-1440.png), [390px sign-in](/home/ubuntu/project1-ui-ux/docs/audits/visual/crop-login-390.png), and [360px sign-in](/home/ubuntu/project1-ui-ux/docs/audits/visual/crop-login-360.png). These images are not screenshots of the authenticated destinations and do not establish a Figma match for the dashboard.

Authenticated visual verification remains blocked: the actual frontend requests `/api/v1/me` and `/api/v1/health/ready` through `127.0.0.1:3030`, and Chromium/Next logs show `ECONNREFUSED` because no backend listener is running there. No authenticated test account was available. The “Enter demo workspace” action was not invoked because it calls the demo-seed path and could write sample records to an unverified backend/database. Therefore, per-destination screenshots, interactive dashboard comparison, and authenticated Arabic/RTL layout verification are still open. No pixel-perfect matching is claimed.

**Verified code checkpoint:** `482f266f86d42cc391cf2263ff303a4c810cf8e0` is pushed to `origin/feature/croptwist-ui-ux-redesign`; `main` remains `998f7a5885e4ee0c9defe28671736560fb1b8762`. The branch is intentionally not merged while GIS integration and authenticated destination regression remain unresolved.
