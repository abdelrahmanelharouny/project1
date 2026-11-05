"""Soil intelligence engine — unit tests (M6B Steps 3–6).

Golden benchmarks are INDEPENDENT hand calculations / authoritative worked
examples, never outputs of the function under test:
- USDA texture classes: corner points, the classic triangle centre, the
  Wikipedia worked example (70 % sand / 10 % clay → sandy loam), boundary
  points transcribed against the soiltexture (R) USDA.TT polygon table.
- SOC stock: dimensional analysis hand-check (OC·BD·(1−vCF)·d·0.1) and
  exact-arithmetic FD-vs-ESM scenario.
- Nutrient conversions: stoichiometry from IUPAC atomic weights, computed
  independently in the test constants.
"""

from __future__ import annotations

import math

import pytest

from app.soil import contracts as sc
from app.soil import chemistry, nutrients, physical, soc
from app.soil.layers import (
    DepthInterval,
    make_depth_interval,
    validate_layer_set,
    depth_weighted_mean,
)


# ---------------------------------------------------------------- depths

class TestDepthIntervals:
    def test_canonical_interval(self):
        iv = make_depth_interval(0, 30, "cm")
        assert (iv.top_cm, iv.bottom_cm) == (0.0, 30.0)
        assert iv.thickness_cm == 30.0

    def test_unit_conversion_mm_and_m(self):
        assert make_depth_interval(0, 300, "mm").bottom_cm == 30.0
        iv = make_depth_interval(0.3, 0.9, "m")
        assert (iv.top_cm, iv.bottom_cm) == (30.0, 90.0)
        assert iv.original_unit == "m"  # original preserved

    def test_unknown_unit_refused(self):
        with pytest.raises(sc.SoilValidationError):
            make_depth_interval(0, 12, "fathoms")

    def test_inverted_interval_refused(self):
        with pytest.raises(sc.SoilValidationError):
            make_depth_interval(30, 0, "cm")

    def test_negative_top_refused(self):
        with pytest.raises(sc.SoilValidationError):
            make_depth_interval(-5, 10, "cm")

    def test_deep_beyond_bound_refused(self):
        with pytest.raises(sc.SoilValidationError):
            make_depth_interval(0, 500, "cm")

    def test_overlap_detection(self):
        a = make_depth_interval(0, 30, "cm")
        b = make_depth_interval(15, 60, "cm")
        check = validate_layer_set([a, b])
        assert check["overlaps"] and check["overlaps"][0]["overlap_cm"] == 15.0

    def test_gap_detection(self):
        a = make_depth_interval(0, 5, "cm")
        b = make_depth_interval(15, 30, "cm")
        check = validate_layer_set([a, b])
        assert check["gaps"] and check["gaps"][0]["gap_cm"] == 10.0

    def test_contiguous_no_findings(self):
        check = validate_layer_set([
            make_depth_interval(0, 5, "cm"),
            make_depth_interval(5, 15, "cm"),
        ])
        assert not check["overlaps"] and not check["gaps"]

    def test_weighted_mean_refuses_overlap(self):
        with pytest.raises(sc.SoilValidationError):
            depth_weighted_mean([
                (make_depth_interval(0, 30, "cm"), 1.0),
                (make_depth_interval(15, 45, "cm"), 2.0),
            ])

    def test_weighted_mean_hand_computed(self):
        mean, total = depth_weighted_mean([
            (make_depth_interval(0, 10, "cm"), 0.10),
            (make_depth_interval(10, 30, "cm"), 0.20),
        ])
        # (0.10*10 + 0.20*20) / 30 = 5/30
        assert math.isclose(mean, 5.0 / 30.0, rel_tol=1e-9)
        assert total == 30.0


# --------------------------------------------------------------- texture

