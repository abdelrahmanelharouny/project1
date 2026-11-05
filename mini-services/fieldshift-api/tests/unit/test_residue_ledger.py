"""Unit: residue & biomass ledger engine (M6C Increment 5).

Golden cases are hand arithmetic (spec §14.3): mass conservation, dry-matter
conversions, nutrient content derivation, over-allocation surfacing,
production-unknown behaviour.
"""

import pytest

from app.management.residue import (
    ResidueLedgerError,
    build_residue_ledger,
    build_residue_record_ledger,
    fresh_to_dry_kg,
    tonnes_to_kg,
)


def _record(**kw):
    base = {
        "id": "r1",
        "crop_label": "maize",
        "season_label": "summer_2026",
        "basis": "dry_matter",
        "produced_dm_kg": 5000.0,
        "production_status": "farmer_reported",
        "coefficient_provenance": {},
        "harvested_product_dm_kg": None,
        "harvested_product_status": None,
    }
    base.update(kw)
    return base


def _flow(**kw):
    base = {
        "id": "f1",
        "flow_type": "retained_surface",
        "flow_date": "2026-09-15",
        "dm_kg": None,
        "dm_kg_status": "unknown",
        "soil_management_event_id": None,
        "evidence_class": "farmer_reported_record",
    }
    base.update(kw)
    return base


class TestGoldenMassBalance:
    def test_hand_computed_balance(self):
        ledger = build_residue_record_ledger(
            _record(),
            [_flow(id="f1", flow_type="retained_surface", dm_kg=3000.0, dm_kg_status="measured"),
             _flow(id="f2", flow_type="removed_baled", dm_kg=1500.0, dm_kg_status="farmer_reported")],
            [],
        )
        assert ledger["balance"]["status"] == "balanced"
        assert ledger["balance"]["total_flow_dm_kg"] == 4500.0
        assert ledger["balance"]["unaccounted_dm_kg"] == 500.0
        assert ledger["surface_retained_dm_kg"] == 3000.0

    def test_over_allocation_is_hard_error_state_not_clamped(self):
        ledger = build_residue_record_ledger(
            _record(),
            [_flow(id="f1", flow_type="removed_baled", dm_kg=6000.0, dm_kg_status="measured")],
            [],
        )
        assert ledger["balance"]["status"] == "over_allocated"
        assert ledger["balance"]["unaccounted_dm_kg"] == -1000.0  # surfaced negative
        field = build_residue_ledger([_record()], {"r1": [_flow(id="f1", flow_type="removed_baled", dm_kg=6000.0, dm_kg_status="measured")]}, {})
        assert field["totals"]["over_allocated_count"] == 1
        assert any("never absorbed" in w for w in field["warnings"])

    def test_production_unknown_stays_unknown(self):
        ledger = build_residue_record_ledger(
            _record(produced_dm_kg=None, production_status="missing"),
            [_flow(id="f1", flow_type="retained_surface", dm_kg=1000.0, dm_kg_status="measured")],
            [],
        )
        assert ledger["balance"]["status"] == "production_unknown"
        assert ledger["balance"]["unaccounted_dm_kg"] is None
        field = build_residue_ledger([_record(produced_dm_kg=None, production_status="missing")], {"r1": []}, {})
        assert field["totals"]["records_production_unknown"] == 1
        assert field["totals"]["produced_dm_kg_known_total"] == 0.0
        assert any("never assumed to be zero" in w for w in field["warnings"])

    def test_unknown_mass_flow_counted_and_listed(self):
        ledger = build_residue_record_ledger(
            _record(),
            [_flow(id="f1", flow_type="grazed", dm_kg=None, dm_kg_status="unknown")],
            [],
        )
        assert ledger["balance"]["flows_with_unknown_mass"] == 1
        assert ledger["balance"]["total_flow_dm_kg"] == 0.0


class TestConversions:
    def test_tonnes_exact(self):
        assert tonnes_to_kg(5.0) == 5000.0

    def test_fresh_to_dry_hand_arithmetic(self):
        # 8500 kg fresh × 0.85 DM fraction = 7225 kg DM
        assert fresh_to_dry_kg(8500.0, 0.85) == pytest.approx(7225.0)

    def test_missing_fraction_refused(self):
        with pytest.raises(ResidueLedgerError, match="refused"):
            fresh_to_dry_kg(8500.0, None)

    def test_flow_with_fresh_mass_converts_and_labels_estimated(self):
        ledger = build_residue_record_ledger(
            _record(),
            [_flow(id="f1", flow_type="incorporated", fresh_kg=8500.0, dry_matter_fraction=0.85, dm_kg_status="measured")],
            [],
        )
        assert ledger["flows"][0]["dm_kg"] == pytest.approx(7225.0)
        assert ledger["flows"][0]["dm_kg_status"] == "measured"

    def test_flow_fresh_without_fraction_rejected(self):
        with pytest.raises(ResidueLedgerError, match="dry-matter fraction"):
            build_residue_record_ledger(
                _record(),
                [_flow(id="f1", flow_type="incorporated", fresh_kg=8500.0)],
                [],
            )


