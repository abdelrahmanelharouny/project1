"""Farmer CSV observations import (Master §11.1-F, Milestone 3).

A controlled, validating import pipeline for farmer-provided observation
records — never a trust-the-file loader:

- Only a strict CSV shape is accepted: `date,variable_code,value,unit,notes`.
- `variable_code` must exist in the canonical catalog; the unit (when given)
  must match the catalog unit, otherwise the row is rejected with a reason.
- Blank values become explicit `missing` observations with a FARMER_BLANK
  flag — a blank reading is information, a fabricated zero is not (rule 11).
- Duplicate (date, variable) pairs inside one file are rejected.
- Every observation is `farmer_reported_record` evidence, `is_synthetic=false`,
  and carries file provenance (name, sha256, row number, original unit).
"""

import csv
import hashlib
import io
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import ValidationFailed
from app.data_platform.contracts.observations import (
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    SpatialSupportType,
    TimeSupport,
)
from app.data_platform.contracts.variables import VARIABLE_CATALOG

PROVIDER_CODE = "farmer_csv"
PROVIDER_NAME = "Farmer CSV Import"
PRODUCT_CODE = "farmer_record"
PRODUCT_VERSION = "v1"
IMPORTER_VERSION = "csv-importer-v1"
REQUIRED_HEADERS = {"date", "variable_code", "value"}
OPTIONAL_HEADERS = {"unit", "notes"}
MAX_ROWS = 20_000


def template_csv() -> str:
    return (
        "date,variable_code,value,unit,notes\n"
        "2024-03-01,precipitation,12.5,mm,heavy overnight rain\n"
        "2024-03-02,precipitation,0,mm,dry day\n"
        "2024-03-03,air_temperature_mean,,degC,sensor offline\n"
    )


def _provenance(file_name: str, file_sha256: str) -> SourceProvenance:
    return SourceProvenance(
        provider_code=PROVIDER_CODE,
        provider_name=PROVIDER_NAME,
        product_code=PRODUCT_CODE,
        product_version=PRODUCT_VERSION,
        license_name=None,
        license_url=None,
        attribution_text="Records supplied by the farmer/operator via CSV import.",
        documentation_url=None,
        known_limitations=(
            "Farmer-reported records are unverified personal observations. They are "
            "never mixed with instrument or model data without the evidence label."
        ),
        retrieval_method="file_upload",
    )


