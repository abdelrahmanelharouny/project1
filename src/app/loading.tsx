import { useTranslations } from 'next-intl'
import { Loader2 } from 'lucide-react'

/**
 * Route-level loading UI (P2). Shown while the SPA shell is being prepared;
 * keeps the app to a single calm, centered indicator instead of a blank page.
 */
export default function Loading() {
  const t = useTranslations('common')

  return (
    <main
      aria-busy="true"
      aria-live="polite"
      className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background p-4"
    >
      <Loader2
        className="h-6 w-6 animate-spin text-muted-foreground"
        aria-hidden="true"
      />
      <p className="text-sm text-muted-foreground">{t('loading')}</p>
    </main>
  )
}
