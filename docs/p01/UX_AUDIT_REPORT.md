# P01-B — UX/UI Audit Report

**Audit date:** 2026-11-13 · Baseline `a83af70` · Method: static source inspection of all 44 `src/components/croptwist/**` files + `src/app/**` shell, quantified greps, and **live browser verification** (Agent Browser against the running dev stack; screenshots in `docs/p01/evidence/`).

**Live-measured facts (this session):**

| Measurement | Result |
|---|---|
| Tab count rendered | **27** (`document.querySelectorAll` tab triggers = 27) |
| Tab strip width @1440×900 | **3,263px in a 1,440px viewport** — ~1,823px hidden scroll on desktop (`evidence/01-desktop-overview-1440px.png`) |
| Tab strip width @390×844 | **3,047px in a 390px viewport — ≈8 screens of horizontal scrolling** (`evidence/03-mobile-tabstrip.png`) |
| First heading after auth | `H2 "Welcome to your workspace"` — **no `<h1>` exists post-auth** |
| Clicking an off-screen tab label ("Reports") via locator | **failed — element not visible/scrollable-to** (live proof of discoverability failure) |
| Console errors during session | 0 |

---

## 1. Navigation — severity: HIGH (primary transformation target)

- **Flat strip of 27 tabs**, no grouping, no separators, no search, no command palette, no breadcrumbs: `TAB_ITEMS` at `src/components/croptwist/workspace.tsx:80-108`; single `<TabsList>` in an `overflow-x-auto` container at `workspace.tsx:353-363`.
- **No scroll-into-view**: `grep scrollIntoView src/` → 0 hits; deep-linked right-side tabs open off-screen; assistive/locator access to late tabs fails (measured above).
- **No role/plan adaptation**: all 27 tabs render for every signed-in user; only in-content gating exists (`p3/team-tab.tsx:220-221`). Billing/Developer show 403-at-click-time for non-org_admins.
- Hidden IA depth: `management.tsx:210-236` nests 6 sub-tabs; `p3/team-tab.tsx` packs 5 concerns into one screen — "27 tabs" understates real IA.
- Terminology collisions: "AI Insights" vs "Insights" (`messages/en/nav.json:15,32`); engineering jargon exposed to farmers ("Features", "Adaptive Evidence", "Failure Lab", "Digital Twin").
- Positive: URL deep-linking is well-built (`workspace.tsx:118-164`); unknown `?tab=` values safely ignored (`workspace.tsx:131`).

## 2. Layout & shell — severity: MEDIUM

- Boot = up to 3 sequential spinners (`page.tsx:13-30` dynamic import → Suspense → workspace `checking`); hardcoded English "Loading CropTwist workspace…" at `page.tsx:18` (only non-i18n string found).
- `src/app/layout.tsx` has **no `viewport` export / `themeColor` / `viewport-fit=cover`** → footer's `pb-[env(safe-area-inset-bottom)]` (`workspace.tsx:170`) is inert on iOS; no header inset.
- Footer is `mt-auto` (not sticky-fixed) inside `min-h-screen flex-col` — acceptable per current contract, but no separation from content on long tabs.
- Route-level states are genuinely good: `loading.tsx` (aria-busy/live, i18n), `error.tsx` (retry+reload+digest), `global-error.tsx`, `not-found.tsx` — all polished.

## 3. Theme & tokens — severity: HIGH

- **Semantic tokens are effectively unused by app code**: only **1** semantic-token class in `src/components/croptwist/**` (`auth-gate.tsx:234 bg-card`); the other 84 occurrences live in `src/components/ui/*` primitives.
- Hardcoded palette dominates: **1,239 `stone-*`** (43 files), **229 `emerald-*`** (34 files), 116 `red-*`, 106 `amber-*`. Primary green hardcoded as `bg-emerald-700 hover:bg-emerald-800` (e.g. `auth-gate.tsx:171,220`, `overview.tsx:173`).
- **Dark mode is dead code**: `next-themes ^0.4.6` in `package.json:50`, complete `.dark` oklch set in `globals.css:81-113`, but `providers.tsx:7-26` has no `ThemeProvider` and `grep dark:` in app code → 0. Unreachable by users.
- **`tailwind.config.ts` is dead and misleading** (verified): `hsl(var(--…))` mappings contradict the oklch values actually used (`globals.css:46-79`); content globs target non-existent dirs; Tailwind v4 never loads it.
- Typography: consistent scale direction but **173 uses of `text-[10px]`/`text-[11px]` across 22 files** (worst: `management.tsx` 25, `soil.tsx` 21, `ai-insights.tsx` 20) — below comfortable/accessible sizes.
- Zero gradient decoration, zero emoji in components (verified) — good.

