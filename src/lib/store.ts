'use client'

import { create } from 'zustand'

import {
  LEGACY_REDIRECTS,
  defaultSubFor,
  isDestinationTab,
  isLegacyTab,
  isValidSub,
  normalizeSub,
  type DestinationId,
  type WorkspaceTab,
} from '@/lib/navigation'

// P02 W1: the URL contract is the nine canonical destination ids plus the 27
// permanent legacy ids. The type re-export keeps every existing
// `import { type WorkspaceTab } from '@/lib/store'` working unchanged.
export type { WorkspaceTab, DestinationId } from '@/lib/navigation'

export interface SelectedField {
  id: string
  name: string
  farmId: string
}

/** P03 W2.4 — one visited view (destination + sub), newest first, in-memory
 * only (no persistence — the palette's Recent group reads this live list). */
export interface RecentView {
  tab: DestinationId
  sub: string | null
}

interface CropTwistUiState {
  /** Canonical destination id (never a legacy id — legacy ids resolve on write). */
  activeTab: DestinationId
  /** Active sub-page for multi-sub destinations; null for single-view ones. */
  activeSub: string | null
  /** Recent views for the command palette (deduped, capped, memory-only). */
  recentViews: RecentView[]
  selectedFarmId: string | null
  selectedField: SelectedField | null
  /** P03 W2.1 — management Simple/Expert toggle. Stored so the shared mode
   * survives moving between the promoted management sub-pages. */
  managementExpert: boolean
  /** Farms & Fields dialog; Overview quick action opens it cross-tab. */
  createFarmDialogOpen: boolean
  setActiveTab: (tab: WorkspaceTab) => void
  /** Navigate with an explicit destination + optional sub-page (URL-sync + rails). */
  navigateTo: (tab: WorkspaceTab, sub?: string | null) => void
  setActiveSub: (sub: string | null) => void
  setManagementExpert: (expert: boolean) => void
  setSelectedFarmId: (farmId: string | null) => void
  setSelectedField: (field: SelectedField | null) => void
  renameSelectedField: (fieldId: string, name: string) => void
  setCreateFarmDialogOpen: (open: boolean) => void
  openCreateFarm: () => void
  goToPassportFor: (field: SelectedField) => void
  goToObservationsFor: (field: SelectedField) => void
  goToFeaturesFor: (field: SelectedField) => void
  goToFieldStateFor: (field: SelectedField) => void
  goToScenariosFor: (field: SelectedField) => void
  /** P12 drift fix: implemented since Milestone 7 but missing from this interface. */
  goToRotationFor: (field: SelectedField) => void
  goToWaterFor: (field: SelectedField) => void
}

/** Recent list update: dedupe consecutive repeats, cap at 8, newest first. */
function pushRecent(recent: RecentView[], view: RecentView): RecentView[] {
  const last = recent[0]
  if (last && last.tab === view.tab && last.sub === view.sub) return recent
  return [{ tab: view.tab, sub: view.sub }, ...recent].slice(0, 8)
}

/**
 * P02 W1 — THE single legacy-resolution point. Every tab write (rail clicks,
 * URL deep links, the entitlement guard's 'billing', the onboarding wizard's
 * 'farms'/'team', the notification bell's link kinds, the goTo* helpers)
 * funnels through `resolveTarget`-equivalent rules, so the 27 legacy `?tab=`
 * ids redirect permanently and no component carries its own mapping logic.
 *
 * Rules:
 *   - legacy id            → mapped destination + sub-page (permanent redirect)
 *   - destination id       → canonical; sub goes through `normalizeSub`
 *                            (aliases first — e.g. `management` → `plan` —
 *                            then validation; invalid/missing falls back to
 *                            the destination default; never blank, never loops)
 *   - unknown id           → state unchanged (previous view preserved — the
 *                            pre-P02 "unknown tab safely ignored" contract)
 *   - re-selecting the ACTIVE destination without an explicit sub keeps the
 *     current sub-page (rail re-click does not reset the user's place)
 */
