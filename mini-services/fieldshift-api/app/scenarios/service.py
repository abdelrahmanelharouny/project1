"""Scenario domain service (Milestone 7.2).

Implements the scenario lifecycle (create → validate → finalize → archive),
version/branch lineage, definition-level comparison and checksum
verification on top of the pure contracts and validation engine.

Hard architectural rules (M7.2 spec §2):

- the parent Field State is the authoritative baseline and is NEVER mutated;
- a scenario is a DEFINITION — no endpoint here executes anything;
- finalized scenarios are immutable (application transitions + DB trigger);
- every reference boundary resolves tenant ownership server-side;
- climate projection / weather forecast / soil / management are reported
  unavailable and never fabricated.
"""

import uuid as uuid_mod
from datetime import date as date_cls
from datetime import datetime, timezone as dt_timezone
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db import models as dbm
from app.field_state import contracts as fsc
from app.field_state.manifest import canonical_json
from app.scenarios import contracts as sc
from app.scenarios import validation as sv

# Statuses from which the definition may still be edited (resets to draft).
EDITABLE_STATUSES = frozenset(
    {
        sc.ScenarioStatus.DRAFT.value,
        sc.ScenarioStatus.VALIDATION_PENDING.value,
        sc.ScenarioStatus.VALID.value,
        sc.ScenarioStatus.CONDITIONALLY_VALID.value,
        sc.ScenarioStatus.INVALID.value,
    }
)
VALIDATABLE_STATUSES = frozenset({sc.ScenarioStatus.DRAFT.value})
# Draft edits are allowed; invalid rows must be PATCHed back to draft first.
VALIDATE_ALLOWED_STATUSES = EDITABLE_STATUSES - {sc.ScenarioStatus.INVALID.value}

ARCHIVABLE_STATUSES = frozenset(
    {
        sc.ScenarioStatus.DRAFT.value,
        sc.ScenarioStatus.VALIDATION_PENDING.value,
        sc.ScenarioStatus.VALID.value,
        sc.ScenarioStatus.CONDITIONALLY_VALID.value,
        sc.ScenarioStatus.INVALID.value,
        sc.ScenarioStatus.FINALIZED.value,
    }
)


