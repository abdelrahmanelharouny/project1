/**
 * P02 W1 — Central navigation model for the nine-destination workspace.
 *
 * SINGLE SOURCE OF TRUTH for:
 *   - the nine primary destinations ("Fewer destinations, deeper capabilities,
 *     clearer decisions" — docs/p01/NAVIGATION_REDESIGN_BLUEPRINT.md),
 *   - the permanent legacy `?tab=` redirect map for all 27 former tab ids
 *     (docs/p01/UX_MIGRATION_MATRIX.md §3 — legacy ids remain valid forever,
 *     they redirect, they are never removed),
 *   - sub-page validation (`?sub=`) with safe fallbacks.
 *
 * This module is intentionally PURE (no React, no zustand, no next/*): it is
 * imported by the store, by navigation components and by unit tests
 * (`bun test tests/frontend/`). Do not add framework imports here.
 *
 * Legacy mapping logic lives ONLY here — never scatter redirects across
 * components. Consumers (store actions, URL sync, notification bell targets,
 * entitlement-guard upgrade target) all resolve through `resolveTarget`.
 */

// ---------------------------------------------------------------------------
// Destination model
// ---------------------------------------------------------------------------

export const DESTINATION_IDS = [
  'overview',
  'farms',
  'datahub',
  'cropintel',
  'geo',
  'decisions',
  'copilot',
  'reports',
  'settings',
] as const

export type DestinationId = (typeof DESTINATION_IDS)[number]

export interface SubPageDef {
  id: string
  /** i18n key inside the `destinations.sub` namespace. */
  labelKey: string
}

export interface DestinationDef {
  id: DestinationId
  /** i18n key inside the `destinations` namespace. */
  labelKey: string
  /** Ordered sub-pages. Empty for single-view destinations. */
  subPages: readonly SubPageDef[]
}

/**
 * The nine destinations in workflow-spine order (data → intelligence →
 * decisions → explanation → administration). Sub-page order inside Decision
 * Center follows the verified decision chain (blueprint C4).
 */
export const DESTINATIONS: readonly DestinationDef[] = [
  { id: 'overview', labelKey: 'overview', subPages: [] },
  { id: 'farms', labelKey: 'farms', subPages: [] },
  {
    id: 'datahub',
    labelKey: 'datahub',
    subPages: [
      { id: 'observations', labelKey: 'observations' },
      { id: 'features', labelKey: 'features' },
      { id: 'passport', labelKey: 'passport' },
      { id: 'evidence', labelKey: 'evidence' },
    ],
  },
  {
    id: 'cropintel',
    labelKey: 'cropintel',
    // P03 W2.1: management's six internal sub-views are promoted to visible,
    // URL-keyed sub-pages (blueprint §C2: "6 sub-views → 6 sub-pages").
    // `?sub=management` keeps resolving forever via SUB_ALIASES below.
    subPages: [
      { id: 'rotation', labelKey: 'rotation' },
      { id: 'irrigation', labelKey: 'irrigation' },
      { id: 'soil', labelKey: 'soil' },
      { id: 'plan', labelKey: 'plan' },
      { id: 'covers', labelKey: 'covers' },
      { id: 'timeline', labelKey: 'timeline' },
      { id: 'residue', labelKey: 'residue' },
      { id: 'erosion', labelKey: 'erosion' },
      { id: 'operations', labelKey: 'operations' },
      { id: 'soilmemory', labelKey: 'soilmemory' },
      { id: 'forecast', labelKey: 'forecast' },
    ],
  },
  {
    id: 'geo',
    labelKey: 'geo',
    subPages: [{ id: 'map', labelKey: 'map' }],
  },
  {
    id: 'decisions',
    labelKey: 'decisions',
    subPages: [
      { id: 'state', labelKey: 'state' },
      { id: 'scenarios', labelKey: 'scenarios' },
      { id: 'sensitivity', labelKey: 'sensitivity' },
      { id: 'robust', labelKey: 'robust' },
      { id: 'documents', labelKey: 'documents' },
      { id: 'failurelab', labelKey: 'failurelab' },
      { id: 'portfolio', labelKey: 'portfolio' },
      { id: 'twin', labelKey: 'twin' },
    ],
  },
  { id: 'copilot', labelKey: 'copilot', subPages: [] },
  {
    id: 'reports',
    labelKey: 'reports',
    subPages: [
      { id: 'reports', labelKey: 'reports' },
      { id: 'analytics', labelKey: 'analytics' },
    ],
  },
  {
    id: 'settings',
    labelKey: 'settings',
    // P03 W2.2: preferences gets its own Settings sub-page (blueprint §C7:
    // "preferences gets a home"). Appended last — existing sub ids never move.
    subPages: [
      { id: 'organization', labelKey: 'organization' },
      { id: 'billing', labelKey: 'billing' },
      { id: 'developer', labelKey: 'developer' },
      { id: 'preferences', labelKey: 'preferences' },
    ],
  },
]

