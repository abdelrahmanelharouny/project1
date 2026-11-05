"""M6C practice knowledge seed pack — management practices & operation templates.

HONESTY CONTRACT (docs/m6c/M6C_GAP_ANALYSIS.md §13, spec §3):

- Every mechanism / requirement / trade-off / risk claim cites one of this
  pack's sources; nothing is invented and NOTHING numeric ships here:
  no seeding rates, no termination lead times, no machinery capacities,
  no cover percentages, no thresholds. Numbers can only enter through
  region-scoped, versioned pack updates with their own provenance.
- All rows are validation_status="reference" — nothing here is
  confirmed_regional, so no practice becomes a hard recommendation until a
  local agronomist review upgrades it (the M5/M6A gating is inherited).
- Trade-offs are deliberately two-sided: every practice carries at least one
  negative or context-dependent dimension, because no practice is universally
  beneficial (spec non-negotiable 5).
- Mechanism claims are qualitative process statements consistent with the
  cited source's own wording (FAO conservation-agriculture pages, USDA NRCS
  practice standard & technical sheets, the National Agronomy Manual, and the
  RUSLE2 scope statements). Regional applicability is declared only where the
  source itself scopes the claim (the NRCS documents scope themselves to the
  US; the FAO pages are global-qualitative).
- Sources were fetched and read during M6C Increment 1 (see
  docs/m6c/M6C_GAP_ANALYSIS.md §11); wording here paraphrases their content
  without adding quantities the sources do not state.
"""

from typing import Any

PACK_CODE = "kp-m6c-practices"
PACK_VERSION = "kp-m6c-practices-2026.11.1"

# Source keys
_FAOCAP = "fao_ca_principles"
_FAOCOV = "fao_ca_soil_cover"
_FAHOW = "fao_ca_how"
_AC340 = "nrcs_ac340"
_TERM = "nrcs_termination_fs"
_RESH = "nrcs_residue_harvest"
_NAM = "nrcs_nam_water_erosion"
_RUSLE = "rusle2_scope"
_ASABE = "asabe_scheduling_2024"

EVIDENCE_PUBLISHED = "published_reference"


def _mech(code, text, source, *, confidence="moderate", conditions=None):
    row = {
        "mechanism_code": code,
        "text": text,
        "source_key": source,
        "evidence_class": EVIDENCE_PUBLISHED,
        "confidence": confidence,
    }
    if conditions:
        row["conditions"] = conditions
    return row


def _req(code, kind, text, source, *, confidence="moderate"):
    return {
        "requirement_code": code,
        "kind": kind,
        "text": text,
        "source_key": source,
        "evidence_class": EVIDENCE_PUBLISHED,
        "confidence": confidence,
    }


def _to(dimension, direction, text, source, *, confidence="moderate", conditions=None):
    row = {
        "dimension": dimension,
        "direction": direction,
        "text": text,
        "source_key": source,
        "evidence_class": EVIDENCE_PUBLISHED,
        "confidence": confidence,
    }
    if conditions:
        row["conditions"] = conditions
    return row


def _risk(code, text, source, *, confidence="moderate", conditions=None):
    row = {
        "risk_code": code,
        "text": text,
        "source_key": source,
        "evidence_class": EVIDENCE_PUBLISHED,
        "confidence": confidence,
    }
    if conditions:
        row["conditions"] = conditions
    return row


