# CropTwist redesign regression report

**Status:** Partial verification checkpoint — authenticated workflows and per-destination visual QA remain blocked.<br>
**Repository:** `https://github.com/abdelrahmanelharouny/project1`<br>
**Branch:** `feature/croptwist-ui-ux-redesign`<br>
**Base SHA:** `38f8891696f6c27e79e25ddf65b33549f4a51397` (`feature/ai-complete-integration`)<br>
**Latest code commit / push:** `482f266f86d42cc391cf2263ff303a4c810cf8e0`; local and remote branch refs matched at verification. Remote `main` remains `998f7a5885e4ee0c9defe28671736560fb1b8762`.

## Automated checks

| Check | Result |
|---|---|
| `npx --yes --package bun@1.4.4 bun test tests/frontend` | **PASS** — 146 tests, 0 failed, across 8 files; includes navigation contract, GIS utilities, HTTPS/local cookie behavior, and crop-history period filtering. |
| `npx --yes --package bun@1.4.4 bun run lint` | **PASS** — ESLint completed without findings. |
| `npx --yes --package bun@1.4.4 bun x tsc --noEmit` | **PASS** — no TypeScript diagnostics. |
| `npx --yes --package bun@1.4.4 bun run build` | **PASS** — Next.js production build and standalone asset copy completed. |
| Python parse of all `messages/**/*.json` plus en/ar key parity | **PASS** — all locale JSON parses; destination labels match (33 keys), rotation messages match (119 keys), and feature messages match (79 keys). |
| `public/manus-routes.json` contract | **PASS** — 12 unique route-state entries including `/?tab=cropintel&sub=rotation-overview` and `/?tab=cropintel&sub=rotation-planner`. |
| Local HTTP checks | **PASS** — `/`, both new rotation query URLs, `/manus-routes.json`, and `/logo.svg` returned HTTP 200. |
| `git diff --check` | **PASS** — no whitespace errors at the check point. |

## Route and behavior regression scope

Two additive Crop Intelligence views were added: Crop Rotation Overview and Rotation Planner. Navigation tests confirm there are 33 sub-pages across the existing six multi-sub destinations; both new route IDs resolve. The established `cropintel:rotation` default and legacy `?tab=rotation` continue to target the original optimizer, while `cropintel:plan` remains the existing management-plan page. The Overview’s year facets and filters are tested against recorded date fields, including null/undated records; the `all` filter preserves all rows without mutating the source array.

The new Planner reuses current candidate-generation, optimizer, and knowledge/evidence components. Its Simple/Expert switch gates existing operations; it does not imply that optimization output is saved or approved. No persistence/approval API exists for a future rotation, so no fake Save/Approve action was added. No endpoint/schema, GIS algorithm, AI provider contract, database model, or cross-branch integration was changed.

## Browser visual evidence

Chromium screenshots of the actual unauthenticated sign-in page are committed under `docs/audits/visual/`:

- [Sign-in — 1440×900](../audits/visual/crop-login-1440.png)
- [Sign-in — 390×844](../audits/visual/crop-login-390.png)
- [Sign-in — 360×800](../audits/visual/crop-login-360.png)

The sign-in card fits those three viewport widths without visible horizontal overflow. These are not authenticated dashboard captures and do not establish visual parity for any destination. The new Overview/Planner components, other seven destinations, responsive authenticated shell, Arabic/RTL workspace, map controls, keyboard/focus states, and screen-reader flows were not visually inspected while authenticated.

## Explicit blocker and safety

The sign-in page’s session and health probes call the local API through `127.0.0.1:3030`. Next.js logs show `ECONNREFUSED` for `GET /api/v1/me` and `GET /api/v1/health/ready`, and a listener check confirmed that nothing is running on port 3030. No authenticated test identity was available. The “Enter demo workspace” control was not invoked because it reaches a demo-seed endpoint and could write sample data to an unverified backend/database.

Therefore, authenticated destination screenshots and Figma comparisons; farm/field mutations; Data Hub ingestion/acquisition; GIS/raster workflows; AI provider flows; decision/report/settings mutations; and API/tenant-isolation integration tests remain **not run / not verified**. This is an environment/authentication blocker, not evidence that those workflows pass. No demo seed, production database write, external-provider call, GIS algorithm change, or AI-model change was performed.

## Delivery state

The verified code commit `482f266f86d42cc391cf2263ff303a4c810cf8e0` is pushed to `origin/feature/croptwist-ui-ux-redesign`; the remote ref matched at verification. The branch is based on `feature/ai-complete-integration` at `38f8891696f6c27e79e25ddf65b33549f4a51397`. Remote `main` remains `998f7a5885e4ee0c9defe28671736560fb1b8762`. No pull request was opened and no merge was performed; GIS integration and full regression remain separate gates.
