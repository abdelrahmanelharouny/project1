"""Unit tests for the pure report renderers (P3 W5) — no DB, no filesystem
writes (the renderers return bytes; only the service touches storage).

Covered:
- PDF: non-empty bytes with %PDF magic; en + ar (shaped via arabic_reshaper
  + python-bidi when a verified Arabic-capable font exists; honest
  ``rendering_notes`` fallback when none).
- XLSX: ZIP magic (PK), one sheet per section + Metadata sheet, units in
  headers, provenance markers for missing sections.
- CSV: UTF-8 BOM for Excel, primary-table flattening via
  ``primary_section``, KPI/metadata fallbacks.
- Missing sections render with explicit provenance=missing markers in every
  format — never silently dropped.
"""

import io
from typing import Any

import pytest

from app.reports import renderers


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Farm performance",
        "report_type": "farm_performance",
        "primary_section": "field_breakdown",
        "org_name": "Green Acres Co.",
        "farm_name": "North Farm",
        "generated_at": "2026-02-11T09:30:00+00:00",
        "date_range": {"from": "2026-01-13", "to": "2026-02-11"},
        "sections": [
            {
                "key": "overview",
                "heading": "Overview",
                "prose": "Scope summary for the period.",
                "kpis": [
                    {"label": "Fields in scope", "value": 2, "unit": "count",
                     "provenance": "observed"},
                    {"label": "Yield", "value": None, "unit": "t/ha",
                     "provenance": "missing", "note": "Not recorded by the platform."},
                ],
                "provenance": "observed",
                "note": None,
            },
            {
                "key": "field_breakdown",
                "heading": "Field breakdown",
                "table": {
                    "columns": ["Field", "Area", "Observations"],
                    "rows": [["North", 2.5, 41], ["South", None, 0]],
                    "units": [None, "ha", "count"],
                },
                "kpis": [],
                "provenance": "observed",
                "note": None,
            },
            {
                "key": "soil",
                "heading": "Soil measurements",
                "prose": "Section could not be gathered.",
                "table": None,
                "kpis": [],
                "provenance": "missing",
                "note": "No soil measurements recorded for this scope.",
            },
        ],
        "provenance_legend": [
            {"code": "observed", "meaning": "Measured platform data."},
            {"code": "missing", "meaning": "The platform does not hold the data."},
        ],
        "assumptions": ["Water volumes derive from precipitation observations."],
        "limitations": ["No charts are embedded in PDF v1."],
        "sources": ["observations — data-platform providers"],
        "rendering_notes": [],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- PDF
def test_pdf_en_renders_nonempty_with_magic() -> None:
    blob = renderers.render_pdf(_payload(), "en")
    assert isinstance(blob, bytes) and len(blob) > 500
    assert blob[:5] == b"%PDF-"


def test_pdf_includes_identifier_and_closes_cleanly() -> None:
    blob = renderers.render_pdf(_payload(), "en")
    assert b"CropTwist" in blob  # footer identifier


def test_pdf_arabic_renders_without_exception() -> None:
    """Arabic payload through the real path: shaped with the verified Unicode
    TTF when the host has one; either way bytes must come out valid."""
    payload = _payload(
        title="أداء المزرعة",
        org_name="مؤسسة الحقول الخضراء",
        sections=[
            {
                "key": "overview",
                "heading": "نظرة عامة",
                "prose": "ملخص النطاق للفترة المحددة.",
                "kpis": [{"label": "عدد الحقول", "value": 2, "unit": "count",
                          "provenance": "observed"}],
                "provenance": "observed",
            },
            {
                "key": "soil",
                "heading": "قياسات التربة",
                "provenance": "missing",
                "note": "لا توجد قياسات تربة مسجلة.",
            },
        ],
    )
    blob = renderers.render_pdf(payload, "ar")
    assert blob[:5] == b"%PDF-"
    has_font = renderers._find_arabic_font() is not None
    if not has_font:
        assert "arabic font not embedded" in payload["rendering_notes"]


def test_pdf_arabic_without_font_degrades_honestly() -> None:
    """No Arabic-capable font → transliterated output + explicit rendering
    note; NEVER tofu and NEVER a crash."""
    import app.reports.renderers as r

    payload = _payload(title="أداء المزرعة", org_name="مؤسسة الحقول")
    monkey_orig = r._ensure_arabic_font_registered
    r._ensure_arabic_font_registered = lambda: None  # simulate bare host
    try:
        blob = renderers.render_pdf(payload, "ar")
    finally:
        r._ensure_arabic_font_registered = monkey_orig
    assert blob[:5] == b"%PDF-"
    assert payload["rendering_notes"] == ["arabic font not embedded"]


def test_transliterate_arabic_maps_to_latin() -> None:
    out = renderers._transliterate_arabic("العربية")
    assert out and out.isascii()
    # Presentation forms fold back via NFKC before mapping.
    shaped = renderers._shape_arabic("مزرعة")
    assert renderers._transliterate_arabic(shaped).isascii()


# ------------------------------------------------------------------ XLSX
def test_xlsx_renders_zip_magic_and_sheets() -> None:
    from openpyxl import load_workbook

    blob = renderers.render_xlsx(_payload(), "en")
    assert isinstance(blob, bytes) and blob[:4] == b"PK\x03\x04"
    wb = load_workbook(io.BytesIO(blob))
    names = wb.sheetnames
    assert "Metadata" in names
    assert "Overview" in names
    assert "Field breakdown" in names