## 4. States (loading / empty / error) — severity: MEDIUM

- Broad coverage: Skeleton ×133/28 files, Loader2 ×62/14, query-state refs ×302/34, toasts ×428/20.
- **Silent-failure data view**: active water plan renders with no loading skeleton and no error branch (`water.tsx:976,1010-1021`; grep `plan.isLoading|plan.isError` → 0).
- **Mislabeled control**: the Overview error card's retry button is labeled "Quick actions" (`overview.tsx:96-98` + `messages/en/overview.json:24`).
- Pattern inconsistency: same concept as Skeleton vs spinner+text (`rotation.tsx:190-193`) vs button-label swap (`soil.tsx:456`) — no shared loader primitive.
- Charts have no own loading/error states (parent-owned, parent coverage varies).
- No per-tab error boundaries; one app-level `error.tsx` covers all.
- Positive: entitlement guard UX (402 → deduped toast + Upgrade) is clean (`src/lib/entitlement-guard.ts`).

## 5. Component patterns — severity: MEDIUM

- Card padding inconsistent: `p-6` only 12×/5 files; `p-4`/`p-3` families elsewhere — no enforced rhythm.
- **Best-in-repo pattern exists but is not propagated**: P3 tabs render desktop tables `hidden md:block` + stacked mobile cards `md:hidden` (`p3/billing-tab.tsx:889-943`, also reports/insights/developer); core (P1/P2) tabs do not.
- `ui/sheet.tsx`, `ui/drawer.tsx`, `ui/command.tsx`, `ui/form.tsx` (react-hook-form), `ui/breadcrumb.tsx` shipped but **never used** in app code — intended patterns never adopted.
- Tooltip used only by 4 P3 tabs; core tabs rely on bare `title=` (`sensitivity.tsx:148,361`).
- Two chart styling generations coexist: `ui/chart.tsx` wrapper (newer) vs raw recharts `ReTooltip` (`observations.tsx:835-868`).

## 6. Accessibility — severity: MEDIUM (strong base, specific gaps)

- Strengths: 529 aria/role/sr-only occurrences/39 files; **all 13 icon-only buttons carry aria-label** (verified across `p3/reports-tab.tsx:652-694`, `workspace.tsx:251-260`, etc.); `role="alert"` error text in forms (`farms-fields.tsx:316`); Radix tabs give arrow-key navigation.
- **No `<h1>` on any authed screen** (only `auth-gate.tsx:128` has one; verified live: first heading is H2).
- **Touch targets below 44px in the primary nav**: tab strip height 36px (`ui/tabs.tsx:29,45`); `h-7 w-7` icon button (`p3/team-tab.tsx:438`); `h-8` controls (`locale-switcher.tsx:40`, `workspace.tsx:244,257`).
- `aria-invalid` only once (`farms-fields.tsx:105`); forms otherwise validate by toast without described-by wiring.
- One hardcoded untranslated aria-label `aria-label="Overview"` (`overview.tsx:84`).

## 7. Mobile — severity: HIGH (nav) / MEDIUM (content)

- The 27-tab strip is the primary mobile navigation — measured **3,047px wide ≈ 8 screens of scrolling at 390px**, no hamburger/sheet/sidebar fallback, no auto-scroll-to-active.
- Responsive prefixes thin in the largest core tabs: `sensitivity.tsx` 1 hit/1,041 lines; `scenario-execution.tsx` 1/681; `robust-plan.tsx` 1/667.
- Wide tables rely on scroll wrappers (`water.tsx:591,630` min-w 560/620px; `ui/table.tsx` overflow-x-auto) — usable but cramped.
- No 390px-breaking fixed widths found; charts use ResponsiveContainer. No console errors at mobile size (verified).

