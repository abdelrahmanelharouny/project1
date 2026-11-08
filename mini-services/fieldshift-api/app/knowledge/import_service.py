"""Knowledge pack import & validation workflow (Milestone 5, ADR-0014).

Import is all-or-nothing: the pack schema is validated (Pydantic), cross
references are checked (contracts.validate_pack_cross_references), and only a
fully valid pack is persisted with its checksum. Re-importing the identical
(pack_code, pack_version) is idempotent — the same checksum returns the
existing pack; a different checksum for the same version is a conflict error.
"""

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.db import models as dbm
from app.knowledge.contracts import (
    KnowledgePackIn,
    PackValidationReport,
    pack_checksum,
    validate_pack_cross_references,
)


def parse_pack(payload: dict[str, Any]) -> tuple[KnowledgePackIn, PackValidationReport]:
    """Parse + cross-validate; raises ValidationFailed with all findings."""
    try:
        pack = KnowledgePackIn.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
            for e in exc.errors()
        ]
        raise ValidationFailed(
            "Knowledge pack failed schema validation.",
            details=[{"field": "pack", "reason": err} for err in errors[:50]],
        ) from None

    report = validate_pack_cross_references(pack)
    if not report.ok:
        raise ValidationFailed(
            "Knowledge pack failed cross-reference validation.",
            details=[{"field": "pack", "reason": err} for err in report.errors[:50]],
        )
    return pack, report


def import_pack(
    db: Session,
    payload: dict[str, Any],
    *,
    activate: bool = False,
    imported_by: uuid.UUID | None = None,
) -> tuple[dbm.KnowledgePack, PackValidationReport, bool]:
    """Import (or idempotently return) a pack. Returns (pack, report, created).

    `activate` marks the pack `active`; imports default to `draft` — going
    live is an explicit step (POST /knowledge/packs/{id}/activate).
    """
    pack_in, report = parse_pack(payload)
    checksum = pack_checksum(pack_in)

    existing = db.scalar(
        select(dbm.KnowledgePack).where(
            dbm.KnowledgePack.pack_code == pack_in.pack_code,
            dbm.KnowledgePack.pack_version == pack_in.pack_version,
        )
    )
    if existing is not None:
        if existing.checksum_sha256 != checksum:
            raise ValidationFailed(
                "A different pack with the same code+version already exists "
                "(checksum mismatch). Publish it under a new version.",
                details=[{
                    "field": "pack_version",
                    "reason": f"{pack_in.pack_code}@{pack_in.pack_version}",
                }],
            )
        if activate and existing.status == "draft":
            existing.status = "active"
            db.flush()
        return existing, report, False

    pack_row = dbm.KnowledgePack(
        pack_code=pack_in.pack_code,
        pack_version=pack_in.pack_version,
        name=pack_in.name,
        description=pack_in.description,
        region_scope=pack_in.region_scope,
        license_name=pack_in.license_name,
        attribution_text=pack_in.attribution_text,
        license_notes=pack_in.license_notes,
        digitization_note=pack_in.digitization_note,
        status="active" if activate else "draft",
        checksum_sha256=checksum,
        content=payload,
        imported_by=imported_by,
    )
    db.add(pack_row)
    db.flush()

    source_rows: dict[str, dbm.KnowledgeSource] = {}
    for s in pack_in.sources:
        row = dbm.KnowledgeSource(
            pack_id=pack_row.id,
            source_key=s.source_key,
            publisher=s.publisher,
            title=s.title,
            url=s.url,
            publication_year=s.publication_year,
            license=s.license,
            citation_text=s.citation_text,
        )
        db.add(row)
        source_rows[s.source_key] = row
    db.flush()

    family_rows: dict[str, dbm.CropFamily] = {}
    for f in pack_in.families:
        row = dbm.CropFamily(
            pack_id=pack_row.id,
            family_key=f.family_key,
            scientific_name=f.scientific_name,
            common_names=f.common_names,
        )
        db.add(row)
        family_rows[f.family_key] = row
    db.flush()

    crop_rows: dict[str, dbm.Crop] = {}
    for c in pack_in.crops:
        row = dbm.Crop(
            pack_id=pack_row.id,
            crop_code=c.crop_code,
            family_id=family_rows[c.family_key].id if c.family_key else None,
            scientific_name=c.scientific_name,
            common_names=c.common_names,
            crop_category=c.crop_category,
            life_cycle_type=c.life_cycle_type,
            is_legume=c.is_legume,
            is_cover_crop_capable=c.is_cover_crop_capable,
            status=c.status,
        )
        db.add(row)
        crop_rows[c.crop_code] = row
    db.flush()

    for c in pack_in.crops:
        crop_row = crop_rows[c.crop_code]
        for t in c.traits:
            db.add(
                dbm.CropTrait(
                    pack_id=pack_row.id,
                    crop_id=crop_row.id,
                    trait_code=t.trait_code,
                    value_numeric=t.value_numeric,
                    value_text=t.value_text,
                    value_low=t.value_low,
                    value_high=t.value_high,
                    unit=t.unit,
                    region_code=t.region_code,
                    management_context=t.management_context,
                    growth_stage=t.growth_stage,
                    conditions=t.conditions,
                    source_id=source_rows[t.source_key].id,
                    evidence_class=t.evidence_class,
                    confidence=t.confidence,
                    validation_status=t.validation_status,
                    notes=t.notes,
                )
            )
        for w in c.calendar_windows:
            db.add(
                dbm.CropCalendarWindow(
                    pack_id=pack_row.id,
                    crop_id=crop_row.id,
                    region_code=w.region_code,
                    hemisphere=w.hemisphere,
                    season_code=w.season_code,
                    planting_start=w.planting_start,
                    planting_end=w.planting_end,
                    harvest_start=w.harvest_start,
                    harvest_end=w.harvest_end,
                    source_id=source_rows[w.source_key].id,
                    evidence_class=w.evidence_class,
                    validation_status=w.validation_status,
                    notes=w.notes,
                )
            )
        for wp in c.water_parameters:
            db.add(
                dbm.CropWaterParameter(
                    pack_id=pack_row.id,
                    crop_id=crop_row.id,
                    growth_stage=wp.growth_stage,
                    kc_value=wp.kc_value,
                    kc_method=wp.kc_method,
                    stage_length_days=wp.stage_length_days,
                    valid_region=wp.valid_region,
                    climate_context=wp.climate_context,
                    source_id=source_rows[wp.source_key].id,
                    evidence_class=wp.evidence_class,
                    validation_status=wp.validation_status,
                    notes=wp.notes,
                )
            )

    for r in pack_in.rotation_rules:
        db.add(
            dbm.RotationRule(
                pack_id=pack_row.id,
                rule_code=r.rule_code,
                rule_type=r.rule_type,
                rule_definition=r.rule_definition,
                applies_to_regions=r.applies_to_regions,
                source_id=source_rows[r.source_key].id,
                validation_status=r.validation_status,
                severity=r.severity,
            )
        )

    # --- M6C: management practices & operation templates ---------------------
    # Same semantics as crops/sources above: rows belong to the imported pack
    # row; re-importing the identical (pack_code, pack_version) is idempotent
    # (returned above via the checksum match, so rows are never duplicated),
    # and superseding an old pack VERSION retires the old pack row wholesale —
    # never a per-row rewrite.
    for p in pack_in.practices:
        db.add(
            dbm.PracticeDefinition(
                pack_id=pack_row.id,
                practice_code=p.practice_code,
                practice_family=p.practice_family,
                name=p.name,
                description=p.description,
                payload={
                    "mechanisms": [m.model_dump() for m in p.mechanisms],
                    "requirements": [q.model_dump() for q in p.requirements],
                    "trade_offs": [t.model_dump() for t in p.trade_offs],
                    "risks": [rk.model_dump() for rk in p.risks],
                    "regional_applicability": [
                        ra.model_dump() for ra in p.regional_applicability
                    ],
                },
                validation_status=p.validation_status,
                status="active",
            )
        )

    for t in pack_in.operation_templates:
        payload: dict[str, Any] = {
            "applies_to_crop_codes": t.applies_to_crop_codes,
            "applies_to_crop_categories": t.applies_to_crop_categories,
            "typical_predecessors": [
                pred.model_dump() for pred in t.typical_predecessors
            ],
            "restriction_kinds": t.restriction_kinds,
        }
        if t.notes is not None:
            payload["notes"] = t.notes
        db.add(
            dbm.OperationTemplate(
                pack_id=pack_row.id,
                template_code=t.template_code,
                operation_type=t.operation_type,
                name=t.name,
                description=t.description,
                payload=payload,
                validation_status=t.validation_status,
                status="active",
            )
        )

    db.flush()
    return pack_row, report, True


