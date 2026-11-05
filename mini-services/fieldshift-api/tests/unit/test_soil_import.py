"""Soil laboratory CSV import — unit tests (M6B Step 3)."""

from __future__ import annotations

import pytest

from app.soil.import_service import (
    ImportReport,
    parse_soil_lab_csv,
    resolve_mapping,
)


CANONICAL_CSV = (
    "sample_code,top_depth,bottom_depth,depth_unit,observed_at,variable_code,value,unit,"
    "detection_limit,result_qualifier,method_code,laboratory_name,report_reference,notes\n"
    "S001,0,30,cm,2026-03-15,soil_ph,7.2,pH,,,ph_water_1_2_5,AgriLab,REP-2026-001,\n"
    "S001,0,30,cm,2026-03-15,soil_organic_carbon,12.5,g/kg,,,walkley_black,AgriLab,REP-2026-001,\n"
    "S001,0,30,cm,2026-03-15,soil_available_phosphorus,<2.0,mg/kg,2.0,<,olsen,AgriLab,REP-2026-001,below detection\n"
    "S002,30,60,cm,2026-03-15,soil_sand_content,55,%,,,hydrometer,AgriLab,REP-2026-001,\n"
    "S002,30,60,cm,2026-03-15,soil_electrical_conductivity,NA,dS/m,,,,,,not measured\n"
)


class TestCanonicalImport:
    def test_parses_and_reports(self):
        rows, report = parse_soil_lab_csv(CANONICAL_CSV.encode())
        assert report.imported == 5
        assert report.rejected == 0
        assert report.warnings_count == 1  # below-detection row
        assert len(rows) == 5

    def test_below_detection_never_zero(self):
        rows, _ = parse_soil_lab_csv(CANONICAL_CSV.encode())
        p_row = next(r for r in rows if r["variable_code"] == "soil_available_phosphorus")
        assert p_row["value"] is None
        assert p_row["result_qualifier"] == "<"
        assert p_row["detection_limit"] == 2.0

    def test_percent_to_gkg_conversion(self):
        rows, _ = parse_soil_lab_csv(CANONICAL_CSV.encode())
        sand = next(r for r in rows if r["variable_code"] == "soil_sand_content")
        assert sand["value"] == 550.0  # 55 % → 550 g/kg
        assert sand["unit"] == "g/kg"

    def test_missing_value_recorded_not_zero(self):
        rows, _ = parse_soil_lab_csv(CANONICAL_CSV.encode())
        ec = next(r for r in rows if r["variable_code"] == "soil_electrical_conductivity")
        assert ec["value"] is None and ec["result_qualifier"] is None

    def test_depth_unit_preserved(self):
        rows, _ = parse_soil_lab_csv(CANONICAL_CSV.encode())
        assert rows[0]["top_depth_cm"] == 0.0 and rows[0]["bottom_depth_cm"] == 30.0

    def test_idempotency_key_is_file_checksum(self):
        _, r1 = parse_soil_lab_csv(CANONICAL_CSV.encode())
        _, r2 = parse_soil_lab_csv(CANONICAL_CSV.encode())
        assert r1.idempotency_key == r2.idempotency_key
        assert len(r1.file_sha256) == 64


class TestRejections:
    def test_unknown_variable_rejected_row_level(self):
        csv_text = CANONICAL_CSV.replace("soil_ph,7.2", "soil_magic,7.2")
        rows, report = parse_soil_lab_csv(csv_text.encode())
        assert report.rejected == 1
        assert "unknown variable_code" in report.rows[0].message

    def test_inverted_depth_rejected(self):
        # both S002 rows share the depth columns; replace() hits both
        csv_text = CANONICAL_CSV.replace("S002,30,60,cm", "S002,60,30,cm")
        _, report = parse_soil_lab_csv(csv_text.encode())
        assert report.rejected == 2
        assert any("must be greater than top depth" in (r.message or "") for r in report.rows)

    def test_duplicate_natural_key_rejected(self):
        duplicated = CANONICAL_CSV + "S001,0,30,cm,2026-03-15,soil_ph,7.1,pH,,,ph_water_1_2_5,AgriLab,REP-2026-001,\n"
        _, report = parse_soil_lab_csv(duplicated.encode())
        assert report.rejected == 1
        assert "duplicate" in report.rows[-1].message

    def test_unconvertible_unit_rejected(self):
        csv_text = CANONICAL_CSV.replace("soil_ph,7.2,pH", "soil_ph,7.2,furlongs")
        _, report = parse_soil_lab_csv(csv_text.encode())
        assert report.rejected == 1
        assert "no declared conversion" in report.rows[0].message

    def test_unparseable_date_rejected(self):
        csv_text = CANONICAL_CSV.replace("2026-03-15,soil_ph", "March 15,soil_ph")
        _, report = parse_soil_lab_csv(csv_text.encode())
        assert report.rejected >= 1


class TestMappingContract:
    def test_builtin_mapping(self):
        mapping = resolve_mapping(None)
        assert mapping["sample_code"] == "sample_code"

    def test_custom_mapping(self):
        mapping = resolve_mapping({"columns": {"Lab No": "sample_code", "Top (cm)": "top_depth",
                                               "Bottom (cm)": "bottom_depth", "Analyte": "variable_code",
                                               "Result": "value"}})
        assert mapping["Lab No"] == "sample_code"
        assert mapping["Analyte"] == "variable_code"

    def test_missing_required_target_refused(self):
        with pytest.raises(Exception):
            resolve_mapping({"columns": {"Lab No": "sample_code"}})

    def test_unknown_target_refused(self):
        with pytest.raises(Exception):
            resolve_mapping({"columns": {"A": "sample_code", "B": "rocket_science",
                                         "C": "top_depth", "D": "bottom_depth",
                                         "E": "variable_code", "F": "value"}})
