# Knowledge Model (Milestone 5)

How agricultural knowledge is stored, versioned and consumed. Authoritative
implementation: `app/db/models.py` (Milestone 5 section, `KnowledgePack` and
related tables), `app/knowledge/` (service, import, contracts) and the
bundled packs in `app/knowledge/packs/`.

## Design goals

1. **Every value is citable.** Each attribute in a knowledge pack points at
   a source row (pack-internal `SourceIn` with title, year, URL) plus a
   confidence label. Nothing is invented; deliberate gaps stay gaps.
2. **Reference until validated.** Values transcribed from published tables
   (FAO-56, EcoCrop, Herridge et al., NRCS practice standards) carry
   `validation_status="reference"`. Only an agronomist review upgrades a
   value to `confirmed_regional`. Hard constraints in the rotation optimizer
   bind only on confirmed values — reference rules inform soft scoring and
   candidate metadata but never silently harden.
3. **Platform-level, not tenant-scoped.** Packs are global; farms consume
   them through candidate generation and planning. Versioning is explicit:
   `(pack_code, pack_version)` is unique and the pack stores a checksum so
   identical imports are idempotent.

## Pack lifecycle and status

| Status | Meaning |
| --- | --- |
| `draft` | Inspectable via the API, inert: not used by engines |
| `active` | Feeds candidate generation and optimization (subject to per-value validation status) |
| `retired` | History; kept for lineage of past runs |

Imports are validated as a whole (`validate_pack_cross_references`): source
references must resolve, curve anchors must be monotonic, water parameters
must reference declared sources. A failed import inserts nothing.

## Bundled packs

- **`kp-seed-global` (`seed_pack_v1.py`)** — crop anchors for the seed crop
  set: FAO-56 Kc curve anchors and stage lengths, rooting depths and
  depletion fractions (Table 22), EcoCrop calendar windows (labelled
  `evidence_class="reference_synthesized"` — coarse northern-hemisphere
  temperate contexts, explicitly not station measurements), rotation
  family rules with mechanism text, and N-fixing capacity estimates
  (Herridge et al.). Faba bean deliberately has no Kc row — its water
  criteria evaluate as `unevaluated` rather than guessed.
- **M6C practices pack (`m6c_practices_pack.py`)** — management practices
  (cover crops, residue, soil cover, erosion) with qualitative mechanisms,
  requirements, trade-offs and risks. Ships **no numbers at all**: no
  seeding rates, no thresholds, no machinery capacities. Trade-offs are
  two-sided by construction; regional applicability is declared only where
  the cited source scopes itself.

## Consumption

- `app/knowledge/service.py` exposes read models (crops, curves, rules) to
  the rotation and water engines.
- `app/rotation/candidates.py` and `app/knowledge/service.rules_between`
  translate pack rows into candidate attributes and rotation-break rules.
- `app/water/knowledge.py` builds a per-crop water readiness matrix that
  distinguishes complete/source-backed, partial, missing,
  not-locally-validated and not-applicable dimensions (see
  `docs/implementation/M6A_READINESS_MATRIX.md`).

## Extending

New knowledge enters as a new pack version through the import endpoint or a
new module under `app/knowledge/packs/`, never by editing a shipped pack in
place. Numbers require region-scoped, versioned updates with their own
provenance (M6C contract).
