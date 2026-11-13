'use client'

/**
 * P03 W2.2 — small shared state primitives for the Workspace & Settings
 * sub-pages (moved out of team-tab.tsx so the extracted Preferences page and
 * the organization page use ONE implementation).
 */

import { useTranslations } from 'next-intl'
import { AlertCircle, RefreshCw } from 'lucide-react'
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function SectionError({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations('p3')
  return (
    <Alert variant="destructive" className="border-red-200 bg-red-50 [&>svg]:text-red-600">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle className="text-red-900">{t('team.sectionError')}</AlertTitle>
      <AlertDescription className="mt-2">
        <Button size="sm" variant="outline" onClick={onRetry} className="gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t('team.retry')}
        </Button>
      </AlertDescription>
    </Alert>
  )
}

export function RowSkeletons({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  )
}
