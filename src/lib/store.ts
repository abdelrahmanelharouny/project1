'use client'

import { create } from 'zustand'

export type WorkspaceTab =
  | 'overview'
  | 'farms'
  | 'observations'
  | 'features'
  | 'rotation'
  | 'water'
  | 'fieldstate'
  | 'scenarios'
  | 'soil'
  | 'management'
  | 'sensitivity'
  | 'decisions'
  | 'aiinsights'
  | 'digitaltwin'
  | 'robustplan'
  | 'passport'

export interface SelectedField {
  id: string
  name: string
  farmId: string
}

interface FieldShiftUiState {
  activeTab: WorkspaceTab
  selectedFarmId: string | null
  selectedField: SelectedField | null
  /** Farms & Fields dialog; Overview quick action opens it cross-tab. */
  createFarmDialogOpen: boolean
  setActiveTab: (tab: WorkspaceTab) => void
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
}

export const useFieldShiftUi = create<FieldShiftUiState>((set) => ({
  activeTab: 'overview',
  selectedFarmId: null,
  selectedField: null,
  createFarmDialogOpen: false,
  setActiveTab: (tab) => set({ activeTab: tab }),
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
  openCreateFarm: () => set({ createFarmDialogOpen: true, activeTab: 'farms' }),
  goToPassportFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'passport' }),
  goToFeaturesFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'features' }),
  goToRotationFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'rotation' }),
  goToWaterFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'water' }),
  goToFieldStateFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'fieldstate' }),
  goToScenariosFor: (field) => set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'scenarios' }),
  goToObservationsFor: (field) =>
    set({ selectedField: field, selectedFarmId: field.farmId, activeTab: 'observations' }),
}))
