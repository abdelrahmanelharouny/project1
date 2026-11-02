# M7.2 — Database & Migration

**Status:** implemented (migration `0008_scenario_domain`, revises `0007_field_state_foundation`)

## 1. Migration contents

Additive; no existing data rewritten.

### 1.1 `scenarios`

Columns: `id` UUID PK; `field_id` FK fields CASCADE; `name` varchar(120); `description` text;
`scenario_type` varchar(40); `scenario_status` varchar(30) default `draft`; `lineage_kind`
varchar(20) default `root`; `scenario_version` int default 1; `parent_field_state_id` FK
field_states **RESTRICT**; `parent_snapshot_checksum` varchar(64); `boundary_version` int;
`parent_scenario_id` FK scenarios **RESTRICT** (nullable); `configuration_schema_version`
varchar(20); `canonical_configuration` JSONB; `configuration_checksum` varchar(64);
`period_start`/`period_end` TIMESTAMPTZ; `timezone` varchar(60) default UTC;
`evidence_classification` varchar(30); `assumption_metadata` JSONB default `{}`;
`validation_summary` JSONB default `{}`; `created_by` UUID; `finalized_at` TIMESTAMPTZ;
`idempotency_key` text; `created_at`/`updated_at` (TimestampMixin semantics).

**Constraints**

| Name | Purpose |
|---|---|
| `ck_scenario_type` | 5-value type enum |
| `ck_scenario_status` | 8-value status enum |
| `ck_scenario_lineage_kind` | root / revision / branch |
| `ck_scenario_evidence_class` | observed / hypothetical / not_available |
| `ck_scenario_type_evidence_binding` | **C2 at DB level** — type and evidence class can never drift apart |
| `ck_scenario_period_order` | `period_end >= period_start` |
| `ck_scenario_finalized_at_present` | finalized ⇒ `finalized_at` NOT NULL |
| `ck_scenario_unavailable_types_never_finalized` | climate/forecast rows could never imply executable capability |

**Indexes**: `uq_scenario_idempotency (field_id, idempotency_key) WHERE idempotency_key IS
NOT NULL` (partial unique — field-scoped replay, the platform idiom), `ix_scenarios_field`,
`ix_scenarios_parent_scenario`, `ix_scenarios_parent_state`.

### 1.2 `scenario_validation_records`

`id` UUID PK; `scenario_id` FK scenarios CASCADE; `scenario_version` int;
`validation_rule_version` varchar(40); `validation_status` varchar(40) CHECK against the
8-value result vocabulary; `validation_result` JSONB (full document); `configuration_checksum`
varchar(64); `created_by` UUID; `created_at` TIMESTAMPTZ server default `now()`.
Index `ix_scenario_validation_scenario`.

### 1.3 Trigger

`enforce_scenario_immutability()` (PL/pgSQL) + `trg_scenario_immutability` BEFORE UPDATE —
freezes every content column on finalized/archived rows; only `finalized → archived` (and
`updated_at`) permitted; archived terminal. See `M7_2_IMMUTABILITY_AND_LINEAGE.md` §2.2.

## 2. Model location

`app/db/models.py::Scenario` / `::ScenarioValidationRecord` — SQLAlchemy 2.0 typed mappings,
UUID client-side defaults (platform idiom: raw SQL must supply UUIDs explicitly).

## 3. Verification (all executed)

| Check | Result |
|---|---|
| Dev DB `alembic upgrade head` | 0007 → **0008_scenario_domain (head)**, exit 0 |
| Clean scratch DB upgrade | tables + columns + indexes + trigger + the two C2-related CHECKs present (`TestM7_2ScenarioDomain::test_upgrade_creates_scenario_schema_and_trigger`) |
| Trigger freeze behavior | raw-SQL tamper attempts (config, checksum, status) all raise; finalized→archived allowed; archived terminal (`test_trigger_freezes_finalized_rows`) |
| Downgrade to 0007 | both tables dropped, trigger function dropped, `alembic current` = 0007, re-upgrade clean (`test_downgrade_to_0007_reverses_scenario_schema`) |
| Pre-existing migrations untouched | 0001–0007 suite unmodified and green |