class TestUsdaTexture:
    def test_corner_sand(self):
        assert physical.classify_usda_texture(sand_pct=100, clay_pct=0).texture_class == "sand"

    def test_corner_clay(self):
        assert physical.classify_usda_texture(sand_pct=0, clay_pct=100).texture_class == "clay"

    def test_corner_silt(self):
        assert physical.classify_usda_texture(sand_pct=0, silt_pct=100, clay_pct=0).texture_class == "silt"

    def test_wikipedia_worked_example(self):
        # Wikipedia (Soil texture): 70 % sand, 10 % clay → sandy loam
        r = physical.classify_usda_texture(sand_pct=70, clay_pct=10)
        assert r.texture_class == "sandy loam"
        assert r.silt_basis == "derived_silt_100_minus_sand_clay"
        assert r.silt_pct == 20.0

    def test_triangle_centre_is_clay_loam(self):
        r = physical.classify_usda_texture(sand_pct=33, silt_pct=34, clay_pct=33)
        assert r.texture_class == "clay loam"
        assert r.silt_basis == "measured"

    def test_silt_loam(self):
        assert physical.classify_usda_texture(sand_pct=20, silt_pct=60, clay_pct=20).texture_class == "silt loam"

    def test_silty_clay(self):
        assert physical.classify_usda_texture(sand_pct=10, silt_pct=50, clay_pct=40).texture_class == "silty clay"

    def test_sandy_clay_loam(self):
        assert physical.classify_usda_texture(sand_pct=55, silt_pct=20, clay_pct=25).texture_class == "sandy clay loam"

    def test_loamy_sand_boundary_point(self):
        # soiltexture USDA.TT edge P20→P21: (85,15,0)–(70,30,0); midpoint on edge
        assert physical.classify_usda_texture(sand_pct=75, silt_pct=25, clay_pct=0).texture_class == "loamy sand"

    def test_sand_interior_point(self):
        # interior of the sand polygon (soiltexture USDA.TT: P15,P25,P20):
        # at sand=90 the class spans silt 0..(100−90)=10
        assert physical.classify_usda_texture(sand_pct=90, silt_pct=8, clay_pct=2).texture_class == "sand"

    def test_boundary_point_resolves_deterministically(self):
        # P20 (85,15,0) is a vertex shared by the sand and loamy-sand polygons;
        # classification is deterministic by documented class order (inclusive
        # edges) — the same input always yields the same class.
        first = physical.classify_usda_texture(sand_pct=85, silt_pct=15, clay_pct=0)
        second = physical.classify_usda_texture(sand_pct=85, silt_pct=15, clay_pct=0)
        assert first.texture_class == second.texture_class

    def test_g_per_kg_input(self):
        r = physical.classify_usda_texture(sand_g_kg=700, clay_g_kg=100)
        assert r.texture_class == "sandy loam"

    def test_inconsistent_three_fractions_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.classify_usda_texture(sand_pct=50, silt_pct=50, clay_pct=50)

    def test_negative_derived_silt_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.classify_usda_texture(sand_pct=95, clay_pct=10)

    def test_both_unit_systems_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.classify_usda_texture(sand_pct=50, clay_g_kg=200)


# ---------------------------------------------------- bulk density/porosity

class TestPorosity:
    def test_hand_computed(self):
        # n = 1 − 1.33/2.65 = 0.498113...
        r = physical.porosity(1.33, None)
        assert r.porosity == round(1.0 - 1.33 / 2.65, 4)
        assert r.basis == "assumed_pd"
        assert r.disclosure  # the 2.65 assumption is disclosed

    def test_measured_pd_not_labelled_estimated(self):
        r = physical.porosity(1.33, 2.60)
        assert r.basis == "measured_pd"
        assert r.disclosure is None

    def test_bd_out_of_range_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.porosity(2.9, None)

    def test_unknown_basis_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.porosity(1.3, None, bulk_density_basis="compacted")


# ------------------------------------------------------------------- AWC

class TestLayerAWC:
    def test_hand_computed_mm(self):
        iv = make_depth_interval(0, 30, "cm")
        awc = physical.layer_awc(iv, 0.32, 0.15)
        assert awc.awc_m3_m3 == 0.17
        # 0.17 × 30 cm × 10 = 51 mm
        assert awc.awc_mm == 51.0

    def test_wp_above_fc_refused(self):
        with pytest.raises(sc.SoilValidationError):
            physical.layer_awc(make_depth_interval(0, 10, "cm"), 0.15, 0.32)

    def test_profile_awc_gap_labelled(self):
        l1 = physical.layer_awc(make_depth_interval(0, 5, "cm"), 0.30, 0.15)
        l2 = physical.layer_awc(make_depth_interval(15, 30, "cm"), 0.30, 0.15)
        total, info = physical.profile_awc_mm([l1, l2])
        # (7.5 + 22.5) mm over measured intervals; the 10 cm gap is NOT interpolated
        assert total == 30.0
        assert info["gaps"] and info["gaps"][0]["gap_cm"] == 10.0
        assert "NOT interpolated" in info["note"]

    def test_profile_awc_overlap_refused(self):
        l1 = physical.layer_awc(make_depth_interval(0, 20, "cm"), 0.30, 0.15)
        l2 = physical.layer_awc(make_depth_interval(10, 30, "cm"), 0.30, 0.15)
        total, info = physical.profile_awc_mm([l1, l2])
        assert total is None
        assert "refused" in info["reason"]


