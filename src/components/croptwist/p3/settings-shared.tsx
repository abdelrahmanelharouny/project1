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
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, describeError } from '@/lib/api'
import { useCropTwistUi } from '@/lib/store'
import { cn } from '@/lib/utils'

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

/**
 * W3 dedupe — ONE implementation of the inline query-error box that the
 * commercial sub-pages (reports / insights, previously billing & developer
 * copies) each carried locally: ApiError 403 gets the dedicated "not allowed"
 * copy, everything else surfaces describeError(err).title.
 */
export function InlineError({ error, className }: { error: unknown; className?: string }) {
  const t = useTranslations('p3b')
  const forbidden = error instanceof ApiError && error.status === 403
  return (
    <div className={cn('rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900', className)}>
      <p className="font-semibold">{forbidden ? t('errors.forbiddenTitle') : t('common.loadError')}</p>
      <p className="mt-1 text-xs leading-relaxed">
        {forbidden ? t('errors.forbiddenBody') : describeError(error).title}
      </p>
    </div>
  )
}

/**
 * W3 dedupe — ONE "no organization yet" empty state for the commercial
 * sub-pages; the CTA navigates to the organization settings page.
 */
export function NoOrgEmptyState({ onGoToTeam, className }: { onGoToTeam?: () => void; className?: string }) {
  const t = useTranslations('p3b')
  return (
    <Card className={className}>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <p className="text-base font-semibold text-stone-900">{t('common.noOrgTitle')}</p>
        <p className="max-w-md text-sm text-stone-500">{t('common.noOrgBody')}</p>
        <Button
          className="mt-2 bg-emerald-700 text-white hover:bg-emerald-800"
          onClick={onGoToTeam ?? (() => useCropTwistUi.getState().setActiveTab('team'))}
        >
          {t('common.noOrgCta')}
        </Button>
      </CardContent>
    </Card>
  )
}
