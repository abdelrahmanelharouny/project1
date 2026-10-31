'use client'

import { useMemo } from 'react'
import { useQuery, useQueries, type UseQueryResult } from '@tanstack/react-query'
import {
  compareFeatureRuns,
  fetchDataCoverage,
  getCatalog,
  getDataPassport,
  getFeatureCatalog,
  getFieldMap,
  getHealth,
  getHealthReady,
  getProvidersHealth,
  listBoundaryVersions,
  listFeatureRuns,
  listFeatureValues,
  listFields,
  listObservations,
  listFarms,
} from '@/lib/api'
import type {
  BoundaryVersionListResponse,
  CatalogResponse,
  DataCoverageResponse,
  DataPassport,
  Farm,
  FeatureCatalogResponse,
  FeatureRunComparison,
  FeatureRunListResponse,
  FeatureValueListResponse,
  Field,
  FieldListResponse,
  FieldMapResponse,
  HealthReadyResponse,
  HealthResponse,
  ObservationListResponse,
  ProvidersHealthResponse,
} from '@/lib/types'

/**
 * Server-state hooks. Every hook relies on the bearer token being present in
 * localStorage (attached by the fetch wrapper) — components only enable them
 * once the user is authenticated.
 */

export function useHealth(): UseQueryResult<HealthResponse> {
  return useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    staleTime: 60_000,
    retry: 1,
  })
}

export function useHealthReady(): UseQueryResult<HealthReadyResponse> {
  return useQuery({
    queryKey: ['health-ready'],
    queryFn: getHealthReady,
    staleTime: 60_000,
    retry: 1,
  })
}

export function useFarms(enabled = true): UseQueryResult<FarmListResponse> {
  return useQuery({
    queryKey: ['farms'],
    queryFn: listFarms,
    enabled,
    staleTime: 15_000,
  })
}

export function useFields(farmId: string | null, enabled = true): UseQueryResult<FieldListResponse> {
  return useQuery({
    queryKey: ['fields', farmId],
    queryFn: () => listFields(farmId as string),
    enabled: enabled && Boolean(farmId),
    staleTime: 15_000,
  })
}

export interface FarmWithFields {
  farm: Farm
  fields: Field[]
  fieldsQuery: UseQueryResult<FieldListResponse>
}

/**
 * Farms with their fields flattened via parallel queries — small workspaces,
 * so this stays cheap. Exposed so tabs that need a global field picker
 * (Observations / Data Passport) can render one list.
 */
export function useFarmsWithFields(enabled = true): {
  farms: FarmWithFields[]
  allFields: Field[]
  isLoading: boolean
  hasError: boolean
} {
  const farmsQuery = useFarms(enabled)
  const farms = useMemo(() => farmsQuery.data?.items ?? [], [farmsQuery.data])

  const fieldQueries = useQueries({
    queries: farms.map((farm) => ({
      queryKey: ['fields', farm.id],
      queryFn: () => listFields(farm.id),
      enabled,
      staleTime: 15_000,
    })),
  })

  const farmsWithFields = useMemo<FarmWithFields[]>(() => {
    return farms.map((farm, index) => ({
      farm,
      fields: fieldQueries[index]?.data?.items ?? [],
      fieldsQuery: fieldQueries[index],
    }))
  }, [farms, fieldQueries])

  const allFields = useMemo(() => farmsWithFields.flatMap((entry) => entry.fields), [farmsWithFields])
  const isLoading = farmsQuery.isLoading || fieldQueries.some((q) => q.isLoading)
  const hasError = farmsQuery.isError || fieldQueries.some((q) => q.isError)

  return { farms: farmsWithFields, allFields, isLoading, hasError }
}

export function useFieldMap(fieldId: string | null): UseQueryResult<FieldMapResponse> {
  return useQuery({
    queryKey: ['field-map', fieldId],
    queryFn: () => getFieldMap(fieldId as string),
    enabled: Boolean(fieldId),
    staleTime: 60_000,
  })
}

export function useBoundaryVersions(fieldId: string | null): UseQueryResult<BoundaryVersionListResponse> {
  return useQuery({
    queryKey: ['boundary-versions', fieldId],
    queryFn: () => listBoundaryVersions(fieldId as string),
    enabled: Boolean(fieldId),
    staleTime: 60_000,
  })
}

export function useCatalog(enabled = true): UseQueryResult<CatalogResponse> {
  return useQuery({
    queryKey: ['catalog'],
    queryFn: getCatalog,
    enabled,
    staleTime: 10 * 60_000,
  })
}

export function useObservations(
  fieldId: string | null,
  start: string,
  end: string,
  enabled = true,
): UseQueryResult<ObservationListResponse> {
  return useQuery({
    queryKey: ['observations', fieldId, start, end],
    queryFn: () => listObservations(fieldId as string, { start, end, limit: 5000 }),
    enabled: enabled && Boolean(fieldId) && Boolean(start) && Boolean(end),
    staleTime: 60_000,
  })
}

export function useDataPassport(fieldId: string | null): UseQueryResult<DataPassport> {
  return useQuery({
    queryKey: ['data-passport', fieldId],
    queryFn: () => getDataPassport(fieldId as string),
    enabled: Boolean(fieldId),
  })
}

export function useProvidersHealth(enabled = true): UseQueryResult<ProvidersHealthResponse> {
  return useQuery({
    queryKey: ['providers-health'],
    queryFn: getProvidersHealth,
    enabled,
    staleTime: 60_000,
  })
}

export function useDataCoverage(fieldId: string | null, enabled = true): UseQueryResult<DataCoverageResponse> {
  return useQuery({
    queryKey: ['data-coverage', fieldId],
    queryFn: () => fetchDataCoverage(fieldId as string),
    enabled: enabled && Boolean(fieldId),
    staleTime: 30_000,
  })
}

// --- feature engineering (Milestone 4) -------------------------------------

export function useFeatureCatalog(enabled = true): UseQueryResult<FeatureCatalogResponse> {
  return useQuery({
    queryKey: ['feature-catalog'],
    queryFn: getFeatureCatalog,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useFeatureRuns(fieldId: string | null, enabled = true): UseQueryResult<FeatureRunListResponse> {
  return useQuery({
    queryKey: ['feature-runs', fieldId],
    queryFn: () => listFeatureRuns(fieldId as string),
    enabled: enabled && Boolean(fieldId),
    staleTime: 5_000,
  })
}

export function useFeatureValues(
  runId: string | null,
  query: { aggregationLevel?: string; qualityStatus?: string },
  enabled = true,
): UseQueryResult<FeatureValueListResponse> {
  return useQuery({
    queryKey: ['feature-values', runId, query.aggregationLevel ?? '', query.qualityStatus ?? ''],
    queryFn: () =>
      listFeatureValues(runId as string, {
        aggregationLevel: query.aggregationLevel,
        qualityStatus: query.qualityStatus,
        limit: 500,
      }),
    enabled: enabled && Boolean(runId),
    staleTime: 30_000,
  })
}

export function useFeatureComparison(
  runId: string | null,
  againstRunId: string | null,
  enabled = true,
): UseQueryResult<FeatureRunComparison> {
  return useQuery({
    queryKey: ['feature-comparison', runId, againstRunId],
    queryFn: () => compareFeatureRuns(runId as string, againstRunId as string),
    enabled: enabled && Boolean(runId) && Boolean(againstRunId) && runId !== againstRunId,
    staleTime: 30_000,
  })
}