# ------------------------------------------------------------- chemistry

class TestChemistry:
    def test_ph_requires_medium(self):
        with pytest.raises(sc.SoilValidationError):
            chemistry.validate_ph_measurement(7.0, "")

    def test_ph_range_enforced(self):
        with pytest.raises(sc.SoilValidationError):
            chemistry.validate_ph_measurement(15.0, "water")

    def test_pH_media_not_comparable(self):
        a = chemistry.validate_ph_measurement(6.8, "water", "1:2.5")
        b = chemistry.validate_ph_measurement(6.2, "cacl2", "1:2.5")
        assert not chemistry.ph_series_comparable(a, b)
        c = chemistry.validate_ph_measurement(7.0, "water", "1:2.5")
        assert chemistry.ph_series_comparable(a, c)

    def test_screening_labels_non_water_medium(self):
        ph = chemistry.validate_ph_measurement(6.2, "cacl2", "1:2.5")
        result = chemistry.ph_screening_against_optimum(ph, 6.0, 7.5, source_citation="EcoCrop (FAO), confidence low")
        assert result["status"] == "within_reference_optimum"
        assert "not directly comparable" in result["screening_note"]

    def test_ece_salinity_classes(self):
        assert chemistry.salinity_class_for_ece(1.5)["salinity_class"] == "non_saline"
        assert chemistry.salinity_class_for_ece(3.0)["salinity_class"] == "slightly_saline"
        assert chemistry.salinity_class_for_ece(10.0)["salinity_class"] == "strongly_saline"
        result = chemistry.salinity_class_for_ece(5.0)
        assert result["ec_type"] == "ECe (saturated paste extract)"
        assert result["indicative"] is True

    def test_ec_cross_ratio_not_comparable(self):
        a = {"soil_solution_ratio": "1:5", "ec_type": "EC_1:5"}
        b = {"soil_solution_ratio": "saturation_extract", "ec_type": "ECe"}
        assert not chemistry.check_ec_method_compatibility(a, b)
        assert chemistry.check_ec_method_compatibility(a, dict(a))


# ------------------------------------------------------------- SOC stock

def _layer(top, bottom, oc, bd, basis="fine_earth", vcf=None, uncertainty=None):
    from app.soil.soc import LayerStockInput

    return LayerStockInput(
        interval=make_depth_interval(top, bottom, "cm"),
        oc_g_kg=oc,
        bulk_density_g_cm3=bd,
        bd_basis=basis,
        coarse_fragment_vol_fraction=vcf,
        oc_uncertainty_g_kg=uncertainty,
    )


