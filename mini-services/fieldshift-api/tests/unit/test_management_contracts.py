"""Unit: M6C management practice knowledge contracts (Increment 2).

Honesty gates enforced here (spec §14.1, §19):
- every practice claim cites a pack source (missing evidence ≠ eligibility)
- the bundled practice pack carries NO numeric parameters (red line: no
  invented seeding rates, termination lead times, thresholds, capacities)
- nothing is confirmed_regional (hard recommendations stay review-gated)
- every practice is two-sided (no universally beneficial practice)
- regional applicability requires a declared basis (never latitude alone)
- checksums of packs without M6C sections are byte-stable vs pre-M6C
  (backward compatibility, gap analysis §10)
"""

import hashlib
import json

import pytest
from pydantic import ValidationError

from app.knowledge.contracts import (
    KnowledgePackIn,
    pack_checksum,
    validate_pack_cross_references,
)
from app.knowledge.packs.m6c_practices_pack import get_m6c_practices_pack
from app.knowledge.packs.seed_pack_v1 import get_seed_pack


def _valid_practices_pack() -> dict:
    return get_m6c_practices_pack()


class TestPracticePackIntegrity:
    def test_practices_pack_validates(self):
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        report = validate_pack_cross_references(pack)
        assert report.ok, report.errors
        assert report.counts["practices"] >= 10
        assert report.counts["operation_templates"] >= 10
        assert report.counts["crops"] == 0

    def test_every_practice_claim_carries_source_and_evidence_class(self):
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        source_keys = {s.source_key for s in pack.sources}
        for practice in pack.practices:
            claims: list[tuple[str, str]] = []
            claims += [(m.source_key, m.evidence_class) for m in practice.mechanisms]
            claims += [(r.source_key, r.evidence_class) for r in practice.requirements]
            claims += [(t.source_key, t.evidence_class) for t in practice.trade_offs]
            claims += [(r.source_key, r.evidence_class) for r in practice.risks]
            claims += [(ra.source_key, "regional") for ra in practice.regional_applicability]
            assert claims, f"practice {practice.practice_code} has no claims"
            for key, evidence in claims:
                assert key in source_keys, (
                    f"practice {practice.practice_code}: unknown source {key}"
                )
                assert evidence, "claim without evidence_class"

    def test_practices_pack_contains_no_numeric_parameters(self):
        """Red line: the seed practice pack must not invent numbers. Any numeric
        value that appears must be a provenance accident (e.g. a year) — so we
        scan the semantic fields only."""
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        for practice in pack.practices:
            claims = (
                practice.mechanisms
                + practice.requirements
                + practice.trade_offs
                + practice.risks
            )
            for claim in claims:
                # claims are qualitative text: no value fields exist on them
                assert not hasattr(claim, "value_numeric")
                assert not hasattr(claim, "value_low")
        # conditions dicts are allowed but must not smuggle numeric agronomy
        for practice in pack.practices:
            for claim in practice.mechanisms + practice.trade_offs + practice.risks:
                for key, value in (claim.conditions or {}).items():
                    assert not isinstance(value, (int, float)) or key in (
                        "confidence_hint",
                    ), f"numeric condition '{key}'={value} in {practice.practice_code}"

    def test_practices_pack_has_no_confirmed_regional(self):
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        for practice in pack.practices:
            assert practice.validation_status != "confirmed_regional"
            for ra in practice.regional_applicability:
                assert ra.validation_status != "confirmed_regional"

    def test_every_practice_is_two_sided(self):
        """No practice is a universal switch: each must carry at least one
        negative or context-dependent trade-off (spec non-negotiable 5)."""
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        for practice in pack.practices:
            directions = {t.direction for t in practice.trade_offs}
            assert directions & {"negative", "context_dependent"}, (
                f"practice {practice.practice_code} ships as universally beneficial"
            )

    def test_cover_termination_has_no_fixed_lead_time(self):
        """Red line: no universal termination lead time may be encoded."""
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        termination = next(
            p for p in pack.practices if p.practice_code == "cover_termination_planning"
        )
        text_blob = " ".join(
            [termination.description]
            + [m.text for m in termination.mechanisms]
            + [r.text for r in termination.requirements]
            + [t.text for t in termination.trade_offs]
            + [r.text for r in termination.risks]
        ).lower()
        for banned in ("days before", "day before", "weeks before", "lead time of"):
            assert banned not in text_blob

    def test_regional_applicability_declares_basis(self):
        pack = KnowledgePackIn.model_validate(_valid_practices_pack())
        scoped = 0
        for practice in pack.practices:
            for ra in practice.regional_applicability:
                scoped += 1
                assert ra.basis
                assert ra.region_code or ra.agroecological_zone
        assert scoped > 0, "pack must declare where its sources are scoped"


