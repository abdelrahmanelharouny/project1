# Task AI-2c — Frontend "AI Insights" tab (recommendations + insights + advisor)

Agent: ai-insights-frontend (task ID AI-2c)
Date: 2026-02-14
Status: ✅ Complete — `bun run lint` clean (exit 0), `bunx tsc --noEmit` shows **zero errors in src/** and messages/** (only pre-existing/out-of-scope errors in `mini-services/llm-bridge/index.ts` created by parallel agent AI-2b, and `skills/image-edit/scripts/image-edit.ts`). Dev server compiles and serves `/?tab=aiinsights` → 200.

## Store tab id (exact)

`'aiinsights'` — added to the `WorkspaceTab` union in `src/lib/store.ts` (after `'decisions'`, before `'digitaltwin'`), rendered in `src/components/fieldshift/workspace.tsx` via `TAB_ITEMS` entry `{ value: 'aiinsights', icon: <Sparkles …> }` + `<TabsContent value="aiinsights">` in the same position. Tab label key `aiinsights` was added to **messages/{en,ar}/nav.json** (workspace renders tab labels from the `nav` namespace using the raw tab id — `t(tab)` in `TabLabel`).

## Files created

| File | Purpose |
|---|---|
| `src/components/fieldshift/ai-insights.tsx` | ~856 lines, default-exported `'use client'` tab component, `useTranslations('aiinsights')`. Sections: `OverviewCard` (engine Badge mode+model, 4 severity stat chips with Info/AlertTriangle/CheckCircle2/XCircle in stone/amber/emerald/red outline tokens, RefreshCw button that spins while `refresh.isPending`, relative `<24h` / short-datetime `generated_at` via locale-aware `Intl`), `RecommendationsSection` (grouped by `response.domains` with per-domain heading + count pill, severity-sorted, per-rec: title/summary/`<figure>` emerald narrative quote/actions bullet list/evidence chips with `title={detail}`/confidence `NN% · basis`/`aria-expanded` rationale toggle, container `max-h-[32rem] overflow-y-auto pe-1 scrollbar-thin`, skeleton + friendly empty CTA that reuses the regenerate button), `InsightsStrip` (metric/value-vs-baseline/z/direction TrendingUp/TrendingDown/Minus cards, severity-tinted kind Badge, emerald "AI brief" Sparkles callout; renders `null` on error/empty), `AdvisorChat` (role="log" aria-live list `max-h-96 overflow-y-auto`, persisted history bubbles `self-end` user / `self-start` assistant with logical rounded corners, evidence chips under the fresh assistant answer, 3-dot animated thinking bubble with `role="status"`, Textarea min-h-11 with Enter-submit/Shift+Enter-newline, 44px Send `size="icon"` with aria-label, disclaimer line using backend `disclaimer` once available with i18n default). |
| `messages/en/aiinsights.json` | 47 keys: title, subtitle, pickFieldDesc, overview*, generate/refresh/refreshing, engineModeRulesLlm/EngineModeRules, countsSummary (ICU plural), severity*, domain*, generatedAt, list*, loadErrorTitle, empty*, rationaleShow/Hide, actionsLabel, evidenceLabel, confidence, narrativeLabel, insights*, briefLabel, kind*, direction*, vsBaseline, zLabel, advisor*, questionPlaceholder, send, thinking, history, noMessagesYet, evidenceChips, disclaimer, advisorError. |
| `messages/ar/aiinsights.json` | Professional Arabic (agricultural register matching decisions.json; "AI Insights" → «رؤى الذكاء الاصطناعي», "Ask the AI Agronomist" → «اسأل الخبير الزراعي الذكي»; full ICU Arabic plural categories =0/one/two/few/many/other for countsSummary). |
| `agent-ctx/AI-2c-frontend-ai-insights.md` | This record. |

## Files modified

| File | Change |
|---|---|
| `src/lib/types.ts` | New "AI Insights" section before the `declare global` block: `RecommendationSeverity`, `RecommendationDomain`, `AiEngineInfo`, `RecommendationEvidence`, `Recommendation`, `RecommendationsResponse` (counts.by_severity as `Partial<Record<…,number>>`), `FieldInsightItem`, `FieldInsightsResponse`, `AdvisorEvidence` (`detail?: string | null` — history/refresh endpoints return it only sometimes), `AdvisorQueryResponse`, `AdvisorHistoryMessage`, `AdvisorHistoryResponse`. |
| `src/lib/api.ts` | Type imports (Advisor*/AiEngineInfo/FieldInsightsResponse/RecommendationsResponse) + 5 endpoint functions at the end: `getRecommendations(fieldId, refresh=false)` (GET with optional `?refresh=true`), `refreshRecommendations(fieldId)` (POST `…/recommendations/refresh`, body `{}`), `getFieldInsights(fieldId)`, `queryAdvisor(fieldId, question)` (POST body `{question}`), `getAdvisorHistory(fieldId, limit=20)` (`?limit=`). |
| `src/hooks/use-fieldshift.ts` | `useMutation, useQueryClient` added to top react-query import; new M8 section with `useFieldRecommendations` (queryKey `['recommendations', fieldId]`, staleTime 60_000), `useRefreshRecommendations` (mutation; invalidates `['recommendations']` + `['field-insights']`), `useFieldInsights` (`['field-insights', fieldId]`, 60_000), `useAdvisorHistory` (`['advisor-history', fieldId, limit]`), `useAdvisorQuery` (mutation; invalidates `['advisor-history']` on success). |
| `src/i18n/config.ts` | `'aiinsights'` added to `messageNamespaces` (between `'decisions'` and `'digitaltwin'`). |
| `src/lib/store.ts` | `'aiinsights'` added to `WorkspaceTab` union. |
| `src/components/fieldshift/workspace.tsx` | `Sparkles` lucide import; `AiInsights` default import; `TAB_ITEMS` + `TabsContent` entries after `decisions`. |
| `messages/en/nav.json`, `messages/ar/nav.json` | `"aiinsights"` tab label keys ("AI Insights" / «رؤى الذكاء الاصطناعي»). |