class TestSocStock:
    def test_hand_computed_layer(self):
        # OC 20 g/kg, BD 1.3 g/cm³, vCF 0.1, d 20 cm
        # 20 × 1.3 × 0.9 × 20 × 0.1 = 46.8 Mg C/ha
        r = soc.layer_soc_stock(_layer(0, 20, 20.0, 1.3, basis="whole_soil", vcf=0.1))
        assert r.soc_stock_mg_ha == 46.8

    def test_dimensional_identity_fine_earth(self):
        # fine-earth basis: OC 15, BD 1.25, d 10 → 15 × 1.25 × 1 × 10 × 0.1 = 18.75
        r = soc.layer_soc_stock(_layer(0, 10, 15.0, 1.25))
        assert r.soc_stock_mg_ha == 18.75

    def test_missing_oc_refused_not_zero(self):
        r = soc.layer_soc_stock(_layer(0, 20, None, 1.3))
        assert r.soc_stock_mg_ha is None
        assert "OC" in r.not_evaluated_reason

    def test_missing_bd_refused_not_assumed(self):
        r = soc.layer_soc_stock(_layer(0, 20, 20.0, None))
        assert r.soc_stock_mg_ha is None
        assert "bulk density" in r.not_evaluated_reason.lower()

    def test_double_correction_hard_error(self):
        # fine-earth BD + vCF supplied → refusal (never double-correct)
        r = soc.layer_soc_stock(_layer(0, 20, 20.0, 1.3, basis="fine_earth", vcf=0.1))
        assert r.soc_stock_mg_ha is None
        assert "double correction" in r.not_evaluated_reason

    def test_whole_soil_requires_vcf(self):
        r = soc.layer_soc_stock(_layer(0, 20, 20.0, 1.5, basis="whole_soil", vcf=None))
        assert r.soc_stock_mg_ha is None
        assert "coarse-fragment" in r.not_evaluated_reason

    def test_profile_total_hand_computed(self):
        layers = [
            _layer(0, 10, 20.0, 1.2),    # 20×1.2×10×0.1 = 24
            _layer(10, 30, 10.0, 1.3),   # 10×1.3×20×0.1 = 26
        ]
        result = soc.profile_soc_stock(layers)
        assert result["profile_total"]["soc_stock_mg_ha"] == 50.0
        assert result["profile_total"]["contiguous"] is True
        assert result["not_evaluated"] == []

    def test_profile_with_gap_labels_coverage(self):
        layers = [
            _layer(0, 10, 20.0, 1.2),     # 24
            _layer(30, 60, 10.0, 1.3),    # 10×1.3×30×0.1 = 39
        ]
        result = soc.profile_soc_stock(layers)
        assert result["profile_total"]["soc_stock_mg_ha"] == 63.0
        assert result["profile_total"]["contiguous"] is False
        assert len(result["warnings"]) >= 1

    def test_profile_overlap_refused(self):
        layers = [_layer(0, 30, 20.0, 1.2), _layer(15, 45, 10.0, 1.3)]
        with pytest.raises(soc.SocStockError):
            soc.profile_soc_stock(layers)

    def test_prediction_layers_flagged(self):
        layer = _layer(0, 5, 22.0, 1.4)
        from app.soil.soc import LayerStockInput

        pred = LayerStockInput(
            interval=layer.interval, oc_g_kg=22.0, bulk_density_g_cm3=1.4,
            bd_basis="fine_earth", coarse_fragment_vol_fraction=None,
            evidence_class="global_soil_prediction", is_prediction=True,
        )
        result = soc.profile_soc_stock([pred])
        assert result["layers"][0]["is_prediction"] is True
        assert any("prediction" in w.lower() for w in result["warnings"])


class TestSocComparisons:
    def test_fixed_depth_detects_bd_change_with_caveat(self):
        base = [_layer(0, 10, 20.0, 1.4)]     # 28 Mg/ha, mass 1400
        follow = [_layer(0, 10, 20.0, 1.2)]   # 24 Mg/ha, mass 1200
        result = soc.fixed_depth_comparison(base, follow)
        assert result["status"] == "evaluated"
        assert result["delta_mg_ha"] == -4.0
        assert any("mass redistribution" in c for c in result["caveats"])

    def test_esm_detects_no_carbon_change(self):
        # same hand-computed scenario: ESM correctly shows 0 delta
        base = [_layer(0, 10, 20.0, 1.4)]
        follow = [_layer(0, 10, 20.0, 1.2)]
        result = soc.equivalent_soil_mass_comparison(base, follow)
        assert result["status"] == "evaluated"
        assert result["delta_mg_ha"] == 0.0
        assert result["reference_mass_mg_ha"] == 1200.0

    def test_esm_two_layer_hand_computed(self):
        base = [
            _layer(0, 10, 20.0, 1.4),    # stock 28, mass 1400
            _layer(10, 30, 10.0, 1.3),   # stock 26, mass 2600
        ]
        follow = [
            _layer(0, 10, 20.0, 1.2),    # stock 24, mass 1200
            _layer(10, 30, 10.0, 1.25),  # stock 25, mass 2500
        ]
        result = soc.equivalent_soil_mass_comparison(base, follow)
        assert result["status"] == "evaluated"
        # target mass 3700 on baseline curve: 28 + (3700−1400)/2600 × 26 = 51.0
        assert result["baseline_stock_mg_ha"] == 51.0
        assert result["follow_up_stock_mg_ha"] == 49.0
        assert result["delta_mg_ha"] == -2.0

    def test_esm_refused_without_bd(self):
        base = [_layer(0, 10, 20.0, None)]
        follow = [_layer(0, 10, 20.0, 1.2)]
        result = soc.equivalent_soil_mass_comparison(base, follow)
        assert result["status"] == "not_evaluated"
        assert "bulk density" in result["reason"]

    def test_fd_refused_on_disjoint_support(self):
        base = [_layer(0, 10, 20.0, 1.3)]
        follow = [_layer(20, 40, 20.0, 1.3)]
        result = soc.fixed_depth_comparison(base, follow)
        assert result["status"] == "not_evaluated"

    def test_esm_refused_when_followup_mass_exceeds_baseline(self):
        base = [_layer(0, 10, 20.0, 1.2)]    # mass 1200
        follow = [_layer(0, 10, 20.0, 1.4)]  # mass 1400
        result = soc.equivalent_soil_mass_comparison(base, follow)
        assert result["status"] == "not_evaluated"
        assert "exceeds" in result["reason"]


