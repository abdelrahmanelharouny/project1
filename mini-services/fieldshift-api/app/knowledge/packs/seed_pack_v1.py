"""Seed knowledge pack v1 — the curated reference data for Milestone 5.

HONESTY CONTRACT (docs/implementation/M5_GAP_ANALYSIS.md, ADR-0014):

- Every attribute cites one of the pack's sources; nothing is invented.
- Values are transcriptions of the cited published tables (FAO-56, EcoCrop,
  Herridge et al.) with per-attribute confidence. They are REFERENCE knowledge
  (`validation_status="reference"`) until an agronomist review upgrades them.
- Calendar windows carry `evidence_class="reference_synthesized"`: they are
  coarse northern-hemisphere temperate contexts consistent with the crops'
  FAO-56 Table 11 station contexts — explicitly NOT station measurements, and
  flagged as requiring regional calibration.
- Deliberate gaps stay gaps: no drought/heat tolerance scores (no defensible
  source), faba bean has NO Kc values (its water criteria must come out
  unevaluated, never guessed). M6A adds faba bean's Table 22 rooting depth and
  depletion fraction — a Kc row is still deliberately absent.
- M6A Phase-0 verification: Kc anchors and stage lengths were re-checked
  against the FAO-56 chapter 6 tables and root depths / depletion fractions
  against chapter 8 Table 22 (both fetched from the FAO document during the
  verification, not transcribed from memory). Findings are recorded in
  docs/implementation/M6A_READINESS_MATRIX.md.
- Rotation rules are `validation_status="reference"` with mechanism text.
  NOTHING in this pack is `confirmed_regional`; hard rotation-break constraints
  therefore bind on nothing until local expert validation happens.
"""

PACK_CODE = "kp-seed-global"
# M6A: 2026.11.1 adds FAO-56 Table 22 depletion fractions (p) for every crop
# and corrects three root-depth transcriptions found during the M6A Phase-0
# verification against the fetched primary source (see
# docs/implementation/M6A_READINESS_MATRIX.md §4). Values remain
# validation_status="reference"; agronomist review is still the only path to
# confirmed_regional.
PACK_VERSION = "kp-seed-2026.11.1"

_FAO56 = "fao56_1998"
_ECOCROP = "fao_ecocrop"
_AGGRIOS = "agrios_2005"
_HERRIDGE = "herridge_2008"

EVIDENCE_PUBLISHED = "published_reference"
EVIDENCE_SYNTHESIZED = "reference_synthesized"


def _trait(trait_code, *, value=None, text=None, low=None, high=None, unit=None,
           source=_FAO56, evidence=EVIDENCE_PUBLISHED, confidence="moderate",
           conditions=None, notes=None):
    row = {"trait_code": trait_code}
    if value is not None:
        row["value_numeric"] = value
    if text is not None:
        row["value_text"] = text
    if low is not None:
        row["value_low"] = low
    if high is not None:
        row["value_high"] = high
    if unit is not None:
        row["unit"] = unit
    row["source_key"] = source
    row["evidence_class"] = evidence
    row["confidence"] = confidence
    if conditions:
        row["conditions"] = conditions
    if notes:
        row["notes"] = notes
    return row


def _window(planting_start, planting_end, harvest_start=None, harvest_end=None, *,
            hemisphere="north", region=None, season_code=None, notes=None):
    row = {
        "planting_start": planting_start,
        "planting_end": planting_end,
        "hemisphere": hemisphere,
        "source_key": _FAO56,  # station-context reference; synthesis declared below
        "evidence_class": EVIDENCE_SYNTHESIZED,
        "validation_status": "reference",
    }
    if harvest_start:
        row["harvest_start"] = harvest_start
    if harvest_end:
        row["harvest_end"] = harvest_end
    if region:
        row["region_code"] = region
    if season_code:
        row["season_code"] = season_code
    row["notes"] = notes or (
        "Coarse reference window consistent with FAO-56 Table 11 station contexts; "
        "requires regional calibration before operational use."
    )
    return row


