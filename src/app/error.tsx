'use client'

import { useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { AlertTriangle, RotateCcw, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

/**
 * Route-level error boundary (P2). Catches render/runtime failures inside the
 * root layout and offers retry / reload. The digest is surfaced so a user can
 * quote the exact server-side correlation reference.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const t = useTranslations('system')
  const tCommon = useTranslations('common')

  useEffect(() => {
    // Client-side observability hook: console today, remote sink later.
    console.error('[fieldshift/web] unhandled error', {
      digest: error.digest,
      message: error.message,
    })
  }, [error])

  return (
    <main
      role="alert"
      className="flex min-h-screen items-center justify-center bg-background p-4"
    >
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden="true" />
          </div>
          <CardTitle>{t('errorTitle')}</CardTitle>
          <CardDescription>{t('errorDescription')}</CardDescription>
        </CardHeader>
        {error.digest ? (
          <CardContent>
            <p className="text-xs text-muted-foreground">
              {t('errorDigest')}:{' '}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {error.digest}
              </code>
            </p>
          </CardContent>
        ) : null}
        <CardFooter className="flex gap-2">
          <Button onClick={reset} className="min-h-11">
            <RotateCcw className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
            {tCommon('retry')}
          </Button>
          <Button
            variant="outline"
            className="min-h-11"
            onClick={() => window.location.reload()}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t('reload')}
          </Button>
        </CardFooter>
      </Card>
    </main>
  )
}
