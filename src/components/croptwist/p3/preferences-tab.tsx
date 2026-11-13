'use client'

/**
 * P03 W2.2 — Preferences as a true Workspace & Settings sub-page
 * (`?tab=settings&sub=preferences`; blueprint §C7: "preferences gets a home").
 *
 * The PreferencesCard/PreferencesForm moved VERBATIM from team-tab.tsx:
 * same settings (locale, timezone, currency, units, week start, agricultural
 * calendar), same persistence (`PUT /api/v1/preferences` via the same query
 * cache key), same defaults, same save/success/error feedback. The interface
 * language itself keeps switching through the header LocaleSwitcher (the
 * form's languageHint copy says exactly that) — nothing invented, nothing
 * removed. Old links: `?tab=team` still lands on Organization & members; the
 * additive alias `?tab=preferences` resolves here.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { describeError } from '@/lib/api'
import { getPreferences, updatePreferences, type UserPreferences } from '@/lib/api-p3-account'
import { RowSkeletons, SectionError } from './settings-shared'

const COMMON_TIMEZONES = [
  'UTC',
  'Africa/Cairo',
  'Africa/Casablanca',
  'Africa/Lagos',
  'Africa/Nairobi',
  'Asia/Amman',
  'Asia/Baghdad',
  'Asia/Beirut',
  'Asia/Dubai',
  'Asia/Riyadh',
  'Asia/Tehran',
  'Asia/Kolkata',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Europe/Istanbul',
  'Europe/London',
  'Europe/Madrid',
  'Europe/Paris',
  'Europe/Rome',
  'Europe/Berlin',
  'Europe/Kyiv',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Mexico_City',
  'America/Sao_Paulo',
  'Australia/Sydney',
]

const COMMON_CURRENCIES = [
  'USD',
  'EUR',
  'GBP',
  'EGP',
  'SAR',
  'AED',
  'MAD',
  'DZD',
  'TND',
  'JOD',
  'KWD',
  'QAR',
  'IQD',
  'TRY',
  'INR',
  'CNY',
  'JPY',
  'AUD',
  'CAD',
  'BRL',
  'ZAR',
]

const CALENDAR_OPTIONS = ['gregorian', 'coptic', 'hijri']

/** Cache key for the preferences form: remounts when server values change
 * (event-driven reset instead of a state-sync effect). */
function preferencesFormKey(data: UserPreferences): string {
  return [
    data.locale,
    data.timezone,
    data.currency_code,
    data.unit_system,
    data.week_start,
    data.agricultural_calendar ?? '',
  ].join('|')
}

