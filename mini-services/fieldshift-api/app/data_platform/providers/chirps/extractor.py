"""CHIRPS v3 GeoTIFF import + field extraction workflow (Master §11.1-B, M3).

CHIRPS is a file/raster product, not an API: the workflow is
  1) the operator supplies a CHIRPS v3 GeoTIFF (bulk/file ingestion), and
  2) the service extracts a field-mean precipitation observation (spatial
     subset) while preserving raster provenance and nodata accounting.

Honesty properties:
- Evidence class is `satellite_derived_estimate`; spatial support
  `polygon_average` over valid cells inside the field boundary.
- Product variant (daily/pentad/monthly) and preliminary/final status are
  recorded and displayed — daily (esp. downscaled) fields must not be treated
  as unquestioned evidence for daily extremes (Master §11.1-B).
- Nodata cells are counted and reported; a low valid-cell ratio raises an
  explicit quality flag. Zero valid cells is a structured error, not a guess.
- Rasters not in EPSG:4326 are rejected instead of silently reprojected.
"""

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from app.core.errors import ProviderRequestError, ValidationFailed
from app.data_platform.contracts.observations import (
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    SpatialSupportType,
    TimeSupport,
)
from app.data_platform.contracts.variables import variable_definition
from app.data_platform.providers.chirps.registry_info import (
    PROVIDER_CODE,
    PROVIDER_NAME,
    PRODUCT_FAMILY,
    SPATIAL_RESOLUTION_M,
    documented_limitations,
)

TIME_SUPPORT_BY_KIND = {
    "daily": TimeSupport.daily,
    "pentad": TimeSupport.pentadal,
    "monthly": TimeSupport.monthly,
}


def _provenance(period_kind: str, product_status: str) -> SourceProvenance:
    return SourceProvenance(
        provider_code=PROVIDER_CODE,
        provider_name=PROVIDER_NAME,
        product_code=f"{PRODUCT_FAMILY}_{period_kind}",
        product_version=f"v3.0-{product_status}",
        license_name="Public domain (CHC)",
        license_url="https://www.chc.ucsb.edu/data/chirps3",
        attribution_text=(
            "CHIRPS v3.0 {kind} ({status}) — Climate Hazards Center, UC Santa Barbara."
        ).format(kind=period_kind, status=product_status),
        documentation_url="https://www.chc.ucsb.edu/data/chirps3",
        known_limitations=documented_limitations(period_kind),
        retrieval_method="file_upload_raster_extract",
    )


def _band_scale_offset(dataset) -> tuple[float, float]:
    """rasterio exposes scales/offsets as methods (<=1.3) or properties (>=1.4)."""
    scales = dataset.scales
    offsets = dataset.offsets
    if callable(scales):
        scales = scales()
    if callable(offsets):
        offsets = offsets()
    return float(scales[0] if scales else 1.0), float(offsets[0] if offsets else 0.0)


def _period_bounds(observed: datetime, period_kind: str) -> tuple[datetime, datetime]:
    day = observed.replace(hour=0, minute=0, second=0, microsecond=0)
    if period_kind == "daily":
        return day, day + timedelta(days=1) - timedelta(seconds=1)
    if period_kind == "pentad":
        start = day - timedelta(days=(day.day - 1) % 5)
        return start, start + timedelta(days=5) - timedelta(seconds=1)
    if period_kind == "monthly":
        start = day.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(seconds=1)
    raise ValidationFailed(
        "Unknown CHIRPS period kind.",
        details=[{"field": "period_kind", "reason": "choose daily, pentad or monthly"}],
    )