def seed_default_packs(db: Session) -> None:
    """Idempotent bootstrap of the bundled knowledge packs (active).

    When a bundled pack's version changes (M6A: 2026.11.0 → 2026.11.1), the
    superseded version of the same pack_code is RETIRED — a lifecycle
    transition (draft → active → retired), not a history rewrite: the old row
    keeps its content and checksum. Without this, two active versions of the
    same rules would load twice into the decision core. M6C adds the bundled
    management-practice pack under the same semantics.
    """
    from app.knowledge.packs.m6c_practices_pack import get_m6c_practices_pack
    from app.knowledge.packs.seed_pack_v1 import get_seed_pack

    # Serialize concurrent seeders (app lifespan vs. any lazy re-bootstrap):
    # interleaved multi-row pack INSERTs can deadlock on Postgres. The
    # advisory xact lock releases with the session's transaction; latecomers
    # then find the pack rows already present and skip (idempotent).
    from sqlalchemy import text

    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('fieldshift:seed:knowledge_packs'))"))

    for get_pack in (get_seed_pack, get_m6c_practices_pack):
        pack, _report, _created = import_pack(db, get_pack(), activate=True)
        superseded = db.scalars(
            select(dbm.KnowledgePack).where(
                dbm.KnowledgePack.pack_code == pack.pack_code,
                dbm.KnowledgePack.pack_version != pack.pack_version,
                dbm.KnowledgePack.status != "retired",
            )
        ).all()
        for old in superseded:
            old.status = "retired"
        if superseded:
            db.flush()
