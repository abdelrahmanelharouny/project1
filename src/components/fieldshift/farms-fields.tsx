'use client'

import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Loader2,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  SquareStack,
  TriangleAlert,
  Tractor,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useTranslations } from 'next-intl'
import { ExportButton } from '@/components/fieldshift/export-button'
import { FarmMap } from '@/components/fieldshift/farm-map'
import { FieldMap } from '@/components/fieldshift/field-map'
import { useBoundaryVersions, useFieldMap, useFields, useFarms } from '@/hooks/use-fieldshift'
import {
  createBoundaryVersion,
  createFarm,
  createField,
  describeError,
  EXAMPLE_GEOMETRY,
  parseGeometryInput,
  patchField,
} from '@/lib/api'
import { formatArea, formatDay, formatDateTime } from '@/lib/format'
import { useFieldShiftUi } from '@/lib/store'
import type {
  BoundaryVersionCreateResponse,
  Farm,
  FarmCreateInput,
  Field,
  FieldCreateResponse,
  GeoJSONGeometry,
  UnitSystem,
} from '@/lib/types'

// ---------------------------------------------------------------------------
// Shared geometry input (add field + update boundary)
// ---------------------------------------------------------------------------

function GeometryInput({
  id,
  value,
  onChange,
  error,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  error?: string | null
}) {
  const t = useTranslations('farms')

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{t('geometryLabel')}</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-emerald-700 hover:text-emerald-800"
          onClick={() => onChange(EXAMPLE_GEOMETRY)}
        >
          <SquareStack className="h-3.5 w-3.5" aria-hidden /> {t('useExampleSquare')}
        </Button>
      </div>
      <Textarea
        id={id}
        rows={7}
        spellCheck={false}
        className="font-mono text-xs"
        placeholder='{"type":"Polygon","coordinates":[[[31.40,31.10],[31.42,31.10],[31.42,31.12],[31.40,31.12],[31.40,31.10]]]}'
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={Boolean(error)}
      />
      {error ? (
        <p className="text-xs font-medium text-red-700" role="alert">
          {error}
        </p>
      ) : (
        <p className="text-xs text-stone-500">{t('geometryHint')}</p>
      )}
    </div>
  )
}

