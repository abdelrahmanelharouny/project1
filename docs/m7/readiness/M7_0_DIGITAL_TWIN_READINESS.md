# M7.0 — Field Digital Twin Readiness

**Inspection date:** 2026-11-01 · **Question:** what level of digital representation does FieldShift *genuinely* support today?
**Verdict up front: the highest honestly supportable level is Level 1 — Historical Digital Profile, with strong, purpose-built ingredients for Level 2.** The existing workspace is a decision-support dashboard over versioned analytical runs; it is **not** a Digital Twin and must not be labelled one. Levels 4–5 are not reachable and there is no calibration dataset or operational feedback loop.

---

## 1. Maturity classification (with evidence)

| Level | Definition (spec) | FieldShift today | Verdict |
|---|---|---|---|
| **L0 — Static Field Record** | field identity + manually recorded information | `fields` + `field_boundary_versions` (append-only, change_reason), `crop_history` (farmer-reported), `farm_constraints`, farmer CSV imports | **ACHIEVED** |
| **L1 — Historical Digital Profile** | environmental, soil, crop, management history | environmental: ✅ observations (5 real/synthetic providers) + 29 versioned features over explicit periods; crop: ✅ crop history + rotation runs + knowledge packs; soil: ⚠️ only SoilGrids 0–5 cm predictions & farmer CSV points — **no sampling events, no profiles, no assessment history (M6B absent)**; management: ❌ none (M6C absent) | **ACHIEVED WITH GAPS** (environmental/crop complete; soil thin; management absent) |
| **L2 — Versioned Field State** | reproducible state snapshots across compatible periods | per-domain versioned snapshots exist (feature runs, water plans, rotation runs — all checksummed, idempotent, with pack refs); **no unified Field State object exists**; boundary versions are not pinned by results (F-01); observation sets not fully pinned (F-03) | **NOT ACHIEVED — but the platform was explicitly built for this** (run-snapshot idiom is exactly the required pattern); M7.1 closes it |
| **L3 — Scenario-capable Field Model** | hypothetical changes evaluated through versioned engines | versioned engines exist (feature, water, rotation) with honest refusal paths; **no scenario orchestration**; water plans already demonstrate immutable re-evaluation under changed allocations | **NOT ACHIEVED** — M7.2–M7.3 scope; engines are ready |
| **L4 — Calibrated Predictive Twin** | model behavior calibrated & evaluated against sufficiently frequent real field observations | **no calibration capability of any kind**: no calibration tables, no parameter estimation, no validation-against-observations loop; FAO-56/FAO-33/Saxton-Rawls are used as *uncalibrated reference methods* with that status disclosed; real-farm observation frequency is entirely user-dependent and currently demo-synthetic | **NOT ACHIEVED — and must not be claimed** |
| **L5 — Operationally Connected Twin** | ongoing observations update state; validated predictive & operational feedback | no ingestion automation/scheduling, no live sensor connectors, no feedback of actual outcomes into model parameters, no reconciliation process | **NOT ACHIEVED** |

**Highest genuine level: L1** (L0 fully, L1 with documented soil/management gaps). The honest classification the spec demands: *FieldShift is a versioned decision-intelligence platform with twin-grade provenance habits, at L1 maturity, on a credible trajectory to L2/L3, with no current basis for L4/L5 claims.*

## 2. Required capability investigation