# ------------------------------------------------------------- helpers
def _as_utc(value: Any, field_name: str) -> datetime:
    """Parse an ISO datetime/date into an aware UTC datetime (M7.1 idiom:
    naive → UTC, plain dates → UTC midnight)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date_cls):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                d = date_cls.fromisoformat(text)
            except ValueError:
                raise ValidationFailed(
                    f"{field_name} must be an ISO-8601 date or datetime.",
                    details=[{"field": field_name, "reason": str(value)}],
                ) from None
            parsed = datetime(d.year, d.month, d.day)
    else:
        raise ValidationFailed(
            f"{field_name} must be an ISO-8601 date or datetime.",
            details=[{"field": field_name, "reason": str(value)}],
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(dt_timezone.utc).isoformat() if value else None


def _transition(scenario: dbm.Scenario, target: str) -> None:
    """Apply a lifecycle transition, enforcing the documented legal table."""
    allowed = sc.LEGAL_TRANSITIONS.get(scenario.scenario_status, frozenset())
    if target not in allowed:
        raise Conflict(
            f"Illegal scenario status transition "
            f"'{scenario.scenario_status}' → '{target}'.",
            code="SCENARIO_INVALID_STATE_TRANSITION",
            details=[
                {"field": "scenario_status", "from": scenario.scenario_status, "to": target}
            ],
        )
    scenario.scenario_status = target


def _require_mutable(scenario: dbm.Scenario, action: str) -> None:
    if scenario.scenario_status in ("finalized", "archived"):
        raise Conflict(
            f"Scenario is {scenario.scenario_status} and immutable; {action} is not "
            "permitted. Create a new version instead.",
            code="SCENARIO_IMMUTABLE",
            details=[{"scenario_status": scenario.scenario_status}],
        )


def _resolve_parent_state(db: Session, field: dbm.Field, state_id: Any) -> dbm.FieldState:
    """Resolve the parent Field State with full reference integrity.

    Tenant ownership is already established for `field` by the API layer;
    the parent state must additionally belong to THAT field — a state from
    any other field (same tenant or not) is refused without leaking its
    existence.
    """
    try:
        parsed = uuid_mod.UUID(str(state_id))
    except (TypeError, ValueError):
        raise ValidationFailed(
            "parent_field_state_id must be a UUID.",
            details=[{"field": "parent_field_state_id"}],
        ) from None
    state = db.get(dbm.FieldState, parsed)
    if state is None or state.field_id != field.id:
        raise ValidationFailed(
            "parent_field_state_id must reference a Field State of the same field.",
            details=[{"field": "parent_field_state_id", "reason": str(state_id)}],
            code="PARENT_STATE_MISMATCH",
        )
    if state.status != "succeeded":
        raise ValidationFailed(
            "The parent Field State has not succeeded and cannot be used as a baseline.",
            details=[{"field": "parent_field_state_id", "status": state.status}],
            code="PARENT_STATE_NOT_SUCCEEDED",
        )
    if not state.checksum_sha256:
        raise ValidationFailed(
            "The parent Field State has no checksum and cannot be referenced.",
            details=[{"field": "parent_field_state_id"}],
            code="PARENT_STATE_NOT_VERIFIED",
        )
    return state


def _resolve_parent_scenario(
    db: Session, field: dbm.Field, scenario_id: Any
) -> dbm.Scenario:
    try:
        parsed = uuid_mod.UUID(str(scenario_id))
    except (TypeError, ValueError):
        raise ValidationFailed(
            "parent_scenario_id must be a UUID.",
            details=[{"field": "parent_scenario_id"}],
        ) from None
    parent = db.get(dbm.Scenario, parsed)
    if parent is None or parent.field_id != field.id:
        raise ValidationFailed(
            "parent_scenario_id must reference a scenario of the same field.",
            details=[{"field": "parent_scenario_id", "reason": str(scenario_id)}],
            code="PARENT_SCENARIO_MISMATCH",
        )
    return parent


def _build_configuration(
    scenario_type: str, raw_config: dict[str, Any] | None
) -> tuple[Any, dict[str, Any]]:
    """Parse + canonicalize the configuration document."""
    if not isinstance(raw_config, dict):
        raise ValidationFailed(
            "configuration must be an object.",
            details=[{"field": "configuration"}],
        )
    payload = {"schema_version": sc.SCENARIO_CONFIG_SCHEMA_VERSION, **raw_config}
    if payload.get("type") not in (None, scenario_type):
        raise ValidationFailed(
            "configuration.type must match the scenario type.",
            details=[{"field": "configuration.type"}],
        )
    payload["type"] = scenario_type
    try:
        model = sc.parse_configuration(scenario_type, payload)
    except PydanticValidationError as exc:
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "reason": err["msg"]}
            for err in exc.errors()
        ]
        raise ValidationFailed(
            "Scenario configuration failed contract validation.",
            details=details,
            code="SCENARIO_CONFIGURATION_INVALID",
        ) from None
    return model, sc.canonicalize_configuration(model)


def _checksum_for(
    *,
    scenario_type: str,
    canonical_configuration: dict[str, Any],
    parent_state: dbm.FieldState,
    timezone: str,
) -> tuple[str, str]:
    payload = sc.scenario_checksum_payload(
        scenario_type=scenario_type,
        configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
        canonical_configuration=canonical_configuration,
        parent_field_state_id=str(parent_state.id),
        parent_snapshot_checksum=parent_state.checksum_sha256 or "",
        boundary_version=parent_state.boundary_version,
        timezone=timezone,
    )
    return sc.compute_scenario_checksum(payload), canonical_json(payload)


# ------------------------------------------------------------- create
def create_scenario(
    db: Session,
    *,
    field: dbm.Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> dbm.Scenario:
    """Create a draft scenario definition (or idempotently return the
    existing one for a repeated idempotency key)."""
    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.Scenario).where(
                dbm.Scenario.idempotency_key == idempotency_key,
                dbm.Scenario.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    scenario_type = payload.get("scenario_type") or (payload.get("configuration") or {}).get("type")
    if not scenario_type:
        raise ValidationFailed(
            "scenario_type is required.",
            details=[{"field": "scenario_type"}],
        )
    if scenario_type not in sc.IMPLEMENTED_SCENARIO_TYPES:
        capability = sc.SCENARIO_TYPE_CAPABILITIES.get(scenario_type)
        reason = (
            capability.unavailable_reason if capability is not None else "Unknown scenario type."
        )
        raise ValidationFailed(
            f"Scenario type '{scenario_type}' is not implemented and cannot be created.",
            details=[{"field": "scenario_type", "reason": reason}],
            code="SCENARIO_TYPE_NOT_IMPLEMENTED",
        )

    name = str(payload.get("name") or "").strip()
    if not name:
        capability = sc.SCENARIO_TYPE_CAPABILITIES[scenario_type]
        name = f"{capability.display_name} scenario"
    if len(name) > sc.SCENARIO_NAME_MAX:
        name = name[: sc.SCENARIO_NAME_MAX]
    description = payload.get("description")
    if description is not None:
        description = str(description).strip() or None

    parent_scenario = None
    lineage_kind = sc.LineageKind.ROOT.value
    scenario_version = 1
    if payload.get("parent_scenario_id"):
        parent_scenario = _resolve_parent_scenario(db, field, payload.get("parent_scenario_id"))
        lineage_kind = sc.LineageKind.BRANCH.value

    model, canonical_config = _build_configuration(scenario_type, payload.get("configuration"))
    config_dict = model.model_dump(mode="json")

    # The parent reference lives INSIDE the configuration document (M7.2
    # spec §6 example); resolve it with full integrity checks.
    parent_state = _resolve_parent_state(db, field, model.parent_field_state_id)

    # Temporal scope: hypothetical types carry their own period; the observed
    # reference inherits the parent state's period verbatim.
    if scenario_type == sc.ScenarioType.HISTORICAL_OBSERVED.value:
        period_start, period_end = parent_state.period_start, parent_state.period_end
    else:
        period = config_dict.get("period") or {}
        period_start = _as_utc(period.get("start"), "configuration.period.start")
        period_end = _as_utc(period.get("end"), "configuration.period.end")

    timezone = parent_state.timezone or "UTC"
    checksum, _canonical_payload = _checksum_for(
        scenario_type=scenario_type,
        canonical_configuration=canonical_config,
        parent_state=parent_state,
        timezone=timezone,
    )

    capability = sc.SCENARIO_TYPE_CAPABILITIES[scenario_type]
    scenario = dbm.Scenario(
        field_id=field.id,
        name=name,
        description=description,
        scenario_type=scenario_type,
        scenario_status=sc.ScenarioStatus.DRAFT.value,
        lineage_kind=lineage_kind,
        scenario_version=scenario_version,
        parent_field_state_id=parent_state.id,
        parent_snapshot_checksum=parent_state.checksum_sha256,
        boundary_version=parent_state.boundary_version,
        parent_scenario_id=parent_scenario.id if parent_scenario is not None else None,
        configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
        canonical_configuration=canonical_config,
        configuration_checksum=checksum,
        period_start=period_start,
        period_end=period_end,
        timezone=timezone,
        evidence_classification=capability.evidence_classification.value,
        assumption_metadata=(config_dict.get("assumption_metadata") or {}),
        validation_summary={},
        created_by=getattr(created_by, "id", None),
        idempotency_key=idempotency_key,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


# ------------------------------------------------------------- reads
def get_scenario(db: Session, scenario_id: uuid_mod.UUID) -> dbm.Scenario | None:
    return db.get(dbm.Scenario, scenario_id)


def list_scenarios(
    db: Session,
    field_id: uuid_mod.UUID,
    *,
    scenario_type: str | None = None,
    scenario_status: str | None = None,
) -> list[dbm.Scenario]:
    query = select(dbm.Scenario).where(dbm.Scenario.field_id == field_id)
    if scenario_type:
        query = query.where(dbm.Scenario.scenario_type == scenario_type)
    if scenario_status:
        query = query.where(dbm.Scenario.scenario_status == scenario_status)
    return list(
        db.execute(query.order_by(dbm.Scenario.created_at.desc())).scalars().all()
    )


# ------------------------------------------------------------- edit / delete
def patch_scenario(
    db: Session,
    scenario: dbm.Scenario,
    payload: dict[str, Any],
) -> dbm.Scenario:
    """Edit a non-finalized definition. Any edit resets validation: the
    previous verdict referred to a configuration that no longer exists."""
    _require_mutable(scenario, "PATCH")
    if scenario.scenario_status not in EDITABLE_STATUSES:
        raise Conflict(
            f"Scenario in status '{scenario.scenario_status}' cannot be edited.",
            code="SCENARIO_INVALID_STATE_TRANSITION",
        )

    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationFailed("name cannot be empty.", details=[{"field": "name"}])
        scenario.name = name[: sc.SCENARIO_NAME_MAX]
    if "description" in payload:
        scenario.description = str(payload.get("description") or "").strip() or None

    if "configuration" in payload:
        raw_config = payload.get("configuration")
        if not isinstance(raw_config, dict) or not raw_config:
            raise ValidationFailed(
                "configuration must be a non-empty object.",
                details=[{"field": "configuration"}],
            )
        model, canonical_config = _build_configuration(scenario.scenario_type, raw_config)
        config_dict = model.model_dump(mode="json")
        checksum, _ = _checksum_for(
            scenario_type=scenario.scenario_type,
            canonical_configuration=canonical_config,
            parent_state=db.get(dbm.FieldState, scenario.parent_field_state_id),
            timezone=scenario.timezone,
        )
        if checksum != scenario.configuration_checksum:
            scenario.canonical_configuration = canonical_config
            scenario.configuration_checksum = checksum
            scenario.assumption_metadata = config_dict.get("assumption_metadata") or {}
            if scenario.scenario_type != sc.ScenarioType.HISTORICAL_OBSERVED.value:
                period = config_dict.get("period") or {}
                scenario.period_start = _as_utc(period.get("start"), "configuration.period.start")
                scenario.period_end = _as_utc(period.get("end"), "configuration.period.end")

    # Any edit resets validation state.
    if scenario.scenario_status != sc.ScenarioStatus.DRAFT.value:
        _transition(scenario, sc.ScenarioStatus.DRAFT.value)
    scenario.validation_summary = {}
    db.commit()
    db.refresh(scenario)
    return scenario


def delete_scenario(db: Session, scenario: dbm.Scenario) -> None:
    """Only drafts can be hard-deleted; everything else must be archived so
    historical references and lineage stay intact."""
    if scenario.scenario_status != sc.ScenarioStatus.DRAFT.value:
        raise Conflict(
            "Only draft scenarios can be deleted; finalized/archived scenarios "
            "must be archived instead to preserve lineage and checksums.",
            code="SCENARIO_DELETE_RESTRICTED",
        )
    children = db.scalar(
        select(dbm.Scenario.id).where(dbm.Scenario.parent_scenario_id == scenario.id).limit(1)
    )
    if children is not None:
        raise Conflict(
            "Scenario has child scenarios in the lineage and cannot be deleted.",
            code="SCENARIO_DELETE_RESTRICTED",
        )
    db.delete(scenario)
    db.commit()


# ------------------------------------------------------------- validation
def _parent_state_view(db: Session, state: dbm.FieldState) -> sv.ParentStateView:
    boundary_row = db.scalar(
        select(dbm.FieldBoundaryVersion.id).where(
            dbm.FieldBoundaryVersion.field_id == state.field_id,
            dbm.FieldBoundaryVersion.version_number == state.boundary_version,
        )
    )
    manifest = state.observation_manifest or {}
    field = db.get(dbm.Field, state.field_id)
    farm = db.get(dbm.Farm, field.farm_id) if field is not None else None
    return sv.ParentStateView(
        field_id=str(state.field_id),
        organization_id=str(farm.organization_id) if farm is not None else "",
        status=state.status,
        checksum=state.checksum_sha256,
        boundary_version=state.boundary_version,
        boundary_record_exists=boundary_row is not None,
        period_start=state.period_start,
        period_end=state.period_end,
        timezone=state.timezone,
        domain_availability=state.domain_availability or {},
        observation_count=int(manifest.get("observation_count") or 0),
        synthetic_observation_count=int(manifest.get("synthetic_observation_count") or 0),
    )


def _scenario_view(scenario: dbm.Scenario) -> sv.ScenarioView:
    return sv.ScenarioView(
        scenario_type=scenario.scenario_type,
        configuration=scenario.canonical_configuration or {},
        parent_field_state_id=str(scenario.parent_field_state_id),
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        period_start=scenario.period_start,
        period_end=scenario.period_end,
    )


def validate_scenario(
    db: Session, scenario: dbm.Scenario, *, created_by: Any = None
) -> dict[str, Any]:
    """Run the pure validation engine and persist an immutable record.

    The verdict is about the DEFINITION's integrity only — never about
    execution or outcomes (nothing executes in M7.2).
    """
    _require_mutable(scenario, "validate")
    if scenario.scenario_status not in VALIDATE_ALLOWED_STATUSES:
        raise Conflict(
            f"Scenario in status '{scenario.scenario_status}' cannot be "
            "validated; edit it (PATCH) to return to draft first.",
            code="SCENARIO_INVALID_STATE_TRANSITION",
        )

    parent_state = db.get(dbm.FieldState, scenario.parent_field_state_id)
    parent_view = _parent_state_view(db, parent_state) if parent_state is not None else None
    requesting_org = ""
    if parent_state is not None:
        field = db.get(dbm.Field, parent_state.field_id)
        farm = db.get(dbm.Farm, field.farm_id) if field is not None else None
        requesting_org = str(farm.organization_id) if farm is not None else ""
    result = sv.validate_scenario(
        _scenario_view(scenario),
        parent_view,
        requesting_organization_id=requesting_org,
    )

    # Draft → validation_pending → result (documented transition path).
    _transition(scenario, sc.ScenarioStatus.VALIDATION_PENDING.value)
    lifecycle = sc.VALIDATION_RESULT_TO_LIFECYCLE.get(result.status, sc.ScenarioStatus.INVALID.value)
    _transition(scenario, lifecycle)

    document = result.to_document()
    document["configuration_checksum"] = scenario.configuration_checksum
    record = dbm.ScenarioValidationRecord(
        scenario_id=scenario.id,
        scenario_version=scenario.scenario_version,
        validation_rule_version=sc.SCENARIO_VALIDATION_RULES_VERSION,
        validation_status=result.status,
        validation_result=document,
        configuration_checksum=scenario.configuration_checksum,
        created_by=getattr(created_by, "id", None),
    )
    db.add(record)
    db.flush()
    scenario.validation_summary = {
        **document,
        "record_id": str(record.id),
        "validated_at": _iso(datetime.now(dt_timezone.utc)),
    }
    db.commit()
    db.refresh(scenario)
    return validation_payload(record, scenario)


def validation_payload(record: dbm.ScenarioValidationRecord, scenario: dbm.Scenario) -> dict[str, Any]:
    return {
        "scenario_id": str(scenario.id),
        "scenario_version": scenario.scenario_version,
        "scenario_status": scenario.scenario_status,
        "validation_rule_version": record.validation_rule_version,
        "validation_status": record.validation_status,
        "configuration_checksum": record.configuration_checksum,
        "validation_result": record.validation_result,
        "record_id": str(record.id),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "note": (
            "Validation assesses the scenario DEFINITION only. No simulation "
            "has been executed and no simulated output exists (M7.3 not "
            "implemented)."
        ),
    }


# ------------------------------------------------------------- finalize
def finalize_scenario(
    db: Session, scenario: dbm.Scenario, *, created_by: Any = None
) -> dbm.Scenario:
    _require_mutable(scenario, "finalize")
    if scenario.scenario_status not in (
        sc.ScenarioStatus.VALID.value,
        sc.ScenarioStatus.CONDITIONALLY_VALID.value,
    ):
        raise Conflict(
            "Only valid or conditionally_valid scenarios can be finalized "
            "(run validation first).",
            code="SCENARIO_INVALID_STATE_TRANSITION",
        )
    _transition(scenario, sc.ScenarioStatus.FINALIZED.value)
    scenario.finalized_at = datetime.now(dt_timezone.utc)
    db.commit()
    db.refresh(scenario)
    return scenario


def archive_scenario(db: Session, scenario: dbm.Scenario) -> dbm.Scenario:
    if scenario.scenario_status not in ARCHIVABLE_STATUSES:
        raise Conflict(
            f"Scenario in status '{scenario.scenario_status}' cannot be archived.",
            code="SCENARIO_INVALID_STATE_TRANSITION",
        )
    _transition(scenario, sc.ScenarioStatus.ARCHIVED.value)
    db.commit()
    db.refresh(scenario)
    return scenario


# ------------------------------------------------------------- versions / lineage
def create_scenario_version(
    db: Session,
    scenario: dbm.Scenario,
    payload: dict[str, Any],
    *,
    created_by: Any = None,
) -> dbm.Scenario:
    """Create a new VERSION of a finalized scenario (spec §7: a changed
    definition is a new version — the original row is never touched)."""
    if scenario.scenario_status != sc.ScenarioStatus.FINALIZED.value:
        raise Conflict(
            "Only finalized scenarios can be versioned; edit drafts directly "
            "with PATCH.",
            code="SCENARIO_INVALID_STATE_TRANSITION",
        )
    field = db.get(dbm.Field, scenario.field_id)
    new_type = payload.get("scenario_type") or scenario.scenario_type
    if new_type != scenario.scenario_type:
        raise ValidationFailed(
            "A new version keeps the scenario type; create a branch (POST "
            "/fields/{id}/scenarios with parent_scenario_id) for a different type.",
            details=[{"field": "scenario_type"}],
            code="SCENARIO_TYPE_MISMATCH",
        )
    configuration = payload.get("configuration")
    if configuration is None:
        configuration = scenario.canonical_configuration
    model, canonical_config = _build_configuration(scenario.scenario_type, configuration)
    config_dict = model.model_dump(mode="json")
    if str(model.parent_field_state_id) != str(scenario.parent_field_state_id):
        raise ValidationFailed(
            "A new version keeps the parent Field State of its predecessor.",
            details=[{"field": "configuration.parent_field_state_id"}],
            code="PARENT_STATE_MISMATCH",
        )
    checksum, _ = _checksum_for(
        scenario_type=scenario.scenario_type,
        canonical_configuration=canonical_config,
        parent_state=db.get(dbm.FieldState, scenario.parent_field_state_id),
        timezone=scenario.timezone,
    )
    if scenario_type_hypothetical(scenario.scenario_type):
        period = config_dict.get("period") or {}
        period_start = _as_utc(period.get("start"), "configuration.period.start")
        period_end = _as_utc(period.get("end"), "configuration.period.end")
    else:
        period_start, period_end = scenario.period_start, scenario.period_end

    version = dbm.Scenario(
        field_id=scenario.field_id,
        name=str(payload.get("name") or scenario.name)[: sc.SCENARIO_NAME_MAX],
        description=payload.get("description", scenario.description),
        scenario_type=scenario.scenario_type,
        scenario_status=sc.ScenarioStatus.DRAFT.value,
        lineage_kind=sc.LineageKind.REVISION.value,
        scenario_version=scenario.scenario_version + 1,
        parent_field_state_id=scenario.parent_field_state_id,
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        parent_scenario_id=scenario.id,
        configuration_schema_version=sc.SCENARIO_CONFIG_SCHEMA_VERSION,
        canonical_configuration=canonical_config,
        configuration_checksum=checksum,
        period_start=period_start,
        period_end=period_end,
        timezone=scenario.timezone,
        evidence_classification=scenario.evidence_classification,
        assumption_metadata=config_dict.get("assumption_metadata") or {},
        validation_summary={},
        created_by=getattr(created_by, "id", None),
        idempotency_key=payload.get("idempotency_key"),
    )
    # `field` is resolved to keep the tenancy chain explicit (same farm).
    assert field is not None and field.id == scenario.field_id
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def scenario_type_hypothetical(scenario_type: str) -> bool:
    return scenario_type in (
        sc.ScenarioType.HISTORICAL_PERTURBATION.value,
        sc.ScenarioType.USER_DEFINED_STRESS.value,
    )


def _version_chain(db: Session, scenario: dbm.Scenario) -> list[dbm.Scenario]:
    """All members of the revision chain containing `scenario` (ancestors +
    self + descendants), ordered by scenario_version."""
    root = scenario
    guard = 0
    while root.parent_scenario_id is not None and root.lineage_kind == sc.LineageKind.REVISION.value:
        parent = db.get(dbm.Scenario, root.parent_scenario_id)
        if parent is None or parent.lineage_kind != sc.LineageKind.REVISION.value:
            break
        root = parent
        guard += 1
        if guard > 1000:  # pragma: no cover — cycle guard
            break
    chain = [root]
    current = root
    guard = 0
    while True:
        child = db.scalar(
            select(dbm.Scenario)
            .where(
                dbm.Scenario.parent_scenario_id == current.id,
                dbm.Scenario.lineage_kind == sc.LineageKind.REVISION.value,
            )
            .order_by(dbm.Scenario.scenario_version.asc())
        )
        if child is None:
            break
        chain.append(child)
        current = child
        guard += 1
        if guard > 1000:  # pragma: no cover — cycle guard
            break
    return chain


def list_versions(db: Session, scenario: dbm.Scenario) -> dict[str, Any]:
    chain = _version_chain(db, scenario)
    return {
        "scenario_id": str(scenario.id),
        "chain_length": len(chain),
        "latest_version": max(s.scenario_version for s in chain),
        "items": [
            {
                "id": str(s.id),
                "scenario_version": s.scenario_version,
                "scenario_status": s.scenario_status,
                "configuration_checksum": s.configuration_checksum,
                "configuration_schema_version": s.configuration_schema_version,
                "name": s.name,
                "parent_scenario_id": str(s.parent_scenario_id) if s.parent_scenario_id else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "finalized_at": s.finalized_at.isoformat() if s.finalized_at else None,
            }
            for s in chain
        ],
    }


def get_lineage(db: Session, scenario: dbm.Scenario) -> dict[str, Any]:
    """Ancestors (any lineage kind) + direct children + revision chain."""
    ancestors: list[dict[str, Any]] = []
    current = scenario
    guard = 0
    while current.parent_scenario_id is not None and guard < 1000:
        parent = db.get(dbm.Scenario, current.parent_scenario_id)
        if parent is None:
            break
        ancestors.append(
            {
                "id": str(parent.id),
                "name": parent.name,
                "scenario_type": parent.scenario_type,
                "scenario_version": parent.scenario_version,
                "lineage_kind": parent.lineage_kind,
                "scenario_status": parent.scenario_status,
                "configuration_checksum": parent.configuration_checksum,
            }
        )
        current = parent
        guard += 1
    children = (
        db.execute(
            select(dbm.Scenario)
            .where(dbm.Scenario.parent_scenario_id == scenario.id)
            .order_by(dbm.Scenario.created_at.asc())
        )
        .scalars()
        .all()
    )
    chain = _version_chain(db, scenario)
    return {
        "scenario_id": str(scenario.id),
        "lineage_kind": scenario.lineage_kind,
        "scenario_version": scenario.scenario_version,
        "ancestors": ancestors,
        "children": [
            {
                "id": str(c.id),
                "name": c.name,
                "scenario_type": c.scenario_type,
                "scenario_version": c.scenario_version,
                "lineage_kind": c.lineage_kind,
                "scenario_status": c.scenario_status,
                "configuration_checksum": c.configuration_checksum,
            }
            for c in children
        ],
        "revision_chain_length": len(chain),
        "note": (
            "Revisions (new versions) and branches share one parent link, "
            "distinguished by lineage_kind; archived scenarios remain part "
            "of the lineage and stay checksum-verifiable."
        ),
    }


# ------------------------------------------------------------- comparison
def _diff_documents(
    left: Any, right: Any, path: str = ""
) -> list[dict[str, Any]]:
    """Structural diff of two canonical documents (leaf-level)."""
    diffs: list[dict[str, Any]] = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else key
            if key not in left:
                diffs.append({"path": child_path, "kind": "added", "left": None, "right": right[key]})
            elif key not in right:
                diffs.append({"path": child_path, "kind": "removed", "left": left[key], "right": None})
            else:
                diffs.extend(_diff_documents(left[key], right[key], child_path))
    elif isinstance(left, list) and isinstance(right, list):
        if left != right:
            diffs.append({"path": path or "$", "kind": "changed", "left": left, "right": right})
    elif left != right:
        diffs.append({"path": path or "$", "kind": "changed", "left": left, "right": right})
    return diffs


def compare_scenarios(
    db: Session, scenario: dbm.Scenario, against: dbm.Scenario
) -> dict[str, Any]:
    """Definition-level comparison ONLY (spec §10). No simulated outputs
    exist in M7.2, so none are compared — the response says so explicitly."""
    parent_a = db.get(dbm.FieldState, scenario.parent_field_state_id)
    parent_b = db.get(dbm.FieldState, against.parent_field_state_id)

    overlap = None
    if parent_a is not None and parent_b is not None:
        overlap = fsc.period_overlap_fraction(
            scenario.period_start, scenario.period_end, against.period_start, against.period_end
        )

    config_diff = _diff_documents(
        scenario.canonical_configuration or {}, against.canonical_configuration or {}
    )
    assumption_paths = [
        d["path"]
        for d in config_diff
        if d["path"].startswith("adjustments.") or d["path"].startswith("period")
    ]

    parents_compatible = (
        scenario.parent_field_state_id == against.parent_field_state_id
        and scenario.parent_snapshot_checksum == against.parent_snapshot_checksum
        and scenario.boundary_version == against.boundary_version
    )

    unavailable = {
        dim: entry
        for dim, entry in sc.SCENARIO_DIMENSION_AVAILABILITY.items()
    }

    return {
        "scenario_a": {
            "id": str(scenario.id),
            "name": scenario.name,
            "scenario_type": scenario.scenario_type,
            "evidence_classification": scenario.evidence_classification,
            "evidence_label": sc.evidence_label(scenario.evidence_classification),
            "scenario_version": scenario.scenario_version,
            "scenario_status": scenario.scenario_status,
            "configuration_checksum": scenario.configuration_checksum,
            "parent_field_state_id": str(scenario.parent_field_state_id),
            "parent_snapshot_checksum": scenario.parent_snapshot_checksum,
            "boundary_version": scenario.boundary_version,
            "period": {"start": _iso(scenario.period_start), "end": _iso(scenario.period_end)},
        },
        "scenario_b": {
            "id": str(against.id),
            "name": against.name,
            "scenario_type": against.scenario_type,
            "evidence_classification": against.evidence_classification,
            "evidence_label": sc.evidence_label(against.evidence_classification),
            "scenario_version": against.scenario_version,
            "scenario_status": against.scenario_status,
            "configuration_checksum": against.configuration_checksum,
            "parent_field_state_id": str(against.parent_field_state_id),
            "parent_snapshot_checksum": against.parent_snapshot_checksum,
            "boundary_version": against.boundary_version,
            "period": {"start": _iso(against.period_start), "end": _iso(against.period_end)},
        },
        "parents": {
            "same_field": scenario.field_id == against.field_id,
            "same_parent_state": scenario.parent_field_state_id == against.parent_field_state_id,
            "parent_checksums_equal": (
                scenario.parent_snapshot_checksum == against.parent_snapshot_checksum
            ),
            "boundary_versions": [scenario.boundary_version, against.boundary_version],
            "boundary_versions_equal": scenario.boundary_version == against.boundary_version,
        },
        "temporal_comparison": {
            "period_overlap_fraction": overlap,
            "compatible_periods": (overlap or 0.0) > 0.0,
        },
        "configuration_diff": config_diff,
        "changed_assumptions": assumption_paths,
        "identical_configuration": scenario.configuration_checksum == against.configuration_checksum,
        "evidence_classes_differ": (
            scenario.evidence_classification != against.evidence_classification
        ),
        "unavailable_dimensions": unavailable,
        "warnings": [
            *(
                [
                    "Scenarios reference DIFFERENT parent Field States — their "
                    "configurations are not grounded in the same baseline evidence."
                ]
                if scenario.parent_field_state_id != against.parent_field_state_id
                else []
            ),
            *(
                ["Scenarios pin different boundary versions — spatial references differ."]
                if scenario.boundary_version != against.boundary_version
                else []
            ),
            *(
                [
                    "Scenarios have different evidence classifications (observed vs "
                    "hypothetical vs not_available) — they are NOT equivalent evidence."
                ]
                if scenario.evidence_classification != against.evidence_classification
                else []
            ),
            *(
                ["The scenario periods do not overlap — differences are not temporally comparable."]
                if overlap is not None and overlap <= 0.0
                else []
            ),
        ],
        "compatibility": {
            "parents_compatible": parents_compatible,
            "note": (
                "Comparisons across incompatible parents or boundary versions "
                "carry an explicit warning and must not be read as a like-for-"
                "like contrast."
            ),
        },
        "note": (
            "Definition-level comparison only. No simulated environmental "
            "outputs exist in M7.2 (M7.3 not implemented), so none are "
            "compared and no score differences are fabricated."
        ),
    }


# ------------------------------------------------------------- verification
def verify_scenario(db: Session, scenario: dbm.Scenario) -> dict[str, Any]:
    """Independently re-verify the stored definition from its own content."""
    payload = sc.scenario_checksum_payload(
        scenario_type=scenario.scenario_type,
        configuration_schema_version=scenario.configuration_schema_version,
        canonical_configuration=scenario.canonical_configuration or {},
        parent_field_state_id=str(scenario.parent_field_state_id),
        parent_snapshot_checksum=scenario.parent_snapshot_checksum,
        boundary_version=scenario.boundary_version,
        timezone=scenario.timezone,
    )
    recomputed = sc.compute_scenario_checksum(payload)
    checksum_valid = scenario.configuration_checksum == recomputed

    parent_state = db.get(dbm.FieldState, scenario.parent_field_state_id)
    parent_intact = (
        parent_state is not None
        and parent_state.status == "succeeded"
        and parent_state.checksum_sha256 == scenario.parent_snapshot_checksum
    )
    boundary_row = None
    if parent_state is not None:
        boundary_row = db.scalar(
            select(dbm.FieldBoundaryVersion.id).where(
                dbm.FieldBoundaryVersion.field_id == parent_state.field_id,
                dbm.FieldBoundaryVersion.version_number == scenario.boundary_version,
            )
        )
    latest_record = db.scalar(
        select(dbm.ScenarioValidationRecord)
        .where(dbm.ScenarioValidationRecord.scenario_id == scenario.id)
        .order_by(dbm.ScenarioValidationRecord.created_at.desc())
        .limit(1)
    )
    return {
        "scenario_id": str(scenario.id),
        "configuration_checksum_valid": checksum_valid,
        "expected_checksum": recomputed,
        "stored_checksum": scenario.configuration_checksum,
        "parent_state_exists": parent_state is not None,
        "parent_snapshot_checksum_matches": parent_intact,
        "boundary_version_record_exists": boundary_row is not None,
        "latest_validation": (
            {
                "record_id": str(latest_record.id),
                "validation_status": latest_record.validation_status,
                "configuration_checksum": latest_record.configuration_checksum,
                "matches_current_configuration": (
                    latest_record.configuration_checksum == scenario.configuration_checksum
                ),
            }
            if latest_record is not None
            else None
        ),
        "verified_at": _iso(datetime.now(dt_timezone.utc)),
        "note": (
            "Verification recomputes the definition checksum from stored "
            "content and re-checks the parent reference. It says nothing "
            "about simulation outcomes (none exist in M7.2)."
        ),
    }


# ------------------------------------------------------------- serializer
def scenario_payload(
    scenario: dbm.Scenario,
    *,
    db: Session | None = None,
    include_validation_history: bool = False,
) -> dict[str, Any]:
    capability = sc.SCENARIO_TYPE_CAPABILITIES.get(scenario.scenario_type)
    payload: dict[str, Any] = {
        "id": str(scenario.id),
        "field_id": str(scenario.field_id),
        "name": scenario.name,
        "description": scenario.description,
        "scenario_type": scenario.scenario_type,
        "scenario_type_display": capability.display_name if capability else scenario.scenario_type,
        "scenario_status": scenario.scenario_status,
        "lineage_kind": scenario.lineage_kind,
        "scenario_version": scenario.scenario_version,
        "parent_scenario_id": str(scenario.parent_scenario_id) if scenario.parent_scenario_id else None,
        "parent_field_state_id": str(scenario.parent_field_state_id),
        "parent_snapshot_checksum": scenario.parent_snapshot_checksum,
        "boundary_version": scenario.boundary_version,
        "configuration_schema_version": scenario.configuration_schema_version,
        "canonical_configuration": scenario.canonical_configuration,
        "configuration_checksum": scenario.configuration_checksum,
        "period": {"start": _iso(scenario.period_start), "end": _iso(scenario.period_end)},
        "timezone": scenario.timezone,
        "evidence_classification": scenario.evidence_classification,
        "evidence_label": sc.evidence_label(scenario.evidence_classification),
        "assumption_metadata": scenario.assumption_metadata,
        "validation_summary": scenario.validation_summary,
        "unavailable_dimensions": {k: dict(v) for k, v in sc.SCENARIO_DIMENSION_AVAILABILITY.items()},
        "created_by": str(scenario.created_by) if scenario.created_by else None,
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
        "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
        "finalized_at": scenario.finalized_at.isoformat() if scenario.finalized_at else None,
        "verify_url": f"/api/v1/scenarios/{scenario.id}/verify",
        "versions_url": f"/api/v1/scenarios/{scenario.id}/versions",
        "lineage_url": f"/api/v1/scenarios/{scenario.id}/lineage",
        "note": (
            "Scenario definition only — no simulation has been executed and "
            "no simulated output exists (M7.3 not implemented)."
        ),
    }
    if db is not None and include_validation_history:
        records = (
            db.execute(
                select(dbm.ScenarioValidationRecord)
                .where(dbm.ScenarioValidationRecord.scenario_id == scenario.id)
                .order_by(dbm.ScenarioValidationRecord.created_at.desc())
            )
            .scalars()
            .all()
        )
        payload["validation_history"] = [
            {
                "record_id": str(r.id),
                "validation_rule_version": r.validation_rule_version,
                "validation_status": r.validation_status,
                "configuration_checksum": r.configuration_checksum,
                "validation_result": r.validation_result,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    return payload


def taxonomy_payload() -> dict[str, Any]:
    return {
        "taxonomy_version": sc.SCENARIO_TAXONOMY_VERSION,
        "configuration_schema_version": sc.SCENARIO_CONFIG_SCHEMA_VERSION,
        "validation_rules_version": sc.SCENARIO_VALIDATION_RULES_VERSION,
        "types": [
            json_cap
            for json_cap in (
                {
                    "scenario_type": cap.scenario_type.value,
                    "display_name": cap.display_name,
                    "capability": cap.capability.value,
                    "evidence_classification": cap.evidence_classification.value,
                    "evidence_label": sc.evidence_label(cap.evidence_classification.value),
                    "description": cap.description,
                    "unavailable_reason": cap.unavailable_reason,
                }
                for cap in sc.SCENARIO_TYPE_CAPABILITIES.values()
            )
        ],
        "dimensions": {k: dict(v) for k, v in sc.SCENARIO_DIMENSION_AVAILABILITY.items()},
        "adjustment_bounds": {
            "temperature_delta_c": [sc.TEMPERATURE_DELTA_C_MIN, sc.TEMPERATURE_DELTA_C_MAX],
            "precipitation_multiplier": [sc.PRECIPITATION_MULTIPLIER_MIN, sc.PRECIPITATION_MULTIPLIER_MAX],
            "precipitation_delta_mm": [sc.PRECIPITATION_DELTA_MM_MIN, sc.PRECIPITATION_DELTA_MM_MAX],
            "water_allocation_multiplier": [
                sc.WATER_ALLOCATION_MULTIPLIER_MIN,
                sc.WATER_ALLOCATION_MULTIPLIER_MAX,
            ],
            "seasonal_timing_shift_days": [sc.SEASONAL_TIMING_SHIFT_DAYS_MIN, sc.SEASONAL_TIMING_SHIFT_DAYS_MAX],
            "rainfall_period_shift_days": [sc.RAINFALL_PERIOD_SHIFT_DAYS_MIN, sc.RAINFALL_PERIOD_SHIFT_DAYS_MAX],
        },
        "lifecycle": {
            "statuses": [s.value for s in sc.ScenarioStatus],
            "legal_transitions": {k: sorted(v) for k, v in sc.LEGAL_TRANSITIONS.items()},
        },
        "note": (
            "Climate projection and weather forecast types are contract "
            "placeholders; creation requests are rejected. Soil and "
            "management scenario dimensions remain unavailable: M6B/M6C are "
            "integrated as data domains, but soil-/management-driven "
            "scenario transformations are not part of the M7.3 execution "
            "engine."
        ),
    }


def capabilities_payload() -> dict[str, Any]:
    return {
        "taxonomy_version": sc.SCENARIO_TAXONOMY_VERSION,
        "capabilities": [
            {
                "scenario_type": cap.scenario_type.value,
                "capability": cap.capability.value,
                "evidence_classification": cap.evidence_classification.value,
                "unavailable_reason": cap.unavailable_reason,
            }
            for cap in sc.SCENARIO_TYPE_CAPABILITIES.values()
        ],
        "dimensions": {k: dict(v) for k, v in sc.SCENARIO_DIMENSION_AVAILABILITY.items()},
        "execution": {
            "scenario_execution": "implemented",
            "reason": (
                "M7.3 scenario execution is implemented for environmental "
                "parameters (temperature deltas, precipitation multipliers/"
                "deltas, timing shifts) over immutable field states; derived "
                "observations and features are stored with lineage and "
                "checksums. Soil and management scenario dimensions are not "
                "part of the execution engine and are never simulated."
            ),
        },
        "digital_twin_level": "Level 1 — Historical Digital Profile (not predictive)",
        "note": (
            "Unavailable capabilities are reported honestly and never "
            "simulated with synthetic substitutes."
        ),
    }


# ---------------------------------------------------------------------------
# P3 entitlement enforcement (Task 3) — scenario-run quota
# ---------------------------------------------------------------------------
# The scenario RUN (execution) is created by
# app/scenario_execution/service.start_scenario_execution; these helpers keep
# the entitlement policy in one place. CONSTRAINT (Task 3): gates apply ONLY
# when the acting principal's organization context has a live subscription —
# users/flows without an organization (legacy personal accounts, P1/P2
# golden cases, seed/demo users) pass through untouched so existing behavior
# is 100% preserved.

def quota_organization_for_run(
    db: Session,
    scenario: dbm.Scenario,
    created_by: Any,
) -> uuid_mod.UUID | None:
    """The organization context a scenario run is billed against, or None.

    It is the scenario's farm organization, and it only counts when the
    acting user is an ACTIVE member of it (API tenant scoping guarantees
    this; background/system runs with `created_by=None` are never gated).
    """
    if created_by is None:
        return None
    field = db.get(dbm.Field, scenario.field_id)
    if field is None:
        return None
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:
        return None
    membership = db.scalar(
        select(dbm.Membership).where(
            dbm.Membership.organization_id == farm.organization_id,
            dbm.Membership.user_id == created_by.id,
            dbm.Membership.status == "active",
        )
    )
    return farm.organization_id if membership is not None else None


def enforce_scenario_run_quota(
    db: Session,
    scenario: dbm.Scenario,
    created_by: Any,
) -> uuid_mod.UUID | None:
    """Raise PaymentRequired when the acting organization's plan quota for
    scenario runs is exhausted. Returns the gated organization id (callers
    increment the usage counter against it after persisting a NEW run), or
    None when no gate applies (no acting user, no org context, or the
    organization has no live subscription)."""
    from app.billing import entitlements

    org_id = quota_organization_for_run(db, scenario, created_by)
    if org_id is None:
        return None
    # P3 gate: only organizations WITH a live subscription are metered.
    if entitlements.get_live_subscription(db, org_id) is None:
        return None
    entitlements.check_quota(db, org_id, entitlements.KEY_SCENARIO_RUNS_PER_MONTH)
    return org_id
