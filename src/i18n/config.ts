/**
 * i18n configuration for CropTwist (next-intl, no i18n routing).
 *
 * The app is a single-route client SPA, so there is no locale prefix in the
 * URL: the active locale is stored in the NEXT_LOCALE cookie and resolved
 * server-side in src/i18n/request.ts. Arabic renders right-to-left via the
 * document `dir` attribute set in the root layout.
 */
export const locales = ['en', 'ar'] as const

export type Locale = (typeof locales)[number]

export const defaultLocale: Locale = 'en'

export const LOCALE_COOKIE = 'NEXT_LOCALE'

/**
 * Message namespaces, one file per namespace under messages/<locale>/.
 * Each namespace is owned by exactly one workstream so parallel edits never
 * collide. When adding a namespace, add a file for EVERY locale (missing
 * locale files gracefully fall back to English).
 */
export const messageNamespaces = [
  'common',
  'nav',
  'destinations',
  'auth',
  'overview',
  'map',
  'export',
  'charts',
  'farms',
  'observations',
  'features',
  'rotation',
  'water',
  'fieldstate',
  'scenarios',
  'soil',
  'management',
  'sensitivity',
  'robustplan',
  'decisions',
  'aiinsights',
  'digitaltwin',
  'passport',
  'satellite',
  'forecast',
  'soilmemory',
  'failurelab',
  'adaptiveevidence',
  'portfolio',
  'p3',
  'p3b',
  'system',
  'scenecatalog',
  'p07map',
  'p07analytics',
] as const

export type MessageNamespace = (typeof messageNamespaces)[number]

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (locales as readonly string[]).includes(value)
}

export function dirFor(locale: Locale): 'ltr' | 'rtl' {
  return locale === 'ar' ? 'rtl' : 'ltr'
}
