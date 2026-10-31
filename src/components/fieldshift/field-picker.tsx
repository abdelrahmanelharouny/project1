'use client'

import { MapPin } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { useFarmsWithFields } from '@/hooks/use-fieldshift'
import { useFieldShiftUi, type SelectedField } from '@/lib/store'

interface FieldPickerProps {
  value: string | null
  onValueChange: (field: SelectedField) => void
  id?: string
  /** Rendered when the workspace has no fields at all. */
  emptyHint?: React.ReactNode
}

/** Shared "pick a field across all farms" dropdown for Observations / Data Passport. */
export function FieldPicker({ value, onValueChange, id, emptyHint }: FieldPickerProps) {
  const { farms, allFields, isLoading } = useFarmsWithFields()

  if (isLoading) {
    return <Skeleton className="h-9 w-full sm:w-[280px]" aria-label="Loading fields" />
  }

  if (allFields.length === 0) {
    return (
      emptyHint ?? (
        <div className="flex items-center gap-2 text-sm text-stone-500">
          <span>No fields yet.</span>
          <GoToFarmsButton label="Create a farm & field" />
        </div>
      )
    )
  }

  return (
    <Select
      value={value ?? undefined}
      onValueChange={(fieldId) => {
        const field = allFields.find((entry) => entry.id === fieldId)
        if (field) onValueChange({ id: field.id, name: field.name, farmId: field.farm_id })
      }}
    >
      <SelectTrigger id={id} className="w-full sm:w-[280px] bg-white" aria-label="Select a field">
        <SelectValue placeholder="Select a field" />
      </SelectTrigger>
      <SelectContent>
        {farms.map(({ farm, fields }) =>
          fields.length > 0 ? (
            <SelectGroup key={farm.id}>
              <SelectLabel>{farm.name}</SelectLabel>
              {fields.map((field) => (
                <SelectItem key={field.id} value={field.id}>
                  <span className="inline-flex items-center gap-1.5">
                    <MapPin className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
                    {field.name}
                  </span>
                </SelectItem>
              ))}
            </SelectGroup>
          ) : null,
        )}
      </SelectContent>
    </Select>
  )
}

export function GoToFarmsButton({ label = 'Go to Farms & Fields' }: { label?: string }) {
  const setActiveTab = useFieldShiftUi((s) => s.setActiveTab)
  return (
    <Button variant="outline" size="sm" onClick={() => setActiveTab('farms')}>
      {label}
    </Button>
  )
}