def test_xlsx_units_in_headers_and_provenance_markers() -> None:
    from openpyxl import load_workbook

    blob = renderers.render_xlsx(_payload(), "en")
    wb = load_workbook(io.BytesIO(blob))
    ws = wb["Field breakdown"]
    # Row 1 heading, row 2 provenance, row 3 blank, row 4 headers.
    assert ws.cell(row=1, column=1).value == "Field breakdown"
    assert "Provenance: observed" in str(ws.cell(row=2, column=1).value)
    headers = [ws.cell(row=4, column=c).value for c in (1, 2, 3)]
    assert headers == ["Field", "Area (ha)", "Observations (count)"]
    assert ws.cell(row=5, column=1).value == "North"

    soil = wb["Soil measurements"]
    assert "Provenance: missing" in str(soil.cell(row=2, column=1).value)
    assert soil.cell(row=4, column=1).value  # honest no-data note present


def test_xlsx_metadata_sheet_carries_context() -> None:
    from openpyxl import load_workbook

    blob = renderers.render_xlsx(_payload(), "en")
    wb = load_workbook(io.BytesIO(blob))
    ws = wb["Metadata"]
    values = {row[0]: row[1] for row in ws.iter_rows(min_row=2, values_only=True)}
    assert values["organization"] == "Green Acres Co."
    assert values["farm"] == "North Farm"
    assert values["period_from"] == "2026-01-13"
    assert values["assumption_1"] == "Water volumes derive from precipitation observations."


# ------------------------------------------------------------------- CSV
def test_csv_bom_and_primary_table_sniff() -> None:
    blob = renderers.render_csv(_payload(), "en")
    assert blob.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM (Excel compatibility)
    text = blob.decode("utf-8-sig")
    assert "# Farm performance" in text
    assert "# section: Field breakdown" in text
    assert "Field,Area (ha),Observations" in text
    assert "North,2.5,41" in text


def test_csv_none_values_render_empty() -> None:
    text = renderers.render_csv(_payload(), "en").decode("utf-8-sig")
    assert "South,,0" in text


def test_csv_falls_back_to_kpis_without_tables() -> None:
    payload = _payload(
        primary_section=None,
        sections=[
            {
                "key": "overview",
                "heading": "Overview",
                "kpis": [{"label": "Fields in scope", "value": 2, "unit": "count",
                          "provenance": "observed"}],
                "provenance": "observed",
            },
            {"key": "soil", "heading": "Soil measurements", "provenance": "missing",
             "note": "No soil measurements recorded."},
        ],
    )
    text = renderers.render_csv(payload, "en").decode("utf-8-sig")
    assert "Label,Value,Unit,Provenance" in text
    assert "Fields in scope,2,count,observed" in text


def test_csv_falls_back_to_metadata_without_kpis() -> None:
    payload = _payload(
        primary_section=None,
        sections=[{"key": "soil", "heading": "Soil measurements",
                   "provenance": "missing", "note": "No data."}],
    )
    payload.pop("assumptions")
    text = renderers.render_csv(payload, "en").decode("utf-8-sig")
    assert "report_title,Farm performance" in text
    assert "organization,Green Acres Co." in text


def test_csv_primary_section_preferred_over_first_table() -> None:
    payload = _payload(
        primary_section="seasonality",
        sections=[
            {
                "key": "field_breakdown",
                "heading": "Field breakdown",
                "table": {"columns": ["Field"], "rows": [["North"]], "units": None},
                "provenance": "observed",
            },
            {
                "key": "seasonality",
                "heading": "Seasonal observations",
                "table": {"columns": ["Month", "Sum"], "rows": [["2026-01", 12.5]],
                          "units": [None, "mm"]},
                "provenance": "observed",
            },
        ],
    )
    text = renderers.render_csv(payload, "en").decode("utf-8-sig")
    assert "# section: Seasonal observations" in text
    assert "Month,Sum (mm)" in text


# ------------------------------------------------- missing-section honesty
def test_missing_sections_render_in_every_format() -> None:
    payload = _payload(
        sections=[
            {"key": "soil", "heading": "Soil measurements", "provenance": "missing",
             "note": "No soil measurements recorded for this scope."},
        ],
        primary_section=None,
    )
    pdf = renderers.render_pdf(payload, "en")
    assert pdf[:5] == b"%PDF-"
    xlsx = renderers.render_xlsx(payload, "en")
    assert xlsx[:4] == b"PK\x03\x04"
    csv_blob = renderers.render_csv(payload, "en")
    assert csv_blob.startswith(b"\xef\xbb\xbf")


def test_normalize_fills_defaults_for_empty_payload() -> None:
    blob = renderers.render_csv({}, "en")
    text = blob.decode("utf-8-sig")
    assert "# Report" in text  # default title, still valid output


# ------------------------------------------------------------- dispatcher
def test_render_dispatch_and_unknown_format() -> None:
    payload = _payload()
    for fmt, magic in (("pdf", b"%PDF-"), ("xlsx", b"PK\x03\x04"), ("csv", b"\xef\xbb\xbf")):
        blob = renderers.render(payload, fmt, "en")
        assert blob[: len(magic)] == magic
    with pytest.raises(ValueError):
        renderers.render(payload, "docx", "en")


def test_all_report_type_registry_keys_have_titles() -> None:
    """Renderer chrome and service payloads agree with the registry — every
    machine key carries both locale titles and default sections."""
    from app.reports import contracts

    expected = {
        "farm_performance", "field_analysis", "soil_health", "water", "rotation",
        "seasonal", "environmental_risk", "recommendations", "org_executive",
        "custom_range",
    }
    assert set(contracts.REPORT_TYPES) == expected
    for key, spec in contracts.REPORT_TYPES.items():
        assert spec.title_en and spec.title_ar
        assert spec.default_sections, key
    assert contracts.REPORT_STATUSES == ("queued", "running", "succeeded", "failed", "expired")
    assert contracts.REPORT_FORMATS == ("pdf", "xlsx", "csv")
    assert contracts.REPORT_LOCALES == ("en", "ar")