## Verification

- `bun run lint` → clean (0 problems). Note: the repo enables `react-hooks/set-state-in-effect` (React Compiler rules) — initial draft had 2 errors (setState inside effects for field-reset and optimistic-clear); fixed by remounting `AdvisorChat` via `key={fieldId}` and awaiting `queryClient.invalidateQueries` inside the mutation `onSuccess` before `setOptimistic([])` (setState in async callback, not effect).
- `bunx tsc --noEmit` → 2 errors total, both outside my scope: `mini-services/llm-bridge/index.ts(184,16) TS2867` (AI-2b's new service, missing @types/bun) and `skills/image-edit/scripts/image-edit.ts(10,4) TS2561` (pre-existing, also noted by task 3b). **No errors in any file I own.**
- Dev log: transient `Module not found: '@/components/fieldshift/ai-insights'` appeared only in the hot-reload window between the workspace.tsx edit and file creation; latest `GET /?tab=aiinsights` → **200, compile clean**.

## Contract notes / mismatches accommodated

1. `counts.by_severity` typed as `Partial<Record<RecommendationSeverity, number>>` and read with `?? 0` — contract example shows all four keys but partial robustness is safer.
2. `AdvisorEvidence.detail` typed `detail?: string | null` (contract shows it for recommendations but not explicitly guaranteed on advisor responses); chips fall back to `label` in the tooltip.
3. `AdvisorQueryResponse.created_at` used with `|| new Date().toISOString()` fallback for the optimistic assistant bubble.
4. `RecommendationsResponse.domains` is treated as the grouping order but any domain present in items and missing from the array is appended (defensive grouping).
5. Unknown `severity`/`domain`/`kind` values at runtime fall back to info-styled badge / raw string instead of crashing.
6. Insights section renders `null` when the endpoint errors or returns no insights + no summary (avoids a permanently broken panel while the backend rolls out); recommendations and advisor errors ARE surfaced via destructive Alert / inline error text.
7. Advisor history entries carry no evidence, so evidence chips render only for the freshly answered message (from `evidence_used`) — they persist in the answer text after history takes over.

## Notes for next agents

- Query keys to reuse/invalidate: `['recommendations', fieldId]`, `['field-insights', fieldId]`, `['advisor-history', fieldId, limit]`.
- `aiinsights` namespace keys are safe to reuse; keep nav.json + config.ts ordering in sync with the tab position.
- If the advisor later returns evidence in history messages, extend `ChatMessage.evidence` mapping in `AdvisorChat`/`ChatBubble` (single place).
- Backend endpoints hit: `GET/POST /api/v1/fields/{id}/recommendations(/refresh)`, `GET /api/v1/fields/{id}/insights`, `POST /api/v1/fields/{id}/advisor/query`, `GET /api/v1/fields/{id}/advisor/history` — all through the shared cookie-auth `request()` wrapper (relative paths + `XTransformPort=3030`).
