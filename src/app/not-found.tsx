import { getTranslations } from 'next-intl/server'
import { Compass } from 'lucide-react'

/**
 * Root-level 404 (P2). The SPA is a single route, so this mostly catches
 * stray deep links to unknown paths; it renders inside the root layout and
 * stays locale-aware (en/ar) via next-intl.
 */
export default async function NotFound() {
  const t = await getTranslations('system')

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background p-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Compass className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="space-y-1">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          404
        </p>
        <h1 className="text-xl font-semibold">{t('notFoundTitle')}</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          {t('notFoundDescription')}
        </p>
      </div>
      <a
        href="/"
        className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        {t('backHome')}
      </a>
    </main>
  )
}