// ---------------------------------------------------------------------------
// Legacy tab contract (permanent redirect map — docs/p01/UX_MIGRATION_MATRIX.md §3)
// ---------------------------------------------------------------------------

/**
 * The 27 legacy `?tab=` identifiers. They remain part of the URL contract
 * forever: any old bookmark, notification link or shared URL keeps working
 * through `resolveTarget`, which redirects to destination + sub-page.
 */
export const LEGACY_TAB_IDS = [
  'overview',
  'farms',
  'observations',
  'features',
  'rotation',
  'water',
  'fieldstate',
  'scenarios',
  'soil',
  'management',
  'sensitivity',
  'decisions',
  'aiinsights',
  'digitaltwin',
  'robustplan',
  'passport',
  'satellite',
  'forecast',
  'soilmemory',
  'failurelab',
  'adaptiveevidence',
  'portfolio',
  'team',
  'billing',
  'insights',
  'reports',
  'developer',
] as const

export type LegacyTabId = (typeof LEGACY_TAB_IDS)[number]

/**
 * Every id that can appear in the URL/store contract: the nine destination
 * ids (canonical, additive) plus the 27 legacy ids (permanent, redirect-only).
 */
export type WorkspaceTab = DestinationId | LegacyTabId

/**
 * Permanent legacy → { destination, sub-page } redirect map. Values mirror
 * docs/p01/UX_MIGRATION_MATRIX.md §3 exactly. Legacy ids whose destination is
 * a single-view map to `sub: null`.
 */
export const LEGACY_REDIRECTS: Readonly<Record<LegacyTabId, ResolvedTarget>> = {
  overview: { tab: 'overview', sub: null },
  farms: { tab: 'farms', sub: null },
  observations: { tab: 'datahub', sub: 'observations' },
  features: { tab: 'datahub', sub: 'features' },
  passport: { tab: 'datahub', sub: 'passport' },
  adaptiveevidence: { tab: 'datahub', sub: 'evidence' },
  rotation: { tab: 'cropintel', sub: 'rotation' },
  water: { tab: 'cropintel', sub: 'irrigation' },
  soil: { tab: 'cropintel', sub: 'soil' },
  // P03 W2.1: the old "Crop management" tab opened on its Plan view, so the
  // permanent redirect now lands on the promoted plan sub-page — the exact
  // same rendered view as before the split.
  management: { tab: 'cropintel', sub: 'plan' },
  soilmemory: { tab: 'cropintel', sub: 'soilmemory' },
  forecast: { tab: 'cropintel', sub: 'forecast' },
  satellite: { tab: 'geo', sub: 'map' },
  fieldstate: { tab: 'decisions', sub: 'state' },
  scenarios: { tab: 'decisions', sub: 'scenarios' },
  sensitivity: { tab: 'decisions', sub: 'sensitivity' },
  robustplan: { tab: 'decisions', sub: 'robust' },
  decisions: { tab: 'decisions', sub: 'documents' },
  failurelab: { tab: 'decisions', sub: 'failurelab' },
  portfolio: { tab: 'decisions', sub: 'portfolio' },
  digitaltwin: { tab: 'decisions', sub: 'twin' },
  aiinsights: { tab: 'copilot', sub: null },
  reports: { tab: 'reports', sub: 'reports' },
  insights: { tab: 'reports', sub: 'analytics' },
  team: { tab: 'settings', sub: 'organization' },
  billing: { tab: 'settings', sub: 'billing' },
  developer: { tab: 'settings', sub: 'developer' },
}