def parse_csv_observations(
    content: str,
    *,
    file_name: str,
    field_area_ha: float | None = None,
    raw_bytes: bytes | None = None,
) -> ProviderFetchResult:
    """Parse + validate CSV content into a canonical provider result.

    Row-level problems do not abort the import: they are counted as rejected
    rows and reported as warnings, so the farmer sees exactly what landed.
    """
    file_sha256 = hashlib.sha256(
        raw_bytes if raw_bytes is not None else content.encode("utf-8")
    ).hexdigest()
    warnings: list[str] = []
    observations: list[CanonicalObservation] = []
    rejected = 0

    content = content.removeprefix("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    original_headers = reader.fieldnames or []
    normalized_headers = [header.strip().lower() for header in original_headers]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ValidationFailed("CSV contains duplicate headers after normalization.")
    reader.fieldnames = normalized_headers
    headers = set(normalized_headers)
    missing = REQUIRED_HEADERS - headers
    if missing:
        raise ValidationFailed(
            "CSV header does not match the template.",
            details=[
                {"field": "header", "reason": f"missing required column(s): {', '.join(sorted(missing))}"}
            ],
        )

    seen_keys: set[tuple[str, str]] = set()
    row_number = 1  # header line
    for row in reader:
        row_number += 1
        if row_number > MAX_ROWS:
            warnings.append(f"Row {row_number}: file exceeds {MAX_ROWS} rows; remaining rows ignored.")
            break

        def cell(name: str) -> str:
            return (row.get(name) or "").strip()

        date_raw = cell("date")
        var_raw = cell("variable_code").lower()
        value_raw = cell("value")
        unit_raw = cell("unit").lower()
        notes_raw = cell("notes")

        # --- date ---
        # Farmer records are LOCAL CALENDAR DATES. Timestamps are rejected:
        # a naive local time cannot be honestly converted to UTC without a
        # zone, and a silent anchor would shift daily aggregation (M4).
        if any(c in date_raw for c in ("T", ":", " ")):
            rejected += 1
            warnings.append(
                f"Row {row_number}: date '{date_raw}' includes a time component; "
                "use a calendar date (YYYY-MM-DD)."
            )
            continue
        try:
            observed = datetime.fromisoformat(date_raw).replace(tzinfo=UTC)
        except ValueError:
            rejected += 1
            warnings.append(f"Row {row_number}: invalid date '{date_raw}'.")
            continue

        # --- variable ---
        vdef = VARIABLE_CATALOG.get(var_raw)
        if vdef is None:
            rejected += 1
            warnings.append(
                f"Row {row_number}: unknown variable_code '{var_raw}' (not in the data dictionary)."
            )
            continue

        # --- unit ---
        if unit_raw and unit_raw != vdef.unit.lower():
            rejected += 1
            warnings.append(
                f"Row {row_number}: unit '{unit_raw}' does not match catalog unit "
                f"'{vdef.unit}' for {var_raw}; convert values before importing."
            )
            continue

        # --- value / missing ---
        missing_value = value_raw == ""
        value: float | None = None
        if not missing_value:
            try:
                value = float(value_raw)
            except ValueError:
                rejected += 1
                warnings.append(f"Row {row_number}: value '{value_raw}' is not a number.")
                continue
            if not math.isfinite(value):
                rejected += 1
                warnings.append(f"Row {row_number}: value '{value_raw}' must be finite.")
                continue

        key = (var_raw, observed.date().isoformat())
        if key in seen_keys:
            rejected += 1
            warnings.append(
                f"Row {row_number}: duplicate {var_raw} entry for {observed.date().isoformat()}; "
                "kept the first occurrence."
            )
            continue
        seen_keys.add(key)

        flags: list[dict[str, Any]] = []
        if missing_value:
            flags.append(
                {
                    "flag_code": "FARMER_BLANK",
                    "severity": "info",
                    "message": "Farmer left the value blank; recorded as missing, not zero.",
                    "details": {"row": row_number},
                }
            )

        metadata: dict[str, Any] = {
            "import_kind": "observations_csv",
            "importer_version": IMPORTER_VERSION,
            "file_name": file_name,
            "file_sha256": file_sha256,
            "source_row": row_number,
            "original_unit": unit_raw or vdef.unit,
            "original_date": date_raw,
            "date_interpretation": "calendar_date_anchored_utc_midnight",
        }
        if notes_raw:
            metadata["notes"] = notes_raw

        observations.append(
            CanonicalObservation(
                variable_code=var_raw,
                value=value,
                unit=vdef.unit,
                observed_at=observed,
                period_start=observed,
                period_end=observed + timedelta(days=1) - timedelta(seconds=1),
                time_support=TimeSupport.daily,
                spatial_support_type=SpatialSupportType.point,
                spatial_resolution_m=None,
                quality_status=QualityStatus.missing if missing_value else QualityStatus.valid,
                uncertainty_value=None,
                uncertainty_type="unknown",
                evidence_class=EvidenceClass.farmer_reported_record,
                is_synthetic=False,
                processing_version=IMPORTER_VERSION,
                metadata=metadata,
                quality_flags=flags,
            )
        )

    received = len(observations) + rejected
    if rejected:
        warnings.insert(0, f"{rejected} of {received} rows were rejected (see warnings for reasons).")
    if not observations and rejected == 0:
        warnings.append("The file contains no data rows.")

    return ProviderFetchResult(
        provider_code=PROVIDER_CODE,
        provenance=_provenance(file_name, file_sha256),
        observations=observations,
        warnings=warnings,
        coverage={
            "import_kind": "observations_csv",
            "file_name": file_name,
            "file_sha256": file_sha256,
            "rows_received": received,
            "rows_rejected": rejected,
            "rows_imported": len(observations),
        },
        provider_request_id=f"farmer-csv:{file_sha256[:12]}",
        raw_reference=None,
        input_record_count=received,
    )