# ------------------------------------------------------------- nutrients

# Independent stoichiometric constants (IUPAC 2021 standard atomic weights)
_M_P, _M_K, _M_O = 30.9738, 39.0983, 15.999
_EXP_P = (2 * _M_P) / (2 * _M_P + 5 * _M_O)
_EXP_K = (2 * _M_K) / (2 * _M_K + _M_O)


class TestNutrientConversions:
    def test_p2o5_exact_stoichiometry(self):
        assert nutrients.P2O5_TO_P == pytest.approx(_EXP_P, rel=1e-12)
        assert nutrients.p2o5_to_p_kg(100.0) == pytest.approx(100.0 * _EXP_P, rel=1e-12)

    def test_k2o_exact_stoichiometry(self):
        assert nutrients.K2O_TO_K == pytest.approx(_EXP_K, rel=1e-12)
        assert nutrients.k2o_to_k_kg(100.0) == pytest.approx(100.0 * _EXP_K, rel=1e-12)

    def test_round_trip(self):
        assert nutrients.p_to_p2o5_kg(nutrients.p2o5_to_p_kg(42.0)) == pytest.approx(42.0, rel=1e-12)
        assert nutrients.k_to_k2o_kg(nutrients.k2o_to_k_kg(42.0)) == pytest.approx(42.0, rel=1e-12)

    def test_negative_refused(self):
        with pytest.raises(nutrients.NutrientBudgetError):
            nutrients.p2o5_to_p_kg(-1.0)


def _input(flow, kind="fertilizer", n=None, p=None, k=None, area=1.0, basis="elemental",
           availability=None, estimate=False):
    return nutrients.NutrientInputRecord(
        flow_id=flow, input_kind=kind, n_kg=n, p_kg=p, k_kg=k, area_ha=area,
        reporting_basis=basis, evidence_class="farmer_reported_record",
        is_estimate=estimate, availability_fraction=availability,
    )


def _output(flow, n=None, p=None, k=None, kind="harvested_product", disclosed=True):
    return nutrients.NutrientOutputRecord(
        flow_id=flow, output_kind=kind, n_kg_ha=n, p_kg_ha=p, k_kg_ha=k,
        concentration_basis="dry_matter", moisture_basis_disclosed=disclosed,
        evidence_class="farmer_reported_record",
    )


