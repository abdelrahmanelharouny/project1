"""Pure report renderers (P3 W5) — no DB, no settings, no I/O beyond bytes.

Input is a NORMALIZED REPORT PAYLOAD (see ``app.reports.contracts``):

    {
      "title": str,
      "report_type": str,            # machine key (also used for CSV choice)
      "primary_section": str|None,   # section key preferred for CSV export
      "org_name": str,
      "farm_name": str|None,
      "generated_at": str|datetime,  # ISO 8601, rendered as UTC
      "date_range": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
      "sections": [ {
           "key": str,               # optional machine key
           "heading": str,
           "prose": str|None,
           "table": {"columns": [...], "rows": [[...]], "units": [...]}|None,
           "kpis": [{"label","value","unit","provenance"}],
           "provenance": "observed"|"model_derived"|"simulated"|"missing",
           "note": str|None,
      } ],
      "provenance_legend": [{"code": str, "meaning": str}],
      "assumptions": [str],
      "limitations": [str],
      "sources": [str],
      "rendering_notes": [str],       # appended to by renderers (honesty)
    }

Every renderer returns ``bytes`` and NEVER touches the filesystem. When a
renderer must degrade (e.g. Arabic requested but no Arabic-capable font on
the host) it appends an honest entry to ``payload["rendering_notes"]``
instead of silently producing tofu glyphs.

Honest limitations (v1, deliberately): no charts embedded in the PDF, no
Arabic shaping inside XLSX/CSV cell values (Excel shapes Arabic natively),
and the PDF preview caps table rows at ``PDF_ROWS_CAP`` with an explicit
omission note.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import xml.sax.saxutils as saxutils
from datetime import UTC, datetime
from typing import Any

# ------------------------------------------------------------------ locales
LOCALES: tuple[str, ...] = ("en", "ar")

MISSING_EN = "—"
MISSING_AR = "غير متوفر"

CHROME: dict[str, dict[str, str]] = {
    "en": {
        "org": "Organization",
        "farm": "Farm",
        "report_type": "Report type",
        "generated": "Generated",
        "date_range": "Period",
        "to": "to",
        "assumptions": "Assumptions",
        "limitations": "Limitations",
        "sources": "Sources",
        "provenance_legend": "Provenance legend",
        "provenance": "Provenance",
        "kpis": "Key figures",
        "note": "Note",
        "metadata": "Metadata",
        "page": "Page",
        "label": "Label",
        "value": "Value",
        "unit": "Unit",
        "missing": MISSING_EN,
        "no_data": "No data available for this section in the selected period.",
        "rows_omitted": "… {n} more rows omitted (PDF preview cap)",
        "identifier": "CropTwist",
    },
    "ar": {
        "org": "المؤسسة",
        "farm": "المزرعة",
        "report_type": "نوع التقرير",
        "generated": "تاريخ الإنشاء",
        "date_range": "الفترة",
        "to": "إلى",
        "assumptions": "الافتراضات",
        "limitations": "القيود",
        "sources": "المصادر",
        "provenance_legend": "مفتاح مصدر البيانات",
        "provenance": "المصدر",
        "kpis": "أرقام رئيسية",
        "note": "ملاحظة",
        "metadata": "البيانات الوصفية",
        "page": "صفحة",
        "label": "البند",
        "value": "القيمة",
        "unit": "الوحدة",
        "missing": MISSING_AR,
        "no_data": "لا توجد بيانات متاحة لهذا القسم في الفترة المحددة.",
        "rows_omitted": "… تم حذف {n} صفاً إضافياً (حد معاينة PDF)",
        "identifier": "CropTwist",
    },
}

# Legend shown when the payload does not carry one (provenance vocabulary is
# the platform-wide contract from app/analytics).
DEFAULT_LEGEND: list[dict[str, str]] = [
    {"code": "observed", "meaning": "Measured platform data."},
    {"code": "model_derived", "meaning": "Computed by a documented formula from observed inputs."},
    {"code": "simulated", "meaning": "Synthetic fixture data — always labelled."},
    {"code": "missing", "meaning": "The platform does not hold the required data."},
]

PDF_ROWS_CAP = 300

# ------------------------------------------------------- Arabic text shaping
_ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
)


def _has_arabic(text: str) -> bool:
    return any(
        lo <= ord(ch) <= hi
        for ch in text
        for lo, hi in _ARABIC_RANGES
    )


# Compact Arabic→Latin transliteration (applied AFTER NFKC, which folds the
# presentation forms produced by the shaper back to base letters).
_AR_LATIN: dict[str, str] = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "a'", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y",
    "آ": "aa", "أ": "a", "إ": "i", "ٱ": "a", " ئ": "y", "ؤ": "w", "ى": "a",
    "ة": "h", "ء": "'",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "،": ",", "؛": ";", "؟": "?",
}
for _haraka in "ًٌٍَُِّْٰ":
    _AR_LATIN[_haraka] = ""


def _transliterate_arabic(text: str) -> str:
    """Last-resort Latin fallback when no Arabic-capable font is embedded."""
    folded = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    for ch in folded:
        out.append(_AR_LATIN.get(ch, ch if ord(ch) < 0x0600 else ""))
    return "".join(out)


def _find_arabic_font() -> tuple[str, str | None] | None:
    """Locate a Unicode TTF with real Arabic coverage on this host.

    Returns (regular_path, bold_path|None) or None. Coverage is VERIFIED
    (base Arabic + presentation forms B) — a font that would render tofu is
    treated as absent so the caller can degrade honestly instead.
    """
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    )
    bold_candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    )
    probe = (0x0627, 0x0644, 0x0639, 0xFEDF, 0xFEE0, 0xFE8D, 0xFEF4)
    for regular in candidates:
        try:
            with open(regular, "rb") as fh:
                if not fh.read(2):
                    continue
        except OSError:
            continue
        if not _font_covers(regular, probe):
            continue
        bold: str | None = None
        for cand in bold_candidates:
            try:
                with open(cand, "rb") as fh:
                    fh.read(2)
                if _font_covers(cand, probe):
                    bold = cand
                    break
            except OSError:
                continue
        return regular, bold
    return None


def _font_covers(path: str, codepoints: tuple[int, ...]) -> bool:
    """True when the TTF at `path` maps every codepoint in `codepoints`."""
    try:
        from reportlab.pdfbase.ttfonts import TTFontFile

        font = TTFontFile(path)
        return all(cp in font.charToGlyph for cp in codepoints)
    except Exception:  # unreadable/unsupported font → do not trust it
        return False


_FONT_STATE: dict[str, str] = {}


def _ensure_arabic_font_registered() -> tuple[str, str] | None:
    """Register the verified Arabic-capable TTF with reportlab (once per
    process). Returns (base_font, heading_font) or None when no usable font
    exists — the caller then degrades honestly."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _FONT_STATE:
        return (_FONT_STATE["base"], _FONT_STATE["heading"]) if "base" in _FONT_STATE else None
    found = _find_arabic_font()
    if found is None:
        _FONT_STATE["unavailable"] = "1"
        return None
    regular_path, bold_path = found
    try:
        pdfmetrics.registerFont(TTFont("CropTwistUnicode", regular_path))
        base = "CropTwistUnicode"
        if bold_path:
            pdfmetrics.registerFont(TTFont("CropTwistUnicode-Bold", bold_path))
            heading = "CropTwistUnicode-Bold"
        else:
            heading = base
    except Exception:
        _FONT_STATE["unavailable"] = "1"
        return None
    _FONT_STATE["base"] = base
    _FONT_STATE["heading"] = heading
    return base, heading