def extract_field_precipitation(
    file_bytes: bytes,
    *,
    file_name: str,
    field_geometry_geojson: dict[str, Any],
    observed_at: datetime,
    period_kind: str = "daily",
    product_status: str = "final",
) -> ProviderFetchResult:
    """Extract one field-mean precipitation observation from a CHIRPS GeoTIFF."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.io import MemoryFile
    from shapely.geometry import shape

    if period_kind not in TIME_SUPPORT_BY_KIND:
        raise ValidationFailed(
            "Unknown CHIRPS period kind.",
            details=[{"field": "period_kind", "reason": "choose daily, pentad or monthly"}],
        )
    if product_status not in ("preliminary", "final"):
        raise ValidationFailed(
            "Unknown CHIRPS product status.",
            details=[{"field": "product_status", "reason": "choose preliminary or final"}],
        )

    file_sha256 = hashlib.sha256(file_bytes).hexdigest()
    geom = shape(field_geometry_geojson)

    with MemoryFile(file_bytes) as memfile:
        with memfile.open() as dataset:
            crs = dataset.crs
            if crs is None or crs.to_epsg() != 4326:
                raise ValidationFailed(
                    "CHIRPS GeoTIFF must be in EPSG:4326; refusing to guess a reprojection.",
                    details=[{"field": "raster_crs", "reason": str(crs)}],
                )
            if dataset.count < 1:
                raise ProviderRequestError(
                    "CHIRPS GeoTIFF has no raster band.",
                    details=[{"field": "raster_band", "reason": "count=0"}],
                )
            band = dataset.read(1, masked=True)
            transform = dataset.transform
            nodata_value = dataset.nodata
            scale_factor, offset_factor = _band_scale_offset(dataset)

            in_field = geometry_mask(
                [json.loads(json.dumps(field_geometry_geojson))],
                out_shape=band.shape,
                transform=transform,
                invert=True,
                all_touched=False,
            )
            values = band[in_field]

            total_cells = int(in_field.sum())
            valid_values = values.compressed() if np.ma.isMaskedArray(values) else np.asarray(values)
            valid_values = valid_values[np.isfinite(valid_values)]
            valid_count = int(valid_values.size)
            nodata_count = max(0, total_cells - valid_count)

            raster_meta = {
                "raster_width": int(dataset.width),
                "raster_height": int(dataset.height),
                "raster_bounds": [float(v) for v in dataset.bounds],
                "raster_transform_scale": [abs(float(transform.a)), abs(float(transform.e))],
                "nodata_value": None if nodata_value is None else float(nodata_value),
                "gdal_scale": scale_factor,
                "gdal_offset": offset_factor,
            }

    if total_cells == 0:
        raise ValidationFailed(
            "The field boundary does not intersect the raster extent.",
            details=[{"field": "raster_extent", "reason": str(raster_meta["raster_bounds"])}],
        )
    if valid_count == 0:
        raise ValidationFailed(
            "All raster cells over the field are nodata; refusing to fabricate a value.",
            details=[{"field": "valid_cells", "reason": f"0 of {total_cells} cells valid"}],
        )

    mean_value = float(np.mean(valid_values)) * scale_factor + offset_factor
    coverage_ratio = valid_count / max(1, total_cells)

    flags: list[dict[str, Any]] = []
    if coverage_ratio < 0.5:
        flags.append(
            {
                "flag_code": "CHIRPS_LOW_CELL_COVERAGE",
                "severity": "warning",
                "message": (
                    f"Only {valid_count} of {total_cells} cells over the field were valid "
                    f"({coverage_ratio:.0%}); the field mean is less representative."
                ),
                "details": {"valid_cells": valid_count, "total_cells": total_cells},
            }
        )
    if product_status == "preliminary":
        flags.append(
            {
                "flag_code": "CHIRPS_PRELIMINARY",
                "severity": "info",
                "message": "Preliminary CHIRPS product; values may change in the final release.",
                "details": {},
            }
        )

    vdef = variable_definition("precipitation")
    observed = observed_at.astimezone(UTC)
    period_start, period_end = _period_bounds(observed, period_kind)
    metadata = {
        "import_kind": "chirps_geotiff_extract",
        "file_name": file_name,
        "file_sha256": file_sha256,
        "period_kind": period_kind,
        "product_status": product_status,
        "valid_cells": valid_count,
        "nodata_cells": nodata_count,
        "total_cells": total_cells,
        "valid_cell_ratio": round(coverage_ratio, 4),
        "field_mean_method": "unweighted mean of valid cells intersecting the boundary",
        **raster_meta,
    }

    result = ProviderFetchResult(
        provider_code=PROVIDER_CODE,
        provenance=_provenance(period_kind, product_status),
        observations=[
            CanonicalObservation(
                variable_code="precipitation",
                value=round(mean_value, 3),
                unit=vdef.unit if vdef else "mm",
                observed_at=observed,
                period_start=period_start,
                period_end=period_end,
                time_support=TIME_SUPPORT_BY_KIND[period_kind],
                spatial_support_type=SpatialSupportType.polygon_average,
                spatial_resolution_m=SPATIAL_RESOLUTION_M,
                quality_status=QualityStatus.valid,
                uncertainty_value=None,
                uncertainty_type="unknown",
                evidence_class=EvidenceClass.satellite_derived_estimate,
                is_synthetic=False,
                processing_version="chirps-extractor-v1",
                metadata=metadata,
                quality_flags=flags,
            )
        ],
        warnings=[
            "Rainfall is derived from a gridded satellite-gauge blend, not a rain gauge "
            "in the field; see the product limitations on the passport."
        ],
        coverage={
            "import_kind": "chirps_geotiff_extract",
            "file_name": file_name,
            "file_sha256": file_sha256,
            "period_kind": period_kind,
            "product_status": product_status,
            "valid_cells": valid_count,
            "total_cells": total_cells,
            "valid_cell_ratio": round(coverage_ratio, 4),
        },
        provider_request_id=f"chirps:{file_sha256[:12]}:{observed.date().isoformat()}",
        raw_reference=None,
    )
    return result