class TestPracticeContractRejections:
    def _base(self) -> dict:
        return {
            "practice_code": "test_practice",
            "practice_family": "residue",
            "name": "Test practice",
            "mechanisms": [
                {
                    "mechanism_code": "m1",
                    "text": "A test mechanism claim.",
                    "source_key": "src1",
                    "evidence_class": "published_reference",
                }
            ],
            "trade_offs": [
                {
                    "dimension": "soil_cover",
                    "direction": "positive",
                    "text": "A test trade-off.",
                    "source_key": "src1",
                    "evidence_class": "published_reference",
                }
            ],
        }

    def _pack(self, practice: dict) -> dict:
        return {
            "pack_code": "kp-test-practices",
            "pack_version": "v1",
            "name": "Test practices pack",
            "license_name": "Test license",
            "attribution_text": "Test attribution statement",
            "sources": [
                {
                    "source_key": "src1",
                    "publisher": "Test Publisher",
                    "title": "A test source title",
                    "citation_text": "Test citation text for the source.",
                }
            ],
            "crops": [],
            "practices": [practice],
        }

    def test_unknown_claim_source_rejected_at_cross_validation(self):
        practice = self._base()
        practice["mechanisms"][0]["source_key"] = "not_a_source"
        pack = KnowledgePackIn.model_validate(self._pack(practice))
        report = validate_pack_cross_references(pack)
        assert not report.ok
        assert any("unknown source_key 'not_a_source'" in e for e in report.errors)

    def test_unknown_tradeoff_dimension_rejected(self):
        practice = self._base()
        practice["trade_offs"][0]["dimension"] = "vibes"
        pack = KnowledgePackIn.model_validate(self._pack(practice))
        report = validate_pack_cross_references(pack)
        assert not report.ok
        assert any("unknown trade-off dimension 'vibes'" in e for e in report.errors)

    def test_uncited_practice_rejected_by_schema(self):
        practice = self._base()
        practice["mechanisms"] = []
        practice["trade_offs"] = []
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(self._pack(practice))

    def test_regional_applicability_requires_scope(self):
        practice = self._base()
        practice["regional_applicability"] = [
            {"basis": "we feel it applies", "source_key": "src1"}
        ]
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(self._pack(practice))

    def test_empty_pack_rejected(self):
        payload = self._pack(self._base())
        payload["practices"] = []
        with pytest.raises(ValidationError):
            KnowledgePackIn.model_validate(payload)

    def test_template_predecessor_must_resolve_within_pack(self):
        payload = self._pack(self._base())
        payload["operation_templates"] = [
            {
                "template_code": "op_a",
                "operation_type": "tillage",
                "name": "Op A",
                "typical_predecessors": [
                    {
                        "template_code": "op_missing",
                        "rationale": "Needs the missing operation first.",
                        "source_key": "src1",
                    }
                ],
            }
        ]
        pack = KnowledgePackIn.model_validate(payload)
        report = validate_pack_cross_references(pack)
        assert not report.ok
        assert any("op_missing" in e for e in report.errors)

    def test_template_crop_scoping_must_reference_pack_crops(self):
        payload = self._pack(self._base())
        payload["operation_templates"] = [
            {
                "template_code": "op_b",
                "operation_type": "harvest",
                "name": "Op B",
                "applies_to_crop_codes": ["alien_crop"],
            }
        ]
        pack = KnowledgePackIn.model_validate(payload)
        report = validate_pack_cross_references(pack)
        assert not report.ok
        assert any("alien_crop" in e for e in report.errors)


class TestChecksumBackwardCompatibility:
    def test_checksum_ignores_empty_m6c_sections(self):
        """Pre-M6C packs (no practices/templates) must produce byte-identical
        checksums under the new algorithm — verified by re-deriving the
        pre-M6C canonicalization independently."""
        payload = get_seed_pack()
        pack_new = KnowledgePackIn.model_validate(payload)
        checksum_new = pack_checksum(pack_new)

        # Independent pre-M6C reproduction: strip the two new keys from the
        # dump (the old model_dump simply did not have them).
        dump = pack_new.model_dump()
        dump.pop("practices", None)
        dump.pop("operation_templates", None)
        canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"))
        checksum_old = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert checksum_new == checksum_old

    def test_checksum_changes_when_practices_present(self):
        payload = _valid_practices_pack()
        pack = KnowledgePackIn.model_validate(payload)
        base = pack_checksum(pack)
        payload2 = json.loads(json.dumps(payload))
        payload2["practices"][0]["description"] += " Edited description."
        pack2 = KnowledgePackIn.model_validate(payload2)
        assert pack_checksum(pack2) != base