class TestNutrientBudget:
    def test_fertilizer_hand_computed(self):
        # 46 kg N (urea content) on 2 ha → 23 kg N/ha; removal 18 → balance +5
        r = nutrients.nutrient_budget(
            inputs=[_input("u1", n=46.0, area=2.0)],
            outputs=[_output("g1", n=18.0)],
            season_label="s1",
        )
        assert r["balance"]["N"]["inputs_kg_ha"] == 23.0
        assert r["balance"]["N"]["balance_kg_ha"] == 5.0
        assert r["overall"] == "partial"  # loss flows unknown — never 'complete' by default

    def test_oxide_grade_converted(self):
        # product grade declared as P2O5: 40 kg P2O5 on 1 ha → 17.457 kg P/ha
        r = nutrients.nutrient_budget(
            inputs=[_input("dap", n=10.0, p=40.0, k=None, area=1.0, basis="oxide")],
            outputs=[],
            season_label="s1",
        )
        expected_p = 40.0 * _EXP_P
        assert r["balance"]["P"]["inputs_kg_ha"] == round(expected_p, 6)  # engine rounds 6 dp

    def test_manure_without_availability_excluded_not_zero(self):
        r = nutrients.nutrient_budget(
            inputs=[_input("m1", kind="manure", n=50.0, area=1.0, availability=None)],
            outputs=[_output("g1", n=10.0)],
            season_label="s1",
        )
        # manure EXCLUDED (no availability fraction) — balance shows removal only
        assert r["balance"]["N"]["inputs_kg_ha"] == 0.0
        assert any("availability" in m for m in r["missing_flows"])
        assert any("EXCLUDED" in w for w in r["warnings"])

    def test_manure_with_availability_fraction(self):
        r = nutrients.nutrient_budget(
            inputs=[_input("m1", kind="manure", n=50.0, area=1.0, availability=0.4)],
            outputs=[],
            season_label="s1",
        )
        assert r["balance"]["N"]["inputs_kg_ha"] == 20.0
        assert "× availability 0.4" in r["inputs"][0]["n_note"]

    def test_bnf_is_labelled_estimate(self):
        # BNF estimate midpoint 100 kg N (pack trait, low confidence)
        r = nutrients.nutrient_budget(
            inputs=[_input("bnf", kind="biological_nitrogen_fixation", n=100.0, area=1.0, estimate=True)],
            outputs=[],
            season_label="s1",
        )
        assert r["balance"]["N"]["inputs_kg_ha"] == 100.0
        assert r["inputs"][0]["is_estimate"] is True
        assert "estimated" in r["inputs"][0]["note"]

    def test_removal_without_concentration_refused(self):
        r = nutrients.nutrient_budget(
            inputs=[],
            outputs=[_output("g1", n=None)],
            season_label="s1",
        )
        assert r["overall"] == "not_evaluable"
        assert any("concentration" in m for m in r["missing_flows"])

    def test_unknown_loss_flows_never_zero(self):
        r = nutrients.nutrient_budget(inputs=[], outputs=[_output("g1", n=10.0)], season_label="s1")
        for flow in ("leaching", "denitrification", "volatilization"):
            assert any(flow in m and "NOT assumed zero" in m for m in r["missing_flows"])

    def test_interpretation_disclaims_stock_change(self):
        r = nutrients.nutrient_budget(inputs=[_input("u", n=1.0)], outputs=[_output("g", n=1.0)], season_label="s")
        assert "not a measured soil stock change" in r["interpretation_note"]

    def test_nue_definition_labelled(self):
        r = nutrients.nutrient_budget(
            inputs=[_input("u", n=100.0)], outputs=[_output("g", n=60.0)], season_label="s"
        )
        assert r["nue"]["N"]["value"] == 0.6
        assert "partial-factor productivity" in r["nue"]["N"]["definition"]

    def test_cumulative_skips_unevaluable(self):
        s1 = nutrients.nutrient_budget(inputs=[_input("u", n=50.0)], outputs=[_output("g", n=40.0)], season_label="s1")
        empty = nutrients.nutrient_budget(inputs=[], outputs=[], season_label="s2")
        cum = nutrients.cumulative_budget([s1, empty])
        assert cum["seasons_evaluable"] == 1
        assert cum["seasons_skipped"] == ["s2"]
        assert cum["cumulative_balance_kg_ha"]["N"] == 10.0


# ---------------------------------------------------- versioned surfaces

class TestVersions:
    def test_versions_present(self):
        assert sc.SOIL_ENGINE_VERSION == "soil-engine-1.0.0"
        assert sc.SOIL_METHODS_VERSION == "soil-methods-1.0.0"
        assert sc.SOC_STOCK_VERSION == "soc-stock-1.0.0"
        assert sc.NUTRIENT_BUDGET_VERSION == "nutrient-budget-1.0.0"
        assert sc.TEXTURE_CLASSIFIER_VERSION == "usda-texture-1.0.0"

    def test_variable_dictionary_complete(self):
        codes = {e["code"] for e in sc.SOIL_VARIABLE_DICTIONARY}
        assert {"soil_ph", "soil_organic_carbon", "soil_bulk_density",
                "soil_water_content_fc", "soil_microbial_biomass_c"} <= codes

    def test_checksum_reproducible(self):
        result = soc.profile_soc_stock([_layer(0, 20, 20.0, 1.3)])
        c1 = soc.soc_run_checksum(result)
        c2 = soc.soc_run_checksum(soc.profile_soc_stock([_layer(0, 20, 20.0, 1.3)]))
        assert c1 == c2 and len(c1) == 64
