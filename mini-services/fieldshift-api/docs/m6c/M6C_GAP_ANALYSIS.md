# M6C Gap Analysis — Management Practices Knowledge

Recorded at Milestone 6C (field management: practices, cover crops, residue,
soil cover, erosion screening, operations scheduling) and cited from the
practices pack (`app/knowledge/packs/m6c_practices_pack.py`).

## §11 — Source verification

Every qualitative mechanism claim in the M6C pack paraphrases a source that
was **fetched and read** during M6C Increment 1:

- FAO conservation-agriculture pages (global-qualitative scope),
- USDA NRCS practice standards and technical sheets (US-scoped; the
  documents scope themselves),
- the USDA National Agronomy Manual,
- RUSLE2 scope statements (for the erosion screening's model boundaries).

Paraphrasing is conservative: no quantity, threshold or date appears in the
pack that the sources do not state.

## §13 — Honesty contract for practices

1. **Nothing numeric ships.** No seeding rates, no termination lead times,
   no machinery capacities, no cover percentages, no thresholds. Numbers can
   only enter through region-scoped, versioned pack updates with their own
   provenance.
2. **Everything is `validation_status="reference"`.** No practice becomes a
   hard recommendation until a local agronomist review upgrades it (the
   M5/M6A gating is inherited).
3. **Trade-offs are two-sided.** Every practice carries at least one
   negative or context-dependent dimension — no practice is universally
   beneficial.
4. **Regional applicability is declared only where the source scopes
   itself** (NRCS → US; FAO pages → global-qualitative).
5. **Methods have declared model scope.** The residue ledger is a mass
   balance, not a decomposition simulation; erosion is a screening
   calculation (RUSLE2-style factors with explicitly declared boundaries),
   not a process model; soil cover is a daily cover-fraction computation.

## Remaining gaps

- No region-quantified practice parameters (awaiting region-validated
  pack updates).
- No machinery/logistics optimization beyond the documented operations
  scheduling model (window- and resource-aware scheduling with explicit
  feasibility findings).
- Erosion screening is deliberately coarse (no slope hydraulics, no
  sediment routing) — its outputs are labelled screening results, never
  erosion predictions.
