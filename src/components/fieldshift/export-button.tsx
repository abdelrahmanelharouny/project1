'use client'

import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Download, FileJson, FileSpreadsheet, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { exportCsv, exportFilename, exportJson, type ExportColumn } from '@/lib/export'

interface ExportButtonProps<T extends Record<string, unknown>> {
  /** Base filename without extension (timestamped by the component). */
  baseFilename: string
  /** Row provider — called lazily at click time so the freshest data exports. */
  getRows: () => T[]
  /** Optional column projection (defaults to the row's own keys). */
  columns?: ExportColumn<T>[]
  /** Extra JSON-only payload (e.g. the full response with metadata). */
  getJsonPayload?: () => unknown
  disabled?: boolean
}

/**
 * P1 export pipeline UI: a dropdown offering CSV / JSON download of any
 * table or series. Used across Observations, Water, Sensitivity, Farms &
 * Fields and the crop history table.
 */
export function ExportButton<T extends Record<string, unknown>>({
  baseFilename,
  getRows,
  columns,
  getJsonPayload,
  disabled,
}: ExportButtonProps<T>) {
  const t = useTranslations('export')

  const run = (kind: 'csv' | 'json') => {
    try {
      if (kind === 'csv') {
        const rows = getRows()
        if (rows.length === 0) {
          toast.info(t('noRows'))
          return
        }
        exportCsv(exportFilename(baseFilename, 'csv'), rows, columns)
      } else {
        exportJson(exportFilename(baseFilename, 'json'), getJsonPayload ? getJsonPayload() : getRows())
      }
      toast.success(t('success', { name: baseFilename }))
    } catch (error) {
      toast.error(t('failed'), {
        description: error instanceof Error ? error.message : undefined,
      })
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="border-stone-300" disabled={disabled}>
          <Download className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">{t('label')}</span>
          <span className="sr-only">{t('label')}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuLabel className="flex items-center gap-2 text-xs text-stone-500">
          <Loader2 className="hidden" aria-hidden />
          <Download className="h-3.5 w-3.5" aria-hidden />
          {t('label')}
        </DropdownMenuLabel>
        <DropdownMenuItem onClick={() => run('csv')} className="gap-2">
          <FileSpreadsheet className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('csv')}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => run('json')} className="gap-2">
          <FileJson className="h-4 w-4 text-stone-600" aria-hidden />
          {t('json')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