function GeometryWarningsAlert({
  warnings,
  repaired,
  title,
}: {
  warnings: string[]
  repaired?: boolean
  title: string
}) {
  const t = useTranslations('farms')

  if (warnings.length === 0 && !repaired) return null
  return (
    <Alert className="border-amber-300 bg-amber-50 [&>svg]:text-amber-600">
      <TriangleAlert className="h-4 w-4" />
      <AlertTitle className="text-amber-900">{title}</AlertTitle>
      <AlertDescription className="text-amber-900">
        {repaired ? (
          <p className="mb-1 text-xs font-medium">{t('geometryRepaired')}</p>
        ) : null}
        <ul className="list-disc space-y-0.5 pl-4 text-xs">
          {warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

// ---------------------------------------------------------------------------
// Create farm dialog
// ---------------------------------------------------------------------------

const TIMEZONES = ['UTC', 'Africa/Cairo', 'Europe/Rome', 'America/Chicago', 'Asia/Bangkok']

function CreateFarmDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient()
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const [name, setName] = useState('')
  const [country, setCountry] = useState('')
  const [adminRegion, setAdminRegion] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [currency, setCurrency] = useState('')
  const [unitSystem, setUnitSystem] = useState<UnitSystem>('metric')
  const [language, setLanguage] = useState('en')
  const [formError, setFormError] = useState<string | null>(null)

  // Reset form state when the dialog closes (handler-based, no effect needed).
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      setCountry('')
      setAdminRegion('')
      setTimezone('UTC')
      setCurrency('')
      setUnitSystem('metric')
      setLanguage('en')
      setFormError(null)
    }
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: (input: FarmCreateInput) => createFarm(input),
    onSuccess: (farm) => {
      queryClient.invalidateQueries({ queryKey: ['farms'] })
      toast.success(t('farmCreated', { name: farm.name }), {
        description: `${farm.timezone} · ${farm.currency_code} · ${farm.unit_system}`,
      })
      handleOpenChange(false)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      setFormError(title)
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const countryClean = country.trim().toUpperCase()
    const currencyClean = currency.trim().toUpperCase()
    const languageClean = language.trim().toLowerCase()
    if (!name.trim()) return setFormError(t('nameRequired'))
    if (!/^[A-Z]{2}$/.test(countryClean)) return setFormError(t('countryRequired'))
    if (!/^[A-Z]{3}$/.test(currencyClean)) return setFormError(t('currencyRequired'))
    if (!/^[a-z]{2}$/.test(languageClean)) return setFormError(t('languageRequired'))
    setFormError(null)
    mutation.mutate({
      name: name.trim(),
      country_code: countryClean,
      admin_region: adminRegion.trim() || undefined,
      timezone,
      currency_code: currencyClean,
      unit_system: unitSystem,
      preferred_language: languageClean,
    })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('createTitle')}</DialogTitle>
          <DialogDescription>
            {t('createDesc')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" aria-label={t('createFormAria')}>
          <div className="space-y-1.5">
            <Label htmlFor="farm-name">{t('nameLabel')}</Label>
            <Input
              id="farm-name"
              placeholder={t('namePlaceholder')}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="farm-country">{t('countryLabel')}</Label>
              <Input
                id="farm-country"
                maxLength={2}
                placeholder="EG"
                value={country}
                onChange={(event) => setCountry(event.target.value.toUpperCase())}
                className="uppercase"
              />
              <p className="text-xs text-stone-500">{t('countryHint')}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="farm-region">{t('regionLabel')}</Label>
              <Input
                id="farm-region"
                placeholder={t('regionPlaceholder')}
                value={adminRegion}
                onChange={(event) => setAdminRegion(event.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="farm-timezone">{t('timezoneLabel')}</Label>
              <Select value={timezone} onValueChange={setTimezone}>
                <SelectTrigger id="farm-timezone" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="farm-currency">{t('currencyLabel')}</Label>
              <Input
                id="farm-currency"
                maxLength={3}
                placeholder="USD"
                value={currency}
                onChange={(event) => setCurrency(event.target.value.toUpperCase())}
                className="uppercase"
              />
              <p className="text-xs text-stone-500">{t('currencyHint')}</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="farm-units">{t('unitSystemLabel')}</Label>
              <Select value={unitSystem} onValueChange={(value) => setUnitSystem(value as UnitSystem)}>
                <SelectTrigger id="farm-units" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="metric">{t('unitsMetric')}</SelectItem>
                  <SelectItem value="imperial">{t('unitsImperial')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="farm-language">{t('languageLabel')}</Label>
              <Input
                id="farm-language"
                maxLength={2}
                placeholder="en"
                value={language}
                onChange={(event) => setLanguage(event.target.value.toLowerCase())}
              />
              <p className="text-xs text-stone-500">{t('languageHint')}</p>
            </div>
          </div>
          {formError ? (
            <p className="text-sm font-medium text-red-700" role="alert">
              {formError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {tCommon('cancel')}
            </Button>
            <Button type="submit" className="bg-emerald-700 hover:bg-emerald-800" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
              {t('createSubmit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Add field dialog
// ---------------------------------------------------------------------------

function AddFieldDialog({
  farm,
  open,
  onOpenChange,
  onFieldSelected,
}: {
  farm: Farm
  open: boolean
  onOpenChange: (open: boolean) => void
  onFieldSelected: (field: { id: string; name: string; farmId: string }) => void
}) {
  const queryClient = useQueryClient()
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const [name, setName] = useState('')
  const [geometry, setGeometry] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<{ title: string; description?: string } | null>(null)
  const [created, setCreated] = useState<FieldCreateResponse | null>(null)

  // Reset form state when the dialog closes.
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      setGeometry('')
      setParseError(null)
      setApiError(null)
      setCreated(null)
    }
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: (payload: { name: string; geometry: GeoJSONGeometry }) =>
      createField(farm.id, { name: payload.name, geometry: payload.geometry }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['fields', farm.id] })
      queryClient.invalidateQueries({ queryKey: ['farms'] })
      if (result.geometry_warnings.length > 0) {
        setCreated(result)
        toast.warning(t('fieldCreatedWarnings'), {
          description: t('warningsFromPostgis', { count: result.geometry_warnings.length }),
        })
      } else {
        toast.success(t('fieldCreated', { name: result.name }), {
          description: t('fieldCreatedDesc', {
            area: formatArea(result.area_ha),
            unit: tCommon('ha'),
            version: result.boundary_version,
          }),
        })
        onFieldSelected({ id: result.id, name: result.name, farmId: farm.id })
        handleOpenChange(false)
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      setApiError({ title, description })
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setApiError(null)
    setCreated(null)
    if (!name.trim()) {
      setParseError(t('fieldNameRequired'))
      return
    }
    const parsed = parseGeometryInput(geometry)
    if (!parsed.ok) {
      setParseError(parsed.error)
      return
    }
    setParseError(null)
    mutation.mutate({ name: name.trim(), geometry: parsed.geometry })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('addFieldTitle', { farm: farm.name })}</DialogTitle>
          <DialogDescription>
            {t('addFieldDesc')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" aria-label={t('addFieldFormAria')}>
          <div className="space-y-1.5">
            <Label htmlFor="field-name">{t('fieldLabel')}</Label>
            <Input
              id="field-name"
              placeholder={t('fieldPlaceholder')}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <GeometryInput id="field-geometry" value={geometry} onChange={setGeometry} error={parseError} />

          {created ? (
            <div className="space-y-2">
              <Alert className="border-emerald-300 bg-emerald-50 [&>svg]:text-emerald-700">
                <MapPin className="h-4 w-4" />
                <AlertTitle className="text-emerald-900">
                  {t('fieldCreatedArea', {
                    name: created.name,
                    area: formatArea(created.area_ha),
                    unit: tCommon('ha'),
                  })}
                </AlertTitle>
                <AlertDescription className="text-emerald-900">
                  {t('boundaryPassport', {
                    version: created.boundary_version,
                    status: created.data_passport_status,
                  })}
                </AlertDescription>
              </Alert>
              <GeometryWarningsAlert
                warnings={created.geometry_warnings}
                repaired={created.geometry_repaired}
                title={t('postgisWarnings')}
              />
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    onFieldSelected({ id: created.id, name: created.name, farmId: farm.id })
                    handleOpenChange(false)
                  }}
                >
                  {t('openNewField')}
                </Button>
              </div>
            </div>
          ) : null}

          {apiError ? (
            <Alert variant="destructive">
              <TriangleAlert className="h-4 w-4" />
              <AlertTitle>{apiError.title}</AlertTitle>
              <AlertDescription>{apiError.description ?? t('adjustGeometryRetry')}</AlertDescription>
            </Alert>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {created ? tCommon('close') : tCommon('cancel')}
            </Button>
            <Button type="submit" className="bg-emerald-700 hover:bg-emerald-800" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
              {t('createFieldSubmit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Rename + update boundary dialogs
// ---------------------------------------------------------------------------

function RenameFieldDialog({
  field,
  open,
  onOpenChange,
}: {
  field: Field
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const renameSelectedField = useFieldShiftUi((s) => s.renameSelectedField)
  const [name, setName] = useState(field.name)

  // Sync the input with the current field name each time the dialog opens.
  const handleOpenChange = (next: boolean) => {
    if (next) setName(field.name)
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: () => patchField(field.id, { name: name.trim() }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['fields'] })
      renameSelectedField(updated.id, updated.name)
      toast.success(t('fieldRenamed', { name: updated.name }))
      onOpenChange(false)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim() || name.trim() === field.name) {
      onOpenChange(false)
      return
    }
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('renameTitle')}</DialogTitle>
          <DialogDescription>{t('renameDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" aria-label={t('renameFormAria')}>
          <div className="space-y-1.5">
            <Label htmlFor="rename-field">{t('fieldLabel')}</Label>
            <Input id="rename-field" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {tCommon('cancel')}
            </Button>
            <Button type="submit" className="bg-emerald-700 hover:bg-emerald-800" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {t('saveName')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function UpdateBoundaryDialog({
  field,
  open,
  onOpenChange,
}: {
  field: Field
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const [geometry, setGeometry] = useState('')
  const [reason, setReason] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [result, setResult] = useState<BoundaryVersionCreateResponse | null>(null)

  // Reset form state when the dialog closes.
  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setGeometry('')
      setReason('')
      setParseError(null)
      setResult(null)
    }
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: (payload: { geometry: GeoJSONGeometry; change_reason?: string }) =>
      createBoundaryVersion(field.id, payload),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['fields'] })
      queryClient.invalidateQueries({ queryKey: ['field-map', field.id] })
      queryClient.invalidateQueries({ queryKey: ['boundary-versions', field.id] })
      queryClient.invalidateQueries({ queryKey: ['data-passport', field.id] })
      if (response.geometry_warnings.length > 0) {
        setResult(response)
        toast.warning(t('boundaryStoredWarnings', { version: response.boundary_version }), {
          description: t('reviewWarningsBelow'),
        })
      } else {
        toast.success(t('boundaryUpdated', { version: response.boundary_version }), {
          description: t('boundaryUpdatedDesc', {
            area: formatArea(response.area_ha),
            unit: tCommon('ha'),
          }),
        })
        handleOpenChange(false)
      }
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      setParseError(title)
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setResult(null)
    const parsed = parseGeometryInput(geometry)
    if (!parsed.ok) {
      setParseError(parsed.error)
      return
    }
    setParseError(null)
    mutation.mutate({ geometry: parsed.geometry, change_reason: reason.trim() || undefined })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('updateBoundaryTitle', { version: field.boundary_version + 1 })}</DialogTitle>
          <DialogDescription>
            {t('updateBoundaryDesc')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" aria-label={t('updateBoundaryFormAria')}>
          <GeometryInput id="boundary-geometry" value={geometry} onChange={setGeometry} error={parseError} />
          <div className="space-y-1.5">
            <Label htmlFor="boundary-reason">{t('reasonLabel')}</Label>
            <Input
              id="boundary-reason"
              placeholder={t('reasonPlaceholder')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </div>

          {result ? (
            <div className="space-y-2">
              <Alert className="border-emerald-300 bg-emerald-50 [&>svg]:text-emerald-700">
                <MapPin className="h-4 w-4" />
                <AlertTitle className="text-emerald-900">
                  {t('boundaryStoredArea', {
                    version: result.boundary_version,
                    area: formatArea(result.area_ha),
                    unit: tCommon('ha'),
                  })}
                </AlertTitle>
                <AlertDescription className="text-emerald-900">
                  {t('mapWillRefresh')}
                </AlertDescription>
              </Alert>
              <GeometryWarningsAlert
                warnings={result.geometry_warnings}
                repaired={result.geometry_repaired}
                title={t('postgisWarnings')}
              />
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {result ? tCommon('close') : tCommon('cancel')}
            </Button>
            <Button type="submit" className="bg-emerald-700 hover:bg-emerald-800" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {t('storeVersion')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Field detail (map + versions + actions)
// ---------------------------------------------------------------------------

function FieldDetail({ field }: { field: Field }) {
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const mapQuery = useFieldMap(field.id)
  const versionsQuery = useBoundaryVersions(field.id)
  const [renameOpen, setRenameOpen] = useState(false)
  const [boundaryOpen, setBoundaryOpen] = useState(false)

  return (
    <Card className="border-stone-200 bg-white shadow-sm" aria-label={t('detailAria', { name: field.name })}>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              <MapPin className="h-4 w-4 text-emerald-700" aria-hidden />
              <span className="truncate">{field.name}</span>
              <Badge variant="outline" className="border-stone-300 font-normal text-stone-600">
                {t('boundaryShort', { version: field.boundary_version })}
              </Badge>
              <Badge variant="outline" className="border-stone-300 font-normal capitalize text-stone-600">
                {t('passportBadge', { status: field.data_passport_status })}
              </Badge>
            </CardTitle>
            <CardDescription className="mt-1">
              {t('createdUpdated', {
                created: formatDay(field.created_at),
                updated: formatDay(field.updated_at),
              })}
            </CardDescription>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" size="sm" className="border-stone-300" onClick={() => setRenameOpen(true)}>
              <Pencil className="h-3.5 w-3.5" aria-hidden /> {t('rename')}
            </Button>
            <Button
              size="sm"
              className="bg-emerald-700 hover:bg-emerald-800"
              onClick={() => setBoundaryOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden /> {t('updateBoundary')}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-5">
          <div className="space-y-2 lg:col-span-3">
            {mapQuery.isLoading ? (
              <Skeleton className="h-[300px] w-full rounded-lg md:h-[360px]" aria-label={t('loadingMapAria')} />
            ) : mapQuery.isError || !mapQuery.data ? (
              <div className="flex h-[300px] items-center justify-center rounded-lg border border-dashed border-stone-300 bg-stone-50 text-sm text-stone-500 md:h-[360px]">
                {t('mapUnavailable')}
              </div>
            ) : (
              <FieldMap key={`${mapQuery.data.field.id}-v${mapQuery.data.field.boundary_version}`} mapData={mapQuery.data} />
            )}
            {mapQuery.data ? (
              <div>
                <p className="text-sm font-semibold text-stone-900">
                  {formatArea(mapQuery.data.field.area_ha)} {tCommon('ha')}{' '}
                  <span className="font-normal text-stone-500">{t('geodesicWgs84')}</span>
                </p>
                <p className="text-xs text-stone-500">
                  {mapQuery.data.area_method} · {mapQuery.data.crs} · bbox [{mapQuery.data.bbox.map((n) => n.toFixed(4)).join(', ')}]
                </p>
              </div>
            ) : null}
          </div>

          <div className="space-y-3 lg:col-span-2">
            <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{t('boundaryVersions')}</p>
              {versionsQuery.isLoading ? (
                <div className="mt-2 space-y-2">
                  <Skeleton className="h-8 w-full" />
                  <Skeleton className="h-8 w-full" />
                </div>
              ) : versionsQuery.data && versionsQuery.data.items.length > 0 ? (
                <ul className="mt-2 max-h-44 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
                  {versionsQuery.data.items.map((version) => (
                    <li
                      key={version.id}
                      className="rounded-md border border-stone-200 bg-white px-2.5 py-2 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-stone-800">v{version.version_number}</span>
                        <span className="text-stone-600">{formatArea(version.area_ha)} {tCommon('ha')}</span>
                      </div>
                      <p className="mt-0.5 text-stone-500">
                        {formatDateTime(version.created_at)}
                        {version.change_reason ? ` · ${version.change_reason}` : ''}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-stone-500">{t('noVersionsYet')}</p>
              )}
            </div>
            <p className="text-xs text-stone-500">{t('technicalNote')}</p>
          </div>
        </div>
      </CardContent>

      <RenameFieldDialog field={field} open={renameOpen} onOpenChange={setRenameOpen} />
      <UpdateBoundaryDialog field={field} open={boundaryOpen} onOpenChange={setBoundaryOpen} />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

/**
 * P1 farm map: every field of the selected farm on one offline map, colored
 * per field with a legend; clicking a field selects it in the workspace.
 */
function FarmMapCard({
  farmName,
  fields,
  selectedFieldId,
  onSelectField,
}: {
  farmName: string | null
  fields: Field[]
  selectedFieldId: string | null
  onSelectField: (field: Field) => void
}) {
  const tMap = useTranslations('map')
  if (fields.length === 0) return null
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">
          {tMap('farmMapTitle')}
          {farmName ? ` — ${farmName}` : ''}
        </CardTitle>
        <CardDescription>
          {tMap('farmMapDesc')} {tMap('clickHint')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FarmMap fields={fields} selectedFieldId={selectedFieldId} onFieldSelect={onSelectField} />
      </CardContent>
    </Card>
  )
}

export function FarmsFields() {
  const t = useTranslations('farms')
  const tCommon = useTranslations('common')
  const tNav = useTranslations('nav')
  const farmsQuery = useFarms()
  const storedFarmId = useFieldShiftUi((s) => s.selectedFarmId)
  const setSelectedFarmId = useFieldShiftUi((s) => s.setSelectedFarmId)
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const createFarmOpen = useFieldShiftUi((s) => s.createFarmDialogOpen)
  const setCreateFarmOpen = useFieldShiftUi((s) => s.setCreateFarmDialogOpen)

  const [addFieldOpen, setAddFieldOpen] = useState(false)

  const farms = farmsQuery.data?.items ?? []
  // Default to the first farm without syncing state in an effect.
  const effectiveFarmId = storedFarmId ?? farms[0]?.id ?? null
  const selectedFarm = useMemo(
    () => farms.find((farm) => farm.id === effectiveFarmId) ?? null,
    [farms, effectiveFarmId],
  )
  const fieldsQuery = useFields(effectiveFarmId, Boolean(effectiveFarmId))
  const fields = fieldsQuery.data?.items ?? []
  // Flat records for the CSV/JSON export of the fields table.
  const exportFieldRows = () =>
    fields.map((field) => ({
      name: field.name,
      area_ha: field.area_ha,
      status: field.status,
      observation_count: field.observation_count,
      boundary_version: field.boundary_version,
      created_at: field.created_at,
    }))
  // The detail panel simply renders when the selected field is part of the
  // currently loaded farm — no effect-driven state clearing needed.
  const detailField = selectedField ? (fields.find((f) => f.id === selectedField.id) ?? null) : null

  return (
    <div className="space-y-6" aria-label={t('sectionAria')}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">{tNav('farms')}</h2>
          <p className="text-sm text-stone-500">{t('pickFarmDesc')}</p>
        </div>
        <Button className="bg-emerald-700 hover:bg-emerald-800" onClick={() => setCreateFarmOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden /> {t('newFarm')}
        </Button>
      </div>

      <FarmMapCard
        farmName={selectedFarm?.name ?? null}
        fields={fields}
        selectedFieldId={selectedField?.id ?? null}
        onSelectField={(field) =>
          setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
        }
      />

      {farmsQuery.isLoading ? (
        <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
          <div className="space-y-2">
            <Skeleton className="h-20 w-full rounded-lg" />
            <Skeleton className="h-20 w-full rounded-lg" />
          </div>
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      ) : farmsQuery.isError ? (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-red-900">{t('loadFarmsError')}</p>
            <Button variant="outline" size="sm" onClick={() => farmsQuery.refetch()}>
              <RefreshCw className="h-4 w-4" aria-hidden /> {tCommon('retry')}
            </Button>
          </CardContent>
        </Card>
      ) : farms.length === 0 ? (
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <Tractor className="h-8 w-8 text-stone-400" aria-hidden />
            <div>
              <p className="font-medium text-stone-900">{t('noFarmsYet')}</p>
              <p className="text-sm text-stone-500">{t('noFarmsDesc')}</p>
            </div>
            <Button className="bg-emerald-700 hover:bg-emerald-800" onClick={() => setCreateFarmOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> {t('openCreateFarm')}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[300px_1fr]">
          <section aria-label={t('farmListAria')} className="space-y-2">
            {farms.map((farm) => {
              const active = farm.id === effectiveFarmId
              return (
                <button
                  key={farm.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSelectedFarmId(farm.id)}
                  className={`w-full rounded-lg border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-emerald-700 ${
                    active
                      ? 'border-emerald-300 bg-emerald-50 ring-1 ring-emerald-300'
                      : 'border-stone-200 bg-white hover:border-stone-300'
                  }`}
                >
                  <p className="flex items-center gap-1.5 font-medium text-stone-900">
                    <Tractor className="h-4 w-4 text-emerald-700" aria-hidden />
                    {farm.name}
                  </p>
                  <p className="mt-0.5 text-xs text-stone-500">
                    {farm.country_code} · {farm.timezone} · {farm.currency_code}
                  </p>
                  <p className="mt-1 text-xs text-stone-600">
                    {t('fieldCount', { count: farm.field_count })} · {formatArea(farm.total_area_ha)} {tCommon('ha')}
                  </p>
                </button>
              )
            })}
          </section>

          <section aria-label={t('fieldsSectionAria')} className="min-w-0 space-y-4">
            {selectedFarm ? (
              <Card className="border-stone-200 bg-white shadow-sm">
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <CardTitle className="text-base">{t('farmFieldsTitle', { farm: selectedFarm.name })}</CardTitle>
                      <CardDescription>
                        {selectedFarm.admin_region ? `${selectedFarm.admin_region} · ` : ''}
                        {t('unitsLabel', { units: selectedFarm.unit_system })} · {selectedFarm.preferred_language.toUpperCase()}
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
                        onClick={() => setAddFieldOpen(true)}
                      >
                        <Plus className="h-4 w-4" aria-hidden /> {t('addField')}
                      </Button>
                      <ExportButton
                        baseFilename="fields"
                        getRows={exportFieldRows}
                        columns={[
                          { key: 'name', label: t('colName') },
                          { key: 'area_ha', label: t('colArea') },
                          { key: 'status', label: t('colStatus') },
                          { key: 'observation_count', label: t('colObservations') },
                          { key: 'boundary_version', label: t('colBoundary') },
                          { key: 'created_at', label: t('colCreatedAt') },
                        ]}
                        getJsonPayload={() => fields}
                      />
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {fieldsQuery.isLoading ? (
                    <div className="space-y-2">
                      <Skeleton className="h-10 w-full" />
                      <Skeleton className="h-10 w-full" />
                    </div>
                  ) : fieldsQuery.isError ? (
                    <p className="text-sm text-red-700">{t('loadFieldsError')}</p>
                  ) : fields.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-stone-300 p-6 text-center">
                      <p className="font-medium text-stone-800">{t('noFieldsYetTitle')}</p>
                      <p className="mt-1 text-sm text-stone-500">{t('noFieldsDesc')}</p>
                      <Button
                        variant="outline"
                        className="mt-3 border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
                        onClick={() => setAddFieldOpen(true)}
                      >
                        <Plus className="h-4 w-4" aria-hidden /> {t('addFirstField')}
                      </Button>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow className="hover:bg-transparent">
                            <TableHead>{t('colName')}</TableHead>
                            <TableHead className="text-right">{t('colArea')}</TableHead>
                            <TableHead className="text-right">{t('colBoundary')}</TableHead>
                            <TableHead className="text-right">{t('colObservations')}</TableHead>
                            <TableHead className="text-right">
                              <span className="sr-only">{tCommon('actions')}</span>
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {fields.map((field) => {
                            const active = selectedField?.id === field.id
                            return (
                              <TableRow
                                key={field.id}
                                className={`cursor-pointer ${active ? 'bg-emerald-50/70' : ''}`}
                                onClick={() => setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })}
                              >
                                <TableCell className="font-medium text-stone-900">
                                  <span className="inline-flex items-center gap-1.5">
                                    <MapPin
                                      className={`h-3.5 w-3.5 ${active ? 'text-emerald-700' : 'text-stone-400'}`}
                                      aria-hidden
                                    />
                                    {field.name}
                                  </span>
                                </TableCell>
                                <TableCell className="text-right tabular-nums">{formatArea(field.area_ha)} ha</TableCell>
                                <TableCell className="text-right">v{field.boundary_version}</TableCell>
                                <TableCell className="text-right tabular-nums">{field.observation_count}</TableCell>
                                <TableCell className="text-right">
                                  <Button
                                    size="sm"
                                    variant={active ? 'secondary' : 'ghost'}
                                    className="h-8 text-xs text-emerald-800"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
                                    }}
                                  >
                                    {t('open')}
                                  </Button>
                                </TableCell>
                              </TableRow>
                            )
                          })}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card className="border-dashed border-stone-300 bg-white">
                <CardContent className="p-8 text-center text-sm text-stone-500">
                  {t('selectFarmHint')}
                </CardContent>
              </Card>
            )}

            {detailField ? (
              <FieldDetail field={detailField} />
            ) : selectedField && !detailField ? (
              <Skeleton className="h-64 w-full rounded-lg" aria-label={t('loadingFieldDetailAria')} />
            ) : selectedFarm && fields.length > 0 ? (
              <p className="px-1 text-xs text-stone-500">{t('selectFieldHint')}</p>
            ) : null}
          </section>
        </div>
      )}

      <CreateFarmDialog open={createFarmOpen} onOpenChange={setCreateFarmOpen} />
      {selectedFarm ? (
        <AddFieldDialog
          farm={selectedFarm}
          open={addFieldOpen}
          onOpenChange={setAddFieldOpen}
          onFieldSelected={setSelectedField}
        />
      ) : null}
    </div>
  )
}

export default FarmsFields
