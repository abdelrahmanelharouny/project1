import { cookies } from 'next/headers'
import { getRequestConfig } from 'next-intl/server'
import { defaultLocale, isLocale, LOCALE_COOKIE, messageNamespaces } from './config'

/**
 * English is always loaded first and acts as the fallback base: if a locale
 * file is missing (or a key was not translated yet), the English copy is
 * shown instead of a raw message key.
 */
async function loadNamespace(
  namespace: string,
  locale: string,
): Promise<Record<string, unknown> | null> {
  try {
    const mod = await import(`../../messages/${locale}/${namespace}.json`)
    return (mod.default ?? mod) as Record<string, unknown>
  } catch {
    return null
  }
}

export default getRequestConfig(async () => {
  const store = await cookies()
  const cookieLocale = store.get(LOCALE_COOKIE)?.value
  const locale = isLocale(cookieLocale) ? cookieLocale : defaultLocale

  const messages: Record<string, Record<string, unknown>> = {}
  for (const namespace of messageNamespaces) {
    const english = await loadNamespace(namespace, 'en')
    if (locale === 'en') {
      if (english) messages[namespace] = english
      continue
    }
    const localized = (await loadNamespace(namespace, locale)) ?? {}
    messages[namespace] = { ...(english ?? {}), ...localized }
  }

  return { locale, messages }
})
