'use client'

/**
 * P02 W1 — Map & Satellite destination canvas (blueprint C3).
 *
 * Composition ONLY — both components are mounted verbatim with their existing
 * props/contracts:
 *   - `FarmMap` becomes the destination canvas (fields of the context farm)
 *   - `SatelliteIntelligence` (the former full-width Satellite tab) docks as
 *     the side panel beside the map it will decorate in later phases
 *
 * Honesty contract preserved: this introduces NO imagery, NO raster layers and
 * NO simulated data — it rearranges the existing offline map + vegetation
 * index/scenes surfaces. FarmMap's worker setup stays a module-level singleton
 * (farm-map.tsx) and only one instance is mounted at a time (same as today).
 * Field selection writes the same store slice; clicking a field on the canvas
 * selects it for the satellite panel without navigating away.
 *
 * The Overview map instance is intentionally NOT removed here (that dedupe is
 * Wave 3.2 of the P01 plan) — capabilities are only added, never removed.
 */

import { useCallback } from 'react'
import { useTranslations } from 'next-intl'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { FarmMap } from '@/components/croptwist/farm-map'
import { SatelliteIntelligence } from '@/components/croptwist/satellite'
import { useFields } from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'

export function MapSatellitePane() {
  const tMap = useTranslations('map')
  const tNav = useTranslations('nav')
  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const fieldsQuery = useFields(selectedFarmId, Boolean(selectedFarmId))

  const handleFieldSelect = useCallback(
    (field: { id: string; name: string; farm_id: string }) => {
      setSelectedField({ id: field.id, name: field.name, farmId: field.farm_id })
    },
    [setSelectedField],
  )

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px] [&>*]:min-w-0">
      <Card className="border-stone-200 bg-white shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{tMap('farmMapTitle')}</CardTitle>
          <CardDescription>
            {tMap('farmMapDesc')} {tMap('clickHint')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FarmMap
            fields={fieldsQuery.data?.items ?? []}
            selectedFieldId={selectedField?.id ?? null}
            onFieldSelect={handleFieldSelect}
          />
        </CardContent>
      </Card>
      <div className="min-w-0" aria-label={tNav('satellite')}>
        <SatelliteIntelligence />
      </div>
    </div>
  )
}