export default function PreferencesTab() {
  const t = useTranslations('p3')

  const prefsQuery = useQuery({
    queryKey: ['p3-preferences'],
    queryFn: getPreferences,
  })
  const data = prefsQuery.data

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-stone-900">{t('preferences.title')}</h2>
        <p className="text-sm text-stone-500">{t('preferences.desc')}</p>
      </div>
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-stone-900">{t('preferences.title')}</CardTitle>
          <CardDescription>{t('preferences.desc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {prefsQuery.isLoading ? (
            <RowSkeletons rows={4} />
          ) : prefsQuery.isError ? (
            <SectionError onRetry={() => prefsQuery.refetch()} />
          ) : data ? (
            <PreferencesForm key={preferencesFormKey(data)} data={data} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function PreferencesForm({ data }: { data: UserPreferences }) {
  const t = useTranslations('p3')
  const queryClient = useQueryClient()

  const [locale, setLocale] = useState(data.locale === 'ar' ? 'ar' : 'en')
  const [timezone, setTimezone] = useState(data.timezone || 'UTC')
  const [currency, setCurrency] = useState(data.currency_code || 'USD')
  const [unitSystem, setUnitSystem] = useState<'metric' | 'imperial'>(
    data.unit_system === 'imperial' ? 'imperial' : 'metric',
  )
  const [weekStart, setWeekStart] = useState<'monday' | 'sunday' | 'saturday'>(
    data.week_start === 'sunday' ? 'sunday' : data.week_start === 'saturday' ? 'saturday' : 'monday',
  )
  const [calendar, setCalendar] = useState(data.agricultural_calendar ?? '')

  const mutation = useMutation({
    mutationFn: () =>
      updatePreferences({
        locale,
        timezone,
        currency_code: currency,
        unit_system: unitSystem,
        week_start: weekStart,
        agricultural_calendar: calendar || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-preferences'] })
      toast.success(t('preferences.saved'))
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const timezoneOptions = useMemo(
    () => (COMMON_TIMEZONES.includes(timezone) ? COMMON_TIMEZONES : [timezone, ...COMMON_TIMEZONES]),
    [timezone],
  )
  const currencyOptions = useMemo(
    () => (COMMON_CURRENCIES.includes(currency) ? COMMON_CURRENCIES : [currency, ...COMMON_CURRENCIES]),
    [currency],
  )
  const calendarOptions = useMemo(
    () => (calendar && !CALENDAR_OPTIONS.includes(calendar) ? [calendar, ...CALENDAR_OPTIONS] : CALENDAR_OPTIONS),
    [calendar],
  )

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (!mutation.isPending) mutation.mutate()
      }}
      aria-label={t('preferences.title')}
    >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-locale">{t('preferences.localeLabel')}</Label>
            <Select value={locale} onValueChange={setLocale}>
              <SelectTrigger id="p3-pref-locale" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="en" className="text-xs">
                  {t('preferences.localeEn')}
                </SelectItem>
                <SelectItem value="ar" className="text-xs">
                  {t('preferences.localeAr')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-timezone">{t('preferences.timezoneLabel')}</Label>
            <Select value={timezone} onValueChange={setTimezone}>
              <SelectTrigger id="p3-pref-timezone" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-64">
                {timezoneOptions.map((tz) => (
                  <SelectItem key={tz} value={tz} className="text-xs" dir="ltr">
                    {tz}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-currency">{t('preferences.currencyLabel')}</Label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger id="p3-pref-currency" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-64">
                {currencyOptions.map((code) => (
                  <SelectItem key={code} value={code} className="text-xs">
                    {code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-units">{t('preferences.unitsLabel')}</Label>
            <Select
              value={unitSystem}
              onValueChange={(value) => setUnitSystem(value as 'metric' | 'imperial')}
            >
              <SelectTrigger id="p3-pref-units" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="metric" className="text-xs">
                  {t('preferences.unitsMetric')}
                </SelectItem>
                <SelectItem value="imperial" className="text-xs">
                  {t('preferences.unitsImperial')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-week">{t('preferences.weekStartLabel')}</Label>
            <Select
              value={weekStart}
              onValueChange={(value) => setWeekStart(value as 'monday' | 'sunday' | 'saturday')}
            >
              <SelectTrigger id="p3-pref-week" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="monday" className="text-xs">
                  {t('preferences.weekMonday')}
                </SelectItem>
                <SelectItem value="sunday" className="text-xs">
                  {t('preferences.weekSunday')}
                </SelectItem>
                <SelectItem value="saturday" className="text-xs">
                  {t('preferences.weekSaturday')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p3-pref-calendar">{t('preferences.calendarLabel')}</Label>
            <Select value={calendar} onValueChange={setCalendar}>
              <SelectTrigger id="p3-pref-calendar" className="border-stone-300 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="" className="text-xs">
                  {t('preferences.calendarNone')}
                </SelectItem>
                {calendarOptions.map((option) => (
                  <SelectItem key={option} value={option} className="text-xs">
                    {option === 'gregorian'
                      ? t('preferences.calendarGregorian')
                      : option === 'coptic'
                        ? t('preferences.calendarCoptic')
                        : option === 'hijri'
                          ? t('preferences.calendarHijri')
                          : option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-xs text-stone-500">{t('preferences.languageHint')}</p>
        <Button type="submit" className="gap-1.5" disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {mutation.isPending ? t('preferences.saving') : t('preferences.save')}
        </Button>
    </form>
  )
}
