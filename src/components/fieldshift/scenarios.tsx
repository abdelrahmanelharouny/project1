'use client'

import { useMemo, useState } from 'react'
import {
  BadgeCheck,
  CircleAlert,
  FlaskConical,
  GitBranch,
  Info,
  Lock,
  Play,
  ShieldAlert,
  ShieldCheck,
  Ban,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import {
  useFieldStates,
  useScenarioCapabilities,
  useScenarioTypes,
  useScenarios,
} from '@/hooks/use-fieldshift'
import {
  archiveScenario,
  compareScenarios,
  createScenario,
  createScenarioVersion,
  deleteScenario,
  describeError,
  finalizeScenario,
  getScenarioLineage,
  listScenarioVersions,
  ApiError,
  validateScenario,
  verifyScenario,
} from '@/lib/api'
import { useFieldShiftUi } from '@/lib/store'
import type {
  Scenario,
  ScenarioCompareResponse,
  ScenarioLineageResponse,
  ScenarioStatus,
  ScenarioTaxonomy,
  ScenarioValidateResponse,
  ScenarioVerifyResponse,
  ScenarioVersionsResponse,
} from '@/lib/types'

function apiErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.details[0]
    const detailText = detail?.reason ? `${detail.field}: ${detail.reason}` : detail?.field
    return detailText ? `${err.message} (${detailText})` : err.message
  }
  return describeError(err).description ?? describeError(err).title
}

function shortHash(hash: string | null | undefined): string {
  return hash ? `${hash.slice(0, 12)}…` : '—'
}

function shortIso(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '—'
}

// ---------------------------------------------------------------------------
// Badges (C2: evidence classes are never equivalent)
// ---------------------------------------------------------------------------

function EvidenceBadge({ classification, label }: { classification: string; label?: string }) {
  const map: Record<string, string> = {
    observed: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    hypothetical: 'border-amber-300 bg-amber-50 text-amber-800',
    not_available: 'border-stone-300 bg-stone-100 text-stone-600',
  }
  const icons: Record<string, React.ReactNode> = {
    observed: <BadgeCheck className="h-3 w-3" aria-hidden />,
    hypothetical: <FlaskConical className="h-3 w-3" aria-hidden />,
    not_available: <Ban className="h-3 w-3" aria-hidden />,
  }
  return (
    <Badge variant="outline" className={`gap-1 font-normal ${map[classification] ?? ''}`}>
      {icons[classification]}
      {label ?? classification}
    </Badge>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    draft: 'border-stone-300 bg-white text-stone-600',
    validation_pending: 'border-amber-200 bg-amber-50 text-amber-700',
    valid: 'border-emerald-300 bg-emerald-50 text-emerald-800',
    conditionally_valid: 'border-amber-300 bg-amber-50 text-amber-800',
    invalid: 'border-red-300 bg-red-50 text-red-700',
    finalized: 'border-emerald-400 bg-emerald-100 text-emerald-900',
    archived: 'border-stone-300 bg-stone-100 text-stone-500',
    unsupported: 'border-stone-400 bg-stone-100 text-stone-700',
  }
  return (
    <Badge variant="outline" className={`font-normal ${map[status] ?? ''}`}>
      {status.replace('_', ' ')}
    </Badge>
  )
}

