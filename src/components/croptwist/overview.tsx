'use client'

import { useCallback } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { FlaskConical, Map, Plus, RefreshCw, Ruler, Sprout, Tractor } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFields, useFarms, useHealthReady } from '@/hooks/use-croptwist'
import { ClimateOverview } from '@/components/croptwist/charts/climate-overview'
import { DataCoverage } from '@/components/croptwist/charts/data-coverage'
import { FarmMap } from '@/components/croptwist/farm-map'
import { formatArea } from '@/lib/format'
import { useCropTwistUi } from '@/lib/store'

function StatCard({
  icon,
  label,
  value,
  hint,
  loading,
}: {
  icon: React.ReactNode
  label: string
  value: string
  hint: string
  loading?: boolean
}) {
  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardContent className="flex items-center gap-4 p-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800">
          {icon}
        </span>
        <div className="min-w-0">
          {loading ? (
            <>
              <Skeleton className="mb-1 h-6 w-16" />
              <Skeleton className="h-3 w-24" />
            </>
          ) : (
            <>
              <p className="truncate text-xl font-semibold text-stone-900">{value}</p>
              <p className="truncate text-xs text-stone-500">{label}</p>
            </>
          )}
        </div>
        <span className="sr-only">{hint}</span>
      </CardContent>
    </Card>
  )
}

export function Overview() {
  const t = useTranslations('overview')
  const tMap = useTranslations('map')
  const locale = useLocale()
  const farmsQuery = useFarms()
  const farms = farmsQuery.data?.items ?? []
  const firstFarm = farms[0] ?? null
  const fieldsQuery = useFields(firstFarm?.id ?? null, Boolean(firstFarm))
  const firstField = fieldsQuery.data?.items[0] ?? null
  const healthReady = useHealthReady()

  const setActiveTab = useCropTwistUi((s) => s.setActiveTab)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const openCreateFarm = useCropTwistUi((s) => s.openCreateFarm)
  const goToPassportFor = useCropTwistUi((s) => s.goToPassportFor)

  const handleMapSelect = useCallback(
    (field: { id: string; name: string; farm_id: string }) => {
      setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
      setActiveTab('farms')
    },
    [setActiveTab, setSelectedField],
  )

  const fieldCount = farms.reduce((acc, farm) => acc + (farm.field_count ?? 0), 0)
  const totalAreaHa = farms.reduce((acc, farm) => acc + (farm.total_area_ha ?? 0), 0)
  const loading = farmsQuery.isLoading
  const empty = !loading && farms.length === 0

  return (
    <div className="space-y-6" aria-label="Overview">
      <div>
        <h2 className="text-lg font-semibold text-stone-900">{t('title')}</h2>
        <p className="text-sm text-stone-500">{t('subtitle')}</p>
      </div>

      {farmsQuery.isError ? (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-red-900">
              {t('loadError')} {farmsQuery.error instanceof Error ? farmsQuery.error.message : ''}
            </p>
            <Button variant="outline" size="sm" onClick={() => farmsQuery.refetch()}>
              <RefreshCw className="h-4 w-4" aria-hidden /> {t('quickActions')}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<Tractor className="h-5 w-5" aria-hidden />}
          label={farms.length === 1 ? t('statFarmsOne') : t('statFarms')}
          value={String(farms.length)}
          hint={t('statFarmsHint')}
          loading={loading}
        />
        <StatCard
          icon={<Map className="h-5 w-5" aria-hidden />}
          label={t('statFields')}
          value={String(fieldCount)}
          hint={t('statFieldsHint')}
          loading={loading}
        />
        <StatCard
          icon={<Ruler className="h-5 w-5" aria-hidden />}
          label={t('statArea')}
          value={`${formatArea(totalAreaHa, locale)} ${t('dbAreaUnit')}`}
          hint={t('statAreaHint')}
          loading={loading}
        />
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${
                  healthReady.data?.status === 'ok' ? 'bg-emerald-600' : healthReady.isError ? 'bg-red-500' : 'bg-amber-400 animate-pulse'
                }`}
                aria-hidden
              />
              <p className="text-sm font-medium text-stone-900">
                {healthReady.data
                  ? t('dbOk', { server: healthReady.data.server_version, postgis: healthReady.data.postgis_version })
                  : healthReady.isError
                    ? t('dbUnknown')
                    : t('dbChecking')}
              </p>
            </div>
            <p className="mt-1 text-xs text-stone-500">{t('dbGeodesic')}</p>
          </CardContent>
        </Card>
      </div>

      {!empty && firstField ? (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <ClimateOverview fieldId={firstField.id} />
          <DataCoverage fieldId={firstField.id} />
        </div>
      ) : null}

      {empty ? (
        <Card className="border-emerald-200 bg-emerald-50/60 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base text-emerald-900">
              <Sprout className="h-5 w-5" aria-hidden /> {t('setupTitle')}
            </CardTitle>
            <CardDescription className="text-emerald-800/80">{t('setupDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ol className="space-y-2">
              {(['step1', 'step2', 'step3', 'step4'] as const).map((key, index) => (
                <li key={key} className="flex items-start gap-3 text-sm text-emerald-950">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-[11px] font-semibold text-emerald-50">
                    {index + 1}
                  </span>
                  {t(key)}
                </li>
              ))}
            </ol>
            <Button className="bg-emerald-700 hover:bg-emerald-800" onClick={openCreateFarm}>
              <Plus className="h-4 w-4" aria-hidden /> {t('createFirstFarm')}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {!empty && firstFarm ? (
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{tMap('farmMapTitle')} — {firstFarm.name}</CardTitle>
            <CardDescription>
              {tMap('farmMapDesc')} {tMap('clickHint')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FarmMap fields={fieldsQuery.data?.items ?? []} onFieldSelect={handleMapSelect} />
          </CardContent>
        </Card>
      ) : null}

      {!empty ? (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t('quickActions')}</CardTitle>
              <CardDescription>{t('quickActionsDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
                onClick={openCreateFarm}
              >
                <Plus className="h-4 w-4" aria-hidden /> {t('createFarm')}
              </Button>
              <Button
                variant="outline"
                className="max-w-full whitespace-normal border-stone-300 text-left"
                disabled={!firstField}
                onClick={() => {
                  if (firstField) {
                    goToPassportFor({ id: firstField.id, name: firstField.name, farmId: firstField.farm_id })
                  }
                }}
              >
                <FlaskConical className="h-4 w-4" aria-hidden />
                {firstField ? t('passportOf', { name: firstField.name }) : t('passportNeedField')}
              </Button>
              <Button variant="outline" className="border-stone-300" onClick={() => setActiveTab('observations')}>
                {t('ingestObservations')}
              </Button>
            </CardContent>
          </Card>

          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t('howTitle')}</CardTitle>
              <CardDescription>{t('howDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-stone-600">
              <p>
                <strong className="font-medium text-stone-800">{t('howFarmsName')}</strong> {t('howFarms')}
              </p>
              <p>
                <strong className="font-medium text-stone-800">{t('howObservationsName')}</strong> {t('howObservations')}
              </p>
              <p>
                <strong className="font-medium text-stone-800">{t('howPassportName')}</strong> {t('howPassport')}
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  )
}

export default Overview
