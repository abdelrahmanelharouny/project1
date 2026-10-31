'use client'

import { FlaskConical, Map, Plus, RefreshCw, Ruler, Sprout, Tractor } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFields, useFarms, useHealthReady } from '@/hooks/use-fieldshift'
import { formatArea } from '@/lib/format'
import { useFieldShiftUi } from '@/lib/store'

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

const SETUP_STEPS = [
  'Create a farm — a country, timezone and currency context for your fields.',
  'Draw or paste a field boundary (GeoJSON) — areas are computed geodesically.',
  'Ingest synthetic observations (precipitation, temperature, ET₀…).',
  'Open the Data Passport to see what analyses are ready.',
]

export function Overview() {
  const farmsQuery = useFarms()
  const farms = farmsQuery.data?.items ?? []
  const firstFarm = farms[0] ?? null
  const fieldsQuery = useFields(firstFarm?.id ?? null, Boolean(firstFarm))
  const firstField = fieldsQuery.data?.items[0] ?? null
  const healthReady = useHealthReady()

  const setActiveTab = useFieldShiftUi((s) => s.setActiveTab)
  const openCreateFarm = useFieldShiftUi((s) => s.openCreateFarm)
  const goToPassportFor = useFieldShiftUi((s) => s.goToPassportFor)

  const fieldCount = farms.reduce((acc, farm) => acc + (farm.field_count ?? 0), 0)
  const totalAreaHa = farms.reduce((acc, farm) => acc + (farm.total_area_ha ?? 0), 0)
  const loading = farmsQuery.isLoading
  const empty = !loading && farms.length === 0

  return (
    <div className="space-y-6" aria-label="Overview">
      <div>
        <h2 className="text-lg font-semibold text-stone-900">Welcome to your workspace</h2>
        <p className="text-sm text-stone-500">
          A calm view of your farms, boundaries and data readiness.
        </p>
      </div>

      {farmsQuery.isError ? (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex flex-col items-start gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-red-900">
              Could not load your farms. {farmsQuery.error instanceof Error ? farmsQuery.error.message : ''}
            </p>
            <Button variant="outline" size="sm" onClick={() => farmsQuery.refetch()}>
              <RefreshCw className="h-4 w-4" aria-hidden /> Retry
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<Tractor className="h-5 w-5" aria-hidden />}
          label={farms.length === 1 ? 'Active farm' : 'Active farms'}
          value={String(farms.length)}
          hint="Number of farms in your organization"
          loading={loading}
        />
        <StatCard
          icon={<Map className="h-5 w-5" aria-hidden />}
          label="Fields with boundaries"
          value={String(fieldCount)}
          hint="Total number of fields across farms"
          loading={loading}
        />
        <StatCard
          icon={<Ruler className="h-5 w-5" aria-hidden />}
          label="Total area (hectares)"
          value={`${formatArea(totalAreaHa)} ha`}
          hint="Sum of farm total areas in hectares"
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
                  ? `PostgreSQL ${healthReady.data.server_version} + PostGIS ${healthReady.data.postgis_version}`
                  : healthReady.isError
                    ? 'Database status unknown'
                    : 'Checking database…'}
              </p>
            </div>
            <p className="mt-1 text-xs text-stone-500">
              Field areas use geodesic WGS84 math (PostGIS + PyProj).
            </p>
          </CardContent>
        </Card>
      </div>

      {empty ? (
        <Card className="border-emerald-200 bg-emerald-50/60 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base text-emerald-900">
              <Sprout className="h-5 w-5" aria-hidden /> Set up your first slice
            </CardTitle>
            <CardDescription className="text-emerald-800/80">
              Nothing here yet — four short steps take you from blank workspace to a data passport.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ol className="space-y-2">
              {SETUP_STEPS.map((step, index) => (
                <li key={step} className="flex items-start gap-3 text-sm text-emerald-950">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-[11px] font-semibold text-emerald-50">
                    {index + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
            <Button className="bg-emerald-700 hover:bg-emerald-800" onClick={openCreateFarm}>
              <Plus className="h-4 w-4" aria-hidden /> Create your first farm
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {!empty ? (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Quick actions</CardTitle>
              <CardDescription>Jump straight into the next useful step.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
                onClick={openCreateFarm}
              >
                <Plus className="h-4 w-4" aria-hidden /> Create a farm
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
                {firstField ? `Data Passport of “${firstField.name}”` : 'Data Passport — add a field first'}
              </Button>
              <Button variant="outline" className="border-stone-300" onClick={() => setActiveTab('observations')}>
                Ingest observations
              </Button>
            </CardContent>
          </Card>

          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">How to read this workspace</CardTitle>
              <CardDescription>Decision support, not an autonomous agronomist.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-stone-600">
              <p>
                <strong className="font-medium text-stone-800">Farms & Fields</strong> holds boundaries and versions —
                every boundary change is versioned, and areas are recomputed geodesically.
              </p>
              <p>
                <strong className="font-medium text-stone-800">Observations</strong> runs ingestion jobs against the
                synthetic fixtures and the real Open-Meteo reanalysis archive, or imports your CSV records and CHIRPS
                rasters — every source keeps its own honest evidence label.
              </p>
              <p>
                <strong className="font-medium text-stone-800">Data Passport</strong> is the honesty layer: what data
                exists, how fresh it is, and which analyses are actually available.
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  )
}

export default Overview
