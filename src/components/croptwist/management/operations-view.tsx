'use client'

/**
 * P03 W2.1 — "Operations" sub-page (cropintel/operations). OperationsView
 * moved verbatim from the former management.tsx container. Farm-scoped
 * resource queries stay enabled only with a real farm id.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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
import {
  createFarmResource,
  createScheduleRun,
  generateOperations,
  listFarmResources,
  listFieldOperations,
  listOperationTemplates,
  patchOperation,
} from '@/lib/api'
import type { ScheduleRun } from '@/lib/types'
import { ErrorNote, HonestEmpty, ManagementShell, StatusBadge, today } from './shared'

function OperationsView({ fieldId, farmId, expert }: { fieldId: string; farmId: string | null; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [crop, setCrop] = useState('')
  const [hoursPerDay, setHoursPerDay] = useState('8')
  const [resourceType, setResourceType] = useState('tractor')
  const [resourceName, setResourceName] = useState('')
  const [schedule, setSchedule] = useState<ScheduleRun | null>(null)
  const [error, setError] = useState<unknown>(null)

  const ops = useQuery({
    queryKey: ['operations', fieldId],
    queryFn: () => listFieldOperations(fieldId),
    enabled: Boolean(fieldId),
  })
  const resources = useQuery({
    queryKey: ['resources', farmId],
    queryFn: () => listFarmResources(farmId as string),
    enabled: Boolean(farmId),
  })
  const templates = useQuery({
    queryKey: ['operation-templates'],
    queryFn: listOperationTemplates,
  })

  const generate = useMutation({
    mutationFn: () => generateOperations(fieldId, { crop_label: crop, window_year: new Date().getFullYear() + 1 }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })
  const addResource = useMutation({
    mutationFn: () => createFarmResource(farmId as string, { resource_type: resourceType, name: resourceName || resourceType }),
    onSuccess: () => {
      setError(null)
      setResourceName('')
      qc.invalidateQueries({ queryKey: ['resources', farmId] })
    },
    onError: setError,
  })
  const scheduleRun = useMutation({
    mutationFn: () =>
      createScheduleRun(fieldId, { hours_per_workday: Number(hoursPerDay) || undefined }),
    onSuccess: (r) => {
      setSchedule(r)
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })
  const complete = useMutation({
    mutationFn: (opId: string) => patchOperation(opId, { status: 'completed', completion_date: today() }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="gen-crop" className="text-xs">{t('generateCropLabel')}</Label>
          <Input id="gen-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 w-40 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => generate.mutate()} disabled={generate.isPending || !crop}>
          {generate.isPending ? t('generating') : t('generateFromTemplates')}
        </Button>
        <div className="space-y-1">
          <Label htmlFor="hpd" className="text-xs">{t('hoursLabel')}</Label>
          <Input id="hpd" type="number" min="1" value={hoursPerDay} onChange={(e) => setHoursPerDay(e.target.value)} className="h-9 w-24 text-sm" />
        </div>
        <Button onClick={() => scheduleRun.mutate()} disabled={scheduleRun.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {scheduleRun.isPending ? t('scheduling') : t('scheduleOps')}
        </Button>
      </div>
      <ErrorNote error={error ?? ops.error} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="border-stone-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('opsTitle')}</CardTitle>
            <CardDescription>
              {t('opsDesc')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {ops.isLoading ? <Skeleton className="h-24 w-full" /> : null}
            {ops.data && ops.data.items.length === 0 ? (
              <HonestEmpty>{t('noOpsYet')}</HonestEmpty>
            ) : null}
            {ops.data?.items.map((op) => {
              const entry = schedule?.result.entries.find((e) => e.operation_id === op.id)
              return (
                <div key={op.id} className="rounded-lg border border-stone-100 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={op.status} />
                    <span className="font-medium text-stone-800">{op.title}</span>
                    <span className="text-stone-500">
                      {op.scheduled_start ?? op.earliest_start ?? t('noWindow')}
                      {op.scheduled_end ?? op.latest_finish ? ` → ${op.scheduled_end ?? op.latest_finish}` : ''}
                    </span>
                    {op.status !== 'completed' ? (
                      <Button size="sm" variant="ghost" className="ml-auto h-6 px-2 text-[11px]" onClick={() => complete.mutate(op.id)} disabled={complete.isPending}>
                        {t('markDone')}
                      </Button>
                    ) : null}
                  </div>
                  {entry && entry.status === 'unscheduled' && entry.reason ? (
                    <p className="mt-1 text-[11px] text-amber-800">{entry.reason}</p>
                  ) : null}
                  {op.status_reason ? <p className="mt-1 text-[11px] text-amber-800">{op.status_reason}</p> : null}
                </div>
              )
            })}
          </CardContent>
        </Card>

        <Card className="border-stone-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('resourcesTitle')}</CardTitle>
            <CardDescription>{t('resourcesDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="res-type" className="text-xs">{t('typeLabel')}</Label>
                <Select value={resourceType} onValueChange={setResourceType}>
                  <SelectTrigger id="res-type" className="h-9 w-36 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tractor">{t('resTractor')}</SelectItem>
                    <SelectItem value="implement">{t('resImplement')}</SelectItem>
                    <SelectItem value="seeder">{t('resSeeder')}</SelectItem>
                    <SelectItem value="sprayer">{t('resSprayer')}</SelectItem>
                    <SelectItem value="harvester">{t('resHarvester')}</SelectItem>
                    <SelectItem value="baler">{t('resBaler')}</SelectItem>
                    <SelectItem value="contractor">{t('resContractor')}</SelectItem>
                    <SelectItem value="labor_crew">{t('resLabourCrew')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="res-name" className="text-xs">{t('nameLabel')}</Label>
                <Input id="res-name" value={resourceName} onChange={(e) => setResourceName(e.target.value)} placeholder={t('namePlaceholder')} className="h-9 w-36 text-sm" />
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addResource.mutate()} disabled={addResource.isPending || !farmId}>
                {t('addResource')}
              </Button>
            </div>
            {resources.data?.items.length ? (
              <div className="flex flex-wrap gap-1">
                {resources.data.items.map((r) => (
                  <Badge key={r.id} variant="outline" className="px-1.5 py-0 text-[10px]">{r.name}</Badge>
                ))}
              </div>
            ) : (
              <HonestEmpty>{t('noResources')}</HonestEmpty>
            )}
            {schedule ? (
              <div className="border-t border-stone-100 pt-2 text-[11px] text-stone-600">
                <p className="font-medium text-stone-700">{t('lastSchedule')}</p>
                <p>
                  {t('scheduleSummary', {
                    status: schedule.result.solver.status,
                    scheduled: schedule.result.entries.filter((e) => e.status === 'scheduled').length,
                    unscheduled: schedule.result.entries.filter((e) => e.status === 'unscheduled').length,
                  })}
                </p>
                <p className="text-stone-500">
                  {t('weatherPending')}
                </p>
                {schedule.result.conflicts.map((c, i) => (
                  <p key={i} className="text-red-700">{c.message}</p>
                ))}
              </div>
            ) : null}
            {expert && templates.data ? (
              <p className="text-[11px] text-stone-400">
                {t('templatePack', {
                  total: templates.data.total,
                  status: templates.data.operation_templates[0]?.validation_status ?? '—',
                })}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export function OperationsPage() {
  return (
    <ManagementShell labelKey="operations">
      {({ fieldId, farmId, expert }) => <OperationsView fieldId={fieldId} farmId={farmId} expert={expert} />}
    </ManagementShell>
  )
}
