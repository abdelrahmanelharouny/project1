"""Water knowledge read-model + readiness matrix (Milestone 6A — Phase 0/1).

Reads the pure `KnowledgeCrop` containers assembled by the knowledge service
and answers: for each crop, which water dimensions are complete, partial,
missing or not applicable — with the citations that back every present value.
The readiness matrix distinguishes complete/source-backed, partially
documented, missing, not-locally-validated and not-applicable (see
docs/implementation/M6A_READINESS_MATRIX.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rotation.problem import KnowledgeBaseData, KnowledgeCrop
from app.water.curve import KcCurve, build_curve
from app.water.soil import adjust_p_for_etc


class WaterKnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class WaterKnowledge:
    """Water-relevant knowledge for ONE crop (all items cite their source)."""

    crop_code: str
    pack_code: str
    pack_version: str
    curve: KcCurve | None
    curve_gap_reason: str | None
    zr_min_m: float | None
    zr_max_m: float | None
    zr_reference_m: float | None          # midpoint, disclosed as such
    zr_source: dict[str, Any] | None
    p_table: float | None
    p_source: dict[str, Any] | None
    validation_status: str                # min status across the water items
    notes: tuple[str, ...] = ()

    @property
    def has_etc_inputs(self) -> bool:
        return self.curve is not None


def _ref_from_trait(trait) -> dict[str, Any]:
    return {
        "type": "knowledge_trait",
        "trait_code": trait.trait_code,
        "pack_code": trait.pack_code,
        "pack_version": trait.pack_version,
        "source_key": trait.source_key,
        "citation_text": trait.citation_text,
        "evidence_class": trait.evidence_class,
        "confidence": trait.confidence,
        "validation_status": trait.validation_status,
        "value_low": trait.value_low,
        "value_high": trait.value_high,
    }


def water_knowledge_for_crop(crop: KnowledgeCrop) -> WaterKnowledge:
    curve: KcCurve | None = None
    curve_gap: str | None = None
    if crop.water_params is None:
        curve_gap = (
            "no sourced single-Kc anchor set in the knowledge base — crop ETc "
            "intentionally not estimated (never guessed)"
        )
    else:
        wp = crop.water_params
        stage_lengths = {
            stage: crop.numeric_trait(code)
            for stage, code in (
                ("initial", "stage_init_days"),
                ("development", "stage_dev_days"),
                ("mid", "stage_mid_days"),
                ("late", "stage_late_days"),
            )
        }
        missing_stages = [s for s, v in stage_lengths.items() if v is None]
        if missing_stages:
            curve_gap = (
                "Kc anchors present but stage lengths missing for: "
                f"{', '.join(missing_stages)} — curve not reconstructed"
            )
        else:
            try:
                curve = build_curve(
                    stage_lengths=stage_lengths,
                    kc_initial=wp.kc_initial,
                    kc_mid=wp.kc_mid,
                    kc_late=wp.kc_late,
                    source_key=wp.source_key,
                    citation_text=wp.citation_text,
                    evidence_class=wp.evidence_class,
                    pack_code=wp.pack_code,
                    pack_version=wp.pack_version,
                )
            except ValueError as exc:
                curve_gap = f"curve refused: {exc}"

    zr_trait = crop.trait("root_depth_effective_m")
    zr_min = zr_trait.value_low if zr_trait else None
    zr_max = zr_trait.value_high if zr_trait else None
    zr_mid = round((zr_min + zr_max) / 2.0, 4) if (zr_min is not None and zr_max is not None) else None

    p_trait = crop.trait("stress_depletion_fraction_p")

    statuses = set()
    if curve is not None:
        # WaterParams carries no per-row validation status; the anchor rows
        # were imported as 'reference' (pack-level). The curve evidence class
        # marks the provenance; treat the curve as reference knowledge.
        statuses.add("reference")
    if zr_trait is not None:
        statuses.add(zr_trait.validation_status)
    if p_trait is not None:
        statuses.add(p_trait.validation_status)
    validation = (
        "reference"
        if not statuses
        else ("reference" if "reference" in statuses else sorted(statuses)[0])
    )

    notes: list[str] = []
    if zr_min is not None and zr_max is not None:
        notes.append(
            f"root-zone depth uses the FAO-56 Table 22 range midpoint "
            f"{zr_mid} m of {zr_min}–{zr_max} m (disclosed assumption)"
        )
    if p_trait is not None:
        notes.append(
            "depletion fraction p applies for ETc ≈ 5 mm/day; the engine adjusts "
            "p = p + 0.04·(5 − ETc) when a season ETc mean exists (FAO-56 Table 22 footnote 2)"
        )

    return WaterKnowledge(
        crop_code=crop.crop_code,
        pack_code=crop.pack_code,
        pack_version=crop.pack_version,
        curve=curve,
        curve_gap_reason=curve_gap,
        zr_min_m=zr_min,
        zr_max_m=zr_max,
        zr_reference_m=zr_mid,
        zr_source=_ref_from_trait(zr_trait) if zr_trait else None,
        p_table=p_trait.value_numeric if p_trait else None,
        p_source=_ref_from_trait(p_trait) if p_trait else None,
        validation_status=validation,
        notes=tuple(notes),
    )


def water_knowledge_map(knowledge: KnowledgeBaseData) -> dict[str, WaterKnowledge]:
    return {code: water_knowledge_for_crop(c) for code, c in knowledge.crops.items()}


# ------------------------------------------------------------ readiness


def _dimension(status: str, detail: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": status, "detail": detail, "source": source}


def readiness_for_crop(wk: WaterKnowledge) -> dict[str, Any]:
    """Crop-by-crop readiness row. Statuses:
    complete | partial | missing | not_locally_validated | not_applicable."""
    dimensions: dict[str, Any] = {}

    # Kc anchors
    if wk.curve is not None:
        dimensions["kc_anchors"] = _dimension(
            "complete",
            "FAO-56 single-Kc anchors (initial/mid/late) with stage lengths",
            {
                "type": "crop_water_parameters",
                "source_key": wk.curve.source_key,
                "citation_text": wk.curve.citation_text,
                "evidence_class": wk.curve.evidence_class,
                "pack_version": wk.curve.pack_version,
            },
        )
    else:
        dimensions["kc_anchors"] = _dimension("missing", wk.curve_gap_reason or "no Kc evidence")

    # Stage lengths
    if wk.curve is not None:
        dimensions["stage_lengths"] = _dimension(
            "complete",
            "init/dev/mid/late stage durations (FAO-56 Table 11 context)",
            {
                "type": "crop_water_parameters",
                "source_key": wk.curve.source_key,
                "citation_text": wk.curve.citation_text,
            },
        )
    else:
        dimensions["stage_lengths"] = _dimension(
            "missing", "stage durations unavailable — ETc curve not reconstructable"
        )

    # Rooting depth
    if wk.zr_reference_m is not None:
        dimensions["rooting_depth"] = _dimension(
            "partial",
            f"FAO-56 Table 22 effective rooting depth range {wk.zr_min_m}–{wk.zr_max_m} m; "
            f"the engine uses the disclosed midpoint {wk.zr_reference_m} m "
            "(stage-wise root development is not modelled)",
            wk.zr_source,
        )
    else:
        dimensions["rooting_depth"] = _dimension("missing", "no rooting-depth evidence")

    # Stress sensitivity
    if wk.p_table is not None:
        dimensions["stress_sensitivity"] = _dimension(
            "partial",
            f"FAO-56 Table 22 depletion fraction p = {wk.p_table} (for ETc ≈ 5 mm/day); "
            "adjusted with p + 0.04·(5 − ETc). Table-22 p is a generic response "
            "factor, not a locally calibrated stress threshold.",
            wk.p_source,
        )
    else:
        dimensions["stress_sensitivity"] = _dimension(
            "missing", "no depletion fraction p in the knowledge base — Ks not evaluated"
        )

    # Soil hydraulic properties — crop-independent; the knowledge base holds none
    dimensions["soil_hydraulic_properties"] = _dimension(
        "missing",
        "no field capacity / wilting point rows exist in the knowledge base; "
        "inputs come from farmer measurements or the verified Saxton-Rawls (2006) "
        "pedotransfer over texture (opt-in), otherwise the root-zone balance "
        "stays unevaluated",
    )

    # Regional applicability
    dimensions["regional_applicability"] = _dimension(
        "not_locally_validated",
        f"all water values are validation_status='{wk.validation_status}' — "
        "pending regional confirmation via the agronomist review workflow",
    )

    overall = "complete"
    for dim in dimensions.values():
        if dim["status"] in ("missing",):
            overall = "partial" if overall == "complete" else overall
        if dim["status"] == "not_locally_validated":
            overall = overall if overall != "complete" else "not_locally_validated"
    if wk.curve is None:
        overall = "missing"

    return {
        "crop_code": wk.crop_code,
        "overall": overall,
        "etc_computable": wk.has_etc_inputs,
        "dimensions": dimensions,
        "notes": list(wk.notes),
    }


def readiness_matrix(knowledge: KnowledgeBaseData) -> dict[str, Any]:
    """The full readiness matrix payload (API/UI + Phase-0 artifact backing)."""
    wk_map = water_knowledge_map(knowledge)
    rows = [readiness_for_crop(wk_map[code]) for code in sorted(wk_map)]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["overall"]] = counts.get(row["overall"], 0) + 1
    return {
        "crops": rows,
        "summary": {
            "total_crops": len(rows),
            "by_overall": counts,
            "note": (
                "Readiness distinguishes complete/partial/missing/not-locally-validated; "
                "'missing' rows keep the dimension unevaluated — never guessed."
            ),
        },
    }


def adjusted_p(wk: WaterKnowledge, etc_mean_mm_per_day: float | None) -> float | None:
    """Pack p adjusted for the season ETc mean; None stays None."""
    if wk.p_table is None:
        return None
    if etc_mean_mm_per_day is None:
        return wk.p_table
    return adjust_p_for_etc(wk.p_table, etc_mean_mm_per_day)
