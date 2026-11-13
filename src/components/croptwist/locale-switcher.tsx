'use client'

import { useLocale, useTranslations } from 'next-intl'
import { useRouter } from 'next/navigation'
import { Languages } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'
import { locales, LOCALE_COOKIE, type Locale } from '@/i18n/config'

const LOCALE_LABELS: Record<Locale, string> = {
  en: 'English',
  ar: 'العربية',
}

/**
 * Locale switcher (P1 i18n): writes the NEXT_LOCALE cookie and refreshes the
 * server components so the new message catalogs and the RTL direction apply.
 * Zustand UI state survives the refresh.
 */
export function LocaleSwitcher() {
  const locale = useLocale()
  const router = useRouter()
  const t = useTranslations('common')

  return (
    <Select
      value={locale}
      onValueChange={(next) => {
        if (next === locale) return
        document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`
        router.refresh()
      }}
    >
      <SelectTrigger
        aria-label={t('locale')}
        className="h-10 w-[124px] gap-1.5 border-stone-300 bg-white px-2.5 text-xs text-stone-700"
      >
        <span className="flex items-center gap-1.5 text-stone-500">
          <Languages className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span className="truncate">{LOCALE_LABELS[locale as Locale] ?? locale}</span>
      </SelectTrigger>
      <SelectContent>
        {locales.map((value) => (
          <SelectItem key={value} value={value}>
            {LOCALE_LABELS[value]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