function tabState(
  state: Pick<CropTwistUiState, 'activeTab' | 'activeSub' | 'recentViews'>,
  tab: WorkspaceTab,
  explicitSub?: string | null,
): Pick<CropTwistUiState, 'activeTab' | 'activeSub' | 'recentViews'> {
  // Destination ids win for the four ids that exist as BOTH legacy and
  // destination (overview/farms/reports/decisions) — same order as
  // resolveTarget, so store writes and URL deep links always agree.
  if (isDestinationTab(tab)) {
    if (explicitSub) {
      const normalized = normalizeSub(tab, explicitSub)
      if (normalized) {
        return { activeTab: tab, activeSub: normalized, recentViews: pushRecent(state.recentViews, { tab, sub: normalized }) }
      }
      return { activeTab: tab, activeSub: defaultSubFor(tab), recentViews: pushRecent(state.recentViews, { tab, sub: defaultSubFor(tab) }) }
    }
    // No explicit sub: keep the current sub-page when re-selecting the active
    // destination (rail re-click preserves the place), else the destination default.
    if (tab === state.activeTab) {
      return { activeTab: tab, activeSub: state.activeSub, recentViews: state.recentViews }
    }
    const def = defaultSubFor(tab)
    return { activeTab: tab, activeSub: def, recentViews: pushRecent(state.recentViews, { tab, sub: def }) }
  }
  // Pure legacy id (e.g. water, fieldstate, team): the mapped sub-page IS the
  // intent — always applied (goToWaterFor after goToRotationFor must move
  // rotation → irrigation even though both live in Crop Intelligence). A valid
  // explicit sub for the mapped destination still wins (?tab=management&sub=…).
  if (isLegacyTab(tab)) {
    const mapped = LEGACY_REDIRECTS[tab]
    if (explicitSub) {
      const normalized = normalizeSub(mapped.tab, explicitSub)
      if (normalized) {
        return { activeTab: mapped.tab, activeSub: normalized, recentViews: pushRecent(state.recentViews, { tab: mapped.tab, sub: normalized }) }
      }
    }
    return { activeTab: mapped.tab, activeSub: mapped.sub, recentViews: pushRecent(state.recentViews, { tab: mapped.tab, sub: mapped.sub }) }
  }
  // Unknown id: state unchanged (pre-P02 "unknown tab safely ignored" contract).
  return { activeTab: state.activeTab, activeSub: state.activeSub, recentViews: state.recentViews }
}

export const useCropTwistUi = create<CropTwistUiState>((set) => ({
  activeTab: 'overview',
  activeSub: null,
  recentViews: [],
  selectedFarmId: null,
  selectedField: null,
  managementExpert: false,
  createFarmDialogOpen: false,
  setActiveTab: (tab) => set((state) => tabState(state, tab)),
  navigateTo: (tab, sub) => set((state) => tabState(state, tab, sub)),
  setActiveSub: (sub) =>
    set((state) => {
      if (!isValidSub(state.activeTab, sub)) return {}
      return {
        activeSub: sub,
        recentViews: pushRecent(state.recentViews, { tab: state.activeTab, sub }),
      }
    }),
  setManagementExpert: (expert) => set({ managementExpert: expert }),
  setSelectedFarmId: (farmId) => set({ selectedFarmId: farmId }),
  setSelectedField: (field) =>
    set((state) => ({
      selectedField: field,
      // keep the farm selector in sync when a field of another farm is chosen
      selectedFarmId: field ? field.farmId : state.selectedFarmId,
    })),
  renameSelectedField: (fieldId, name) =>
    set((state) =>
      state.selectedField && state.selectedField.id === fieldId
        ? { selectedField: { ...state.selectedField, name } }
        : {},
    ),
  setCreateFarmDialogOpen: (open) => set({ createFarmDialogOpen: open }),
  openCreateFarm: () =>
    set((state) => {
      const next = tabState(state, 'farms')
      return { ...next, createFarmDialogOpen: true }
    }),
  goToPassportFor: (field) =>
    set((state) => ({ ...tabState(state, 'passport'), selectedField: field, selectedFarmId: field.farmId })),
  goToFeaturesFor: (field) =>
    set((state) => ({ ...tabState(state, 'features'), selectedField: field, selectedFarmId: field.farmId })),
  goToRotationFor: (field) =>
    set((state) => ({ ...tabState(state, 'rotation'), selectedField: field, selectedFarmId: field.farmId })),
  goToWaterFor: (field) =>
    set((state) => ({ ...tabState(state, 'water'), selectedField: field, selectedFarmId: field.farmId })),
  goToFieldStateFor: (field) =>
    set((state) => ({ ...tabState(state, 'fieldstate'), selectedField: field, selectedFarmId: field.farmId })),
  goToScenariosFor: (field) =>
    set((state) => ({ ...tabState(state, 'scenarios'), selectedField: field, selectedFarmId: field.farmId })),
  goToObservationsFor: (field) =>
    set((state) => ({ ...tabState(state, 'observations'), selectedField: field, selectedFarmId: field.farmId })),
}))
