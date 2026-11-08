# M7.7 Digital Twin Architecture

The digital twin layer. Implementation: `app/digital_twin/service.py`
(assembly & validation) with contracts in
`app/digital_twin/contracts.py`.

## What the twin is

A **traceable field-level representation** that connects the platform's
immutable artifacts into one navigable structure:

```
field identity / boundary versions
    → immutable Field State snapshots (checksummed)
    → observations & provenance → derived features
    → finalized scenarios → M7.3 scenario executions
    → M7.4 sensitivity analyses
    → M7.5 robust rotation runs → M7.6 decision documents
```

## Honesty rules

- **Not a decorative dashboard.** Every section links to underlying
  artifact ids and checksums; validation re-verification results are
  persisted as immutable records, so a twin snapshot states not only what
  the data is but whether it still checks out.
- **Information classes are distinguished everywhere.** Observed /
  transformed / calculated are labelled; scenario derivatives are always
  marked hypothetical.
- **Maturity is classified from IMPLEMENTED capabilities only.** No
  predictive, autonomous or forecasting claims — no such infrastructure
  exists in the platform (no forecast, projection or satellite providers;
  see `../../KNOWN_LIMITATIONS.md`).
- **No duplicated verification.** Validation walks reuse the EXISTING
  per-artifact verifiers (field states, executions, analyses, robust runs,
  decision documents). The twin aggregates their verdicts; it never
  re-implements an integrity check.

## Assembly and validation flow

1. Resolve the field and its boundary versions (tenant-authorized).
2. Collect the artifact chain above, newest-first, respecting immutability
   and status gates (only result-bearing artifacts are summarized).
3. Summarize each link with ids, checksums, method versions and key
   outcomes — referencing, never copying, the underlying evidence.
4. Run the validation walk (the per-artifact `/verify` endpoints' logic)
   and persist the outcome as an immutable validation record.

## Consequences

- A twin view is reproducible: given the same artifact set, the assembly is
  deterministic (documented sort orders, no clock-dependent content in
  stable sections).
- Gaps are visible: missing links (e.g. no finalized scenario yet) appear
  as explicit empty sections with reasons, not as blank space.
- The twin adds no new analytics; if evidence does not exist upstream, the
  twin cannot show it — by design.
