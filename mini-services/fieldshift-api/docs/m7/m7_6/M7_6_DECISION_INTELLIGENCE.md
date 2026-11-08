# M7.6 Decision Intelligence

The decision comparison layer. Implementation: `app/decision/contracts.py`
(document status/section vocabularies) and `app/decision/service.py`
(generation).

## What a decision document is

ONE immutable, checksummed document per field that unifies M7.3 scenario
executions, M7.4 sensitivity analyses and M7.5 robust rotation runs into a
traceable decision view. Generation **reads aggregates only**: no engine is
re-run, no calculation is duplicated — executions were computed once by
M7.3, sensitivities by M7.4, robust evaluations by M7.5. This module only
assembles, ranks-within-unit and explains.

## Scientific discipline (non-negotiable)

- **No composite scores.** No unsupported rankings, no probabilities, no
  yield predictions, no universal recommendations — ever.
- **Rankings only within the same unit.** A millimetre can be ranked
  against a millimetre; a degree Celsius is never ranked against a
  millimetre. Every ranking is a documented key sort (magnitude
  descending, then identifiers), so identical inputs yield an identical
  document and checksum.
- **Full traceability.** Every section item carries its source references
  (execution run id + output checksum, analysis id, robust run id) and the
  method versions of the engines that produced the evidence.
- **Missing evidence is a first-class section.** Unavailable and unevaluated
  evidence is reported with reasons — never a footnote, never silently
  dropped, never zero-filled.

## Document shape

A decision document groups, per field:

1. **Scenario deltas** — per execution, the changes its transformations
   induced (unit-qualified, checksum-referenced).
2. **Sensitivity findings** — per analysis, the classified responses and
   their bounds, with the uncertainty-registry references.
3. **Robust results** — per robust run, the shared-plan verdict,
   worst-case objective and (optional) regret, with caps and exclusions
   stated.
4. **Unavailable evidence** — structured reasons for everything that could
   not be evaluated.

Statuses mirror the execution layer (`queued`, `running`, `succeeded`,
`completed_with_limitations`, `failed`); result-bearing statuses are
immutable and trigger-frozen.

## What it deliberately does not do

It does not choose for the farmer, does not collapse trade-offs into a
score, and does not extrapolate beyond the evidence its source artifacts
carry. Interpretation stays with the user; the document's job is to make
every claim checkable against its source artifact.
