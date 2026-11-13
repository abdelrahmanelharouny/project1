'use client'

/**
 * P02 W1 / P03 W2.3 — persistent farm/field context bar (blueprint §2.1: the
 * shared FieldPicker that lived in 20 tabs moves into ONE instance in the
 * shell). It is now also the single place that validates the context:
 *
 * Bindings are unchanged: it reads/writes the same `selectedField` store
 * slice the per-tab pickers used, so selection stays synchronized across
 * destination changes and deep links (?farm=&field=&fieldName=) keep driving
 * it. A selected field that is missing from the user's accessible fields
 * (deleted, revoked, or an invalid deep link) renders an honest unavailable
 * notice with a real clear action instead of a broken Select — never silently
 * zeroed, and never auto-cleared on transient load failures.
 */

import { FieldPicker } from '@/components/croptwist/field-picker'
import { UnavailableFieldNotice, useFieldAvailability, useFieldContext } from '@/components/croptwist/field-context'

export function ContextBar({ className }: { className?: string }) {
  const { selectedField, setSelectedField } = useFieldContext()
  const availability = useFieldAvailability()

  return (
    <div className={className}>
      {selectedField && availability === 'unavailable' ? (
        <UnavailableFieldNotice field={selectedField} onClear={() => setSelectedField(null)} />
      ) : (
        <FieldPicker
          value={selectedField?.id ?? null}
          onValueChange={setSelectedField}
        />
      )}
    </div>
  )
}