| Capability | What exists | What is missing for the next level |
|---|---|---|
| Field state representation | per-domain snapshots (see L2 row) + the M7.0 Field State readiness design (`M7_0_FIELD_STATE_READINESS.md`) | the unified state object itself (M7.1); boundary pinning (F-01) |
| Data synchronization | manual/idempotent ingestion jobs (5 providers), natural-key dedupe, provider health probes | no scheduled/automated sync, no connector framework, no retry worker (inline execution only) |
| State history | boundary versions + run histories + audit_events (before/after snapshots) | state-level history (once states exist); retention/archival policy |
| Observation updates | append-only observations with evidence classes; re-ingest is idempotent | no update/backfill semantics beyond append; staleness policy absent (Field State F-10) |
| Scenario comparisons | within-run strategy comparison; run-to-run feature comparison (Δ=0 reproducibility path) | cross-run and cross-scenario comparison surfaces (F-18); scenario tables (M7.2) |
| Model calibration capability | **none** — engines are fixed reference implementations with versioned parameters (Kc tables, PTF coefficients); no fitting loop | everything: calibration protocol, objective functions, holdout validation, per-field parameter sets; **prerequisite: frequent real observations (none guaranteed)** |
| Parameter versioning | **strong**: engine/method versions, feature catalog versions, pack versions+checksums, PTF version — every analytical artifact records what produced it | nothing material; this is the platform's best twin-grade property |
| Actual farm outcome feedback | farmer CSV observations & crop history capture *some* outcomes (dates, reported values); yield/economics deliberately not estimated | no outcome entity linking planned vs realized (no harvest records, no actual-irrigation records beyond "not_supplied") |
| State reconciliation | idempotency + checksums give *computational* reconciliation; cross-run comparison tooling exists for features | no semantic reconciliation (conflicting evidence between sources at state level — Field State F-11) |

## 3. Honest-labeling requirements for the UI (Phase I tie-in)

Given this classification, the frontend must (continue to) avoid twin-claims:
- The workspace already brands itself as decision support with synthetic-data banners (`workspace.tsx:40`, `auth-gate.tsx:259-261`).
- Any future "Digital Twin" surface must present L-level framing (e.g., "Historical profile — v1 field states"), never "live twin", until L4 prerequisites exist.
- "Predictive" wording is already refused platform-wide ("historical proxy, NOT a forecast" — water/service.py:114, rotation/service.py:264); this must extend to any twin timeline UI.

## 4. Findings register

| ID | Severity | Domain | Affected | Current | Expected | Evidence | Impact | Blocks M7? |
|---|---|---|---|---|---|---|---|---|
| F-24 | High | Twin | no unified state object | per-domain snapshots only | M7.1 Field State assembly (by reference) | Field State doc §1 | defines the twin ceiling at L1→L2 | No (it IS M7.1) |
| F-25 | High | Twin | no calibration framework | uncalibrated reference methods only | L4 permanently gated on real, sufficiently frequent observations + calibration design | §1 L4 | any L4 claim would be scientifically invalid | N/A (out of scope for M7 increments 1–7; M7.8 note) |
| F-26 | Medium | Twin | no operational feedback loop | no outcome-vs-plan reconciliation | L5 gated on operational connectivity + validated prediction | §1 L5 | out of M7 scope | N/A |
| F-27 | Medium | Twin | soil/management history absent | L1 profile incomplete | honest gap display; M6B/M6C scope decision needed | as-built §4.6/4.7 | twin timeline will have two empty lanes | Conditional (timeline UX only) |
| F-28 | Low | Twin | ingestion is manual/inline | no automated sync | L5 requires worker/queue infrastructure (also API/DB doc F-31) | API doc §2.3 | future | No |

## 5. Readiness verdict

| Level | Status |
|---|---|
| L0 Static record | **READY** (achieved) |
| L1 Historical digital profile | **READY_WITH_LIMITATIONS** (achieved; soil thin, management absent) |
| L2 Versioned field state | **PARTIAL** — all ingredients exist (checksummed run snapshots, pack refs, boundary versions); assembly missing (M7.1) |
| L3 Scenario-capable model | **PARTIAL** — engines ready; scenario layer missing (M7.2–M7.4) |
| L4 Calibrated predictive twin | **NOT_IMPLEMENTED** — no calibration basis; must not be claimed |
| L5 Operationally connected twin | **NOT_IMPLEMENTED** — no operational connectivity or validated feedback |