## 8. Cognitive load & duplication — severity: HIGH

- Overview = ~9 blocks / ~10 concepts — acceptable, but "how it works" prose duplicates onboarding content, and health appears 3×.
- Field context re-selected in 20 tabs via `FieldPicker` while Overview ignores the selection entirely → "which field am I looking at?" is inconsistent across tabs.
- Scenario chain artifacts (runs/ids/verify) re-presented in 5 tabs (scenarios→sensitivity→robust→decisions→digital twin).
- Management tab hides 6 sub-IA levels; team tab packs 5 concerns; three separate tabs for soil concepts (Soil / Field State / Soil Memory).

---

## 9. Ranked problem list

| # | Sev | Problem | Evidence |
|---|---|---|---|
| P1 | HIGH | 27-tab flat strip; 3,263px@1440 / 3,047px@390; no grouping/search/scroll-into-view | `workspace.tsx:80-108,353-363`; live measurements |
| P2 | HIGH | Theme system dead: no ThemeProvider, 0 dark: classes, ~1,690 hardcoded palette classes, 1 semantic-token use | `providers.tsx:7-26`, `globals.css:81-113`, grep counts |
| P3 | HIGH | `tailwind.config.ts` dead/misleading (hsl vars, wrong globs) | `tailwind.config.ts:6-53` vs `globals.css:46-79` |
| P4 | HIGH | Overview ignores selected farm/field (binds `farms[0]`) | `overview.tsx:59-62` (verified live source) |
| P5 | HIGH | Silent-failure water plan view (no loading/error) | `water.tsx:976,1010-1021` |
| P6 | HIGH | Mislabeled retry button ("Quick actions") | `overview.tsx:96-98` |
| P7 | MED | Empty-state CTAs jump to Observations with empty field | `features.tsx:573`, `rotation.tsx:867`, `water.tsx:998` |
| P8 | MED | Touch targets 36px in tab strip; h-7/h-8 controls | `ui/tabs.tsx:29,45`; `p3/team-tab.tsx:438` |
| P9 | MED | No h1 post-auth; aria-invalid once; untranslated aria-label | live DOM; `farms-fields.tsx:105`; `overview.tsx:84` |
| P10 | MED | Safe-area inert (no viewport export) | `layout.tsx` vs `workspace.tsx:170` |
| P11 | MED | Toast-first errors (428 calls) without per-tab boundaries | grep counts |
| P12 | MED | Dead code: `use-fieldshift.ts` (516 lines), store drift `store.ts:82-83`, empty `maplibre-gl-shared.mjs` | grep + `wc -c` verified |
| P13 | LOW | Loading pattern inconsistency (3 styles, no primitive) | `rotation.tsx:190` vs `soil.tsx:456` vs Skeleton×28 |
| P14 | LOW | `text-[10px]/[11px]` ×173/22 files | grep counts |
| P15 | LOW | Tooltip only in P3 tabs; title= elsewhere | `sensitivity.tsx:148,361` |
| P16 | LOW | Unused ui primitives (sheet/drawer/command/form/breadcrumb) | grep imports = 0 |
| P17 | LOW | `router.replace` deep-link breaks Back-button tab history | `workspace.tsx:159` |

## 10. What is working well (keep and build on)

- URL deep-linking architecture (`workspace.tsx:118-164`) — extend, don't replace.
- Entitlement-guard UX (`src/lib/entitlement-guard.ts`) — clean, deduped, honest.
- P3 tab patterns: loading skeletons per section, mobile stacked cards, `dir="ltr"` pins for machine values — adopt as the house pattern.
- Route-level error/loading/not-found states — polished and accessible.
- Provenance honesty in UI (SyntheticBadge, "No data" chips, never zero-filled).
- Zero console errors across desktop/mobile session; zero emoji/decoration clutter.
