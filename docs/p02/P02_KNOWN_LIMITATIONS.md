# P02-D — Known Limitations & Deferred Work (W0+W1)

Honest record of what W0+W1 does NOT cover, plus follow-ups for W2+.

## 1. Deferred to W2 (per P01 plan sequencing — not defects)

| Item | Plan ref | Note |
|---|---|---|
| Management's 6 internal sub-views stay behind its in-component switcher (not URL-keyed `?sub=`) | W2.1 | Moved verbatim by design; state-loss semantics unchanged from pre-P02. |
| Preferences remains a section inside team-tab (no true Settings sub-page yet) | W2.2 | `settings/organization` renders the team tab incl. preferences until extraction. |
| Shared execution-picker across sensitivity/robust/decisions not extracted | W2.3 | Artifacts still re-selected per view (journey J9 friction unchanged). |
| Command palette = navigation commands ONLY (9 destinations + 24 sub-pages) | W2.4 | No field commands, no artifact actions — deliberately, to avoid inventing actions. |
| Overview dedupe (retire its map instance, fold "how it works" prose) | W3.2 | Overview keeps its map + charts; nothing removed in W1. |
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

## 5. Open risks for W2

1. **Sub-page state loss is Radix-unmount semantics** (same as the old 27-tab strip). If W2 URL-keys management's sub-views, keep the internal state keyed consistently or users lose scroll/selection on destination switches.
2. **Context-bar + per-tab empty-state pickers coexist by design** (tab-specific guidance kept). If W2 removes any empty-state picker, its CTA target must be preserved.
3. **Rail fits at ≥xl (1280px)** via the max-w-7xl shell. If a tenth destination or longer labels arrive (e.g. localizations longer than English), re-measure or the rail will rely on the scroll+scrollIntoView fallback below the fit threshold.
4. **Palette growth:** W2 adds field commands; keep the "real commands only" contract — palette items must map to existing actions.
5. **`?sub=` grammar is now part of the URL contract.** W2 extractions (management sub-pages, preferences) must keep old URLs resolving: `?tab=cropintel&sub=management` must keep working after sub-pages split (default to the first sub-view, never 404/loop).
