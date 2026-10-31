"""Unit: knowledge pack contracts — schema validation, cross-references,
conflict detection, provenance completeness, checksum stability (Milestone 5,
ADR-0014)."""

import pytest
from pydantic import ValidationError

from app.knowledge.contracts import (
    KnowledgePackIn,
    pack_checksum,
    validate_pack_cross_references,
)
from app.knowledge.packs.seed_pack_v1 import get_seed_pack


def _valid_pack() -> dict:
    return get_seed_pack()


class TestSeedPackIsValid:
    def test_seed_pack_validates(self):
        pack = KnowledgePackIn.model_validate(_valid_pack())
        report = validate_pack_cross_references(pack)
        assert report.ok, report.errors
        assert report.counts["crops"] >= 5
        assert report.counts["sources"] >= 3
        assert report.counts["rotation_rules"] >= 3

    def test_every_seed_trait_carries_source_and_citation(self):
        pack = KnowledgePackIn.model_validate(_valid_pack())
        source_keys = {s.source_key for s in pack.sources}
        for crop in pack.crops:
            for trait in crop.traits:
                assert trait.source_key in source_keys
                assert trait.evidence_class
                assert trait.confidence in ("high", "moderate", "low", "unknown")
        for source in pack.sources:
            assert len(source.citation_text) > 8
            assert source.publisher
            assert source.title

    def test_every_seed_kc_row_has_source_and_confidence(self):
        pack = KnowledgePackIn.model_validate(_valid_pack())
        kc_crops = 0
        for crop in pack.crops:
            if crop.water_parameters:
                kc_crops += 1
                for wp in crop.water_parameters:
                    assert wp.source_key
                    assert wp.evidence_class == "published_reference"
        assert kc_crops >= 5

    def test_seed_pack_has_no_confirmed_regional_rules(self):
        """Honesty: the bundled seed pack must NOT claim regional confirmation —
        hard enforcement is reserved for locally validated knowledge."""
        pack = KnowledgePackIn.model_validate(_valid_pack())
        for rule in pack.rotation_rules:
            assert rule.validation_status != "confirmed_regional"

    def test_deliberate_gaps_stay_gaps(self):
        """faba_bean must have NO Kc rows (never guessed); no crop may carry an
        invented drought/heat tolerance score."""
        pack = KnowledgePackIn.model_validate(_valid_pack())
        faba = next(c for c in pack.crops if c.crop_code == "faba_bean")
        assert faba.water_parameters == []
        for crop in pack.crops:
            codes = {t.trait_code for t in crop.traits}
            assert "drought_tolerance_class" not in codes
            assert "heat_tolerance_class" not in codes

    def test_checksum_is_stable_and_content_sensitive(self):
        pack_a = KnowledgePackIn.model_validate(_valid_pack())
        pack_b = KnowledgePackIn.model_validate(_valid_pack())
        assert pack_checksum(pack_a) == pack_checksum(pack_b)
        mutated = _valid_pack()
        mutated["crops"][0]["traits"][0]["value_numeric"] = (
            mutated["crops"][0]["traits"][0]["value_numeric"] + 0.001
        )
        pack_c = KnowledgePackIn.model_validate(mutated)
        assert pack_checksum(pack_a) != pack_checksum(pack_c)


class TestPackSchemaValidation:
    def test_missing_license_rejected(self):
        pack = _valid_pack()
        del pack["license_name"]
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(pack)

    def test_missing_attribution_rejected(self):
        pack = _valid_pack()
        pack["attribution_text"] = ""
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(pack)

    def test_trait_without_source_rejected(self):
        pack = _valid_pack()
        pack["crops"][0]["traits"][0]["source_key"] = "unknown_source"
        parsed = KnowledgePackIn.model_validate(pack)
        report = validate_pack_cross_references(parsed)
        assert not report.ok
        assert any("unknown source_key" in e for e in report.errors)

    def test_unknown_family_reference_rejected(self):
        pack = _valid_pack()
        pack["crops"][0]["family_key"] = "nope_family"
        parsed = KnowledgePackIn.model_validate(pack)
        report = validate_pack_cross_references(parsed)
        assert not report.ok

    def test_conflicting_trait_values_rejected(self):
        pack = _valid_pack()
        crop = pack["crops"][0]
        base = dict(crop["traits"][0])
        base["value_numeric"] = base["value_numeric"] + 1.0
        crop["traits"].append(base)
        parsed = KnowledgePackIn.model_validate(pack)
        report = validate_pack_cross_references(parsed)
        assert not report.ok
        assert any("conflicting trait values" in e for e in report.errors)

    def test_rule_referencing_unknown_crop_rejected(self):
        pack = _valid_pack()
        rule = pack["rotation_rules"][0]["rule_definition"]
        rule["successor"] = {"kind": "crop", "key": "ghost_crop"}
        parsed = KnowledgePackIn.model_validate(pack)
        report = validate_pack_cross_references(parsed)
        assert not report.ok
        assert any("unknown crop" in e for e in report.errors)

    def test_break_rule_requires_min_break_seasons(self):
        pack = _valid_pack()
        pack["rotation_rules"][0]["rule_definition"]["min_break_seasons"] = 0
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(pack)

    def test_trait_cannot_have_both_numeric_and_text(self):
        pack = _valid_pack()
        pack["crops"][0]["traits"][0]["value_text"] = "oops"
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(pack)

    def test_invalid_confidence_rejected(self):
        pack = _valid_pack()
        pack["crops"][0]["traits"][0]["confidence"] = "definitely_certain"
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(pack)


class TestRegionalApplicability:
    def test_region_scoped_trait_keys_are_distinct(self):
        """A regional trait and its global counterpart coexist explicitly
        (stored under different keys) — never silently overwritten."""
        from app.rotation.problem import KnowledgeCrop, TraitValue

        def _t(region):
            return TraitValue(
                trait_code="duration_days_total", value_numeric=120, value_text=None,
                value_low=None, value_high=None, unit="d", region_code=region,
                evidence_class="published_reference", confidence="moderate",
                validation_status="reference", source_key="s", citation_text="c",
                pack_code="p", pack_version="v",
            )

        crop = KnowledgeCrop(
            crop_code="x", pack_code="p", pack_version="v", family_key=None,
            scientific_name=None, common_name=None, crop_category=None,
            life_cycle_type=None, is_legume=False, is_cover_crop_capable=False,
            traits={"duration_days_total": _t(None), "duration_days_total@EG": _t("EG")},
        )
        assert crop.resolve_trait("duration_days_total", "EG").region_code == "EG"
        assert crop.resolve_trait("duration_days_total", "FR").region_code is None
        assert crop.resolve_trait("duration_days_total").region_code is None