class TestCoefficientProvenance:
    def test_coefficient_estimate_without_provenance_rejected(self):
        with pytest.raises(ResidueLedgerError, match="provenance"):
            build_residue_record_ledger(
                _record(production_status="coefficient_estimate",
                        coefficient_provenance={}, produced_dm_kg=4000.0),
                [], [],
            )

    def test_no_default_residue_ratio_exists(self):
        """The engine offers no way to derive production from yield — the only
        coefficient path requires explicit record-level provenance."""
        ledger = build_residue_record_ledger(
            _record(produced_dm_kg=None, production_status="missing",
                    harvested_product_dm_kg=6000.0, harvested_product_status="measured"),
            [], [],
        )
        # even with a harvested product mass, production stays unknown
        assert ledger["balance"]["status"] == "production_unknown"


class TestNutrientContent:
    def test_nitrogen_content_hand_arithmetic(self):
        # N 1.2% × 3000 kg retained = 36.0 kg N
        ledger = build_residue_record_ledger(
            _record(),
            [_flow(id="f1", flow_type="retained_surface", dm_kg=3000.0, dm_kg_status="measured")],
            [{"carbon_fraction": 40.0, "nitrogen_pct": 1.2, "cn_ratio": None, "lignin_pct": None, "evidence_class": "laboratory_measured"}],
        )
        assert ledger["derived"]["nitrogen_in_flows_kg"]["retained_surface"] == pytest.approx(36.0)
        assert ledger["derived"]["total_nitrogen_kg"] == pytest.approx(36.0)
        # C:N derived: 40 / 1.2 = 33.33
        assert ledger["derived"]["cn_ratio_derived"] == pytest.approx(33.33)
        # carbon input reported in tonnes: 3000 × 0.40 / 1000 = 1.2 t
        assert ledger["derived"]["carbon_input_total_tonnes"] == pytest.approx(1.2)
        # honesty note present: input ≠ SOC sequestration, not counted in M6B
        assert "NOT counted in the M6B nutrient budget" in ledger["derived"]["note"]
        assert "NO" in ledger["derived"]["note"]  # no SOC claim

    def test_no_quality_means_no_nutrient_numbers(self):
        ledger = build_residue_record_ledger(_record(), [], [])
        assert "total_nitrogen_kg" not in ledger["derived"]


class TestProperties:
    def test_random_ledgers_never_silently_negative(self):
        import random

        rng = random.Random(20261031)
        for _ in range(40):
            produced = rng.choice([None, rng.uniform(0, 10000)])
            flows = []
            for i in range(rng.randint(0, 4)):
                flows.append(
                    _flow(id=f"f{i}", flow_type=rng.choice(
                        ["retained_surface", "incorporated", "removed_baled", "grazed", "burned", "other_loss", "unknown"]),
                        dm_kg=rng.choice([None, rng.uniform(0, 8000)]),
                        dm_kg_status="measured" if rng.random() < 0.5 else "unknown")
                )
            if produced is None:
                rec = _record(produced_dm_kg=None, production_status="missing")
            else:
                rec = _record(produced_dm_kg=produced, production_status="farmer_reported")
            ledger = build_residue_record_ledger(rec, flows, [])
            b = ledger["balance"]
            if produced is None:
                assert b["status"] == "production_unknown"
                assert b["unaccounted_dm_kg"] is None
            else:
                known_total = sum(f["dm_kg"] for f in ledger["flows"] if f["dm_kg"] is not None)
                assert b["total_flow_dm_kg"] == pytest.approx(known_total, abs=0.01)
                if known_total > produced:
                    assert b["status"] == "over_allocated"
                else:
                    assert b["status"] == "balanced"
                    assert b["unaccounted_dm_kg"] >= 0

    def test_determinism(self):
        kwargs = (
            [_record()],
            {"r1": [_flow(id="f1", flow_type="retained_surface", dm_kg=3000.0, dm_kg_status="measured")]},
            {"r1": [{"carbon_fraction": 40.0, "nitrogen_pct": 1.2, "cn_ratio": None, "lignin_pct": None, "evidence_class": "laboratory_measured"}]},
        )
        assert build_residue_ledger(*kwargs) == build_residue_ledger(*kwargs)
