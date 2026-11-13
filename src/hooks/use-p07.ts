'use client'

/**
 * P07 react-query hooks — layer catalog, spatial analytics, anomalies,
 * comparison, farm overview. Polling is NOT used for these read models
 * (they change only when processing completes; the existing processing
 * ledger hook already polls that lifecycle).
 */

import { useQuery } from '@tanstack/react-query'

import {
  getFarmSatelliteOverview,
  getFieldAnomalies,
  getFieldComparison,
  getFieldLayerCatalog,
  getFieldSpatialAnalytics,
} from '@/lib/api-p07'
import type {
  P07AnomalyResponse,
  P07Comparison,
  P07FarmOverview,
  P07LayerCatalog,
  P07SpatialAnalytics,
} from '@/lib/types-p07'

export function useLayerCatalog(fieldId: string | null | undefined) {
  return useQuery<P07LayerCatalog>({
    queryKey: ['p07-layer-catalog', fieldId],
    queryFn: () => getFieldLayerCatalog(fieldId as string),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSpatialAnalytics(fieldId: string | null | undefined, index: string) {
  return useQuery<P07SpatialAnalytics>({
    queryKey: ['p07-spatial-analytics', fieldId, index],
    queryFn: () => getFieldSpatialAnalytics(fieldId as string, index),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSpatialAnomalies(fieldId: string | null | undefined, index = 'ndvi') {
  return useQuery<P07AnomalyResponse>({
    queryKey: ['p07-anomalies', fieldId, index],
    queryFn: () => getFieldAnomalies(fieldId as string, index),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSpatialComparison(
  fieldId: string | null | undefined,
  params: { index?: string; targetFieldId?: string; acquiredAtA?: string; acquiredAtB?: string },
) {
  return useQuery<P07Comparison>({
    queryKey: [
      'p07-comparison',
      fieldId,
      params.index,
      params.targetFieldId,
      params.acquiredAtA,
      params.acquiredAtB,
    ],
    queryFn: () => getFieldComparison(fieldId as string, params),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useFarmSatelliteOverview(farmId: string | null | undefined, index = 'ndvi') {
  return useQuery<P07FarmOverview>({
    queryKey: ['p07-farm-overview', farmId, index],
    queryFn: () => getFarmSatelliteOverview(farmId as string, index),
    enabled: !!farmId,
    staleTime: 30_000,
  })
}