def _shape_arabic(text: str) -> str:
    """Reshape + bidi-reorder Arabic text for visual rendering engines."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text))


# --------------------------------------------------------------- normalization
def _as_utc_text(value: Any, locale: str) -> str:
    """Render a datetime/ISO string in locale format, always labelled UTC."""
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if dt is None:
        return str(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    if locale == "ar":
        return dt.strftime("%Y/%m/%d %H:%M") + " UTC"
    return dt.strftime("%d %b %Y %H:%M") + " UTC"


def _fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)


def _normalize(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """Fill defaults and return a shallow-normalized copy of the payload."""
    data = dict(payload or {})
    data.setdefault("title", "Report")
    data.setdefault("report_type", "custom_range")
    data.setdefault("primary_section", None)
    data.setdefault("org_name", "")
    data.setdefault("farm_name", None)
    data["generated_at"] = _as_utc_text(data.get("generated_at") or datetime.now(UTC), locale)
    dr = dict(data.get("date_range") or {})
    data["date_range"] = {
        "from": _fmt_date(dr.get("from") or ""),
        "to": _fmt_date(dr.get("to") or ""),
    }
    sections = []
    for section in data.get("sections") or []:
        sec = dict(section or {})
        sec.setdefault("heading", "")
        sec.setdefault("prose", None)
        sec.setdefault("table", None)
        sec.setdefault("kpis", [])
        sec.setdefault("provenance", "missing")
        sec.setdefault("note", None)
        sections.append(sec)
    data["sections"] = sections
    data.setdefault("provenance_legend", DEFAULT_LEGEND)
    for key in ("assumptions", "limitations", "sources", "rendering_notes"):
        data.setdefault(key, [])
    return data


def _chrome(locale: str) -> dict[str, str]:
    return CHROME.get(locale, CHROME["en"])


def _missing(locale: str) -> str:
    return MISSING_AR if locale == "ar" else MISSING_EN


def _cell_text(value: Any, locale: str) -> str:
    if value is None:
        return _missing(locale)
    return str(value)


def _headers_with_units(table: dict[str, Any]) -> list[str]:
    columns = [str(c) for c in table.get("columns") or []]
    units = table.get("units")
    if not units:
        return columns
    out = []
    for i, col in enumerate(columns):
        unit = units[i] if i < len(units) else None
        out.append(f"{col} ({unit})" if unit else col)
    return out


def _primary_table(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Choose the table flattened into the CSV export.

    Preference: the section whose key matches payload["primary_section"]
    (when it has a table) → the first section with a table → None.
    """
    wanted = payload.get("primary_section")
    sections = payload.get("sections") or []
    if wanted:
        for sec in sections:
            if sec.get("key") == wanted and sec.get("table"):
                return sec["table"], sec.get("heading")
    for sec in sections:
        if sec.get("table"):
            return sec["table"], sec.get("heading")
    return None, None


