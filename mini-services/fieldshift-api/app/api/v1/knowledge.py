"""Knowledge base endpoints (Milestone 5): packs, sources, crops, traits,
calendar windows, water parameters, rotation rules + pack import workflow.

Knowledge is platform-level: read endpoints require authentication but are
NOT tenant-scoped. Import/activation are authenticated writes with audit
events (the curation workflow's first slice).
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_principal
from app.knowledge.import_service import import_pack, pack_checksum
from app.knowledge.contracts import KnowledgePackIn
from app.management.practices import (
    active_operation_templates,
    active_practices,
    practice_evidence_coverage,
)

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/packs")
def list_packs(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    packs = db.scalars(
        select(dbm.KnowledgePack).order_by(
            dbm.KnowledgePack.pack_code, dbm.KnowledgePack.pack_version
        )
    ).all()
    items = []
    for p in packs:
        n_crops = db.scalar(
            select(dbm.func.count()).select_from(dbm.Crop).where(dbm.Crop.pack_id == p.id)
        )
        n_traits = db.scalar(
            select(dbm.func.count()).select_from(dbm.CropTrait).where(dbm.CropTrait.pack_id == p.id)
        )
        n_rules = db.scalar(
            select(dbm.func.count())
            .select_from(dbm.RotationRule)
            .where(dbm.RotationRule.pack_id == p.id)
        )
        n_sources = db.scalar(
            select(dbm.func.count())
            .select_from(dbm.KnowledgeSource)
            .where(dbm.KnowledgeSource.pack_id == p.id)
        )
        n_practices = db.scalar(
            select(dbm.func.count())
            .select_from(dbm.PracticeDefinition)
            .where(dbm.PracticeDefinition.pack_id == p.id)
        )
        n_operation_templates = db.scalar(
            select(dbm.func.count())
            .select_from(dbm.OperationTemplate)
            .where(dbm.OperationTemplate.pack_id == p.id)
        )
        items.append(
            {
                "id": str(p.id),
                "pack_code": p.pack_code,
                "pack_version": p.pack_version,
                "name": p.name,
                "description": p.description,
                "region_scope": p.region_scope,
                "status": p.status,
                "license_name": p.license_name,
                "attribution_text": p.attribution_text,
                "license_notes": p.license_notes,
                "digitization_note": p.digitization_note,
                "checksum_sha256": p.checksum_sha256,
                "imported_at": p.imported_at.isoformat() if p.imported_at else None,
                "counts": {
                    "crops": int(n_crops or 0),
                    "traits": int(n_traits or 0),
                    "rotation_rules": int(n_rules or 0),
                    "sources": int(n_sources or 0),
                    "practices": int(n_practices or 0),
                    "operation_templates": int(n_operation_templates or 0),
                },
            }
        )
    return {"packs": items, "total": len(items)}


@router.get("/knowledge/packs/{pack_id}/sources")
def list_pack_sources(
    pack_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    pack = db.get(dbm.KnowledgePack, pack_id)
    if pack is None:
        raise NotFound("Knowledge pack not found.")
    sources = db.scalars(
        select(dbm.KnowledgeSource)
        .where(dbm.KnowledgeSource.pack_id == pack_id)
        .order_by(dbm.KnowledgeSource.source_key)
    ).all()
    return {
        "pack": {"id": str(pack.id), "pack_code": pack.pack_code, "pack_version": pack.pack_version},
        "sources": [
            {
                "source_key": s.source_key,
                "publisher": s.publisher,
                "title": s.title,
                "url": s.url,
                "publication_year": s.publication_year,
                "license": s.license,
                "citation_text": s.citation_text,
            }
            for s in sources
        ],
    }


@router.get("/knowledge/crops")
def list_crops(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """All crops from ACTIVE packs, with family + trait summary (per-crop trait
    counts by source) — the knowledge browser view."""
    crops = db.scalars(
        select(dbm.Crop)
        .options()
        .where(dbm.Crop.status == "active")
        .order_by(dbm.Crop.crop_code)
    ).all()
    active_pack_ids = {str(p.id) for p in db.scalars(
        select(dbm.KnowledgePack).where(dbm.KnowledgePack.status == "active")
    ).all()}
    families = {
        f.id: f for f in db.scalars(select(dbm.CropFamily)).all()
    }
    # Deepening F-9: when the same crop_code exists in several ACTIVE packs,
    # the read model must resolve deterministically like load_knowledge does
    # (latest (pack_version, pack_code) wins) — not on arbitrary row order.
    pack_meta = {
        p.id: (p.pack_code, p.pack_version)
        for p in db.scalars(select(dbm.KnowledgePack)).all()
    }
    by_code: dict[str, tuple[tuple[str, str], Any]] = {}
    for c in crops:
        if str(c.pack_id) not in active_pack_ids:
            continue
        meta = pack_meta.get(c.pack_id, ("", ""))
        key = (meta[1], meta[0])
        if c.crop_code not in by_code or key > by_code[c.crop_code][0]:
            by_code[c.crop_code] = (key, c)
    items = []
    for crop_code in sorted(by_code):
        c = by_code[crop_code][1]
        trait_rows = db.scalars(
            select(dbm.CropTrait).where(dbm.CropTrait.crop_id == c.id)
        ).all()
        trait_codes = sorted({t.trait_code for t in trait_rows})
        windows = db.scalars(
            select(dbm.CropCalendarWindow).where(dbm.CropCalendarWindow.crop_id == c.id)
        ).all()
        water = db.scalars(
            select(dbm.CropWaterParameter).where(dbm.CropWaterParameter.crop_id == c.id)
        ).all()
        family = families.get(c.family_id) if c.family_id else None
        items.append(
            {
                "id": str(c.id),
                "crop_code": c.crop_code,
                "scientific_name": c.scientific_name,
                "common_names": c.common_names,
                "family_key": family.family_key if family else None,
                "family_scientific_name": family.scientific_name if family else None,
                "crop_category": c.crop_category,
                "life_cycle_type": c.life_cycle_type,
                "is_legume": c.is_legume,
                "is_cover_crop_capable": c.is_cover_crop_capable,
                "trait_codes": trait_codes,
                "has_kc_parameters": len(water) > 0,
                "calendar_windows": [
                    {
                        "region_code": w.region_code,
                        "hemisphere": w.hemisphere,
                        "planting_start": w.planting_start,
                        "planting_end": w.planting_end,
                        "harvest_start": w.harvest_start,
                        "harvest_end": w.harvest_end,
                        "evidence_class": w.evidence_class,
                        "validation_status": w.validation_status,
                        "notes": w.notes,
                    }
                    for w in windows
                ],
            }
        )
    return {"crops": items, "total": len(items)}


@router.get("/knowledge/crops/{crop_code}")
def crop_detail(
    crop_code: str,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # Deepening F-9: resolve through ACTIVE packs with the same deterministic
    # latest-version-wins rule as load_knowledge; an unfiltered first-row pick
    # could return a retired pack's row or depend on arbitrary DB order.
    crop = db.scalar(
        select(dbm.Crop)
        .join(dbm.KnowledgePack, dbm.Crop.pack_id == dbm.KnowledgePack.id)
        .where(
            dbm.Crop.crop_code == crop_code,
            dbm.Crop.status == "active",
            dbm.KnowledgePack.status == "active",
        )
        .order_by(
            dbm.KnowledgePack.pack_version.desc(),
            dbm.KnowledgePack.pack_code.desc(),
        )
        .limit(1)
    )
    if crop is None:
        raise NotFound("Crop not found in the knowledge base.")
    pack = db.get(dbm.KnowledgePack, crop.pack_id)
    traits = db.scalars(
        select(dbm.CropTrait)
        .options()
        .where(dbm.CropTrait.crop_id == crop.id)
        .order_by(dbm.CropTrait.trait_code)
    ).all()
    source_ids = {t.source_id for t in traits}
    sources = {
        s.id: s
        for s in db.scalars(
            select(dbm.KnowledgeSource).where(dbm.KnowledgeSource.id.in_(source_ids))
        ).all()
    }
    windows = db.scalars(
        select(dbm.CropCalendarWindow).where(dbm.CropCalendarWindow.crop_id == crop.id)
    ).all()
    water = db.scalars(
        select(dbm.CropWaterParameter).where(dbm.CropWaterParameter.crop_id == crop.id)
    ).all()
    water_sources = {
        s.id: s
        for s in db.scalars(
            select(dbm.KnowledgeSource).where(
                dbm.KnowledgeSource.id.in_({w.source_id for w in water} or {uuid.uuid4()})
            )
        ).all()
    }

    def trait_payload(t: dbm.CropTrait) -> dict[str, Any]:
        src = sources.get(t.source_id)
        return {
            "trait_code": t.trait_code,
            "value_numeric": t.value_numeric,
            "value_text": t.value_text,
            "value_low": t.value_low,
            "value_high": t.value_high,
            "unit": t.unit,
            "region_code": t.region_code,
            "evidence_class": t.evidence_class,
            "confidence": t.confidence,
            "validation_status": t.validation_status,
            "notes": t.notes,
            "source": {
                "source_key": src.source_key if src else None,
                "citation_text": src.citation_text if src else None,
                "publisher": src.publisher if src else None,
                "url": src.url if src else None,
            },
        }

    return {
        "crop_code": crop.crop_code,
        "scientific_name": crop.scientific_name,
        "common_names": crop.common_names,
        "crop_category": crop.crop_category,
        "life_cycle_type": crop.life_cycle_type,
        "is_legume": crop.is_legume,
        "is_cover_crop_capable": crop.is_cover_crop_capable,
        "pack": {
            "pack_code": pack.pack_code if pack else None,
            "pack_version": pack.pack_version if pack else None,
            "status": pack.status if pack else None,
            "license_name": pack.license_name if pack else None,
            "attribution_text": pack.attribution_text if pack else None,
            "digitization_note": pack.digitization_note if pack else None,
        },
        "traits": [trait_payload(t) for t in traits],
        "calendar_windows": [
            {
                "region_code": w.region_code,
                "hemisphere": w.hemisphere,
                "season_code": w.season_code,
                "planting_start": w.planting_start,
                "planting_end": w.planting_end,
                "harvest_start": w.harvest_start,
                "harvest_end": w.harvest_end,
                "evidence_class": w.evidence_class,
                "validation_status": w.validation_status,
                "notes": w.notes,
            }
            for w in windows
        ],
        "water_parameters": [
            {
                "growth_stage": w.growth_stage,
                "kc_value": w.kc_value,
                "kc_method": w.kc_method,
                "evidence_class": w.evidence_class,
                "validation_status": w.validation_status,
                "notes": w.notes,
                "source": {
                    "source_key": (water_sources.get(w.source_id).source_key
                                   if w.source_id in water_sources else None),
                    "citation_text": (water_sources.get(w.source_id).citation_text
                                      if w.source_id in water_sources else None),
                },
            }
            for w in water
        ],
    }


@router.get("/knowledge/rotation-rules")
def list_rotation_rules(
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    rules = db.scalars(
        select(dbm.RotationRule).order_by(dbm.RotationRule.rule_code)
    ).all()
    active_pack_ids = {str(p.id) for p in db.scalars(
        select(dbm.KnowledgePack).where(dbm.KnowledgePack.status == "active")
    ).all()}
    source_ids = {r.source_id for r in rules}
    sources = {
        s.id: s
        for s in db.scalars(
            select(dbm.KnowledgeSource).where(dbm.KnowledgeSource.id.in_(source_ids or {uuid.uuid4()}))
        ).all()
    }
    items = []
    for r in rules:
        if str(r.pack_id) not in active_pack_ids:
            continue
        src = sources.get(r.source_id)
        d = r.rule_definition or {}
        items.append(
            {
                "rule_code": r.rule_code,
                "rule_type": r.rule_type,
                "predecessor": d.get("predecessor"),
                "successor": d.get("successor"),
                "target": d.get("target"),
                "min_break_seasons": d.get("min_break_seasons", 0),
                "mechanism": d.get("mechanism"),
                "scope_note": d.get("scope_note"),
                "applies_to_regions": r.applies_to_regions,
                "validation_status": r.validation_status,
                "severity": r.severity,
                "hard_enforceable": r.validation_status == "confirmed_regional",
                "source": {
                    "source_key": src.source_key if src else None,
                    "citation_text": src.citation_text if src else None,
                },
            }
        )
    confirmed = sum(1 for i in items if i["hard_enforceable"])
    return {
        "rules": items,
        "total": len(items),
        "confirmed_regional_count": confirmed,
        "note": "Only confirmed_regional rules are enforced as hard constraints; "
        "reference rules inform explanations and require local validation.",
    }


def _template_evidence_coverage(template: dict[str, Any]) -> dict[str, Any]:
    """Transparency coverage for an operation template: how many sequencing
    claims carry a resolved citation (same convention as practices — coverage,
    never confidence)."""
    predecessors = template.get("payload", {}).get("typical_predecessors", [])
    return {
        "claim_counts": {"typical_predecessors": len(predecessors)},
        "claims_cited": {
            "typical_predecessors": sum(1 for c in predecessors if c.get("citation"))
        },
    }


@router.get("/knowledge/practices")
def list_practices(
    family: str | None = Query(default=None, max_length=40),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Management practice definitions from ACTIVE packs (M6C): every claim in
    the payload carries its resolved citation, plus the evidence-coverage
    transparency metric. Practices from draft packs are inert."""
    practices = active_practices(db)
    if family:
        practices = [p for p in practices if p["practice_family"] == family]
    for practice in practices:
        practice["evidence_coverage"] = practice_evidence_coverage(practice)
    return {"practices": practices, "total": len(practices)}


