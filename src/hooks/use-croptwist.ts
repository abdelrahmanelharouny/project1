'use client'

import { useMemo } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import {
  compareFeatureRuns,
  createFieldState,
  fetchDataCoverage,
  getCatalog,
  getDataPassport,
  getFeatureCatalog,
  getFieldMap,
  getFieldState,
  getHealth,
  getHealthReady,
  getProvidersHealth,
  getWaterMethods,
  getWaterPlan,
  getWaterReadiness,
  listBoundaryVersions,
  listFeatureRuns,
  listFeatureValues,
  listFieldStates,
  listFields,
  listObservations,
  listFarms,
  listWaterPlans,
  verifyFieldState,
  getScenarioCapabilities,
  getScenarioTypes,
  listScenarios,
} from '@/lib/api'
import type {
  BoundaryVersionListResponse,
  CatalogResponse,
  CropHistoryListResponse,
  DataCoverageResponse,
  DataPassport,
  Farm,
  FeatureCatalogResponse,
  FeatureRunComparison,
  FeatureRunListResponse,
  FieldState,
  FieldStateListResponse,
  FieldStateVerifyResponse,
  FeatureValueListResponse,
  Field,
  FieldListResponse,
  FarmListResponse,
  FieldMapResponse,
  HealthReadyResponse,
  HealthResponse,
  KnowledgeCropListResponse,
  KnowledgePackListResponse,
  KnowledgePackSourcesResponse,
  ObservationListResponse,
  ProvidersHealthResponse,
  RotationComparisonResponse,
  RotationRun,
  RotationRunListResponse,
  RotationRulesResponse,
  WaterMethodsResponse,
  WaterPlan,
  ScenarioListResponse,
  ScenarioTaxonomy,
  ScenarioCapabilities,
  WaterPlanListResponse,
  WaterReadinessResponse,
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

// =============================================================
// Milestone 5 — knowledge base & rotation intelligence
// =============================================================

import {
  getKnowledgeCrops,
  getKnowledgePackSources,
  getKnowledgePacks,
  getRotationComparison,
  getRotationRules,
  getRotationRun,
  listCropHistory,
  listRotationRuns,
} from '@/lib/api'

export function useKnowledgePacks(enabled = true): UseQueryResult<KnowledgePackListResponse> {
  return useQuery({
    queryKey: ['knowledge-packs'],
    queryFn: getKnowledgePacks,
    enabled,
  })
}

export function useKnowledgePackSources(packId: string | null): UseQueryResult<KnowledgePackSourcesResponse> {
  return useQuery({
    queryKey: ['knowledge-pack-sources', packId],
    queryFn: () => getKnowledgePackSources(packId as string),
    enabled: !!packId,
  })
}

export function useKnowledgeCrops(enabled = true): UseQueryResult<KnowledgeCropListResponse> {
  return useQuery({
    queryKey: ['knowledge-crops'],
    queryFn: getKnowledgeCrops,
    enabled,
  })
}

export function useRotationRules(enabled = true): UseQueryResult<RotationRulesResponse> {
  return useQuery({
    queryKey: ['rotation-rules'],
    queryFn: getRotationRules,
    enabled,
  })
}

export function useCropHistory(fieldId: string | null): UseQueryResult<CropHistoryListResponse> {
  return useQuery({
    queryKey: ['crop-history', fieldId],
    queryFn: () => listCropHistory(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useRotationRuns(fieldId: string | null): UseQueryResult<RotationRunListResponse> {
  return useQuery({
    queryKey: ['rotation-runs', fieldId],
    queryFn: () => listRotationRuns(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useRotationRun(runId: string | null): UseQueryResult<RotationRun> {
  return useQuery({
    queryKey: ['rotation-run', runId],
    queryFn: () => getRotationRun(runId as string),
    enabled: !!runId,
  })
}

export function useRotationComparison(runId: string | null): UseQueryResult<RotationComparisonResponse> {
  return useQuery({
    queryKey: ['rotation-comparison', runId],
    queryFn: () => getRotationComparison(runId as string),
    enabled: !!runId,
  })
}

// Milestone 6A — water intelligence
export function useWaterMethods(enabled = true): UseQueryResult<WaterMethodsResponse> {
  return useQuery({
    queryKey: ['water-methods'],
    queryFn: getWaterMethods,
    enabled,
    staleTime: 5 * 60 * 1000,
  })
}

export function useWaterReadiness(fieldId: string | null): UseQueryResult<WaterReadinessResponse> {
  return useQuery({
    queryKey: ['water-readiness', fieldId],
    queryFn: () => getWaterReadiness(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useWaterPlans(fieldId: string | null): UseQueryResult<WaterPlanListResponse> {
  return useQuery({
    queryKey: ['water-plans', fieldId],
    queryFn: () => listWaterPlans(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useWaterPlan(planId: string | null): UseQueryResult<WaterPlan> {
  return useQuery({
    queryKey: ['water-plan', planId],
    queryFn: () => getWaterPlan(planId as string),
    enabled: !!planId,
  })
}

// =============================================================
// Milestone 7.1 — field state foundation
// =============================================================

export function useFieldStates(fieldId: string | null): UseQueryResult<FieldStateListResponse> {
  return useQuery({
    queryKey: ['field-states', fieldId],
    queryFn: () => listFieldStates(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useFieldState(stateId: string | null): UseQueryResult<FieldState> {
  return useQuery({
    queryKey: ['field-state', stateId],
    queryFn: () => getFieldState(stateId as string),
    enabled: !!stateId,
  })
}

export function useFieldStateVerify(stateId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['field-state-verify', stateId],
    queryFn: () => verifyFieldState(stateId as string),
    enabled: !!stateId && enabled,
  })
}

// ---------------------------------------------------------------------------
// Scenarios (M7.2)
// ---------------------------------------------------------------------------

export function useScenarios(fieldId: string | null): UseQueryResult<ScenarioListResponse> {
  return useQuery({
    queryKey: ['scenarios', fieldId],
    queryFn: () => listScenarios(fieldId as string),
    enabled: !!fieldId,
  })
}

export function useScenarioTypes(): UseQueryResult<ScenarioTaxonomy> {
  return useQuery({
    queryKey: ['scenario-types'],
    queryFn: getScenarioTypes,
    staleTime: 5 * 60 * 1000,
  })
}

export function useScenarioCapabilities(): UseQueryResult<ScenarioCapabilities> {
  return useQuery({
    queryKey: ['scenario-capabilities'],
    queryFn: getScenarioCapabilities,
    staleTime: 5 * 60 * 1000,
  })
}

// =============================================================
// Milestone 6B — soil intelligence
// =============================================================

import {
  getSoilDataReadiness,
  getSoilHealth,
  getSoilIndicators,
  getSoilMethods,
  getSoilProfile,
  listSocRuns,
} from '@/lib/api'
import type {
  SoilDataReadinessResponse,
  SoilHealthResponse,
  SoilIndicatorsResponse,
  SoilMethodsResponse,
  SoilProfileResponse,
  SocStockRunListResponse,
} from '@/lib/types'

export function useSoilProfile(fieldId: string | null): UseQueryResult<SoilProfileResponse> {
  return useQuery({
    queryKey: ['soil-profile', fieldId],
    queryFn: () => getSoilProfile(fieldId as string),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSoilIndicators(fieldId: string | null): UseQueryResult<SoilIndicatorsResponse> {
  return useQuery({
    queryKey: ['soil-indicators', fieldId],
    queryFn: () => getSoilIndicators(fieldId as string),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSoilHealth(fieldId: string | null): UseQueryResult<SoilHealthResponse> {
  return useQuery({
    queryKey: ['soil-health', fieldId],
    queryFn: () => getSoilHealth(fieldId as string),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSoilDataReadiness(fieldId: string | null): UseQueryResult<SoilDataReadinessResponse> {
  return useQuery({
    queryKey: ['soil-data-readiness', fieldId],
    queryFn: () => getSoilDataReadiness(fieldId as string),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

export function useSocRuns(fieldId: string | null): UseQueryResult<SocStockRunListResponse> {
  return useQuery({
    queryKey: ['soc-runs', fieldId],
    queryFn: () => listSocRuns(fieldId as string),
    enabled: !!fieldId,
    staleTime: 15_000,
  })
}

export function useSoilMethods(): UseQueryResult<SoilMethodsResponse> {
  return useQuery({
    queryKey: ['soil-methods'],
    queryFn: getSoilMethods,
    staleTime: 10 * 60 * 1000,
  })
}

// =============================================================
// Milestone 8 — AI insights: recommendations, field brief, advisor
// P1: locale-aware (A10), cache-aware (A3), sessions (A8), feedback (A12)
// =============================================================

import {
  getAdvisorHistory,
  getFieldInsights,
  getRecommendations,
  queryAdvisor,
  recordRecommendationFeedback,
  refreshRecommendations,
} from '@/lib/api'
import type {
  AdvisorHistoryResponse,
  FeedbackState,
  FieldInsightsResponse,
  RecommendationsResponse,
} from '@/lib/types'
import { useLocale } from 'next-intl'
import type { AiLocale } from '@/lib/api'

function toAiLocale(locale: string): AiLocale {
  return locale === 'ar' ? 'ar' : 'en'
}

/** Stored domain recommendations (rules + LLM narrative). */
export function useFieldRecommendations(
  fieldId: string | null,
): UseQueryResult<RecommendationsResponse> {
  const locale = useLocale()
  return useQuery({
    queryKey: ['recommendations', fieldId, locale],
    queryFn: () => getRecommendations(fieldId as string, false, { locale: toAiLocale(locale) }),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

/** Regenerate recommendations through the AI pipeline; syncs insights too. */
export function useRefreshRecommendations(fieldId: string | null) {
  const queryClient = useQueryClient()
  const locale = useLocale()
  return useMutation({
    mutationFn: (options: { force?: boolean } = {}) =>
      refreshRecommendations(fieldId as string, {
        force: options.force,
        locale: toAiLocale(locale),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      queryClient.invalidateQueries({ queryKey: ['field-insights'] })
    },
  })
}

/** Anomaly/trend insights plus the short AI field brief. */
export function useFieldInsights(fieldId: string | null): UseQueryResult<FieldInsightsResponse> {
  const locale = useLocale()
  return useQuery({
    queryKey: ['field-insights', fieldId, locale],
    queryFn: () => getFieldInsights(fieldId as string, toAiLocale(locale)),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

/** Recent advisor conversation for the field (user/assistant pairs). */
export function useAdvisorHistory(
  fieldId: string | null,
  limit = 20,
  sessionId?: string | null,
): UseQueryResult<AdvisorHistoryResponse> {
  return useQuery({
    queryKey: ['advisor-history', fieldId, limit, sessionId ?? null],
    queryFn: () => getAdvisorHistory(fieldId as string, limit, sessionId),
    enabled: !!fieldId,
  })
}

/** Ask the AI agronomist; the answer is persisted server-side into history. */
export function useAdvisorQuery(fieldId: string | null) {
  const queryClient = useQueryClient()
  const locale = useLocale()
  return useMutation({
    mutationFn: (input: { question: string; sessionId: string | null }) =>
      queryAdvisor(fieldId as string, input.question, {
        sessionId: input.sessionId,
        locale: toAiLocale(locale),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['advisor-history'] })
    },
  })
}

/** A12: record one feedback transition; refreshes the recommendations view. */
export function useRecommendationFeedback(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { recommendationId: string; state: FeedbackState; reason?: string }) =>
      recordRecommendationFeedback(input.recommendationId, input.state, input.reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recommendations', fieldId] })
    },
  })
}

// -------------------------------------------------------------
// P2 hooks (satellite, climate, soil memory, failure lab, evidence, portfolio)
// -------------------------------------------------------------

export function useVegetationSummary(fieldId: string | null, index = 'ndvi') {
  return useQuery({
    queryKey: ['vegetation-summary', fieldId, index],
    queryFn: () => getVegetationSummary(fieldId!, index),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useVegetationScenes(fieldId: string | null) {
  return useQuery({
    queryKey: ['vegetation-scenes', fieldId],
    queryFn: () => getVegetationScenes(fieldId!),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useClimateCapabilities() {
  return useQuery({
    queryKey: ['climate-capabilities'],
    queryFn: getClimateCapabilities,
    staleTime: 5 * 60_000,
  })
}

export function useForecastWindow(fieldId: string | null, variableCode: string) {
  return useQuery({
    queryKey: ['forecast-window', fieldId, variableCode],
    queryFn: () => getForecastWindow(fieldId!, variableCode),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useForecastRisks(fieldId: string | null) {
  return useQuery({
    queryKey: ['forecast-risks', fieldId],
    queryFn: () => getForecastRisks(fieldId!),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useIngestForecast(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { variables?: string[]; forecast_days?: number }) => ingestForecast(fieldId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['forecast-window', fieldId] })
      queryClient.invalidateQueries({ queryKey: ['forecast-risks', fieldId] })
    },
  })
}

export function useSoilTimeline(fieldId: string | null) {
  return useQuery({
    queryKey: ['soil-timeline', fieldId],
    queryFn: () => getSoilTimeline(fieldId!),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useSoilAlerts(fieldId: string | null) {
  return useQuery({
    queryKey: ['soil-alerts', fieldId],
    queryFn: () => getSoilAlerts(fieldId!),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

export function useCreateSoilSnapshot(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (asOf: string) => createSoilSnapshot(fieldId!, asOf),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['soil-timeline', fieldId] })
      queryClient.invalidateQueries({ queryKey: ['soil-alerts', fieldId] })
    },
  })
}

export function useCreateSoilChangeEstimate(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { start: string; end: string }) =>
      createSoilChangeEstimate(fieldId!, input.start, input.end),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['soil-timeline', fieldId] })
    },
  })
}

export function useStressPacks() {
  return useQuery({
    queryKey: ['stress-packs'],
    queryFn: getStressPacks,
    staleTime: 5 * 60_000,
  })
}

export function useRotationStressRuns(fieldId: string | null) {
  return useQuery({
    queryKey: ['rotation-stress-runs', fieldId],
    queryFn: () => getRotationStressRuns(fieldId!),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useCreateRotationStressRun(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { packs: Array<string | Record<string, unknown>>; candidates?: string[] }) =>
      createRotationStressRun(fieldId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rotation-stress-runs', fieldId] })
    },
  })
}

export function useEvidenceGaps(fieldId: string | null) {
  return useQuery({
    queryKey: ['evidence-gaps', fieldId],
    queryFn: () => getEvidenceGaps(fieldId!),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

export function useStaleness(fieldId: string | null) {
  return useQuery({
    queryKey: ['evidence-staleness', fieldId],
    queryFn: () => getStaleness(fieldId!),
    enabled: !!fieldId,
    staleTime: 60_000,
  })
}

export function useEvidenceActions(fieldId: string | null) {
  return useQuery({
    queryKey: ['evidence-actions', fieldId],
    queryFn: () => getEvidenceActions(fieldId!),
    enabled: !!fieldId,
    staleTime: 30_000,
  })
}

export function useCreateEvidenceAction(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { gap_code: string; action_type: string; title: string }) =>
      createEvidenceAction(fieldId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evidence-actions', fieldId] })
    },
  })
}

export function useTransitionEvidenceAction(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { actionId: string; toStatus: string; note?: string }) =>
      transitionEvidenceAction(fieldId!, input.actionId, input.toStatus, input.note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evidence-actions', fieldId] })
    },
  })
}

export function useApplyEvidence(fieldId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { ref_kind: string; ref_id?: string; action_id?: string }) =>
      applyEvidence(fieldId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evidence-staleness', fieldId] })
      queryClient.invalidateQueries({ queryKey: ['evidence-actions', fieldId] })
      queryClient.invalidateQueries({ queryKey: ['recommendations', fieldId] })
      queryClient.invalidateQueries({ queryKey: ['vegetation-summary', fieldId] })
    },
  })
}

export function usePortfolioConstraints() {
  return useQuery({
    queryKey: ['portfolio-constraints'],
    queryFn: getPortfolioConstraints,
    staleTime: 5 * 60_000,
  })
}

export function usePortfolioRuns(farmId: string | null) {
  return useQuery({
    queryKey: ['portfolio-runs', farmId],
    queryFn: () => getPortfolioRuns(farmId!),
    enabled: !!farmId,
    staleTime: 30_000,
  })
}

export function usePortfolioRun(runId: string | null) {
  return useQuery({
    queryKey: ['portfolio-run', runId],
    queryFn: () => getPortfolioRun(runId!),
    enabled: !!runId,
    staleTime: 60_000,
  })
}

export function useCreatePortfolioRun(farmId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof createPortfolioRun>[1]) => createPortfolioRun(farmId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portfolio-runs', farmId] })
    },
  })
}

import {
  applyEvidence,
  createEvidenceAction,
  createPortfolioRun,
  createRotationStressRun,
  createSoilChangeEstimate,
  createSoilSnapshot,
  getClimateCapabilities,
  getEvidenceActions,
  getEvidenceGaps,
  getForecastRisks,
  getForecastWindow,
  getPortfolioConstraints,
  getPortfolioRun,
  getPortfolioRuns,
  getRotationStressRun,
  getRotationStressRuns,
  getSoilAlerts,
  getSoilTimeline,
  getStaleness,
  getStressPacks,
  getVegetationScenes,
  getVegetationSummary,
  ingestForecast,
  transitionEvidenceAction,
} from '@/lib/api'
