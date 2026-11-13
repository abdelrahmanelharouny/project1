# P02-D — Known Limitations & Deferred Work (W0+W1)

Honest record of what W0+W1 does NOT cover, plus follow-ups for W2+.

> **P03 W2 update (2026-11-13):** §1 items 1–4 (W2.1–W2.4) are now
> implemented — see `docs/p03/P03_IMPLEMENTATION_SUMMARY.md` for scope and
> verification. Items 5–7 of §1 (W3 scope) and all of §2 remain open.

## 1. Deferred to W2 (per P01 plan sequencing — not defects)

| Item | Plan ref | Note |
|---|---|---|
| ~~Management's 6 internal sub-views stay behind its in-component switcher~~ **RESOLVED in W2.1** | W2.1 | Six views promoted to URL-keyed `?sub=` sub-pages of Crop Intelligence; `?sub=management` aliases to `plan` forever (`SUB_ALIASES`); Simple/Expert toggle store-backed (`managementExpert`) so the mode survives moving between the sub-pages. |
| ~~Preferences remains a section inside team-tab~~ **RESOLVED in W2.2** | W2.2 | PreferencesCard moved verbatim to `?tab=settings&sub=preferences` (+ additive `?tab=preferences` alias); `?tab=team` still lands on Organization & members. |
| ~~Shared execution-picker across sensitivity/robust/decisions not extracted~~ **RESOLVED in W2.3** | W2.3 | `field-context.tsx` (useFieldContext / FieldContextGate / useFieldAvailability) adopted by six views; ContextBar is the single validating picker (unavailable-field notice instead of silent zeroing); per-tab guidance gates kept by design (P02 §5.2). |
| ~~Command palette = navigation commands ONLY~~ **RESOLVED in W2.4** | W2.4 | Four real command groups (Navigation destinations, Sections incl. promoted management sub-pages + Preferences, Farm & field context from the user's accessible resources, Actions: create farm/field + copy share link) plus a memory-only Recent group. Reachable on desktop (trigger + Ctrl/Cmd+K) and mobile (nav-sheet "Search & commands" row). |
| Overview dedupe (retire its map instance, fold "how it works" prose) | W3.2 | Overview keeps its map + charts; nothing removed in W1/W2. |
| Forecast `verifyForecasts` UI still unwired | W3.4 | Pre-existing gap (P01 audit §4.4), unchanged. |
| Loading/error primitive rollout beyond water+overview | W0.7 | Shared primitives exist (`state-views.tsx`); other tabs keep their existing (working) states. |

## 2. In-scope but partial

| Item | Status | Detail |
|---|---|---|
| 44px touch targets | Primary nav fully compliant (rail 44px, sheet 44px, hamburger 44×44); audit-named header sites bumped to `h-9`/`h-10` (36–40px) | A repo-wide sweep of every sub-44px control is not done — residual small controls exist inside dense tables (pre-existing, unchanged). |
| W0.6 theme tokens | Light-only formalized; dead config deleted; `.dark` kept dormant + documented | The ~1,690 hardcoded stone-/emerald- utilities are NOT migrated to semantic tokens — that is the later visual redesign phase (deliberate, avoids a broad restyle). |
| aria-invalid wiring | Audit-named site (`farms-fields.tsx`) already wired; broader described-by wiring not extended | Remaining forms validate via toast without aria-describedby (pre-existing pattern; tracked for the a11y pass in the visual phase). |
| Backend pytest battery | Not re-run inside P02 | Host environment lacks backend deps (pre-existing); behavior guaranteed unchanged via API e2e smoke + zero backend diffs. A containerized battery run belongs in the next backend-touching phase. |

## 3. Documented semantic decisions W2+ must respect

1. **`decisions` collision:** bare `?tab=decisions` = Decision Center default (Field state); the legacy "Decision documents" view lives at `?tab=decisions&sub=documents` (`P02_NAVIGATION_MAPPING.md` §1).
2. **Destination-ids-win resolution order** in both `resolveTarget` and the store resolver — keep them in lockstep.
3. **Store is the only legacy-resolution point** — never re-introduce per-component mapping.
4. **History semantics:** user navigation pushes; canonicalization replaces. Components that navigate MUST go through store actions (not raw router writes) to keep the push/replace model.

## 4. Environment quirks (sandbox, not product)

- **Tailwind v4 dev-scan lag:** under `next dev --webpack`, newly-introduced utility classes (e.g. `xl:block`) were not compiled until the dev server restarted (observed twice). A restart fixes it; a fresh `next build` is unaffected. If a P02+ branch appears unstyled at a breakpoint, restart `bun run dev` before debugging.
- **agent-browser network route:** request interception matched with glob `**/water-plans/**` but not `**/api/v1/water-plans/*`; browser HTTP-cache also serves previously-fetched GETs while "offline". Verification used real network failure + cold cache instead.
- Backend pytest battery remains host-unrunnable (no psycopg2/sqlalchemy in the host python env).

## 5. Open risks for W2 (all addressed in W2 — kept for the record)

1. **Sub-page state loss is Radix-unmount semantics** (same as the old 27-tab strip). → W2 URL-keys management's sub-views and keeps the shared Simple/Expert mode in the store (`managementExpert`); per-view local state (e.g. a drafted cover-crop window) still resets on view change — unchanged semantics, same as pre-W2.
2. **Context-bar + per-tab empty-state pickers coexist by design** (tab-specific guidance kept). → W2.3 extracted the six verbatim copies into `FieldContextGate` and kept the remaining custom guidance gates intact with their CTA targets.
3. **Rail fits at ≥xl (1280px)** via the max-w-7xl shell. → W2.1 grows the Crop Intelligence rail from 8 to 11 sub-pages; vertical (desktop) / horizontal scrollable (mobile) rails absorb the growth without horizontal page overflow (verified 1440 + 390, LTR + RTL). Destination rail unchanged (still nine).
4. **Palette growth:** W2 adds field commands; keep the "real commands only" contract — palette items must map to existing actions. → W2.4 keeps the contract: every command maps to an existing capability; context commands come from the user's accessible farms/fields only; empty/loading and no-field states render honest entries.
5. **`?sub=` grammar is now part of the URL contract.** → W2 keeps old URLs resolving: `?tab=cropintel&sub=management` aliases to `plan` forever via `SUB_ALIASES` (never 404, never loops); the legacy `?tab=management` redirect lands on the same default view the old tab opened (plan); `?tab=preferences` is additive. Unit-tested in `tests/frontend/navigation.test.ts` (45 tests).