@router.get("/knowledge/operation-templates")
def list_operation_templates(
    operation_type: str | None = Query(default=None, max_length=60),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Operation templates from ACTIVE packs (M6C) with resolved citations on
    their typical-predecessor sequencing claims."""
    templates = active_operation_templates(db)
    if operation_type:
        templates = [t for t in templates if t["operation_type"] == operation_type]
    for template in templates:
        template["evidence_coverage"] = _template_evidence_coverage(template)
    return {"operation_templates": templates, "total": len(templates)}


class PackImportRequest(BaseModel):
    pack: dict[str, Any] = Field(description="Knowledge pack document (JSON).")
    activate: bool = False


@router.post("/knowledge/packs/import", status_code=status.HTTP_201_CREATED)
def import_knowledge_pack(
    body: PackImportRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> JSONResponse:
    # RBAC (P0-2): knowledge packs are platform-level (no farm scope), so the
    # gate is org-level — manager+ in at least one of the principal's orgs.
    principal.require_any_org_role("manager")
    pack_row, report, created = import_pack(
        db,
        body.pack,
        activate=body.activate,
        imported_by=principal.id,
    )
    db.add(
        dbm.AuditEvent(
            actor_id=principal.id,
            entity_type="knowledge_pack",
            entity_id=str(pack_row.id),
            action="imported" if created else "reimported",
            after_snapshot={
                "pack_code": pack_row.pack_code,
                "pack_version": pack_row.pack_version,
                "checksum": pack_row.checksum_sha256,
                "status": pack_row.status,
            },
        )
    )
    db.commit()
    body_out = {
        "created": created,
        "pack": {
            "id": str(pack_row.id),
            "pack_code": pack_row.pack_code,
            "pack_version": pack_row.pack_version,
            "status": pack_row.status,
            "checksum_sha256": pack_row.checksum_sha256,
        },
        "validation": {"ok": report.ok, **report.model_dump()},
    }
    return JSONResponse(status_code=201 if created else 200, content=body_out)


class PackActivateRequest(BaseModel):
    activate: bool = True


@router.post("/knowledge/packs/{pack_id}/activate")
def activate_pack(
    pack_id: uuid.UUID,
    body: PackActivateRequest,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    # RBAC (P0-2): activation/retirement is platform-level — manager+ in any org.
    principal.require_any_org_role("manager")
    pack = db.get(dbm.KnowledgePack, pack_id)
    if pack is None:
        raise NotFound("Knowledge pack not found.")
    pack.status = "active" if body.activate else "retired"
    db.add(
        dbm.AuditEvent(
            actor_id=principal.id,
            entity_type="knowledge_pack",
            entity_id=str(pack.id),
            action="activated" if body.activate else "retired",
            after_snapshot={"status": pack.status},
        )
    )
    db.commit()
    return {"id": str(pack.id), "status": pack.status}