// ---------------------------------------------------------------------------
// Sub-page aliases (P03 W2 — permanent, like the legacy tab map)
// ---------------------------------------------------------------------------

/**
 * Old `?sub=` values that remain valid forever after W2 promoted management's
 * internal views. `?tab=cropintel&sub=management` (the P02 URL for the whole
 * management suite) resolves to the suite's default view (plan) — never 404,
 * never a loop. Keep entries additive; never repurpose an alias.
 */
export const SUB_ALIASES: Readonly<Record<DestinationId, Readonly<Record<string, string>>>> = {
  cropintel: { management: 'plan' },
  overview: {},
  farms: {},
  datahub: {},
  geo: {},
  decisions: {},
  copilot: {},
  reports: {},
  settings: {},
}

/** Extra additive tab aliases beyond the 27 legacy ids (P03 W2.2): friendly
 * canonical entry points that never existed as tabs but must keep resolving. */
export const EXTRA_TAB_ALIASES: Readonly<Record<string, ResolvedTarget>> = {
  preferences: { tab: 'settings', sub: 'preferences' },
}

/**
 * Normalize a raw `?sub=` value for a destination: applies SUB_ALIASES, then
 * validates. Returns null when the sub is not usable for that destination.
 */
export function normalizeSub(id: DestinationId, sub: string | null | undefined): string | null {
  if (!sub) return null
  const aliased = SUB_ALIASES[id]?.[sub]
  const candidate = aliased ?? sub
  return isValidSub(id, candidate) ? candidate : null
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

export interface ResolvedTarget {
  tab: DestinationId
  sub: string | null
}

export function destinationById(id: string): DestinationDef | undefined {
  return DESTINATIONS.find((d) => d.id === id)
}

/** First sub-page of a destination, or null for single-view destinations. */
export function defaultSubFor(id: DestinationId): string | null {
  const dest = destinationById(id)
  if (!dest || dest.subPages.length === 0) return null
  return dest.subPages[0].id
}

export function isValidSub(id: DestinationId, sub: string | null | undefined): boolean {
  if (!sub) return false
  const dest = destinationById(id)
  return !!dest && dest.subPages.some((s) => s.id === sub)
}

/**
 * Resolve any raw `?tab=` value (plus optional `?sub=`) into the canonical
 * destination/sub-page target.
 *
 * Rules (deep-link contract, blueprint §5):
 *   - destination id            → canonical target (sub validated, defaults applied)
 *   - legacy id (all 27, forever) → redirect target from LEGACY_REDIRECTS
 *   - null / unknown id         → null (caller keeps its current/fallback view;
 *                                 identical to the pre-P02 "unknown tab safely
 *                                 ignored" behavior — no redirect loops)
 *
 * `resolveTarget` is idempotent: resolving its own output returns the same
 * target, so canonicalized URLs never bounce.
 */
export function resolveTarget(tab: string | null | undefined, sub?: string | null | undefined): ResolvedTarget | null {
  if (!tab) return null
  const dest = destinationById(tab)
  if (dest) {
    const normalized = normalizeSub(dest.id, sub)
    if (normalized) return { tab: dest.id, sub: normalized }
    return { tab: dest.id, sub: defaultSubFor(dest.id) }
  }
  const legacy = LEGACY_REDIRECTS[tab as LegacyTabId]
  if (legacy) return { tab: legacy.tab, sub: legacy.sub }
  return EXTRA_TAB_ALIASES[tab] ?? null
}

/** True when the value is one of the 27 permanent legacy ids. */
export function isLegacyTab(tab: string | null | undefined): tab is LegacyTabId {
  return !!tab && Object.prototype.hasOwnProperty.call(LEGACY_REDIRECTS, tab)
}

/** True when the value is one of the nine canonical destination ids. */
export function isDestinationTab(tab: string | null | undefined): tab is DestinationId {
  return !!tab && DESTINATION_IDS.includes(tab as DestinationId)
}
