# Scientific Audit — Findings Register (Pre-M6 Deepening)

The pre-M6 "scientific deepening" program audited the M1–M5 implementation
(geometry, observations, passport, feature engine, knowledge base, rotation
optimizer) against its own scientific claims. This document is the findings
register that `tests/unit/test_deepening_regressions.py` pins: **every F-xx
finding has at least one regression test**, so a fix that regresses fails CI.

Companion records: the deepening exit report and methodology documents live
in the platform docs (`/home/z/my-project/docs/deepening/`); this file is the
backend-local index cited from the code.

## Scope of the audit

- Geodesic area and geometry validation (ring closure, self-intersection,
  antimeridian handling) cross-checked against PostGIS `geography ST_Area`.
- Canonical observation contracts (missing = NULL, never zero).
- Deterministic synthetic provider (seeded hashing, injected gaps).
- Feature engine daily-series arithmetic (GDD, precipitation accumulations,
  temperature summaries) and its catalog versioning.
- Knowledge pack honesty (per-attribute citations, validation status).
- Rotation mathematics: candidate generation, water requirement estimates,
  hard constraints, objective normalization, Pareto computation.

## Finding classes (F-xx)

The register uses stable finding ids (`F-1`, `F-2`, …) referenced from code
comments and tests. Classes of issues found and fixed:

- **F-3 / F-18 — index and constraint drift:** tables created by
  `create_all` lacked indexes/constraints introduced later; migrations are
  now the only path to a correct schema (`tests/conftest.py` migrates to
  head and stamps appropriately).
- **F-8 — provenance labels lost in aggregation:** SoilGrids-derived values
  kept their prediction label through every transformation; a field-level
  prediction interval aggregated from pixel quantiles is reported as
  unavailable rather than averaged-and-relabeled.
- **Numeric edges in the feature engine:** zero-width windows, empty series
  and missing inputs evaluate to `not_evaluated` instead of silently
  producing zeros.
- **Rotation evaluation honesty:** criteria are normalized within the
  candidate set; the solver's internal objective is never reported as
  evidence; infeasibility maps back to named constraints.

## Rules that came out of the deepening

1. **Pure-layer tests need no database or HTTP** (pure functions stay pure:
   no clock, no randomness).
2. **Determinism is testable** — identical inputs produce identical outputs
   for the synthetic provider, the feature engine and the optimizer.
3. **No numeric fudges** — no epsilon-clamped divisions, no zero-fills;
   unavailability is structured and explicit.
4. **Every fix lands with a regression test** in
   `tests/unit/test_deepening_regressions.py` or the module's own suite.

## Status

All findings from the audit are closed and pinned by tests. Later programs
(M6A water, M6B soil, M6C management, M7 scenarios/decision layer) inherited
the same rules and run their own verification reports (see the milestone
docs alongside this file).