def _p(value):
    """FAO-56 Table 22 soil water depletion fraction p (for ETc ≈ 5 mm/day).
    The ETc adjustment p = p_table + 0.04·(5 − ETc) is applied by the water
    engine when a season ETc mean exists (Table 22 footnote 2, verified)."""
    return _trait(
        "stress_depletion_fraction_p", value=value, unit="fraction",
        notes="FAO-56 Table 22 depletion fraction p for ETc ≈ 5 mm/day; "
              "adjusted by the water engine with p = p + 0.04·(5 − ETc).",
    )


def _kc(stage, value, stage_days, *, notes=None):
    return {
        "growth_stage": stage,
        "kc_value": value,
        "kc_method": "single",
        "stage_length_days": stage_days,
        "source_key": _FAO56,
        "evidence_class": EVIDENCE_PUBLISHED,
        "confidence": "moderate",
        "notes": notes or "FAO-56 single Kc (Table 11/12 typical values).",
    }


def _eco(temp_min_abs, opt_min, opt_max, precip_min, precip_max, ph_min, ph_max):
    return [
        _trait("temp_min_abs_degC", value=temp_min_abs, unit="degC", source=_ECOCROP,
               confidence="moderate"),
        _trait("temp_opt_min_degC", value=opt_min, unit="degC", source=_ECOCROP,
               confidence="moderate"),
        _trait("temp_opt_max_degC", value=opt_max, unit="degC", source=_ECOCROP,
               confidence="moderate"),
        _trait("precip_min_annual_mm", value=precip_min, unit="mm", source=_ECOCROP,
               confidence="moderate"),
        _trait("precip_max_annual_mm", value=precip_max, unit="mm", source=_ECOCROP,
               confidence="moderate"),
        _trait("ph_opt_min", value=ph_min, unit="pH", source=_ECOCROP, confidence="low"),
        _trait("ph_opt_max", value=ph_max, unit="pH", source=_ECOCROP, confidence="low"),
    ]


def _stages(init, dev, mid, late):
    return [
        _trait("stage_init_days", value=init, unit="d"),
        _trait("stage_dev_days", value=dev, unit="d"),
        _trait("stage_mid_days", value=mid, unit="d"),
        _trait("stage_late_days", value=late, unit="d"),
        _trait("duration_days_total", value=init + dev + mid + late, unit="d"),
    ]


def _kcs(ini, mid, end, notes=None):
    """Stage Kc anchor rows; the FAO-56 single-Kc curve (linear ramps across
    development/late stages) is constructed by the water estimator from these
    anchors + the stage_* trait lengths. Stage lengths live on crop traits."""
    base_notes = notes or "FAO-56 single Kc (Table 11/12 typical values)."
    return [
        _kc("initial", ini, None, notes=base_notes),
        _kc("mid", mid, None, notes=base_notes),
        _kc("late", end, None, notes=base_notes),
    ]


