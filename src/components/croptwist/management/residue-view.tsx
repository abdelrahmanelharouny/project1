'use client'

/**
 * P03 W2.1 — "Residue" sub-page (cropintel/residue). ResidueView moved
 * verbatim from the former management.tsx container.
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
import { createResidueFlow, createResidueRecord, getResidueLedger } from '@/lib/api'
import type { ResidueLedgerResponse } from '@/lib/types'
import { ErrorNote, HonestEmpty, ManagementShell, StatusBadge } from './shared'

function ResidueView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const ledger = useQuery({
    queryKey: ['residue-ledger', fieldId],
    queryFn: () => getResidueLedger(fieldId),
    enabled: Boolean(fieldId),
  })
  const [crop, setCrop] = useState('')
  const [produced, setProduced] = useState('')
  const [flowType, setFlowType] = useState('retained_surface')
  const [flowKg, setFlowKg] = useState('')
  const [targetRecord, setTargetRecord] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const addRecord = useMutation({
    mutationFn: () =>
      createResidueRecord(fieldId, {
        crop_label: crop,
        production_status: produced ? 'farmer_reported' : 'missing',
        produced_dm_kg: produced ? Number(produced) : undefined,
      }),
    onSuccess: (rec) => {
      setError(null)
      setCrop('')
      setProduced('')
      setTargetRecord(rec.id)
      qc.invalidateQueries({ queryKey: ['residue-ledger', fieldId] })
    },
    onError: setError,
  })

  const addFlow = useMutation({
    mutationFn: () =>
      createResidueFlow(targetRecord as string, {
        flow_type: flowType,
        dm_kg: flowKg ? Number(flowKg) : undefined,
        dm_kg_status: flowKg ? 'farmer_reported' : 'unknown',
      }),
    onSuccess: () => {
      setError(null)
      setFlowKg('')
      qc.invalidateQueries({ queryKey: ['residue-ledger', fieldId] })
    },
    onError: setError,
  })

  const data: ResidueLedgerResponse | undefined = ledger.data

  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {t('residueIntro')}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="res-crop" className="text-xs">{t('cropLabel')}</Label>
          <Input id="res-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 w-40 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="res-prod" className="text-xs">{t('producedLabel')}</Label>
          <Input id="res-prod" type="number" min="0" value={produced} onChange={(e) => setProduced(e.target.value)} className="h-9 w-44 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => addRecord.mutate()} disabled={addRecord.isPending || !crop}>
          {addRecord.isPending ? t('saving') : t('addRecord')}
        </Button>
      </div>
      <ErrorNote error={error} />

      {ledger.isLoading ? <Skeleton className="h-32 w-full" /> : null}
      <ErrorNote error={ledger.error} />

      {data ? (
        <div className="space-y-3">
          {data.warnings.map((w, i) => (
            <p key={i} className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{w}</p>
          ))}
          {data.records.length === 0 ? (
            <HonestEmpty>{t('noRecords')}</HonestEmpty>
          ) : (
            data.records.map((rec) => (
              <Card key={rec.record.id} className="border-stone-200">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">{rec.record.crop_label}</CardTitle>
                    <StatusBadge status={rec.balance.status} />
                  </div>
                  <CardDescription>
                    {t('recordDesc', {
                      amount: rec.record.produced_dm_kg !== null ? `${rec.record.produced_dm_kg} kg DM` : t('unknownAmount'),
                      status: rec.record.production_status.replace(/_/g, ' '),
                    })}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-stone-600">
                  {rec.flows.map((f) => (
                    <div key={f.id} className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">{f.flow_type.replace(/_/g, ' ')}</Badge>
                      <span>{f.dm_kg !== null ? `${f.dm_kg} kg` : t('massUnknown')}</span>
                      <span className="text-stone-400">{f.dm_kg_status}</span>
                    </div>
                  ))}
                  <p>
                    {t('balanceLine', {
                      flows: rec.balance.total_flow_dm_kg,
                      unaccounted: rec.balance.unaccounted_dm_kg !== null ? `${rec.balance.unaccounted_dm_kg} kg` : t('notComputable'),
                    })}
                  </p>
                  {expert && rec.derived.total_nitrogen_kg !== undefined ? (
                    <p className="text-[11px]">
                      {t('nitrogenNote', { value: String(rec.derived.total_nitrogen_kg) })}
                    </p>
                  ) : null}
                  {targetRecord === rec.record.id ? (
                    <div className="flex flex-wrap items-end gap-2 border-t border-stone-100 pt-2">
                      <div className="space-y-1">
                        <Label htmlFor={`flow-type-${rec.record.id}`} className="text-xs">{t('flowLabel')}</Label>
                        <Select value={flowType} onValueChange={setFlowType}>
                          <SelectTrigger id={`flow-type-${rec.record.id}`} className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="retained_surface">{t('flowRetained')}</SelectItem>
                            <SelectItem value="incorporated">{t('flowIncorporated')}</SelectItem>
                            <SelectItem value="removed_baled">{t('flowRemoved')}</SelectItem>
                            <SelectItem value="grazed">{t('flowGrazed')}</SelectItem>
                            <SelectItem value="burned">{t('flowBurned')}</SelectItem>
                            <SelectItem value="other_loss">{t('flowOther')}</SelectItem>
                            <SelectItem value="unknown">{t('flowUnknownFate')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`flow-kg-${rec.record.id}`} className="text-xs">{t('dmKgLabel')}</Label>
                        <Input id={`flow-kg-${rec.record.id}`} type="number" min="0" value={flowKg} onChange={(e) => setFlowKg(e.target.value)} className="h-9 w-36 text-sm" />
                      </div>
                      <Button size="sm" variant="outline" className="h-9" onClick={() => addFlow.mutate()} disabled={addFlow.isPending}>
                        {t('addFlow')}
                      </Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setTargetRecord(rec.record.id)}>
                      {t('addFlowToRecord')}
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

export function ResiduePage() {
  return (
    <ManagementShell labelKey="residue">
      {({ fieldId, expert }) => <ResidueView fieldId={fieldId} expert={expert} />}
    </ManagementShell>
  )
}