function FindingList({ findings }: { findings: Array<{ code: string; severity: string; message: string }> }) {
  if (!findings.length) return null
  const colors: Record<string, string> = {
    error: 'text-red-700',
    warning: 'text-amber-700',
    info: 'text-stone-600',
  }
  return (
    <ul className="mt-2 space-y-1.5">
      {findings.map((f, i) => (
        <li key={`${f.code}-${i}`} className="flex gap-2 text-xs">
          <span className={`mt-0.5 shrink-0 font-medium ${colors[f.severity] ?? 'text-stone-600'}`}>
            {f.severity}
          </span>
          <span className="text-stone-700">
            <span className="font-mono text-[11px] text-stone-500">{f.code}</span> — {f.message}
          </span>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Create form
// ---------------------------------------------------------------------------

const ADJUSTMENT_FIELDS: Array<{ key: string; label: string; placeholder: string }> = [
  { key: 'temperature_delta_c', label: 'Temperature shift (°C)', placeholder: 'e.g. 2.0' },
  { key: 'precipitation_multiplier', label: 'Precipitation ratio (×, 1 = unchanged)', placeholder: 'e.g. 0.8' },
  { key: 'water_allocation_multiplier', label: 'Irrigation allocation ratio (×)', placeholder: 'e.g. 0.7' },
  { key: 'precipitation_delta_mm', label: 'Precipitation shift (mm)', placeholder: 'e.g. -50' },
  { key: 'seasonal_timing_shift_days', label: 'Seasonal timing shift (days)', placeholder: 'e.g. 10' },
  { key: 'rainfall_period_shift_days', label: 'Rainfall period shift (days)', placeholder: 'e.g. -14' },
]

function CreateScenarioCard({
  fieldId,
  fieldStates,
  taxonomy,
}: {
  fieldId: string
  fieldStates: Array<{ id: string; label: string; status: string; checksum_sha256: string | null; boundary_version: number; period_start: string; period_end: string }>
  taxonomy: ScenarioTaxonomy
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [scenarioType, setScenarioType] = useState('user_defined_stress')
  const [stateId, setStateId] = useState('')
  const [periodStart, setPeriodStart] = useState('2016-01-01')
  const [periodEnd, setPeriodEnd] = useState('2017-12-31')
  const [adjustments, setAdjustments] = useState<Record<string, string>>({
    temperature_delta_c: '2.0',
    water_allocation_multiplier: '0.7',
  })
  const [assumptionDescription, setAssumptionDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)

  const implementedTypes = taxonomy.types.filter((t) => t.capability === 'implemented')
  const unimplementedTypes = taxonomy.types.filter((t) => t.capability !== 'implemented')
  const isHypothetical = scenarioType !== 'historical_observed'

  const succeededStates = fieldStates.filter((s) => s.status === 'succeeded')

  const mutation = useMutation({
    mutationFn: async () => {
      const adjustmentPayload: Record<string, number> = {}
      for (const [key, value] of Object.entries(adjustments)) {
        if (value !== '' && value !== undefined) {
          const numeric = Number(value)
          if (!Number.isNaN(numeric)) adjustmentPayload[key] = numeric
        }
      }
      const configuration: Record<string, unknown> = {
        type: scenarioType,
        parent_field_state_id: stateId,
      }
      if (isHypothetical) {
        configuration.period = { start: periodStart, end: periodEnd }
        configuration.adjustments = adjustmentPayload
        configuration.assumption_metadata = {
          origin: 'user_defined',
          status: 'hypothetical',
          description: assumptionDescription || undefined,
        }
      }
      const createdScenario = await createScenario(fieldId, {
        scenario_type: scenarioType,
        name: name || undefined,
        configuration: configuration as never,
      })
      return createdScenario
    },
    onSuccess: (scenario) => {
      setError(null)
      setCreated(`${scenario.name} (v${scenario.scenario_version}, checksum ${shortHash(scenario.configuration_checksum)})`)
      setName('')
      queryClient.invalidateQueries({ queryKey: ['scenarios', fieldId] })
    },
    onError: (err) => {
      setCreated(null)
      setError(apiErrorText(err))
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FlaskConical className="h-4 w-4 text-emerald-700" aria-hidden />
          Define a scenario
        </CardTitle>
        <CardDescription>
          A scenario is a checked, versioned <strong>definition</strong> against an immutable
          Field State. Nothing is simulated in M7.2 — a valid configuration is not a result.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="scenario-name">Name</Label>
            <Input
              id="scenario-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Hot-dry stress 2016"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="scenario-type">Scenario type</Label>
            <Select value={scenarioType} onValueChange={setScenarioType}>
              <SelectTrigger id="scenario-type" aria-label="Scenario type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {implementedTypes.map((t) => (
                  <SelectItem key={t.scenario_type} value={t.scenario_type}>
                    {t.display_name} — {t.evidence_classification}
                  </SelectItem>
                ))}
                {unimplementedTypes.map((t) => (
                  <SelectItem key={t.scenario_type} value={t.scenario_type} disabled>
                    {t.display_name} — not implemented
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="scenario-state">Parent Field State (immutable baseline)</Label>
          <Select
            value={stateId}
            onValueChange={(value) => {
              setStateId(value)
              const state = succeededStates.find((s) => s.id === value)
              if (state) {
                setPeriodStart(state.period_start.slice(0, 10))
                setPeriodEnd(state.period_end.slice(0, 10))
              }
            }}
          >
            <SelectTrigger id="scenario-state" aria-label="Parent field state">
              <SelectValue placeholder="Select a succeeded field state…" />
            </SelectTrigger>
            <SelectContent>
              {succeededStates.length === 0 && (
                <div className="px-3 py-2 text-xs text-stone-500">
                  No succeeded field states yet — assemble one in the Field State tab first.
                </div>
              )}
              {succeededStates.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.label} · boundary v{s.boundary_version} · {shortHash(s.checksum_sha256)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {isHypothetical && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="period-start">Period start (UTC)</Label>
                <Input
                  id="period-start"
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="period-end">Period end (UTC)</Label>
                <Input
                  id="period-end"
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                />
              </div>
            </div>

            <div>
              <p className="mb-2 text-sm font-medium">Hypothetical assumptions</p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {ADJUSTMENT_FIELDS.map((f) => (
                  <div key={f.key} className="space-y-1">
                    <Label htmlFor={`adj-${f.key}`} className="text-xs">
                      {f.label}
                    </Label>
                    <Input
                      id={`adj-${f.key}`}
                      inputMode="decimal"
                      className="h-9"
                      placeholder={f.placeholder}
                      value={adjustments[f.key] ?? ''}
                      onChange={(e) => setAdjustments((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-3 space-y-1.5">
                <Label htmlFor="assumption-desc" className="text-xs">
                  Assumption description (recorded as user-defined & hypothetical)
                </Label>
                <Input
                  id="assumption-desc"
                  value={assumptionDescription}
                  onChange={(e) => setAssumptionDescription(e.target.value)}
                  placeholder="e.g. hotter and drier growing season with reduced allocation"
                />
              </div>
            </div>
          </>
        )}

        {scenarioType === 'historical_observed' && (
          <Alert>
            <Info className="h-4 w-4" aria-hidden />
            <AlertTitle>Observed reference</AlertTitle>
            <AlertDescription>
              A historical observed scenario carries no assumptions: it labels the parent
              Field State&apos;s recorded condition as the reference. Evidence class:{' '}
              <strong>observed</strong> — never a prediction.
            </AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <ShieldAlert className="h-4 w-4" aria-hidden />
            <AlertTitle>Could not create scenario</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {created && (
          <Alert>
            <BadgeCheck className="h-4 w-4 text-emerald-700" aria-hidden />
            <AlertTitle>Scenario created (draft)</AlertTitle>
            <AlertDescription>{created}</AlertDescription>
          </Alert>
        )}

        <Button
          onClick={() => mutation.mutate()}
          disabled={!stateId || mutation.isPending || !scenarioType}
          className="min-h-11"
        >
          {mutation.isPending ? 'Creating…' : 'Create scenario definition'}
        </Button>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Scenario card with actions
// ---------------------------------------------------------------------------

function ScenarioCard({
  scenario,
  fieldId,
  onCompare,
  compareTarget,
}: {
  scenario: Scenario
  fieldId: string
  onCompare: (id: string) => void
  compareTarget: string | null
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [validation, setValidation] = useState<ScenarioValidateResponse | null>(null)
  const [verify, setVerify] = useState<ScenarioVerifyResponse | null>(null)
  const [versions, setVersions] = useState<ScenarioVersionsResponse | null>(null)
  const [lineage, setLineage] = useState<ScenarioLineageResponse | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['scenarios', fieldId] })

  const runAction = (fn: () => Promise<unknown>, onDone?: (data: unknown) => void) =>
    async () => {
      setError(null)
      try {
        const data = await fn()
        onDone?.(data)
        invalidate()
      } catch (err) {
        setError(apiErrorText(err))
      }
    }

  const isFinalized = scenario.scenario_status === 'finalized'
  const isArchived = scenario.scenario_status === 'archived'
  const canFinalize = scenario.scenario_status === 'valid' || scenario.scenario_status === 'conditionally_valid'
  const canDelete = scenario.scenario_status === 'draft'

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">
              {scenario.name}{' '}
              <span className="text-xs font-normal text-stone-500">
                v{scenario.scenario_version} · {scenario.lineage_kind}
              </span>
            </CardTitle>
            <CardDescription className="mt-1 [overflow-wrap:anywhere]">
              {scenario.scenario_type_display} · parent state {shortHash(scenario.parent_field_state_id)} · boundary v{scenario.boundary_version}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <EvidenceBadge classification={scenario.evidence_classification} label={scenario.evidence_label} />
            <StatusBadge status={scenario.scenario_status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600 sm:grid-cols-3">
          <div>
            <dt className="text-stone-400">Period</dt>
            <dd>
              {shortIso(scenario.period.start)} → {shortIso(scenario.period.end)}
            </dd>
          </div>
          <div>
            <dt className="text-stone-400">Timezone</dt>
            <dd>{scenario.timezone}</dd>
          </div>
          <div>
            <dt className="text-stone-400">Config checksum</dt>
            <dd className="break-all font-mono" title={scenario.configuration_checksum}>
              {shortHash(scenario.configuration_checksum)}
            </dd>
          </div>
          <div>
            <dt className="text-stone-400">Schema</dt>
            <dd>{scenario.configuration_schema_version}</dd>
          </div>
          <div>
            <dt className="text-stone-400">Parent snapshot checksum</dt>
            <dd className="break-all font-mono" title={scenario.parent_snapshot_checksum}>
              {shortHash(scenario.parent_snapshot_checksum)}
            </dd>
          </div>
          <div>
            <dt className="text-stone-400">Finalized</dt>
            <dd>{scenario.finalized_at ? shortIso(scenario.finalized_at) : '—'}</dd>
          </div>
        </dl>

        {scenario.assumption_metadata && Object.keys(scenario.assumption_metadata).length > 0 && (
          <p className="min-w-0 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 [overflow-wrap:anywhere]">
            <strong>Hypothetical assumptions</strong> ({String((scenario.assumption_metadata as Record<string, unknown>).origin ?? 'user_defined')}
            , {String((scenario.assumption_metadata as Record<string, unknown>).status ?? 'hypothetical')}):{' '}
            {String((scenario.assumption_metadata as Record<string, unknown>).description ?? '—')}
          </p>
        )}

        {error && (
          <Alert variant="destructive">
            <ShieldAlert className="h-4 w-4" aria-hidden />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {validation && (
          <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
            <p className="text-xs font-medium text-stone-700">
              Validation: <span className="font-mono">{validation.validation_status}</span> → scenario{' '}
              <span className="font-mono">{validation.scenario_status}</span> · rules {validation.validation_rule_version}
            </p>
            <FindingList findings={validation.validation_result.findings} />
            <p className="mt-2 text-[11px] text-stone-500">{validation.note}</p>
          </div>
        )}

        {verify && (
          <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-stone-700">
              {verify.configuration_checksum_valid ? (
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
              ) : (
                <ShieldAlert className="h-3.5 w-3.5 text-red-700" aria-hidden />
              )}
              Checksum valid: {String(verify.configuration_checksum_valid)} · parent state intact:{' '}
              {String(verify.parent_state_exists && verify.parent_snapshot_checksum_matches)} · boundary record:{' '}
              {String(verify.boundary_version_record_exists)}
            </p>
          </div>
        )}

        {versions && (
          <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
            <p className="text-xs font-medium text-stone-700">Version chain ({versions.chain_length})</p>
            <ul className="mt-1 space-y-1">
              {versions.items.map((v) => (
                <li key={v.id} className="break-all text-xs text-stone-600">
                  v{v.scenario_version} · {v.scenario_status} · {shortHash(v.configuration_checksum)}
                  {v.finalized_at ? ` · finalized ${shortIso(v.finalized_at)}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        {lineage && (
          <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
            <p className="text-xs font-medium text-stone-700">Lineage</p>
            <ul className="mt-1 space-y-1 text-xs text-stone-600">
              {lineage.ancestors.map((a) => (
                <li key={a.id} className="break-all">
                  ↑ {a.name} (v{a.scenario_version}, {a.lineage_kind})
                </li>
              ))}
              <li>
                ● this: {lineage.scenario_id} (v{lineage.scenario_version}, {lineage.lineage_kind})
              </li>
              {lineage.children.map((ch) => (
                <li key={ch.id} className="break-all">
                  ↓ {ch.name} (v{ch.scenario_version}, {ch.lineage_kind}, {ch.scenario_status})
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            disabled={isFinalized || isArchived || scenario.scenario_status === 'unsupported'}
            onClick={runAction(() => validateScenario(scenario.id), (data) => setValidation(data as ScenarioValidateResponse))}
          >
            Validate
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            disabled={!canFinalize}
            onClick={runAction(() => finalizeScenario(scenario.id))}
          >
            <Lock className="mr-1 h-3.5 w-3.5" aria-hidden />
            Finalize
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            disabled={!isFinalized}
            onClick={runAction(
              () =>
                createScenarioVersion(scenario.id, {
                  configuration: scenario.canonical_configuration as never,
                }),
              undefined
            )}
            title="Create a new draft version of this finalized scenario"
          >
            <GitBranch className="mr-1 h-3.5 w-3.5" aria-hidden />
            New version
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            onClick={runAction(() => listScenarioVersions(scenario.id), (data) => {
              setVersions(data as ScenarioVersionsResponse)
              setLineage(null)
            })}
          >
            Versions
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            onClick={runAction(() => getScenarioLineage(scenario.id), (data) => {
              setLineage(data as ScenarioLineageResponse)
              setVersions(null)
            })}
          >
            Lineage
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            onClick={runAction(() => verifyScenario(scenario.id), (data) => setVerify(data as ScenarioVerifyResponse))}
          >
            Verify checksum
          </Button>
          <Button
            size="sm"
            variant={compareTarget === scenario.id ? 'default' : 'outline'}
            className="min-h-9"
            onClick={() => onCompare(scenario.id)}
            title="Select as comparison side A"
          >
            Compare
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="min-h-9 text-stone-500"
            disabled={isFinalized || isArchived}
            onClick={runAction(() => archiveScenario(scenario.id))}
          >
            Archive
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="min-h-9 text-red-600"
            disabled={!canDelete}
            onClick={runAction(() => deleteScenario(scenario.id))}
          >
            Delete
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Comparison panel
// ---------------------------------------------------------------------------

function ComparisonCard({
  result,
  onClose,
}: {
  result: ScenarioCompareResponse
  onClose: () => void
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Definition comparison</CardTitle>
        <CardDescription>{result.note}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 text-xs sm:grid-cols-2">
          {[result.scenario_a, result.scenario_b].map((s, i) => (
            <div key={s.id} className="min-w-0 rounded-md border border-stone-200 p-3">
              <p className="font-medium text-stone-800">
                Side {i === 0 ? 'A' : 'B'}: {s.name} (v{s.scenario_version}, {s.scenario_status})
              </p>
              <p className="mt-1 text-stone-600">
                {s.scenario_type} · <EvidenceBadge classification={s.evidence_classification} label={s.evidence_classification} />
              </p>
              <p className="break-all font-mono text-[11px] text-stone-500">checksum {shortHash(s.configuration_checksum)}</p>
              <p className="text-stone-600">
                parent {shortHash(s.parent_field_state_id)} · boundary v{s.boundary_version}
              </p>
            </div>
          ))}
        </div>

        {result.warnings.length > 0 && (
          <Alert>
            <CircleAlert className="h-4 w-4" aria-hidden />
            <AlertTitle>Compatibility warnings</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {result.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <div className="rounded-md border border-stone-200 p-3">
          <p className="text-xs font-medium text-stone-700">
            Configuration differences ({result.configuration_diff.length})
            {result.identical_configuration && ' — identical'}
          </p>
          {result.configuration_diff.length > 0 && (
            <ul className="mt-1 space-y-1 text-xs">
              {result.configuration_diff.map((d, i) => (
                <li key={`${d.path}-${i}`} className="break-all font-mono text-[11px] text-stone-600">
                  {d.kind} <span className="text-stone-800">{d.path}</span>: {JSON.stringify(d.left)} → {JSON.stringify(d.right)}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1 text-[11px] text-stone-500">
            Period overlap fraction: {result.temporal_comparison.period_overlap_fraction ?? '—'}
          </p>
        </div>
        <Button size="sm" variant="ghost" className="min-h-9" onClick={onClose}>
          Close comparison
        </Button>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function Scenarios() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const fieldId = selectedField?.id ?? null

  const scenariosQuery = useScenarios(fieldId)
  const statesQuery = useFieldStates(fieldId)
  const taxonomyQuery = useScenarioTypes()
  const capabilitiesQuery = useScenarioCapabilities()

  const [compareSideA, setCompareSideA] = useState<string | null>(null)
  const [compareError, setCompareError] = useState<string | null>(null)
  const [comparison, setComparison] = useState<ScenarioCompareResponse | null>(null)

  const scenarios = useMemo(() => scenariosQuery.data?.items ?? [], [scenariosQuery.data])
  const fieldStates = useMemo(
    () =>
      (statesQuery.data?.items ?? []).map((s) => ({
        id: s.id,
        label: s.label,
        status: s.status,
        checksum_sha256: s.checksum_sha256,
        boundary_version: s.boundary_version,
        period_start: s.period.start,
        period_end: s.period.end,
      })),
    [statesQuery.data],
  )

  const handleCompare = async (scenarioId: string) => {
    setCompareError(null)
    if (!compareSideA) {
      setCompareSideA(scenarioId)
      setComparison(null)
      return
    }
    if (compareSideA === scenarioId) {
      setCompareSideA(null)
      return
    }
    try {
      const result = await compareScenarios(compareSideA, scenarioId)
      setComparison(result)
      setCompareSideA(null)
    } catch (err) {
      setCompareError(apiErrorText(err))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">Scenario Workspace</h2>
          <p className="text-sm text-stone-500">
            Define, validate, version and compare hypothetical field scenarios against immutable
            Field States. Definitions only — no simulation exists yet.
          </p>
        </div>
        <FieldPicker value={null} onValueChange={setSelectedField} />
      </div>

      {!fieldId && (
        <Card>
          <CardContent className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
            <Play className="h-8 w-8 text-stone-300" aria-hidden />
            <p className="text-sm text-stone-500">Select a field to work with scenarios.</p>
          </CardContent>
        </Card>
      )}

      {fieldId && (
        <>
          {capabilitiesQuery.data && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Platform scenario capabilities</CardTitle>
                <CardDescription>{capabilitiesQuery.data.note}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {Object.entries(capabilitiesQuery.data.dimensions).map(([dim, entry]) => (
                    <div
                      key={dim}
                      className="min-w-0 rounded-md border border-stone-200 bg-stone-50 p-3"
                      title={entry.reason}
                    >
                      <Badge variant="outline" className="border-stone-400 bg-stone-100 font-normal text-stone-700">
                        <Ban className="mr-1 h-3 w-3" aria-hidden />
                        {dim.replace('_', ' ')}
                      </Badge>
                      <p className="mt-1.5 text-[11px] leading-snug text-stone-500">{entry.reason}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-stone-500">
                  {capabilitiesQuery.data.execution.reason} Digital twin:{' '}
                  {capabilitiesQuery.data.digital_twin_level}.
                </p>
              </CardContent>
            </Card>
          )}

          {taxonomyQuery.data && fieldStates.length >= 0 && (
            <CreateScenarioCard
              fieldId={fieldId}
              fieldStates={fieldStates}
              taxonomy={taxonomyQuery.data}
            />
          )}
          {taxonomyQuery.isLoading && <Skeleton className="h-64 w-full" />}

          {compareError && (
            <Alert variant="destructive">
              <ShieldAlert className="h-4 w-4" aria-hidden />
              <AlertTitle>Comparison failed</AlertTitle>
              <AlertDescription>{compareError}</AlertDescription>
            </Alert>
          )}
          {comparison && <ComparisonCard result={comparison} onClose={() => setComparison(null)} />}
          {compareSideA && (
            <Alert>
              <Info className="h-4 w-4" aria-hidden />
              <AlertTitle>Comparison side A selected</AlertTitle>
              <AlertDescription>Pick another scenario and press Compare.</AlertDescription>
            </Alert>
          )}

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-stone-700">
              Scenarios on this field ({scenarios.length})
            </h3>
            {scenariosQuery.isLoading && <Skeleton className="h-24 w-full" />}
            {!scenariosQuery.isLoading && scenarios.length === 0 && (
              <Card>
                <CardContent className="py-8 text-center text-sm text-stone-500">
                  No scenarios defined yet. Create one above — start from a succeeded Field State.
                </CardContent>
              </Card>
            )}
            {scenarios.map((s) => (
              <ScenarioCard
                key={s.id}
                scenario={s}
                fieldId={fieldId}
                onCompare={handleCompare}
                compareTarget={compareSideA}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