SEED_PACK: dict = {
    "pack_code": PACK_CODE,
    "pack_version": PACK_VERSION,
    "name": "Global reference seed pack (FAO-56 / EcoCrop / textbook pathology)",
    "description": (
        "Species-level reference knowledge for a deliberately small crop set. "
        "All attributes cite their published source; calendar windows are coarse "
        "reference_synthesized contexts. Reference validation only — regional "
        "confirmation requires the agronomist review workflow."
    ),
    "region_scope": "global",
    "license_name": "Mixed — see sources and license_notes",
    "attribution_text": (
        "Crop water parameters and durations from FAO Irrigation and Drainage Paper 56 "
        "(Allen et al., 1998). Ecological amplitude ranges from the FAO EcoCrop database. "
        "Host-pathogen rotation mechanisms from Agrios (2005). Nitrogen fixation from "
        "Herridge, Peoples & Boddey (2008)."
    ),
    "license_notes": (
        "FAO publications and the EcoCrop database are reused with attribution; verify "
        "current FAO reuse terms before commercial redistribution. This pack bundles "
        "digitized values, not the source databases."
    ),
    "digitization_note": (
        "Values were transcribed from the cited printed tables/databases into this pack "
        "by hand. Transcription accuracy is pending agronomist review "
        "(validation_status='reference'). Do not treat any value as regionally confirmed. "
        "Version 2026.11.1 (M6A): depletion fractions p and rooting depths were re-verified "
        "against the FAO-56 chapter 6/8 tables fetched from the FAO document during the "
        "M6A Phase-0 verification; three root-depth transcriptions were corrected "
        "(barley, dry bean, cotton) and Table 22 p values were added for every crop. "
        "See docs/implementation/M6A_READINESS_MATRIX.md."
    ),
    "sources": [
        {
            "source_key": _FAO56,
            "publisher": "FAO",
            "title": "Crop evapotranspiration — Guidelines for computing crop water "
                     "requirements (FAO Irrigation and Drainage Paper 56)",
            "url": "https://www.fao.org/4/x0490e/x0490e00.htm",
            "publication_year": 1998,
            "license": "FAO — reuse with attribution",
            "citation_text": "Allen, R.G., Pereira, L.S., Raes, D. & Smith, M. (1998). "
                             "Crop evapotranspiration. FAO Irrigation and Drainage Paper 56. Rome.",
        },
        {
            "source_key": _ECOCROP,
            "publisher": "FAO",
            "title": "EcoCrop crop ecological requirements database",
            "url": "https://ecocrop.fao.org",
            "publication_year": None,
            "license": "FAO — reuse with attribution",
            "citation_text": "FAO. EcoCrop: the crop environmental requirements database. "
                             "Food and Agriculture Organization of the United Nations, Rome.",
        },
        {
            "source_key": _AGGRIOS,
            "publisher": "Elsevier Academic Press",
            "title": "Plant Pathology (5th edition)",
            "url": None,
            "publication_year": 2005,
            "license": "Citation only — no content redistributed",
            "citation_text": "Agrios, G.N. (2005). Plant Pathology (5th ed.). "
                             "Elsevier Academic Press, Amsterdam.",
        },
        {
            "source_key": _HERRIDGE,
            "publisher": "Springer (Plant and Soil)",
            "title": "Global inputs of biological nitrogen fixation in agricultural systems",
            "url": "https://doi.org/10.1007/s11104-008-9668-3",
            "publication_year": 2008,
            "license": "Citation only",
            "citation_text": "Herridge, D.F., Peoples, M.B. & Boddey, R.M. (2008). Global "
                             "inputs of biological nitrogen fixation in agricultural systems. "
                             "Plant and Soil 311, 1-18.",
        },
    ],
    "families": [
        {"family_key": "poaceae", "scientific_name": "Poaceae", "common_names": ["grasses"]},
        {"family_key": "solanaceae", "scientific_name": "Solanaceae", "common_names": ["nightshades"]},
        {"family_key": "fabaceae", "scientific_name": "Fabaceae", "common_names": ["legumes"]},
        {"family_key": "asteraceae", "scientific_name": "Asteraceae", "common_names": ["composites"]},
        {"family_key": "malvaceae", "scientific_name": "Malvaceae", "common_names": ["mallows"]},
        {"family_key": "amaryllidaceae", "scientific_name": "Amaryllidaceae", "common_names": ["alliums"]},
    ],
    "crops": [
        {
            "crop_code": "maize",
            "family_key": "poaceae",
            "scientific_name": "Zea mays",
            "common_names": ["corn", "maize"],
            "crop_category": "cereal",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(20, 40, 50, 30) + [
                _trait("root_depth_effective_m", low=1.0, high=1.7, unit="m"),
                _p(0.55),
            ] + _eco(8, 18, 30, 450, 1500, 5.8, 7.2),
            "calendar_windows": [_window("04-15", "06-15", "08-15", "10-15")],
            "water_parameters": _kcs(0.30, 1.20, 0.60),
        },
        {
            "crop_code": "wheat_spring",
            "family_key": "poaceae",
            "scientific_name": "Triticum aestivum (spring types)",
            "common_names": ["spring wheat", "bread wheat"],
            "crop_category": "cereal",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(20, 25, 60, 30) + [
                _trait("root_depth_effective_m", low=1.0, high=1.5, unit="m"),
                _p(0.55),
            ] + _eco(5, 15, 24, 400, 1000, 6.0, 7.5),
            "calendar_windows": [_window("03-01", "04-30", "07-01", "08-31")],
            "water_parameters": _kcs(0.30, 1.15, 0.35),
        },
        {
            "crop_code": "barley",
            "family_key": "poaceae",
            "scientific_name": "Hordeum vulgare",
            "common_names": ["barley"],
            "crop_category": "cereal",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(15, 25, 50, 30) + [
                # M6A verification: corrected 1.0–1.2 → FAO-56 Table 22 1.0–1.5.
                _trait("root_depth_effective_m", low=1.0, high=1.5, unit="m"),
                _p(0.55),
            ] + _eco(3, 12, 22, 300, 1000, 6.0, 8.0),
            "calendar_windows": [_window("03-01", "04-15", "06-15", "08-15")],
            "water_parameters": _kcs(0.30, 1.15, 0.25),
        },
        {
            "crop_code": "potato",
            "family_key": "solanaceae",
            "scientific_name": "Solanum tuberosum",
            "common_names": ["potato"],
            "crop_category": "root_tuber",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(25, 30, 45, 30) + [
                _trait("root_depth_effective_m", low=0.4, high=0.6, unit="m"),
                _p(0.35),
            ] + _eco(2, 15, 22, 500, 1200, 4.8, 6.5),
            "calendar_windows": [
                _window("03-15", "05-15", "07-15", "09-30"),
                _window("12-01", "01-31", "03-15", "05-15", region="EG",
                        notes="Mild-winter regional reference (e.g. Nile winter plantings); "
                              "reference_synthesized context, requires regional calibration."),
            ],
            "water_parameters": _kcs(0.50, 1.15, 0.75),
        },
        {
            "crop_code": "soybean",
            "family_key": "fabaceae",
            "scientific_name": "Glycine max",
            "common_names": ["soybean", "soya"],
            "crop_category": "oilseed_pulse",
            "life_cycle_type": "annual",
            "is_legume": True,
            "is_cover_crop_capable": False,
            "traits": _stages(20, 35, 40, 25) + [
                _trait("root_depth_effective_m", low=0.6, high=1.3, unit="m"),
                _p(0.50),
                _trait("n_fixation_capacity_kg_ha", low=50, high=150, unit="kg N/ha/season",
                       source=_HERRIDGE, confidence="low",
                       notes="Order-of-magnitude BNF range for well-nodulated grain legumes "
                             "(Herridge et al. 2008); site-specific values vary widely."),
            ] + _eco(8, 20, 30, 450, 1200, 6.0, 7.5),
            "calendar_windows": [_window("05-01", "06-15", "09-15", "10-31")],
            "water_parameters": _kcs(0.40, 1.15, 0.50),
        },
        {
            "crop_code": "dry_bean",
            "family_key": "fabaceae",
            "scientific_name": "Phaseolus vulgaris",
            "common_names": ["common bean", "dry bean"],
            "crop_category": "pulse",
            "life_cycle_type": "annual",
            "is_legume": True,
            "is_cover_crop_capable": False,
            "traits": _stages(20, 30, 40, 20) + [
                # M6A verification: corrected 0.6–1.2 → FAO-56 Table 22
                # "Beans, dry and Pulses" 0.6–0.9.
                _trait("root_depth_effective_m", low=0.6, high=0.9, unit="m"),
                _p(0.45),
                _trait("n_fixation_capacity_kg_ha", low=30, high=100, unit="kg N/ha/season",
                       source=_HERRIDGE, confidence="low",
                       notes="Common bean is a weaker N fixer than soybean; coarse range."),
            ] + _eco(8, 18, 27, 350, 1000, 6.0, 7.5),
            "calendar_windows": [_window("05-01", "06-15", "08-15", "10-01")],
            "water_parameters": _kcs(0.40, 1.15, 0.35,
                notes="FAO-56 Table 12 dry beans; end Kc for dry harvest."),
        },
        {
            "crop_code": "faba_bean",
            "family_key": "fabaceae",
            "scientific_name": "Vicia faba",
            "common_names": ["faba bean", "broad bean"],
            "crop_category": "pulse",
            "life_cycle_type": "annual",
            "is_legume": True,
            "is_cover_crop_capable": True,
            "traits": [
                _trait("duration_days_total", low=110, high=150, unit="d", source=_ECOCROP,
                       confidence="low",
                       notes="Coarse cycle length from EcoCrop context; no FAO-56 stage "
                             "table entry digitized for this pack."),
                # M6A: Table 22 gives faba bean (dry/seed) Zr 0.5–0.7 m and
                # p 0.45 — rooting/stress knowledge, NOT a Kc. The Kc gap below
                # stays deliberately open (no defensible transcription).
                _trait("root_depth_effective_m", low=0.5, high=0.7, unit="m"),
                _p(0.45),
                _trait("n_fixation_capacity_kg_ha", low=60, high=200, unit="kg N/ha/season",
                       source=_HERRIDGE, confidence="low"),
            ] + _eco(2, 10, 22, 450, 1000, 6.0, 8.0),
            "calendar_windows": [_window("10-15", "12-15", "03-15", "05-15")],
            # DELIBERATE GAP: no Kc rows — no defensible transcription available.
            "water_parameters": [],
        },
        {
            "crop_code": "sunflower",
            "family_key": "asteraceae",
            "scientific_name": "Helianthus annuus",
            "common_names": ["sunflower"],
            "crop_category": "oilseed",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(25, 35, 45, 30) + [
                _trait("root_depth_effective_m", low=0.8, high=1.5, unit="m"),
                _p(0.45),
            ] + _eco(5, 20, 28, 400, 1200, 6.0, 8.0),
            "calendar_windows": [_window("04-01", "05-31", "08-15", "10-15")],
            "water_parameters": _kcs(0.35, 1.15, 0.35),
        },
        {
            "crop_code": "cotton",
            "family_key": "malvaceae",
            "scientific_name": "Gossypium hirsutum",
            "common_names": ["cotton"],
            "crop_category": "fibre",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(30, 50, 55, 45) + [
                # M6A verification: corrected 0.6–1.8 → FAO-56 Table 22 1.0–1.7.
                _trait("root_depth_effective_m", low=1.0, high=1.7, unit="m"),
                _p(0.65),
            ] + _eco(12, 25, 32, 500, 1500, 5.5, 8.0),
            "calendar_windows": [_window("04-15", "06-01", "09-01", "11-15")],
            "water_parameters": _kcs(0.35, 1.18, 0.50),
        },
        {
            "crop_code": "tomato",
            "family_key": "solanaceae",
            "scientific_name": "Solanum lycopersicum",
            "common_names": ["tomato"],
            "crop_category": "vegetable",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(30, 40, 40, 25) + [
                _trait("root_depth_effective_m", low=0.7, high=1.5, unit="m"),
                _p(0.40),
            ] + _eco(7, 18, 28, 400, 1000, 5.5, 7.5),
            "calendar_windows": [_window("04-01", "05-31", "07-15", "09-30")],
            "water_parameters": _kcs(0.60, 1.15, 0.80,
                notes="FAO-56 fresh-market tomato end Kc; mechanized harvest uses 0.70."),
        },
        {
            "crop_code": "onion",
            "family_key": "amaryllidaceae",
            "scientific_name": "Allium cepa",
            "common_names": ["onion"],
            "crop_category": "vegetable",
            "life_cycle_type": "annual",
            "is_legume": False,
            "is_cover_crop_capable": False,
            "traits": _stages(15, 25, 70, 40) + [
                _trait("root_depth_effective_m", low=0.3, high=0.6, unit="m"),
                _p(0.30),
            ] + _eco(3, 13, 25, 350, 800, 5.5, 7.5),
            "calendar_windows": [
                _window("10-15", "12-15", "04-15", "06-15"),
                _window("03-01", "04-15", "07-15", "08-31"),
            ],
            "water_parameters": _kcs(0.70, 1.05, 0.75),
        },
    ],
    "rotation_rules": [
        {
            "rule_code": "host_pathogen_solanaceae_break",
            "rule_type": "host_pathogen",
            "rule_definition": {
                "predecessor": {"kind": "family", "key": "solanaceae"},
                "successor": {"kind": "family", "key": "solanaceae"},
                "min_break_seasons": 1,
                "mechanism": "Soilborne pathogens of solanaceous hosts (e.g. Verticillium "
                             "wilt, Rhizoctonia) persist between related hosts; crop "
                             "rotation with unrelated hosts is standard disease-management "
                             "guidance.",
                "scope_note": "Family-level rule is justified by the shared-host mechanism "
                              "in the cited source; local confirmation still required.",
            },
            "applies_to_regions": [],
            "source_key": _AGGRIOS,
            "validation_status": "reference",
            "severity": "recommended",
        },
        {
            "rule_code": "host_pathogen_fabaceae_break",
            "rule_type": "host_pathogen",
            "rule_definition": {
                "predecessor": {"kind": "family", "key": "fabaceae"},
                "successor": {"kind": "family", "key": "fabaceae"},
                "min_break_seasons": 1,
                "mechanism": "Legume-specific soilborne diseases (e.g. Fusarium and "
                             "root-rot complexes) build up under repeated legume hosts; "
                             "rotation breaks are standard guidance.",
                "scope_note": "Family-level rule justified by shared-host mechanism; "
                              "local confirmation still required.",
            },
            "applies_to_regions": [],
            "source_key": _AGGRIOS,
            "validation_status": "reference",
            "severity": "recommended",
        },
        {
            "rule_code": "rotation_break_maize_after_maize",
            "rule_type": "rotation_break",
            "rule_definition": {
                "predecessor": {"kind": "crop", "key": "maize"},
                "successor": {"kind": "crop", "key": "maize"},
                "min_break_seasons": 1,
                "mechanism": "Continuous maize carries over stalk-boring insects and "
                             "maize-specific diseases and shows a documented yield drag "
                             "relative to rotated maize in agronomy literature.",
                "scope_note": "Crop-pair rule (NOT extended to the whole grass family).",
            },
            "applies_to_regions": [],
            "source_key": _AGGRIOS,
            "validation_status": "reference",
            "severity": "recommended",
        },
        {
            "rule_code": "rotation_break_cotton_after_cotton",
            "rule_type": "rotation_break",
            "rule_definition": {
                "predecessor": {"kind": "crop", "key": "cotton"},
                "successor": {"kind": "crop", "key": "cotton"},
                "min_break_seasons": 1,
                "mechanism": "Repeated cotton sustains cotton-specific soilborne disease "
                             "and nematode pressure; rotation with unrelated crops is "
                             "standard guidance.",
                "scope_note": "Crop-pair rule (NOT extended to the whole mallow family).",
            },
            "applies_to_regions": [],
            "source_key": _AGGRIOS,
            "validation_status": "reference",
            "severity": "recommended",
        },
        {
            "rule_code": "succession_legume_precedes_cereal",
            "rule_type": "succession_compatibility",
            "rule_definition": {
                "predecessor": {"kind": "family", "key": "fabaceae"},
                "successor": {"kind": "family", "key": "poaceae"},
                "min_break_seasons": 0,
                "mechanism": "Cereals following legumes benefit from biological nitrogen "
                             "fixation contributions; treated as favourable succession, "
                             "not a requirement.",
                "scope_note": "Directional benefit; absence of a legume predecessor is "
                              "not an exclusion.",
            },
            "applies_to_regions": [],
            "source_key": _HERRIDGE,
            "validation_status": "reference",
            "severity": "advisory",
        },
        {
            "rule_code": "cover_crop_fabaceae_winter",
            "rule_type": "cover_crop_suitability",
            "rule_definition": {
                "target": {"kind": "family", "key": "fabaceae"},
                "mechanism": "Winter faba bean can serve as a nitrogen-contributing "
                             "cover/green-manure crop in mild-winter regions; requires "
                             "local confirmation of termination timing.",
            },
            "applies_to_regions": [],
            "source_key": _HERRIDGE,
            "validation_status": "reference",
            "severity": "advisory",
        },
    ],
}


def get_seed_pack() -> dict:
    import copy

    return copy.deepcopy(SEED_PACK)
