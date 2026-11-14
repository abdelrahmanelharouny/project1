'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Info, Loader2, Sprout } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { FieldPicker } from '@/components/croptwist/field-picker'
import { ExportButton } from '@/components/croptwist/export-button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCropHistory } from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { cropHistoryForPeriod, cropHistoryYears } from '@/lib/crop-history-filter'

function area(value: number | null): string {
  return value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

export function RotationOverview() {
  const t = useTranslations('rotation')
  const tCommon = useTranslations('common')
  const selectedField = useCropTwistUi((state) => state.selectedField)
  const setSelectedField = useCropTwistUi((state) => state.setSelectedField)
  const navigateTo = useCropTwistUi((state) => state.navigateTo)
  const [period, setPeriod] = useState('all')
  const history = useCropHistory(selectedField?.id ?? null)
  const allItems = history.data?.items ?? []
  const years = cropHistoryYears(allItems)
  const rows = cropHistoryForPeriod(allItems, period)

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-400">{t('overviewEyebrow')}</p>
          <h2 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">{t('overviewTitle')}</h2>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">{t('overviewDesc')}</p>
        </div>
        <Button
          onClick={() => navigateTo('cropintel', 'rotation-planner')}
          disabled={!selectedField}
          className="w-full shrink-0 sm:w-auto"
        >
          <Sprout className="h-4 w-4" aria-hidden />
          {t('editRotation')}
        </Button>
      </div>

      {!selectedField ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('selectedFieldLabel')}</CardTitle>
            <CardDescription>{t('pickFieldHint')}</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldPicker
              value={null}
              onValueChange={setSelectedField}
              emptyHint={
                <Button variant="outline" size="sm" onClick={() => navigateTo('farms')}>
                  {tCommon('createFarmField')}
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-emerald-800/70 text-emerald-300">
              {t('selectedFieldLabel')}: {selectedField.name}
            </Badge>
            <Badge variant="outline" className="border-border text-muted-foreground">
              {t('historyBadge')}
            </Badge>
          </div>

          <Card>
            <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-1">
                <CardTitle className="text-base">{t('historyTitle')}</CardTitle>
                <CardDescription>{t('historyDesc')}</CardDescription>
              </div>
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
                <Select value={period} onValueChange={setPeriod}>
                  <SelectTrigger className="w-full sm:w-[190px]" aria-label={t('periodFilterLabel')}>
                    <SelectValue placeholder={t('periodFilterLabel')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t('allPeriods')}</SelectItem>
                    {years.map((year) => (
                      <SelectItem key={year} value={year}>{t('yearOption', { year })}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <ExportButton
                  baseFilename="crop-history"
                  getRows={() => rows.map((item) => ({
                    crop_label: item.crop_label,
                    season_label: item.season_label,
                    sowing_date: item.sowing_date,
                    harvest_date: item.harvest_date,
                    area_ha: item.area_ha,
                    source: item.source,
                    evidence_class: item.evidence_class,
                  }))}
                  columns={[
                    { key: 'crop_label', label: t('labelCrop') },
                    { key: 'season_label', label: t('labelSeason') },
                    { key: 'sowing_date', label: t('labelSowing') },
                    { key: 'harvest_date', label: t('labelHarvest') },
                    { key: 'area_ha', label: t('colArea') },
                    { key: 'source', label: t('colSource') },
                    { key: 'evidence_class', label: t('evidenceClass') },
                  ]}
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <Alert className="border-emerald-900/40 bg-emerald-950/20">
                <Info className="h-4 w-4 text-emerald-300" aria-hidden />
                <AlertDescription className="text-xs leading-relaxed text-muted-foreground">
                  {t('historyOnlyNotice')}
                </AlertDescription>
              </Alert>

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{t('historyCount', { count: rows.length })}</span>
                {history.isFetching && !history.isLoading ? (
                  <span className="flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />{t('historyLoading')}</span>
                ) : null}
              </div>

              {history.isLoading ? (
                <div className="flex items-center gap-2 rounded-lg border border-border bg-card/60 px-4 py-8 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  {t('historyLoading')}
                </div>
              ) : history.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>{t('historyErrorTitle')}</AlertTitle>
                  <AlertDescription className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <span>{t('historyError')}</span>
                    <Button variant="outline" size="sm" onClick={() => void history.refetch()}>
                      {t('retryHistory')}
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : rows.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border bg-card/50 px-4 py-8 text-center">
                  <Sprout className="mx-auto mb-2 h-5 w-5 text-emerald-400" aria-hidden />
                  <p className="text-sm text-muted-foreground">
                    {allItems.length === 0 ? t('historyEmpty') : t('historyPeriodEmpty')}
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <Table className="min-w-[680px]">
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('labelCrop')}</TableHead>
                        <TableHead>{t('labelSeason')}</TableHead>
                        <TableHead>{t('labelSowing')}</TableHead>
                        <TableHead>{t('labelHarvest')}</TableHead>
                        <TableHead>{t('colArea')}</TableHead>
                        <TableHead>{t('colSource')}</TableHead>
                        <TableHead>{t('evidenceClass')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell className="font-medium text-foreground">
                            {item.crop_code ? `${item.crop_code} · ` : ''}{item.crop_label}
                          </TableCell>
                          <TableCell>{item.season_label ?? '—'}</TableCell>
                          <TableCell>{item.sowing_date ?? '—'}</TableCell>
                          <TableCell>{item.harvest_date ?? '—'}</TableCell>
                          <TableCell>{area(item.area_ha)}</TableCell>
                          <TableCell className="max-w-[180px] truncate" title={item.source}>{item.source}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="font-normal">{item.evidence_class}</Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
