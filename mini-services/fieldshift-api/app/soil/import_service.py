"""Soil laboratory CSV import (Milestone 6B.1 §4.4 — Step 3).

An extensible, mapping-contract importer: a mapping spec (JSON) declares how
a laboratory template's columns map onto the canonical soil schema. The
built-in template (`canonical_lab_v1`) accepts the canonical column names;
client-supplied mappings translate any other template. Design properties:

- field validation, sample identification, depth validation (cm/mm/m),
  property mapping through the canonical variable dictionary,
- unit normalization with DECLARED conversions only,
- analytical method mapping (method descriptors become registry rows),
- detection-limit parsing ("<0.05" → qualifier + limit, value None — never
  silently zero),
- missing-value handling, duplicate detection (natural key), row-level
  provenance, file sha256, idempotency by checksum, import warnings,
  rejected-row reporting.

PDF/image report extraction is deliberately NOT implemented — unverified OCR
is never accepted as a validated laboratory measurement.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.soil import contracts as sc
from app.soil.layers import make_depth_interval

BUILTIN_TEMPLATE = "canonical_lab_v1"

CANONICAL_COLUMNS = {
    "sample_code": "sample_code",
    "top_depth": "top_depth",
    "bottom_depth": "bottom_depth",
    "depth_unit": "depth_unit",
    "observed_at": "observed_at",
    "variable_code": "variable_code",
    "value": "value",
    "unit": "unit",
    "detection_limit": "detection_limit",
    "result_qualifier": "result_qualifier",
    "method_code": "method_code",
}

# declared unit conversions (unit → canonical unit factor)
UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("g/kg", "g/kg"): 1.0,
    ("%", "g/kg"): 10.0,
    ("mg/kg", "mg/kg"): 1.0,
    ("ppm", "mg/kg"): 1.0,
    ("g/cm3", "g/cm3"): 1.0,
    ("kg/dm3", "g/cm3"): 1.0,
    ("dS/m", "dS/m"): 1.0,
    ("mS/cm", "dS/m"): 1.0,
    ("vol%", "vol%"): 1.0,
    ("cmolc/kg", "cmol(+)/kg"): 1.0,
    ("pH", "pH"): 1.0,
}


class SoilImportError(ValueError):
    pass


@dataclass
class ImportRowResult:
    row_number: int
    status: str                 # imported | rejected | warning
    sample_code: str | None
    message: str | None = None
    measurement_id: str | None = None


@dataclass
class ImportReport:
    template: str
    file_sha256: str
    rows_total: int
    imported: int
    rejected: int
    warnings_count: int
    rows: list[ImportRowResult] = field(default_factory=list)
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "file_sha256": self.file_sha256,
            "rows_total": self.rows_total,
            "imported": self.imported,
            "rejected": self.rejected,
            "warnings": self.warnings_count,
            "rows": [
                {
                    "row_number": r.row_number,
                    "status": r.status,
                    "sample_code": r.sample_code,
                    "message": r.message,
                    "measurement_id": r.measurement_id,
                }
                for r in self.rows
            ],
            "idempotency_key": self.idempotency_key,
        }


def resolve_mapping(mapping_spec: dict[str, Any] | None) -> dict[str, str]:
    """Column-name → canonical-field mapping.

    No spec (or a spec without a 'columns' key — e.g. configuration-only
    specs carrying default_field_id) uses the built-in canonical template.
    A provided 'columns' object maps template columns onto canonical fields;
    unknown targets are refused."""
    if mapping_spec is None:
        return dict(CANONICAL_COLUMNS)
    columns = mapping_spec.get("columns")
    if columns is None:
        return dict(CANONICAL_COLUMNS)
    if not isinstance(columns, dict) or not columns:
        raise SoilImportError("mapping spec 'columns' must be a non-empty object")
    resolved: dict[str, str] = {}
    for column, target in columns.items():
        if target not in CANONICAL_COLUMNS.values():
            raise SoilImportError(
                f"mapping target '{target}' is not a canonical field "
                f"(known: {', '.join(sorted(CANONICAL_COLUMNS.values()))})"
            )
        resolved[str(column)] = target
    for required in ("sample_code", "top_depth", "bottom_depth", "variable_code", "value"):
        if required not in resolved.values():
            raise SoilImportError(f"mapping is missing the required target '{required}'")
    return resolved


def _cell(row: dict[str, str], mapping: dict[str, str], canonical: str) -> str | None:
    for column, target in mapping.items():
        if target == canonical:
            raw = row.get(column)
            if raw is None or not str(raw).strip():
                return None
            return str(raw).strip()
    return None


def _parse_value(raw: str | None) -> tuple[float | None, float | None, str | None]:
    """Parse a value cell → (value, detection_limit, qualifier).

    '<0.05' → (None, 0.05, '<')  — below detection: the VALUE is unknown,
    never zero. Plain numbers parse directly."""
    if raw is None:
        return None, None, None
    text = raw.strip()
    if not text or text.upper() in {"NA", "N/A", "NULL", "ND", "-"}:
        return None, None, None
    if text.startswith("<"):
        limit_text = text[1:].strip()
        try:
            return None, float(limit_text), "<"
        except ValueError:
            raise SoilImportError(f"unparseable detection limit '{text}'") from None
    if text.startswith(">"):
        limit_text = text[1:].strip()
        try:
            return None, float(limit_text), ">"
        except ValueError:
            raise SoilImportError(f"unparseable qualifier limit '{text}'") from None
    try:
        return float(text), None, None
    except ValueError:
        raise SoilImportError(f"unparseable value '{text}'") from None


def _parse_date_cell(raw: str | None, row_number: int) -> date:
    if raw is None:
        raise SoilImportError("observed_at is required")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise SoilImportError(f"unparseable date '{raw}' (supported: YYYY-MM-DD, YYYY/MM/DD, DD.MM.YYYY, DD/MM/YYYY)")


def _convert_unit(value: float, declared: str | None, canonical: str, row_number: int) -> tuple[float, str]:
    """Normalize a declared unit to the canonical unit via DECLARED factors."""
    if declared is None:
        return value, canonical  # importer default: the canonical unit is assumed and recorded
    factor = UNIT_CONVERSIONS.get((declared, canonical))
    if factor is None:
        raise SoilImportError(
            f"no declared conversion {declared} → {canonical} (unit left unmapped — "
            "row rejected rather than guessed)"
        )
    return value * factor, canonical


def parse_soil_lab_csv(
    content: bytes,
    *,
    mapping_spec: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], ImportReport]:
    """Parse CSV rows into canonical measurement dicts + the import report.

    Pure parsing/validation (no DB): the caller persists within its own
    transaction. Idempotency: the file sha256 doubles as the natural
    idempotency key."""
    text = content.decode("utf-8-sig")
    sha256 = hashlib.sha256(content).hexdigest()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise SoilImportError("empty CSV — no header row")
    mapping = resolve_mapping(mapping_spec)
    unknown_columns = [
        c for c in reader.fieldnames
        if c not in mapping and c not in ("notes", "laboratory_name", "report_reference")
    ]

    results: list[dict[str, Any]] = []
    report = ImportReport(
        template=BUILTIN_TEMPLATE if mapping_spec is None else str(mapping_spec.get("template", "custom")),
        file_sha256=sha256,
        rows_total=0,
        imported=0,
        rejected=0,
        warnings_count=0,
        idempotency_key=f"soil-lab:{sha256[:16]}",
    )

    seen_keys: set[tuple] = set()
    for row_number, row in enumerate(reader, start=2):
        report.rows_total += 1
        sample_code = _cell(row, mapping, "sample_code")
        try:
            if not sample_code:
                raise SoilImportError("sample_code is required")
            variable_code = _cell(row, mapping, "variable_code")
            if not variable_code:
                raise SoilImportError("variable_code is required")
            vdef = sc.soil_variable_definition(variable_code)
            if vdef is None:
                raise SoilImportError(f"unknown variable_code '{variable_code}'")
            top_raw = _cell(row, mapping, "top_depth")
            bottom_raw = _cell(row, mapping, "bottom_depth")
            if top_raw is None or bottom_raw is None:
                raise SoilImportError("depth columns are required")
            depth_unit = _cell(row, mapping, "depth_unit") or "cm"
            interval = make_depth_interval(float(top_raw), float(bottom_raw), depth_unit)
            value_raw = _cell(row, mapping, "value")
            value, detection_limit, qualifier = _parse_value(value_raw)
            declared_unit = _cell(row, mapping, "unit") or vdef["unit"]
            if value is not None:
                value, canonical_unit = _convert_unit(value, declared_unit, vdef["unit"], row_number)
            else:
                canonical_unit = vdef["unit"]
            observed_at = _parse_date_cell(_cell(row, mapping, "observed_at"), row_number)

            natural_key = (
                sample_code, variable_code,
                interval.top_cm, interval.bottom_cm,
                observed_at.isoformat(), _cell(row, mapping, "method_code"),
            )
            if natural_key in seen_keys:
                raise SoilImportError("duplicate row (same sample/variable/depth/date/method)")
            seen_keys.add(natural_key)

            if detection_limit is not None and qualifier == "<":
                report.warnings_count += 1
                row_status = "warning"
                message = "value below detection limit — recorded with qualifier, not zero"
            else:
                row_status = "imported"
                message = None

            results.append({
                "sample_code": sample_code,
                "variable_code": variable_code,
                "value": value,
                "unit": canonical_unit,
                "top_depth_cm": interval.top_cm,
                "bottom_depth_cm": interval.bottom_cm,
                "original_depth_unit": interval.original_unit,
                "original_top": interval.original_top,
                "original_bottom": interval.original_bottom,
                "observed_at": observed_at.isoformat(),
                "detection_limit": detection_limit,
                "result_qualifier": qualifier,
                "method_code": _cell(row, mapping, "method_code"),
                "laboratory_name": row.get("laboratory_name"),
                "report_reference": row.get("report_reference"),
                "notes": row.get("notes"),
            })
            report.imported += 1
            report.rows.append(ImportRowResult(
                row_number=row_number, status=row_status,
                sample_code=sample_code, message=message,
            ))
        except SoilImportError as exc:
            report.rejected += 1
            report.rows.append(ImportRowResult(
                row_number=row_number, status="rejected",
                sample_code=sample_code, message=str(exc),
            ))
        except (TypeError, ValueError) as exc:
            report.rejected += 1
            report.rows.append(ImportRowResult(
                row_number=row_number, status="rejected",
                sample_code=sample_code, message=f"invalid number/depth: {exc}",
            ))

    if unknown_columns:
        report.warnings_count += 1
        report.rows.append(ImportRowResult(
            row_number=0, status="warning", sample_code=None,
            message=f"unmapped columns ignored: {', '.join(unknown_columns)}",
        ))
    return results, report
