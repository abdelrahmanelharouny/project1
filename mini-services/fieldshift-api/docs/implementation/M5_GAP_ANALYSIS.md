# M5 Gap Analysis — Knowledge Base Honesty

Recorded at Milestone 5 (agricultural knowledge base & decision
intelligence) and cited by the bundled seed pack
(`app/knowledge/packs/seed_pack_v1.py`). It defines the honesty contract
that every later milestone inherited.

## What M5 set out to build

A source-cited crop knowledge base feeding the CP-SAT rotation optimizer:
crop definitions, Kc curve anchors, calendar windows, rotation rules
(family breaks, N-fixing), plus the optimizer plumbing (candidates,
constraints, objectives, explanations).

## Gaps identified — and how the code behaves because of them

1. **No in-house agronomy.** Every attribute must cite a published source
   (FAO-56, EcoCrop, Herridge et al.). Attributes without a defensible
   source are **omitted entirely** — e.g. no drought/heat tolerance scores
   ship in the seed pack because no citable source was transcribed.
2. **Calendar windows are synthesized contexts, not measurements.** EcoCrop
   windows carry `evidence_class="reference_synthesized"`: coarse
   northern-hemisphere temperate contexts consistent with the crops' FAO-56
   station contexts, flagged as requiring regional calibration.
3. **Reference values cannot harden into constraints.** Rotation rules and
   crop parameters are `validation_status="reference"`; hard rotation-break
   constraints bind on nothing until an agronomist upgrades them to
   `confirmed_regional`. The optimizer therefore never silently treats a
   reference rule as law.
4. **Deliberate data gaps stay gaps.** Faba bean ships without Kc values;
   its water criteria evaluate as `unevaluated`, never guessed. M6A later
   added its rooting depth and depletion fraction (FAO-56 Table 22) — a Kc
   row is still deliberately absent.
5. **Scope limits of the optimizer** (documented in the same program):
   seasonal assignment model, documented caps on solve time
   (`MAX_SOLVE_SECONDS`), deterministic solves, post-hoc criteria
   recomputation. No multi-year soil-carbon dynamics, no price forecasts —
   out of scope, not simulated.

## Disposition

All five gaps remain accurate as constraints on the system: they are
enforced by pack validation, the knowledge contracts
(`validate_pack_cross_references`) and the optimizer's use of validation
status. The M6A readiness matrix
(`docs/implementation/M6A_READINESS_MATRIX.md`) extends this analysis to
water-specific knowledge dimensions.