def _kpi_table(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows: list[list[Any]] = []
    for sec in payload.get("sections") or []:
        for kpi in sec.get("kpis") or []:
            rows.append([
                kpi.get("label"),
                "" if kpi.get("value") is None else kpi.get("value"),
                kpi.get("unit") or "",
                kpi.get("provenance") or "missing",
            ])
    if not rows:
        return None
    return {
        "columns": ["Label", "Value", "Unit", "Provenance"],
        "rows": rows,
        "units": None,
    }


def _meta_table(payload: dict[str, Any]) -> dict[str, Any]:
    t = _chrome("en")
    rows = [
        ["report_title", payload.get("title", "")],
        ["report_type", payload.get("report_type", "")],
        ["organization", payload.get("org_name", "")],
        ["farm", payload.get("farm_name") or ""],
        ["generated_at", payload.get("generated_at", "")],
        ["period_from", payload["date_range"]["from"]],
        ["period_to", payload["date_range"]["to"]],
    ]
    for i, item in enumerate(payload.get("assumptions") or [], start=1):
        rows.append([f"assumption_{i}", item])
    for i, item in enumerate(payload.get("limitations") or [], start=1):
        rows.append([f"limitation_{i}", item])
    for i, item in enumerate(payload.get("sources") or [], start=1):
        rows.append([f"source_{i}", item])
    for note in payload.get("rendering_notes") or []:
        rows.append(["rendering_note", note])
    return {"columns": [t["label"], t["value"]], "rows": rows, "units": None}


# ------------------------------------------------------------------- PDF
def render_pdf(payload: dict[str, Any], locale: str = "en") -> bytes:
    """Render the payload as a paginated A4 PDF (platypus layout).

    Arabic (locale=ar): text is shaped via arabic_reshaper + python-bidi and
    drawn with a verified Unicode TTF when one exists on the host; without
    one the document falls back to transliterated Latin and records
    ``"arabic font not embedded"`` in payload["rendering_notes"] — never
    silent tofu.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    data = _normalize(payload, locale)
    t = _chrome(locale)
    rtl = locale == "ar"

    base_font = "Helvetica"
    heading_font = "Helvetica-Bold"
    if rtl and _has_arabic(_flatten_text(data)):
        registered = _ensure_arabic_font_registered()
        if registered is None:
            data["rendering_notes"].append("arabic font not embedded")
        else:
            base_font, heading_font = registered

    def shape(text: str) -> str:
        if rtl and _has_arabic(text) and base_font != "Helvetica":
            try:
                return _shape_arabic(text)
            except Exception:
                return _transliterate_arabic(text)
        if rtl and _has_arabic(text) and base_font == "Helvetica":
            return _transliterate_arabic(text)
        return text

    alignment = TA_RIGHT if rtl else TA_LEFT
    wrap = "RTL" if rtl else None

    def style(name: str, size: int, *, bold: bool = False, grey: bool = False) -> ParagraphStyle:
        return ParagraphStyle(
            name,
            fontName=heading_font if bold else base_font,
            fontSize=size,
            leading=size * 1.35,
            alignment=alignment,
            wordWrap=wrap,
            textColor=colors.HexColor("#555555") if grey else colors.HexColor("#111111"),
            spaceAfter=4,
        )

    st_title = style("title", 18, bold=True)
    st_h2 = style("h2", 13, bold=True)
    st_body = style("body", 9.5)
    st_small = style("small", 8, grey=True)
    st_cell = ParagraphStyle(
        "cell", fontName=base_font, fontSize=7.5, leading=9.5,
        alignment=alignment, wordWrap=wrap,
    )
    st_cell_head = ParagraphStyle(
        "cellhead", fontName=heading_font, fontSize=7.5, leading=9.5,
        alignment=alignment, wordWrap=wrap, textColor=colors.white,
    )

    def para(text: str, st: ParagraphStyle) -> Paragraph:
        return Paragraph(saxutils.escape(shape(str(text))), st)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=48,
        title=str(data.get("title") or "Report"),
        author=t["identifier"],
    )

    def footer(canvas, _doc) -> None:  # noqa: ANN001 — reportlab signature
        canvas.saveState()
        canvas.setFont(base_font, 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        label = shape(f"{t['identifier']} — {t['page']} {canvas.getPageNumber()}")
        if rtl:
            canvas.drawRightString(A4[0] - 42, 30, label)
        else:
            canvas.drawString(42, 30, label)
        canvas.restoreState()

    story: list[Any] = []
    story.append(para(data.get("title") or "Report", st_title))
    meta_lines = [
        f"{t['org']}: {data.get('org_name') or t['missing']}",
    ]
    if data.get("farm_name"):
        meta_lines.append(f"{t['farm']}: {data['farm_name']}")
    meta_lines.append(f"{t['report_type']}: {data.get('report_type')}")
    meta_lines.append(f"{t['generated']}: {data['generated_at']}")
    meta_lines.append(
        f"{t['date_range']}: {data['date_range']['from']} {t['to']} {data['date_range']['to']}"
    )
    for line in meta_lines:
        story.append(para(line, st_body))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#BBBBBB")))
    story.append(Spacer(1, 8))

    for sec in data["sections"]:
        story.append(para(sec["heading"] or "", st_h2))
        story.append(para(f"{t['provenance']}: {sec['provenance']}", st_small))
        if sec.get("prose"):
            story.append(para(sec["prose"], st_body))
        if sec.get("note"):
            story.append(para(f"{t['note']}: {sec['note']}", st_small))
        kpis = sec.get("kpis") or []
        if kpis:
            story.append(Spacer(1, 3))
            story.append(para(t["kpis"], st_body))
            kpi_rows = [[t["label"], t["value"], t["unit"], t["provenance"]]]
            for kpi in kpis:
                value = kpi.get("value")
                kpi_rows.append([
                    kpi.get("label") or "",
                    _cell_text(value, locale),
                    kpi.get("unit") or "",
                    kpi.get("provenance") or "missing",
                ])
            story.append(_styled_table(kpi_rows, st_cell, st_cell_head, colors, rtl))
            story.append(Spacer(1, 4))
        table = sec.get("table")
        if table and (table.get("rows") or table.get("columns")):
            story.append(Spacer(1, 3))
            headers = [shape(h) for h in _headers_with_units(table)]
            rows = [[_cell_text(v, locale) for v in row] for row in (table.get("rows") or [])]
            omitted = 0
            if len(rows) > PDF_ROWS_CAP:
                omitted = len(rows) - PDF_ROWS_CAP
                rows = rows[:PDF_ROWS_CAP]
            if not rows:
                rows = [[t["no_data"]] + [""] * max(0, len(headers) - 1)]
            story.append(_styled_table([headers, *rows], st_cell, st_cell_head, colors, rtl))
            if omitted:
                story.append(para(t["rows_omitted"].format(n=omitted), st_small))
        elif not kpis:
            story.append(para(t["no_data"], st_small))
        story.append(Spacer(1, 10))

    story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#BBBBBB")))
    story.append(para(t["provenance_legend"], st_h2))
    for entry in data.get("provenance_legend") or []:
        story.append(para(f"{entry.get('code')}: {entry.get('meaning')}", st_small))
    for key, title_key in (
        ("assumptions", "assumptions"),
        ("limitations", "limitations"),
        ("sources", "sources"),
    ):
        items = data.get(key) or []
        story.append(Spacer(1, 6))
        story.append(para(t[title_key], st_h2))
        if not items:
            story.append(para(t["missing"], st_small))
        for item in items:
            story.append(para(f"• {item}", st_body))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _flatten_text(data: dict[str, Any]) -> str:
    """Every display string in the payload, for the Arabic-detection probe."""
    parts: list[str] = [
        str(data.get("title") or ""), str(data.get("org_name") or ""),
        str(data.get("farm_name") or ""),
    ]
    for sec in data.get("sections") or []:
        parts.append(str(sec.get("heading") or ""))
        parts.append(str(sec.get("prose") or ""))
        parts.append(str(sec.get("note") or ""))
        table = sec.get("table") or {}
        parts.extend(str(c) for c in table.get("columns") or [])
        for row in table.get("rows") or []:
            parts.extend(str(v) for v in row if v is not None)
        for kpi in sec.get("kpis") or []:
            parts.append(str(kpi.get("label") or ""))
    for key in ("assumptions", "limitations", "sources"):
        parts.extend(str(x) for x in data.get(key) or [])
    return " ".join(parts)


def _styled_table(rows: list[list[Any]], st_cell, st_cell_head, colors, rtl: bool):  # noqa: ANN001
    """Build a wrapped reportlab Table with header styling."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, Table, TableStyle

    ncols = max(len(r) for r in rows)
    norm = [list(r) + [""] * (ncols - len(r)) for r in rows]
    wrapped: list[list[Any]] = []
    for i, row in enumerate(norm):
        st = st_cell_head if i == 0 else st_cell
        wrapped.append([Paragraph(str(v), st) for v in row])
    page_w = A4[0] - 84  # usable width between the 42pt margins
    widths = [page_w / ncols] * ncols
    tbl = Table(wrapped, colWidths=widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#33526B")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl




# ------------------------------------------------------------------- XLSX
def render_xlsx(payload: dict[str, Any], locale: str = "en") -> bytes:
    """Render the payload as an XLSX workbook.

    One sheet per section (heading as sheet name, sanitized to Excel's 31-char
    limit), styled header row, units embedded in column headers, provenance
    column on KPI blocks, plus a "Metadata" sheet (org, farm, generated_at,
    period, assumptions, limitations, sources, rendering notes). Excel shapes
    Arabic text natively — cell values are stored unshaped (logical order).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = _normalize(payload, locale)
    t = _chrome(locale)

    wb = Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill("solid", fgColor="33526B")
    header_font = Font(bold=True, color="FFFFFF")
    title_font = Font(bold=True, size=12)
    small_font = Font(size=9, color="666666")

    used_names: set[str] = set()

    def sheet_name(heading: str, index: int) -> str:
        cleaned = "".join(c for c in str(heading or t["metadata"]) if c not in '[]:*?/\\')
        cleaned = cleaned.strip() or t["metadata"]
        name = cleaned[:28]
        candidate = name
        n = 1
        while candidate.lower() in used_names:
            suffix = f" ({n})"
            candidate = name[: 28 - len(suffix)] + suffix
            n += 1
        used_names.add(candidate.lower())
        return candidate

    for index, sec in enumerate(data["sections"], start=1):
        ws = wb.create_sheet(title=sheet_name(sec.get("heading", ""), index))
        ws.sheet_view.rightToLeft = locale == "ar"
        row = 1
        ws.cell(row=row, column=1, value=sec.get("heading") or "").font = title_font
        row += 1
        prov_line = f"{t['provenance']}: {sec.get('provenance')}"
        if sec.get("note"):
            prov_line += f" | {t['note']}: {sec['note']}"
        ws.cell(row=row, column=1, value=prov_line).font = small_font
        row += 2
        kpis = sec.get("kpis") or []
        if kpis:
            ws.cell(row=row, column=1, value=t["kpis"]).font = title_font
            row += 1
            headers = [t["label"], t["value"], t["unit"], t["provenance"]]
            for col, header in enumerate(headers, start=1):
                cell = ws.cell(row=row, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
            row += 1
            for kpi in kpis:
                ws.cell(row=row, column=1, value=kpi.get("label"))
                value = kpi.get("value")
                ws.cell(row=row, column=2, value=value if value is not None else t["missing"])
                ws.cell(row=row, column=3, value=kpi.get("unit") or "")
                ws.cell(row=row, column=4, value=kpi.get("provenance") or "missing")
                row += 1
            row += 1
        table = sec.get("table")
        if table and (table.get("columns") or table.get("rows")):
            headers = _headers_with_units(table)
            for col, header in enumerate(headers, start=1):
                cell = ws.cell(row=row, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            row += 1
            for record in table.get("rows") or []:
                for col, value in enumerate(record, start=1):
                    ws.cell(
                        row=row, column=col,
                        value=value if value is not None else t["missing"],
                    )
                row += 1
        elif not kpis:
            ws.cell(row=row, column=1, value=t["no_data"]).font = small_font
            row += 1
        if sec.get("prose"):
            row += 1
            ws.cell(row=row, column=1, value=str(sec["prose"])).font = small_font
        for col_idx in range(1, 9):
            ws.column_dimensions[get_column_letter(col_idx)].width = 22

    # Metadata sheet (always last).
    meta = _meta_table(data)
    ws = wb.create_sheet(title=t["metadata"][:31])
    ws.sheet_view.rightToLeft = locale == "ar"
    for col, header in enumerate(meta["columns"], start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
    for r, record in enumerate(meta["rows"], start=2):
        ws.cell(row=r, column=1, value=record[0])
        ws.cell(row=r, column=2, value=record[1])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# -------------------------------------------------------------------- CSV
def render_csv(payload: dict[str, Any], locale: str = "en") -> bytes:
    """Render the payload as a single UTF-8 **with BOM** CSV (Excel-friendly).

    The flattened table is the section selected by payload["primary_section"]
    (falling back to the first section that carries a table, then to KPIs,
    then to a metadata listing). Header comment lines carry the report
    identity and provenance.
    """
    data = _normalize(payload, locale)
    t = _chrome(locale)

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow([f"# {data.get('title') or 'Report'}"])
    writer.writerow([f"# {t['org']}: {data.get('org_name') or ''}"])
    if data.get("farm_name"):
        writer.writerow([f"# {t['farm']}: {data['farm_name']}"])
    writer.writerow([f"# {t['report_type']}: {data.get('report_type')}"])
    writer.writerow([f"# {t['generated']}: {data['generated_at']}"])
    writer.writerow([
        f"# {t['date_range']}: {data['date_range']['from']} {t['to']} {data['date_range']['to']}",
    ])
    for note in data.get("rendering_notes") or []:
        writer.writerow([f"# rendering_note: {note}"])

    table, section_heading = _primary_table(data)
    if table is not None:
        writer.writerow([])
        writer.writerow([f"# section: {section_heading or ''}"])
        headers = _headers_with_units(table)
        writer.writerow(headers)
        for record in table.get("rows") or []:
            writer.writerow(["" if v is None else v for v in record])
    else:
        kpis = _kpi_table(data)
        if kpis is not None:
            writer.writerow([])
            writer.writerow([f"# {t['kpis']}"])
            writer.writerow(kpis["columns"])
            writer.writerows(kpis["rows"])
        else:
            meta = _meta_table(data)
            writer.writerow([])
            writer.writerow([f"# {t['metadata']}"])
            writer.writerow(meta["columns"])
            writer.writerows(meta["rows"])

    # utf-8-sig prepends the BOM so Excel detects the encoding.
    return buf.getvalue().encode("utf-8-sig")


RENDERERS: dict[str, Any] = {
    "pdf": render_pdf,
    "xlsx": render_xlsx,
    "csv": render_csv,
}


def render(payload: dict[str, Any], output_format: str, locale: str = "en") -> bytes:
    """Dispatch by format; unknown formats raise ValueError (service maps to
    ValidationFailed)."""
    fn = RENDERERS.get(output_format)
    if fn is None:
        raise ValueError(f"Unknown report format '{output_format}'.")
    return fn(payload, locale)
