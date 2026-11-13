'use client'

/**
 * P07 — Analytics hub (the `reports:analytics` destination content).
 *
 * Tabs: Overview (the existing P3 InsightsTab, unchanged) · Field performance
 * (satellite + spatial analytics) · Environmental (real observation series)
 * · Anomalies (gated signals, never diagnoses).
 *
 * URL contract: this hub owns ONLY the `analytics` param — read once from
 * useSearchParams, written with router.replace while PRESERVING every other
 * param (tab/sub/farm/field/fieldName belong to the workspace contract).
 * Radix Tabs give keyboard navigation (arrows + Home/End) for free; the tab
 * strip wraps on mobile so no section is ever cut off.
 */

import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import InsightsTab from '@/components/croptwist/p3/insights-tab'
import AnomaliesTab from '@/components/croptwist/p7/anomalies-tab'
import EnvironmentalTab from '@/components/croptwist/p7/environmental-tab'
import SatelliteAnalyticsTab from '@/components/croptwist/p7/satellite-analytics-tab'

const ANALYTICS_SECTIONS = ['overview', 'field', 'environmental', 'anomalies'] as const

type AnalyticsSection = (typeof ANALYTICS_SECTIONS)[number]

function isAnalyticsSection(value: string | null | undefined): value is AnalyticsSection {
  return !!value && (ANALYTICS_SECTIONS as readonly string[]).includes(value)
}

export default function AnalyticsHub() {
  const t = useTranslations('p07analytics')
  const router = useRouter()
  const searchParams = useSearchParams()

  const raw = searchParams.get('analytics')
  const section: AnalyticsSection = isAnalyticsSection(raw) ? raw : 'overview'

  const setSectionParam = (next: AnalyticsSection) => {
    const params = new URLSearchParams(searchParams.toString())
    if (next === 'overview') {
      params.delete('analytics') // overview stays the canonical default
    } else {
      params.set('analytics', next)
    }
    const qs = params.toString()
    router.replace(qs ? `/?${qs}` : '/', { scroll: false })
  }

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('hub.title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('hub.subtitle')}</p>
      </header>

      <Tabs value={section} onValueChange={(v) => setSectionParam(v as AnalyticsSection)}>
        <TabsList
          aria-label={t('hub.tabsLabel')}
          className="h-auto flex-wrap justify-start gap-1 bg-stone-100 p-1"
        >
          {ANALYTICS_SECTIONS.map((key) => (
            <TabsTrigger
              key={key}
              value={key}
              className="data-[state=active]:bg-white data-[state=active]:text-emerald-900"
            >
              {t(`hub.tab${key.charAt(0).toUpperCase()}${key.slice(1)}`)}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="min-w-0">
          <InsightsTab />
        </TabsContent>
        <TabsContent value="field" className="min-w-0">
          <SatelliteAnalyticsTab />
        </TabsContent>
        <TabsContent value="environmental" className="min-w-0">
          <EnvironmentalTab />
        </TabsContent>
        <TabsContent value="anomalies" className="min-w-0">
          <AnomaliesTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