_SOURCES = [
    {
        "source_key": _FAOCAP,
        "publisher": "FAO",
        "title": "Conservation Agriculture — principles (minimum soil disturbance, permanent soil cover, species diversification)",
        "url": "https://www.fao.org/conservation-agriculture/en/",
        "license": "FAO web content — citation",
        "citation_text": (
            "Food and Agriculture Organization of the United Nations. "
            "Conservation Agriculture principles. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _FAOCOV,
        "publisher": "FAO",
        "title": "Soil Organic Cover in Conservation Agriculture",
        "url": "https://www.fao.org/conservation-agriculture/in-practice/soil-organic-cover/en/",
        "license": "FAO web content — citation",
        "citation_text": (
            "Food and Agriculture Organization of the United Nations. "
            "Soil Organic Cover in Conservation Agriculture. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _FAHOW,
        "publisher": "FAO",
        "title": "How to Practice Conservation Agriculture (cropping-cycle operations framing)",
        "url": "https://www.fao.org/agriculture/crops/thematic-sitemap/theme/spi/scpi-home/managing-ecosystems/conservation-agriculture/ca-how/en/",
        "license": "FAO web content — citation",
        "citation_text": (
            "Food and Agriculture Organization of the United Nations. "
            "How to Practice Conservation Agriculture. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _AC340,
        "publisher": "USDA NRCS",
        "title": "Cover Crop Conservation Practice Standard (Code 340)",
        "url": "https://www.nrcs.usda.gov/resources/guides-and-instructions/cover-crop-ac-340-conservation-practice-standard",
        "license": "Public domain (US Government)",
        "citation_text": (
            "USDA Natural Resources Conservation Service. Cover Crop (Ac.) "
            "Conservation Practice Standard 340. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _TERM,
        "publisher": "USDA NRCS",
        "title": "Cover Crop Termination technical sheet",
        "url": "https://www.nrcs.usda.gov/sites/default/files/2025-04/Cover_Crop_Termination-FS_0.pdf",
        "license": "Public domain (US Government)",
        "citation_text": (
            "USDA Natural Resources Conservation Service. Cover Crop "
            "Termination fact sheet (2025). Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _RESH,
        "publisher": "USDA NRCS",
        "title": "Harvesting Crop Residue (2016)",
        "url": "https://www.nrcs.usda.gov/sites/default/files/2024-10/HarvestingCropResidueOctober2016.pdf",
        "license": "Public domain (US Government)",
        "citation_text": (
            "USDA Natural Resources Conservation Service. Harvesting Crop "
            "Residue (October 2016). Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _NAM,
        "publisher": "USDA NRCS",
        "title": "National Agronomy Manual — water erosion & residue effects (190-V-NAM, amend. 5, 2022 PDF edition)",
        "url": "https://www.nrcs.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf",
        "license": "Public domain (US Government)",
        "citation_text": (
            "USDA Natural Resources Conservation Service. National Agronomy "
            "Manual, water erosion chapters. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _RUSLE,
        "publisher": "USDA NRCS / USDA ARS",
        "title": "RUSLE2 technology and scope (water-erosion tool for sheet & rill processes; factor definitions)",
        "url": "https://www.nrcs.usda.gov/resources/tech-tools/water-erosion-rusle2",
        "license": "Public domain (US Government)",
        "citation_text": (
            "USDA NRCS RUSLE2 water-erosion technology page and USDA ARS "
            "RUSLE2 definitions. Accessed 2026-10-31."
        ),
    },
    {
        "source_key": _ASABE,
        "publisher": "ASABE",
        "title": "Scheduling of Robotics or Machinery Operations in Agricultural Fields: A Review (2024)",
        "url": "https://elibrary.asabe.org/abstract.asp?aid=54815",
        "license": "ASABE — citation",
        "citation_text": (
            "American Society of Agricultural and Biological Engineers. "
            "Scheduling of Robotics or Machinery Operations in Agricultural "
            "Fields: A Review (2024). Accessed 2026-10-31."
        ),
    },
]


def _practice(code, family, name, description, *, mechanisms, requirements,
              trade_offs, risks, regional=None, validation="reference"):
    return {
        "practice_code": code,
        "practice_family": family,
        "name": name,
        "description": description,
        "validation_status": validation,
        "mechanisms": mechanisms,
        "requirements": requirements,
        "trade_offs": trade_offs,
        "risks": risks,
        "regional_applicability": regional or [],
    }


_US_SCOPED = [{
    "region_code": "US",
    "basis": "source document is a USDA NRCS standard/manual scoped to US practice",
    "source_key": _AC340,
    "validation_status": "reference",
}]


def get_m6c_practices_pack() -> dict[str, Any]:
    """The bundled M6C practice knowledge pack as an importable payload."""
    practices = [
        _practice(
            "cover_cropping", "cover_crop",
            "Cover cropping",
            "Growing a non-cash crop primarily to protect and improve the soil "
            "between main crops; benefits and risks are context-specific.",
            mechanisms=[
                _mech("soil_protection", "A living cover protects the soil surface "
                      "between main crops — FAO lists permanent soil organic cover "
                      "among its conservation-agriculture principles.", _FAOCAP),
                _mech("organic_input", "Cover vegetation adds plant material to the "
                      "soil; FAO's soil-organic-cover guidance describes cover crops "
                      "as a source of organic matter for soil biology.", _FAOCOV,
                      conditions={"context": "magnitude depends on species, biomass and management"}),
                _mech("erosion_reduction", "USDA NRCS Code 340 lists reducing erosion "
                      "from wind and water among the standard's stated purposes.", _AC340),
                _mech("nitrogen_fixation", "Where the cover species is a legume grown "
                      "under suitable conditions, the cover can add biologically fixed "
                      "nitrogen; NRCS cover-crop guidance treats this as species- and "
                      "management-dependent.", _AC340,
                      confidence="low",
                      conditions={"requirement": "legume species; inoculation, biomass and termination management suitable"}),
                _mech("weed_suppression", "NRCS Code 340 lists weed suppression among "
                      "the purposes a cover crop may serve.", _AC340, confidence="low"),
            ],
            requirements=[
                _req("sowing_window", "window", "A locally valid sowing window with "
                     "enough season length for establishment before adverse conditions.",
                     _AC340),
                _req("seed", "seed", "Seed of a species suited to the local context "
                     "(NRCS guidance requires species adaptation criteria to be met).",
                     _AC340),
                _req("termination_plan", "knowledge", "A termination approach suited to "
                     "the species, the following crop and local conditions.", _TERM),
                _req("termination_capability", "equipment", "Equipment, livestock or "
                     "labor able to execute the chosen termination method.", _TERM),
            ],
            trade_offs=[
                _to("soil_cover", "positive",
                    "Extends the period with living protective cover beyond the main "
                    "crop season.", _FAOCAP),
                _to("erosion_protection", "positive",
                    "Living cover during the off-season addresses the erosion purposes "
                    "named in NRCS Code 340.", _AC340),
                _to("water_demand", "negative",
                    "A growing cover crop consumes water; NRCS termination guidance "
                    "treats soil-moisture depletion before the following crop as a "
                    "central termination-timing consideration.", _TERM,
                    confidence="moderate"),
                _to("water_demand", "positive",
                    "Cover and residues can reduce evaporation from the soil surface; "
                    "FAO soil-organic-cover guidance notes moisture moderation under "
                    "cover.", _FAOCOV, confidence="low",
                    conditions={"context": "net effect is location- and season-specific"}),
                _to("crop_establishment", "context_dependent",
                    "Termination timing trades cover-crop biomass against water and "
                    "seedbed conditions for the following crop.", _TERM),
                _to("machinery", "negative",
                    "Adds establishment and termination operations that need equipment "
                    "time.", _ASABE, confidence="low"),
                _to("cost", "negative",
                    "Seed and extra field operations are costs NRCS planners weigh "
                    "against the practice's purposes.", _AC340, confidence="low"),
            ],
            risks=[
                _risk("water_depletion", "A cover that grows too long into the "
                      "pre-planting period can deplete root-zone water needed by the "
                      "following crop; NRCS termination guidance frames termination "
                      "timing around this trade-off.", _TERM),
                _risk("regrowth_seed_set", "Termination that is too late or ineffective "
                      "can allow regrowth or seed set, turning the cover into a weed "
                      "problem for the following crop.", _TERM, confidence="low"),
                _risk("pest_bridge", "A living cover can act as a host or green bridge "
                      "for pests or diseases of the following crop in some crop "
                      "sequences; NRCS planning guidance treats pest considerations as "
                      "site- and rotation-specific.", _AC340, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "residue_retention", "residue",
            "Surface residue retention",
            "Leaving crop residue on the soil surface after harvest instead of "
            "removing, burning or burying it.",
            mechanisms=[
                _mech("detachment_protection", "Surface residue intercepts raindrops "
                      "and slows runoff; the National Agronomy Manual's water-erosion "
                      "material describes residue cover as reducing soil detachment.",
                      _NAM),
                _mech("moisture_moderation", "Residue cover moderates surface "
                      "conditions; FAO's soil-organic-cover guidance describes mulch/cover "
                      "effects on evaporation and temperature.", _FAOCOV,
                      confidence="low"),
                _mech("organic_input", "Retained residue is an organic-matter input; "
                      "FAO conservation-agriculture guidance treats crop residues as the "
                      "soil-cover resource.", _FAOCAP),
            ],
            requirements=[
                _req("retention_decision", "knowledge", "A harvest-time decision to "
                     "leave residue in place, with spreading/management so planter "
                     "performance is not compromised.", _RESH),
                _req("planter_residue_capability", "equipment", "Planting equipment "
                     "able to operate through surface residue, where amounts warrant "
                     "it.", _RESH, confidence="low"),
            ],
            trade_offs=[
                _to("erosion_protection", "positive",
                    "Residue cover is the erosion-protective factor the National "
                    "Agronomy Manual's water-erosion guidance builds on.", _NAM),
                _to("soil_cover", "positive",
                    "Retained residue maintains protective cover after harvest.",
                    _FAOCAP),
                _to("nutrient_cycling", "positive",
                    "Retained residue keeps the nutrients it contains in the field as "
                    "it decomposes; the NRCS residue-harvesting note describes the "
                    "nutrient value of residue.", _RESH),
                _to("crop_establishment", "context_dependent",
                    "Heavy surface residue can interfere with planting; the NRCS "
                    "residue note discusses management to avoid establishment "
                    "problems.", _RESH, confidence="low"),
                _to("machinery", "context_dependent",
                    "Handling residue may require equipment configuration changes.",
                    _RESH, confidence="low"),
            ],
            risks=[
                _risk("cool_wet_conditions", "In cool or wet settings a thick residue "
                      "layer can keep the seedbed cold and wet longer; NRCS residue "
                      "guidance notes residue effects on soil conditions vary by "
                      "climate and soil.", _RESH, confidence="low"),
                _risk("pest_carryover", "Residue can carry over some residue-borne "
                      "disease and pest contexts; effects are rotation- and "
                      "pathogen-specific and are not generalized here.", _NAM,
                      confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "residue_removal_baling", "residue",
            "Residue removal / baling",
            "Collecting and exporting residue (e.g. as baled feed or feedstock) "
            "after harvest.",
            mechanisms=[
                _mech("harvested_value", "Baling turns residue into a marketable or "
                      "on-farm feed resource; the NRCS residue-harvesting note treats "
                      "removal as a deliberate use of the residue.", _RESH),
                _mech("seedbed_clearance", "Removing residue clears the surface for "
                      "subsequent operations where residue amounts interfere with "
                      "them.", _RESH, confidence="low"),
            ],
            requirements=[
                _req("baling_equipment", "equipment", "Baling/hauling equipment or a "
                     "contractor able to collect and remove the residue.", _RESH),
                _req("removal_plan", "knowledge", "A removal level planned against "
                     "soil-productivity considerations (the NRCS note treats removal "
                     "rate as the central management decision).", _RESH),
            ],
            trade_offs=[
                _to("revenue", "positive",
                    "Removed residue can be sold or fed; the NRCS note frames residue "
                    "as a harvestable resource with value.", _RESH, confidence="low"),
                _to("erosion_protection", "negative",
                    "Removing residue removes the surface protection it provided; the "
                    "NRCS note links removal to increased erosion exposure.", _RESH),
                _to("nutrient_cycling", "negative",
                    "Removed residue exports the nutrients it contains; the NRCS note "
                    "describes nutrient removal with baling.", _RESH),
                _to("soil_organic_matter", "negative",
                    "Removal also removes the carbon input the residue would have "
                    "provided (the NRCS note discusses long-term productivity "
                    "effects).", _RESH),
            ],
            risks=[
                _risk("productivity_decline", "Sustained, unaccounted residue removal "
                      "can reduce soil productivity — the central caution of the NRCS "
                      "residue-harvesting note.", _RESH),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "residue_incorporation", "residue",
            "Residue incorporation",
            "Mixing or ploughing residue into the soil instead of leaving it on "
            "the surface.",
            mechanisms=[
                _mech("decomposition_contact", "Incorporation mixes residue into the "
                      "topsoil where moisture and biological contact speed "
                      "decomposition; FAO's CA material contrasts incorporation with "
                      "surface retention.", _FAOCOV, confidence="low"),
                _mech("nutrient_return", "Decomposed incorporated residue returns its "
                      "nutrients within the topsoil.", _FAOCOV, confidence="low"),
            ],
            requirements=[
                _req("tillage_pass", "equipment", "A tillage implement able to mix the "
                     "residue to the intended depth.", _FAHOW),
            ],
            trade_offs=[
                _to("nutrient_cycling", "positive",
                    "Nutrients in the residue are returned to the soil (as with "
                    "retention, the fate differs).", _FAOCOV, confidence="low"),
                _to("soil_cover", "negative",
                    "Incorporation removes the surface cover; FAO's "
                    "conservation-agriculture principle of permanent soil organic "
                    "cover argues for surface retention.", _FAOCAP),
                _to("erosion_protection", "negative",
                    "Without surface residue, raindrop detachment protection is lost "
                    "(the mechanism the National Agronomy Manual describes for "
                    "residue cover).", _NAM),
            ],
            risks=[
                _risk("exposed_period", "The interval between incorporation and next "
                      "canopy establishment is a period without the protective surface "
                      "cover the erosion guidance relies on.", _NAM, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "mulching", "soil_cover",
            "Mulching",
            "Applying protective material (crop residues, composts or other "
            "mulches) over the soil surface.",
            mechanisms=[
                _mech("surface_protection", "FAO's soil-organic-cover guidance "
                      "describes surface cover/mulch protecting the soil and feeding "
                      "soil organisms.", _FAOCOV),
                _mech("moisture_moderation", "Mulch moderates evaporation and "
                      "temperature swings at the surface (FAO cover guidance).",
                      _FAOCOV, confidence="low"),
            ],
            requirements=[
                _req("mulch_material", "other", "A mulch material source with known "
                     "provenance (its own nutrient and contaminant profile).",
                     _FAOCOV, confidence="low"),
                _req("application_labor", "labor", "Labor or equipment to apply the "
                     "mulch layer.", _FAHOW, confidence="low"),
            ],
            trade_offs=[
                _to("soil_cover", "positive", "Adds protective cover independently of "
                    "the crop cycle.", _FAOCOV),
                _to("cost", "negative", "Material and application are costs (FAO "
                    "guidance presents mulching as an input-dependent practice).",
                    _FAOCOV, confidence="low"),
                _to("crop_establishment", "context_dependent",
                    "Mulch can slow spring soil warming or interfere with direct "
                    "seeding depending on climate and crop.", _FAOCOV, confidence="low"),
            ],
            risks=[
                _risk("material_contaminants", "Off-farm mulch materials can carry "
                      "weed seeds or contaminants; FAO guidance advises attention to "
                      "mulch quality.", _FAOCOV, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "reduced_tillage", "tillage",
            "Reduced / minimum tillage",
            "Reducing the intensity or number of tillage passes, consistent with "
            "FAO's minimum-disturbance principle (where locally appropriate).",
            mechanisms=[
                _mech("disturbance_reduction", "FAO lists minimum mechanical soil "
                      "disturbance as a conservation-agriculture principle; reduced "
                      "tillage is the graded implementation of that principle.", _FAOCAP),
                _mech("cover_preservation", "Less tillage leaves more residue on the "
                      "surface, preserving the protective cover (FAO soil-cover "
                      "guidance).", _FAOCOV),
            ],
            requirements=[
                _req("suitable_equipment", "equipment", "Equipment suited to reduced- "
                      "or no-till establishment.", _FAHOW, confidence="low"),
                _req("adapted_management", "knowledge", "Weed, pest and fertility "
                      "management adapted to the changed tillage system (FAO guidance "
                      "describes CA as a system, not a single substitution).", _FAHOW),
            ],
            trade_offs=[
                _to("erosion_protection", "positive",
                    "Maintained cover and less disturbance reduce erosion exposure "
                    "(FAO principle; consistent with the National Agronomy Manual's "
                    "residue-erosion mechanism).", _FAOCAP),
                _to("soil_organic_matter", "positive",
                    "FAO's CA guidance links reduced disturbance with soil biological "
                    "activity and organic-matter conservation.", _FAOCAP,
                    confidence="low"),
                _to("crop_establishment", "context_dependent",
                    "Establishment can be harder in reduced-till systems without "
                    "adapted equipment and management.", _FAHOW, confidence="low"),
                _to("pests_diseases", "context_dependent",
                    "Pest, weed and disease dynamics change under reduced tillage and "
                    "require adapted strategies rather than being universally better "
                    "or worse.", _FAHOW, confidence="low"),
            ],
            risks=[
                _risk("transition_management", "FAO guidance stresses that CA is a "
                      "system transition; partial adoption without adapted management "
                      "may not deliver expected outcomes.", _FAHOW, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "contour_operations", "erosion_control",
            "Contour-aligned operations",
            "Conducting tillage, planting and related operations across (rather "
            "than up-and-down) the slope where water erosion is the concern.",
            mechanisms=[
                _mech("runoff_slowing", "The National Agronomy Manual's water-erosion "
                      "material and the RUSLE support-practice (P) factor treat "
                      "contour orientation as reducing runoff concentration and "
                      "transport on slopes.", _NAM, confidence="low",
                      conditions={"domain": "rainfall-driven sheet and rill processes"}),
            ],
            requirements=[
                _req("slope_context", "knowledge", "Knowledge of the field's slope "
                     "pattern; the support-practice effect is slope- and "
                     "implementation-dependent.", _RUSLE, confidence="low"),
                _req("guidance_capability", "equipment", "Guidance or marking capability "
                     "to keep passes on the contour.", _NAM, confidence="low"),
            ],
            trade_offs=[
                _to("erosion_protection", "positive",
                    "Contour operations act as a support practice against sheet and "
                    "rill erosion within RUSLE's scope.", _RUSLE, confidence="low"),
                _to("machinery", "context_dependent",
                    "Working on the contour can reduce field efficiency on complex "
                    "shapes (scheduling machinery operations across slopes is a known "
                    "planning problem).", _ASABE, confidence="low"),
            ],
            risks=[
                _risk("overflow_failure", "Where design or execution fails, contour "
                      "rows can concentrate overflow; the erosion literature treats "
                      "contouring as slope- and storm-dependent in effectiveness.",
                      _NAM, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "strip_cropping", "erosion_control",
            "Strip cropping",
            "Alternating strips of different crops or cover across the slope or "
            "along the contour.",
            mechanisms=[
                _mech("runoff_breaks", "The National Agronomy Manual's water-erosion "
                      "material includes strip cropping among practices that break "
                      "slope length and trap transported material.", _NAM,
                      confidence="low",
                      conditions={"domain": "rainfall-driven sheet and rill processes"}),
            ],
            requirements=[
                _req("strip_plan", "knowledge", "A strip layout plan consistent with "
                     "the field's slope and the farm's rotation.", _NAM, confidence="low"),
            ],
            trade_offs=[
                _to("erosion_protection", "positive",
                    "Strip cropping is a recognized support practice against sheet "
                    "and rill erosion within RUSLE's scope.", _RUSLE, confidence="low"),
                _to("machinery", "negative",
                    "Narrower strips add turns and complicate machinery scheduling "
                    "(machinery-scheduling literature treats field geometry as a "
                    "driver of non-productive time).", _ASABE, confidence="low"),
                _to("revenue", "context_dependent",
                    "Strip layout constrains crop choice per strip; economics depend "
                    "on the rotation.", _NAM, confidence="low"),
            ],
            risks=[],
            regional=_US_SCOPED,
        ),
        _practice(
            "vegetated_buffer", "erosion_control",
            "Buffer strips / vegetated barriers",
            "Permanent vegetated strips at the field edge or in-flow paths to "
            "intercept runoff and sediment leaving the cropped area.",
            mechanisms=[
                _mech("sediment_interception", "The National Agronomy Manual's "
                      "water-erosion material includes buffers/barriers among measures "
                      "that intercept flow and trap sediment.", _NAM, confidence="low"),
            ],
            requirements=[
                _req("establishment_area", "other", "Area taken out of production for "
                     "the buffer, and its establishment/maintenance.", _NAM,
                     confidence="low"),
            ],
            trade_offs=[
                _to("erosion_protection", "positive",
                    "Buffers reduce off-site transport; they complement, not replace, "
                    "in-field erosion control.", _NAM, confidence="low"),
                _to("revenue", "negative",
                    "Buffer area is removed from production.", _NAM, confidence="low"),
            ],
            risks=[
                _risk("maintenance_needs", "Buffers lose function if channels form "
                      "through them or maintenance lapses; effectiveness is "
                      "design-dependent.", _NAM, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "controlled_traffic", "traffic",
            "Controlled traffic (where supported)",
            "Confining machinery wheels to permanent lanes so the cropped bed "
            "carries fewer loads.",
            mechanisms=[
                _mech("compaction_limitation", "FAO's conservation-agriculture "
                      "material discusses controlled traffic as a complementary "
                      "measure limiting compaction of the cropped area.", _FAOCAP,
                      confidence="low"),
            ],
            requirements=[
                _req("lane_system", "other", "A lane geometry matched to machinery "
                     "widths; CA guidance treats this as system-level design.",
                     _FAOCAP, confidence="low"),
            ],
            trade_offs=[
                _to("crop_establishment", "positive",
                    "Less compaction of the root zone supports establishment and "
                    "rooting (FAO CA framing).", _FAOCAP, confidence="low"),
                _to("machinery", "context_dependent",
                    "Requires machinery-width discipline and adaptation; transition "
                    "costs exist.", _FAOCAP, confidence="low"),
            ],
            risks=[],
            regional=_US_SCOPED,
        ),
        _practice(
            "cover_termination_planning", "termination",
            "Cover-crop termination planning",
            "Choosing the termination window and method for a cover crop as an "
            "explicit decision rather than a fixed calendar rule.",
            mechanisms=[
                _mech("decision_dimensions", "NRCS termination guidance frames "
                      "termination as species-, method-, location- and cropping-system-"
                      "dependent — there is no universal termination date.", _TERM),
                _mech("water_release", "Termination stops cover water use; the "
                      "following crop's water availability depends on when and how "
                      "termination happens (NRCS termination guidance).", _TERM),
            ],
            requirements=[
                _req("method_choice", "knowledge", "A method (mechanical, chemical or "
                      "livestock-based where relevant) suited to the species and "
                      "system.", _TERM),
                _req("termination_equipment", "equipment", "Equipment/labor able to "
                     "execute the chosen method at the chosen time.", _TERM),
            ],
            trade_offs=[
                _to("water_demand", "context_dependent",
                    "Earlier termination conserves soil moisture for the following "
                    "crop; later termination builds more biomass — NRCS presents this "
                    "as the core timing trade-off.", _TERM),
                _to("soil_organic_matter", "context_dependent",
                    "Longer growth yields more biomass/organic input; the timing "
                    "decision balances that against the following crop.", _TERM,
                    confidence="low"),
                _to("crop_establishment", "context_dependent",
                    "Termination-to-planting sequencing affects seedbed conditions; "
                    "NRCS treats the interval as system-specific.", _TERM,
                    confidence="low"),
            ],
            risks=[
                _risk("late_termination", "Late or incomplete termination risks "
                      "regrowth, seed set and soil-moisture depletion (NRCS "
                      "termination guidance).", _TERM),
            ],
            regional=_US_SCOPED,
        ),
        _practice(
            "field_access_management", "traffic",
            "Field access & traffic management",
            "Planning when and where machines enter the field so operations avoid "
            "avoidable compaction and rutting.",
            mechanisms=[
                _mech("load_avoidance", "Avoiding traffic on wet, low-strength soil "
                      "limits compaction and rutting; the compaction mechanism is the "
                      "reason scheduling systems treat field condition as a constraint "
                      "(machinery-scheduling literature; National Agronomy Manual "
                      "discusses soil-condition constraints on operations).", _ASABE,
                      confidence="low"),
            ],
            requirements=[
                _req("readiness_check", "knowledge", "A field-readiness assessment "
                     "before entry — in this platform it is a manual check because "
                     "trafficability thresholds are not universal (spec §8.5).",
                     _ASABE, confidence="low"),
                _req("access_alternatives", "other", "Alternative access or timing "
                     "options when the field is not ready.", _ASABE, confidence="low"),
            ],
            trade_offs=[
                _to("crop_establishment", "positive",
                    "Avoiding wet-soil traffic preserves seedbed structure.",
                    _ASABE, confidence="low"),
                _to("labor", "context_dependent",
                    "Waiting for field readiness delays operations and complicates "
                    "scheduling (a core tension in machinery-scheduling research).",
                    _ASABE, confidence="low"),
            ],
            risks=[
                _risk("timeliness_pressure", "Schedule pressure can push operations "
                      "onto unready fields; the scheduler must surface the conflict "
                      "rather than absorb it.", _ASABE, confidence="low"),
            ],
            regional=_US_SCOPED,
        ),
    ]

    templates = [
        {
            "template_code": "op_harvest",
            "operation_type": "harvest",
            "name": "Harvest",
            "description": "Harvest the main crop; the operation that ends the "
                           "cropping cycle and makes residue available.",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [],
            "restriction_kinds": ["weather", "access"],
            "notes": "Sequence framing follows the FAO cropping-cycle description; "
                     "no duration or capacity is implied.",
        },
        {
            "template_code": "op_residue_chop_spread",
            "operation_type": "residue_management",
            "name": "Residue chopping / spreading",
            "description": "Size and evenly spread harvest residue to support the "
                           "chosen residue fate.",
            "applies_to_crop_categories": ["cereal", "oilseed", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_harvest",
                "rationale": "Residue handling follows harvest — the crop cycle "
                             "framing places post-harvest residue management after "
                             "the harvest operation.",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["access"],
            "notes": None,
        },
        {
            "template_code": "op_residue_baling",
            "operation_type": "residue_management",
            "name": "Residue baling / removal",
            "description": "Collect and export residue when baling/removal is the "
                           "chosen fate (see the residue_removal_baling practice).",
            "applies_to_crop_categories": ["cereal", "oilseed", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_harvest",
                "rationale": "Baling is a post-harvest operation in the cropping "
                             "cycle.",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["access"],
            "notes": None,
        },
        {
            "template_code": "op_soil_sampling",
            "operation_type": "soil_sampling",
            "name": "Soil sampling",
            "description": "Collect soil samples for laboratory analysis (feeds the "
                           "M6B soil domain).",
            "applies_to_crop_categories": [],
            "applies_to_crop_codes": [],
            "typical_predecessors": [],
            "restriction_kinds": ["access"],
            "notes": "Often placed before fertilizer decisions; the platform does "
                     "not hard-code that ordering — it is a farmer/planner choice.",
        },
        {
            "template_code": "op_tillage_seedbed",
            "operation_type": "tillage",
            "name": "Tillage / seedbed preparation",
            "description": "Prepare the seedbed at the intensity the farmer's "
                           "tillage system implies.",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_harvest",
                "rationale": "Seedbed preparation for the next crop follows the "
                             "previous harvest in the cropping-cycle framing.",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["soil_moisture", "access"],
            "notes": None,
        },
        {
            "template_code": "op_cover_seeding",
            "operation_type": "cover_crop_seeding",
            "name": "Cover-crop seeding",
            "description": "Sow the planned cover crop within its intended window "
                           "(see the cover_cropping practice).",
            "applies_to_crop_categories": [],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_harvest",
                "rationale": "Cover establishment typically follows harvest of the "
                             "main crop in the cycle framing; relay/intercrop systems "
                             "are exceptions the planner must model explicitly.",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["weather", "soil_moisture"],
            "notes": None,
        },
        {
            "template_code": "op_cover_termination",
            "operation_type": "cover_crop_termination",
            "name": "Cover-crop termination",
            "description": "Terminate the cover crop by the chosen method at the "
                           "planned window (see cover_termination_planning).",
            "applies_to_crop_categories": [],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_cover_seeding",
                "rationale": "Termination requires an established cover crop.",
                "source_key": _TERM,
            }],
            "restriction_kinds": ["weather", "access"],
            "notes": "No fixed lead time before the next crop is implied (spec "
                     "red line).",
        },
        {
            "template_code": "op_main_planting",
            "operation_type": "planting",
            "name": "Main-crop planting",
            "description": "Plant the main crop.",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_tillage_seedbed",
                "rationale": "Planting requires a prepared seedbed in the cropping-"
                             "cycle framing (reduced/no-till systems still require a "
                             "pass that performs this function).",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["weather", "soil_moisture", "access"],
            "notes": None,
        },
        {
            "template_code": "op_fertilizer_application",
            "operation_type": "fertilizer_application",
            "name": "Fertilizer / amendment application",
            "description": "Apply planned nutrients or amendments (quantities come "
                           "from the M6B nutrient domain, never from templates).",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [],
            "restriction_kinds": ["weather", "access"],
            "notes": "Placement relative to planting is a planner decision; "
                     "templates do not impose it.",
        },
        {
            "template_code": "op_irrigation",
            "operation_type": "irrigation",
            "name": "Irrigation application",
            "description": "Apply irrigation (planned quantities link to the M6A "
                           "water ladder where a plan exists).",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [],
            "restriction_kinds": ["access"],
            "notes": None,
        },
        {
            "template_code": "op_spraying",
            "operation_type": "spraying",
            "name": "Spraying (where relevant)",
            "description": "Apply permitted crop-protection products; legality and "
                           "label constraints are farmer-side responsibilities the "
                           "platform does not validate.",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [],
            "restriction_kinds": ["weather", "access"],
            "notes": "Only emitted when the farmer plans such an operation.",
        },
        {
            "template_code": "op_post_harvest_prep",
            "operation_type": "field_preparation",
            "name": "Post-harvest field preparation",
            "description": "Field tidying/preparation after harvest (drains, "
                           "headlands, access repair).",
            "applies_to_crop_categories": ["cereal", "legume", "oilseed", "vegetable", "fiber"],
            "applies_to_crop_codes": [],
            "typical_predecessors": [{
                "template_code": "op_harvest",
                "rationale": "Post-harvest work follows harvest by definition.",
                "source_key": _FAHOW,
            }],
            "restriction_kinds": ["access"],
            "notes": None,
        },
    ]

    return {
        "pack_code": PACK_CODE,
        "pack_version": PACK_VERSION,
        "name": "M6C Field Management Practices (seed)",
        "description": (
            "Qualitative, source-cited management practice definitions and "
            "operation templates for field management intelligence. Deliberately "
            "contains NO numeric parameters: seeding rates, termination lead "
            "times, machinery capacities, cover thresholds and erosion factors "
            "must arrive as region-scoped, versioned pack updates with their own "
            "provenance. Nothing in this pack is confirmed_regional."
        ),
        "region_scope": "global_qualitative_us_scoped_sources",
        "license_name": "Mixed: USDA NRCS public domain; FAO web content citation; ASABE citation",
        "attribution_text": (
            "Practice mechanisms and trade-offs paraphrase USDA NRCS (Cover Crop "
            "Practice Standard 340; Cover Crop Termination fact sheet 2025; "
            "Harvesting Crop Residue 2016; National Agronomy Manual; RUSLE2 "
            "technology pages), FAO conservation-agriculture web resources, and an "
            "ASABE 2024 machinery-scheduling review. See per-source citations."
        ),
        "license_notes": (
            "USDA NRCS materials are US Government public domain. FAO web content "
            "is cited per FAO reuse policy. ASABE abstract metadata is cited, not "
            "reproduced. This pack carries qualitative claims only."
        ),
        "digitization_note": (
            "Claims paraphrase the cited documents' content as read on 2026-10-31 "
            "during M6C Increment 1 (docs/m6c/M6C_GAP_ANALYSIS.md §11). Paraphrase "
            "is conservative: no quantity, threshold or date appears in this pack. "
            "US-scoped applicability is declared because the NRCS sources scope "
            "themselves to US practice."
        ),
        "sources": _SOURCES,
        "families": [],
        "crops": [],
        "rotation_rules": [],
        "practices": practices,
        "operation_templates": templates,
    }
