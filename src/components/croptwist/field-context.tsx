'use client'

/**
 * P03 W2.3 — shared execution-context primitives (blueprint §2.1/J9).
 *
 * After P02 moved the persistent picker into the shell ContextBar, ~13 tabs
 * still repeated the same "no field selected → guidance + picker" gate and
 * the store bindings were re-declared per file. This module is the single
 * home for that genuinely-repeated behavior:
 *
 *   - `useFieldContext()`      — the store bindings (atomic selectors, no
 *                                object allocation → no extra re-renders)
 *   - `FieldContextGate`       — the exact repeated empty-state card
 *                                (replaces six verbatim copies)
 *   - `useFieldAvailability()` — safe handling of missing/deleted/inaccessible
 *                                deep-linked fields for the shared ContextBar
 *
 * Farm/field data comes only from `useFarmsWithFields` (the authenticated
 * user's accessible resources — server-enforced), so the context commands and
 * availability checks can never expose a farm/field the user cannot access.
 */

import { useTranslations } from 'next-intl'
import { MapPinOff } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { FieldPicker } from '@/components/croptwist/field-picker'
import { useFarmsWithFields } from '@/hooks/use-croptwist'
import { useCropTwistUi, type SelectedField } from '@/lib/store'

/** Store bindings for the shared execution context. Selectors are atomic —
 * components only re-render when the slice they read actually changes. */
export function useFieldContext() {
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const setSelectedFarmId = useCropTwistUi((s) => s.setSelectedFarmId)
  return { selectedField, setSelectedField, selectedFarmId, setSelectedFarmId }
}

/** The repeated "pick a field to see this view" gate — one implementation
 * instead of six verbatim copies (same markup, same FieldPicker binding). */
export function FieldContextGate({ hint }: { hint: string }) {
  const { selectedField, setSelectedField } = useFieldContext()
  if (selectedField) return null
  return (
    <Card>
      <CardContent className="py-10 text-center text-sm text-stone-500">
        <p>{hint}</p>
        <div className="mx-auto mt-4 max-w-xs">
          <FieldPicker value={null} onValueChange={setSelectedField} />
        </div>
      </CardContent>
    </Card>
  )
}

export type FieldAvailability =
  | 'none' // no field selected
  | 'checking' // selected, but the accessible list has not loaded yet
  | 'available' // selected and present in the user's accessible fields
  | 'unavailable' // selected but missing from the accessible fields (deleted, inaccessible, or invalid id)

/**
 * Validate the selected field against the farms/fields the authenticated user
 * can actually access. Never auto-clears the selection (a deep link must not
 * be destroyed by a transient query failure) — callers decide what to render.
 */
export function useFieldAvailability(): FieldAvailability {
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const { allFields, isLoading } = useFarmsWithFields()
  if (!selectedField) return 'none'
  if (isLoading) return 'checking'
  return allFields.some((f) => f.id === selectedField.id) ? 'available' : 'unavailable'
}

/** ContextBar rendering for an unavailable (deleted/inaccessible) field —
 * honest state + a real clear action; no silent zeroing, no fake picker. */
export function UnavailableFieldNotice({ field, onClear }: { field: SelectedField; onClear: () => void }) {
  const t = useTranslations('common')
  return (
    <div
      className="flex w-full items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm sm:w-[280px]"
      role="status"
    >
      <span className="flex min-w-0 items-center gap-1.5 text-amber-900">
        <MapPinOff className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate font-medium">{field.name}</span>
        <span className="shrink-0 text-xs text-amber-800">{t('fieldUnavailable')}</span>
      </span>
      <Button
        variant="outline"
        size="sm"
        className="h-7 shrink-0 px-2 text-xs"
        onClick={onClear}
      >
        {t('clear')}
      </Button>
    </div>
  )
}
