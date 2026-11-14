'use client'

import { useTranslations } from 'next-intl'
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
import { ErrorState } from '@/components/croptwist/state-views'
import { useFarmsWithFields } from '@/hooks/use-croptwist'
import { useCropTwistUi, type SelectedField } from '@/lib/store'

interface FieldPickerProps {
  value: string | null
  onValueChange: (field: SelectedField) => void
  id?: string
  /** Rendered when the workspace has no fields at all. */
  emptyHint?: React.ReactNode
}

/** Shared "pick a field across all farms" dropdown for Observations / Data Passport. */
export function FieldPicker({ value, onValueChange, id, emptyHint }: FieldPickerProps) {
  const t = useTranslations('common')
  const tFarms = useTranslations('farms')
  const { farms, allFields, isLoading, hasError, hasFarmsError, retryFailedQueries } = useFarmsWithFields()
  const errorMessage = hasFarmsError ? tFarms('loadFarmsError') : tFarms('loadFieldsError')

  if (isLoading) {
    return <Skeleton className="h-9 w-full sm:w-[280px]" aria-label={t('loadingFields')} />
  }

  if (hasError && allFields.length === 0) {
    return <ErrorState message={errorMessage} onRetry={retryFailedQueries} />
  }

  if (allFields.length === 0) {
    return (
      emptyHint ?? (
        <div className="flex items-center gap-2 text-sm text-stone-500">
          <span>{t('noFieldsYet')}</span>
          <GoToFarmsButton label={t('createFarmField')} />
        </div>
      )
    )
  }

  return (
    <div className="space-y-2">
      {hasError ? <ErrorState message={errorMessage} onRetry={retryFailedQueries} /> : null}
      <Select
        value={value ?? ''}
        onValueChange={(fieldId) => {
          const field = allFields.find((entry) => entry.id === fieldId)
          if (field) onValueChange({ id: field.id, name: field.name, farmId: field.farm_id })
        }}
      >
        <SelectTrigger id={id} className="w-full sm:w-[280px] bg-white" aria-label={t('selectField')}>
          <SelectValue placeholder={t('selectField')} />
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
    </div>
  )
}

export function GoToFarmsButton({ label }: { label?: string }) {
  const t = useTranslations('common')
  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  return (
    <Button variant="outline" size="sm" onClick={() => setActiveTab('farms')}>
      {label ?? t('goToFarms')}
    </Button>
  )
}
