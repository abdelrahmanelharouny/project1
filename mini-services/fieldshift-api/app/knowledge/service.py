"""Knowledge read services (Milestone 5).

Loads the ACTIVE knowledge packs into the pure dataclasses of
`app.rotation.problem` and answers relationship queries (rules between crops)
with region + validation-status gating. The only module allowed to map
knowledge ORM rows into the decision-core dataclasses.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import models as dbm
from app.rotation.problem import (
    CalendarWindow,
    KnowledgeBaseData,
    KnowledgeCrop,
    RotationRuleData,
    TraitValue,
    WaterParams,
)


def active_packs(db: Session) -> list[dbm.KnowledgePack]:
    return list(
        db.scalars(
            select(dbm.KnowledgePack)
            .where(dbm.KnowledgePack.status == "active")
            .order_by(dbm.KnowledgePack.pack_code, dbm.KnowledgePack.pack_version)
        ).all()
    )


def pack_ref(pack: dbm.KnowledgePack) -> dict[str, Any]:
    return {
        "pack_id": str(pack.id),
        "pack_code": pack.pack_code,
        "pack_version": pack.pack_version,
        "status": pack.status,
        "checksum_sha256": pack.checksum_sha256,
        "license_name": pack.license_name,
        "attribution_text": pack.attribution_text,
    }


def load_knowledge(db: Session) -> KnowledgeBaseData:
    """Load active packs; later pack versions of the same crop_code WIN when
    equal in specificity (import versions a pack as a whole — mixing packs is
    explicit and recorded in pack_refs). Idempotently bootstraps the bundled
    seed pack (same lazy pattern as the data registry and feature definitions)."""
    from app.knowledge.import_service import seed_default_packs

    seed_default_packs(db)
    packs = active_packs(db)
    if not packs:
        return KnowledgeBaseData(pack_refs=(), crops={}, rules=())
    pack_ids = [p.id for p in packs]
    pack_meta = {p.id: (p.pack_code, p.pack_version) for p in packs}

    source_rows = db.scalars(
        select(dbm.KnowledgeSource).where(dbm.KnowledgeSource.pack_id.in_(pack_ids))
    ).all()
    citations = {s.id: s for s in source_rows}

    # Deepening F-9: crop_rows are ordered deterministically so that a
    # crop_code collision across active packs resolves to the LATEST
    # (pack_version, pack_code) lexically — the previous unordered query made
    # the winner depend on arbitrary DB row order (a reproducibility hazard).
    crop_rows = db.scalars(
        select(dbm.Crop)
        .options(joinedload(dbm.Crop.family))
        .join(dbm.KnowledgePack, dbm.Crop.pack_id == dbm.KnowledgePack.id)
        .where(dbm.Crop.pack_id.in_(pack_ids), dbm.Crop.status == "active")
        .order_by(
            dbm.KnowledgePack.pack_version.asc(),
            dbm.KnowledgePack.pack_code.asc(),
            dbm.Crop.crop_code.asc(),
        )
    ).all()
    family_rows = db.scalars(
        select(dbm.CropFamily).where(dbm.CropFamily.pack_id.in_(pack_ids))
    ).all()

    trait_rows = db.scalars(
        select(dbm.CropTrait).where(dbm.CropTrait.pack_id.in_(pack_ids))
    ).all()
    window_rows = db.scalars(
        select(dbm.CropCalendarWindow).where(dbm.CropCalendarWindow.pack_id.in_(pack_ids))
    ).all()
    water_rows = db.scalars(
        select(dbm.CropWaterParameter).where(dbm.CropWaterParameter.pack_id.in_(pack_ids))
    ).all()
    rule_rows = db.scalars(
        select(dbm.RotationRule).where(dbm.RotationRule.pack_id.in_(pack_ids))
    ).all()

    def _trait_value(t: dbm.CropTrait, crop_row: dbm.Crop) -> TraitValue:
        pcode, pver = pack_meta[t.pack_id]
        src = citations[t.source_id]
        return TraitValue(
            trait_code=t.trait_code,
            value_numeric=t.value_numeric,
            value_text=t.value_text,
            value_low=t.value_low,
            value_high=t.value_high,
            unit=t.unit,
            region_code=t.region_code,
            evidence_class=t.evidence_class,
            confidence=t.confidence,
            validation_status=t.validation_status,
            source_key=src.source_key,
            citation_text=src.citation_text,
            pack_code=pcode,
            pack_version=pver,
            notes=t.notes,
        )

    crops: dict[str, KnowledgeCrop] = {}
    for crop_row in crop_rows:
        pcode, pver = pack_meta[crop_row.pack_id]
        # Later pack versions win on crop_code collision (packs compose;
        # the collision is explicit because both pack_refs are recorded).
        # Deterministic: the last row in (pack_version, pack_code) order wins.
        if crop_row.crop_code in crops:
            del crops[crop_row.crop_code]
        family = crop_row.family
        crops[crop_row.crop_code] = KnowledgeCrop(
            crop_code=crop_row.crop_code,
            pack_code=pcode,
            pack_version=pver,
            family_key=family.family_key if family else None,
            scientific_name=crop_row.scientific_name,
            common_name=(crop_row.common_names or [None])[0]
            if crop_row.common_names
            else None,
            crop_category=crop_row.crop_category,
            life_cycle_type=crop_row.life_cycle_type,
            is_legume=crop_row.is_legume,
            is_cover_crop_capable=crop_row.is_cover_crop_capable,
        )

    for t in trait_rows:
        owner = next((c for c in crop_rows if c.id == t.crop_id), None)
        if owner is None or owner.crop_code not in crops:
            continue
        crop = crops[owner.crop_code]
        value = _trait_value(t, owner)
        # Global traits store under the plain trait_code; region-scoped traits
        # store under "code@region". Resolution (regional beats global) happens
        # in `resolve_trait`, keeping coexisting values explicit (ADR-0014).
        key = f"{t.trait_code}@{t.region_code}" if t.region_code else t.trait_code
        crop.traits.setdefault(key, value)

    for w in window_rows:
        owner = next((c for c in crop_rows if c.id == w.crop_id), None)
        if owner is None or owner.crop_code not in crops:
            continue
        pcode, pver = pack_meta[w.pack_id]
        src = citations[w.source_id]
        crops[owner.crop_code].calendar_windows += (
            CalendarWindow(
                region_code=w.region_code,
                hemisphere=w.hemisphere,
                season_code=w.season_code,
                planting_start=w.planting_start,
                planting_end=w.planting_end,
                evidence_class=w.evidence_class,
                validation_status=w.validation_status,
                source_key=src.source_key,
                citation_text=src.citation_text,
                pack_code=pcode,
                pack_version=pver,
                notes=w.notes,
            ),
        )

    # Deepening F-05: anchors are collected first and the WaterParams object is
    # built ONLY when all three FAO-56 anchors exist. A missing anchor used to
    # be silently zero-filled (kc_initial=0.0), which would under-estimate
    # ETc — missing evidence must leave the estimate unevaluated, never zero.
    water_anchor_src: dict[str, tuple[Any, Any, Any, str]] = {}
    for wp in water_rows:
        owner = next((c for c in crop_rows if c.id == wp.crop_id), None)
        if owner is None or owner.crop_code not in crops:
            continue
        if wp.crop_variety_id is not None:
            continue  # variety-level Kc not resolved in this slice
        src = citations[wp.source_id]
        first = water_anchor_src.setdefault(
            owner.crop_code, (src, pack_meta[wp.pack_id], {}, wp.evidence_class)
        )
        first[2][wp.growth_stage] = float(wp.kc_value)
    for crop_code, (src, (pcode, pver), anchors, ev_class) in water_anchor_src.items():
        if {"initial", "mid", "late"} <= set(anchors):
            crops[crop_code].water_params = WaterParams(
                kc_initial=anchors["initial"],
                kc_mid=anchors["mid"],
                kc_late=anchors["late"],
                evidence_class=ev_class,
                source_key=src.source_key,
                citation_text=src.citation_text,
                pack_code=pcode,
                pack_version=pver,
            )
        # else: leave water_params None — the water dimension stays honestly
        # unevaluated for this crop (never reconstructed from zeros).

    rules: list[RotationRuleData] = []
    confirmed = 0
    reference = 0
    for r in rule_rows:
        pcode, pver = pack_meta[r.pack_id]
        src = citations[r.source_id]
        d = r.rule_definition or {}
        pred = d.get("predecessor") or {}
        succ = d.get("successor") or {}
        rule = RotationRuleData(
            rule_code=r.rule_code,
            rule_type=r.rule_type,
            predecessor_kind=pred.get("kind"),
            predecessor_key=pred.get("key"),
            successor_kind=succ.get("kind"),
            successor_key=succ.get("key"),
            min_break_seasons=int(d.get("min_break_seasons", 0)),
            mechanism=str(d.get("mechanism", "")),
            scope_note=d.get("scope_note"),
            applies_to_regions=tuple(r.applies_to_regions or ()),
            validation_status=r.validation_status,
            severity=r.severity,
            source_key=src.source_key,
            citation_text=src.citation_text,
            pack_code=pcode,
            pack_version=pver,
        )
        rules.append(rule)
        if rule.validation_status == "confirmed_regional":
            confirmed += 1
        elif rule.validation_status in ("reference", "locally_validated"):
            reference += 1

    return KnowledgeBaseData(
        pack_refs=tuple(pack_ref(p) for p in packs),
        crops=crops,
        rules=tuple(rules),
        confirmed_rule_count=confirmed,
        reference_rule_count=reference,
    )


# ------------------------------------------------------------ rule matching


def _matches_region(rule: RotationRuleData, country_code: str) -> bool:
    if not rule.applies_to_regions:
        return True  # global scope
    return country_code in rule.applies_to_regions


def rules_between(
    knowledge: KnowledgeBaseData,
    predecessor_crop: str,
    successor_crop: str,
    country_code: str,
    *,
    only_enforceable: bool = False,
) -> list[RotationRuleData]:
    """Rules constraining (predecessor → successor) for a region.

    Matches crop-pair AND family-scoped rules in either direction slot. Region
    gating: rules scoped to other regions never apply. `only_enforceable`
    restricts to confirmed_regional rules (hard-constraint vocabulary)."""
    pred = knowledge.crops.get(predecessor_crop)
    succ = knowledge.crops.get(successor_crop)
    if pred is None or succ is None:
        return []

    def _side_matches(rule_side_kind: str | None, rule_side_key: str | None, crop: KnowledgeCrop) -> bool:
        if rule_side_kind == "crop":
            return rule_side_key == crop.crop_code
        if rule_side_kind == "family":
            return crop.family_key is not None and rule_side_key == crop.family_key
        return False

    matched: list[RotationRuleData] = []
    for rule in knowledge.rules:
        if only_enforceable and not rule.is_hard_enforceable:
            continue
        if not _matches_region(rule, country_code):
            continue
        forward = _side_matches(rule.predecessor_kind, rule.predecessor_key, pred) and _side_matches(
            rule.successor_kind, rule.successor_key, succ
        )
        if forward:
            matched.append(rule)
    return sorted(matched, key=lambda r: r.rule_code)
