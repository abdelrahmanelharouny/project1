"""SoilGrids 2.0 optional WCS provider (Master §11.1-C, Milestone 3).

ISRIC's SoilGrids REST API is documented as paused; the supported access path
is the OGC WCS on maps.isric.org. This provider is *optional infrastructure*:

- It is never required for core availability; when the WCS is unreachable the
  ingestion job fails with a structured PROVIDER_UNAVAILABLE error and every
  other provider keeps working (Master acceptance for Milestone 3).
- Values are model predictions with uncertainty, never lab measurements:
  evidence class `global_soil_prediction`, 90% prediction interval derived
  from the Q0.05/Q0.95 quantile coverages.

Audit fixes (2026-10-31, verified against the live service):
- Coverage IDs follow the live naming `<family>_0-5cm_mean` / `_Q0.05` /
  `_Q0.95` (the historical `Qmean`/`Q005`/`Q095` names return NoSuchCoverage).
- Requests target the per-property MapServer map file (`map=/map/<family>.map`)
  and use the WCS 1.0.0 GetCoverage path with `CRS`/`RESPONSE_CRS=EPSG:4326`,
  which the live service answers with an EPSG:4326 GeoTIFF. The WCS 2.0.1
  Lat/Long subset form is interpreted on the native axes (EPSG:152160, ISRIC's
  custom Mollweide) and was verified to fail; it is not used.
- The output grid is sized to the native ~250 m cell (latitude-dependent
  degree conversion) so the service never resamples beyond native resolution;
  the reprojected-output basis is recorded in metadata.
- Wire-unit conventions verified live and converted explicitly:
  phh2o = pH*10 (÷10), soc = dg/kg (÷10 -> g/kg), sand/clay = g/kg (identity),
  bdod = cg/cm3 (÷100 -> kg/dm3). Conversions are recorded per observation.
- Raster values are masked against the actual field polygon (cell centres, with
  an all-touched fallback for sub-grid fields) — means never include cells that
  do not intersect the field, and cell coverage is accounted and flagged.

Slice-2 scope: the six standard SoilGrids depths arrive with the soil
measurement history milestone; this provider ingests the 0-5 cm depth only,
which keeps the observation natural key collision-free.
"""

import io
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from shapely.geometry import shape

from app.core.config import settings
from app.core.errors import ProviderRequestError, ProviderUnavailable, UnsupportedVariable
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    SpatialSupportType,
    TimeSupport,
    validate_provider_request,
)
from app.data_platform.contracts.variables import variable_definition

logger = logging.getLogger("fieldshift.providers.soilgrids")

PROVIDER_CODE = "soilgrids"
PROVIDER_NAME = "SoilGrids 2.0 (ISRIC) — WCS"
PRODUCT_CODE = "soilgrids_2020_isric"
PRODUCT_VERSION = "2.0-2020"
DEPTH = "0-5cm"
SNAPSHOT_DATE = datetime(2020, 1, 1, tzinfo=UTC)
SPATIAL_RESOLUTION_M = 250.0
NATIVE_CRS_TEXT = "EPSG:152160 (ISRIC custom Mollweide); responses reprojected to EPSG:4326"

# Standard WGS84 degree-length approximations used to size the request grid to
# the native 250 m cell (documented approximation; the response grid is a
# latitude-honest approximation of the native Mollweide cells).
METERS_PER_DEG_LAT = 110_574.0
METERS_PER_DEG_LON_EQUATOR = 111_320.0
MAX_GRID_CELLS_PER_SIDE = 600  # hard safety cap for the bbox request size

# canonical variable -> (coverage family, map file stem, native unit, conversion rule)
COVERAGE_BY_VARIABLE: dict[str, tuple[str, str, str, tuple[str, float] | None]] = {
    "soil_ph": ("phh2o", "phh2o", "pH*10", ("div", 10.0)),
    "soil_organic_carbon": ("soc", "soc", "dg/kg", ("div", 10.0)),
    "soil_sand_content": ("sand", "sand", "g/kg", None),
    "soil_clay_content": ("clay", "clay", "g/kg", None),
    "soil_bulk_density": ("bdod", "bdod", "cg/cm3", ("div", 100.0)),
}

SUPPORTED_VARIABLES = sorted(COVERAGE_BY_VARIABLE.keys())

# Live coverage-id suffixes (verified 2026-10-31 via GetCapabilities) mapped to
# their quantile fractions. `mean` is the distribution mean; Q0.05/Q0.95 bound
# the 90% prediction interval.
COVERAGE_SUFFIXES: dict[str, float | None] = {"mean": None, "Q0.05": 0.05, "Q0.95": 0.95}


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        provider_code=PROVIDER_CODE,
        provider_name=PROVIDER_NAME,
        product_code=PRODUCT_CODE,
        product_version=PRODUCT_VERSION,
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution_text="SoilGrids 2.0 soil property predictions — ISRIC World Soil Information (CC BY 4.0).",
        documentation_url="https://docs.isric.org/globaldata/soilgrids/wcs.html",
        known_limitations=(
            "Global model prediction with quantified uncertainty, not a soil sample. "
            "Never a substitute for laboratory analysis; ~250 m spatial support "
            "smooths local variability. Static snapshot (2020 release), not a "
            "time series. REST API paused; WCS access used (responses reprojected "
            "to EPSG:4326 from the native EPSG:152160 Mollweide grid)."
        ),
        retrieval_method="ogc_wcs_getcoverage",
    )


def _native_grid_size_deg(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Approximate native 250 m cell size in degrees for the bbox centroid latitude."""
    lat = max(-85.0, min(85.0, (bbox[1] + bbox[3]) / 2.0))
    res_y = SPATIAL_RESOLUTION_M / METERS_PER_DEG_LAT
    res_x = SPATIAL_RESOLUTION_M / (METERS_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat)))
    return res_x, res_y


def _coverage_bbox(geom) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geom.bounds
    pad = SPATIAL_RESOLUTION_M / METERS_PER_DEG_LAT  # one native cell of context
    return (minx - pad, miny - pad, maxx + pad, maxy + pad)


def _get_coverage_raster(
    client: httpx.Client,
    *,
    map_stem: str,
    coverage_id: str,
    bbox: tuple[float, float, float, float],
) -> tuple[Any, dict[str, Any]]:
    """Fetch one coverage as GeoTIFF bytes (WCS 1.0.0, EPSG:4326 in/out).

    Returns (masked ndarray, request/raster metadata). The response CRS is
    validated: anything other than EPSG:4326 is a structured error, never a
    silent coordinate guess.
    """
    import rasterio
    from rasterio.io import MemoryFile

    res_x, res_y = _native_grid_size_deg(bbox)
    width = min(MAX_GRID_CELLS_PER_SIDE, max(1, math.ceil((bbox[2] - bbox[0]) / res_x)))
    height = min(MAX_GRID_CELLS_PER_SIDE, max(1, math.ceil((bbox[3] - bbox[1]) / res_y)))
    params = {
        "map": f"/map/{map_stem}.map",
        "SERVICE": "WCS",
        "VERSION": "1.0.0",
        "REQUEST": "GetCoverage",
        "COVERAGE": coverage_id,
        "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "CRS": "EPSG:4326",
        "RESPONSE_CRS": "EPSG:4326",
        "FORMAT": "image/tiff",
        "WIDTH": str(width),
        "HEIGHT": str(height),
    }
    response = client.get(settings.soilgrids_wcs_base_url, params=params)
    content_type = response.headers.get("content-type", "")
    if response.status_code in (400, 404) or "xml" in content_type:
        detail = response.text[:220] if response.text else content_type
        raise ProviderRequestError(
            f"SoilGrids WCS rejected coverage '{coverage_id}' (HTTP {response.status_code}).",
            details=[{"field": "upstream", "reason": detail}],
        )
    if response.status_code != 200:
        raise ProviderUnavailable(
            f"SoilGrids WCS returned HTTP {response.status_code} for '{coverage_id}'.",
            details=[{"field": "upstream", "reason": response.text[:200]}],
        )
    if "tiff" not in content_type and "octet-stream" not in content_type:
        raise ProviderRequestError(
            f"SoilGrids WCS returned unexpected content type for '{coverage_id}'.",
            details=[{"field": "upstream", "reason": content_type}],
        )
    with MemoryFile(io.BytesIO(response.content)) as memfile:
        with memfile.open() as dataset:
            crs = dataset.crs
            if crs is None or crs.to_epsg() != 4326:
                raise ProviderRequestError(
                    "SoilGrids WCS response is not in EPSG:4326; refusing to guess a reprojection.",
                    details=[{"field": "raster_crs", "reason": str(crs)}],
                )
            band = dataset.read(1, masked=True)
            _scales = dataset.scales
            _offsets = dataset.offsets
            if callable(_scales):
                _scales = _scales()
            if callable(_offsets):
                _offsets = _offsets()
            meta = {
                "width": int(dataset.width),
                "height": int(dataset.height),
                "bounds": [float(v) for v in dataset.bounds],
                "response_crs": "EPSG:4326",
                "native_crs": NATIVE_CRS_TEXT,
                "nodata": None if dataset.nodata is None else float(dataset.nodata),
                "scale": float(_scales[0] if _scales else 1.0),
                "offset": float(_offsets[0] if _offsets else 0.0),
            }
            import numpy as np

            data = band if np.ma.isMaskedArray(band) else np.ma.masked_array(band)
    return data, meta


def _field_mask(data, transform, geometry_geojson: dict[str, Any], all_touched: bool):
    from rasterio.features import geometry_mask

    import json as _json

    return geometry_mask(
        [_json.loads(_json.dumps(geometry_geojson))],
        out_shape=data.shape,
        transform=transform,
        invert=True,
        all_touched=all_touched,
    )


def _extract_field_values(
    data, transform, geometry_geojson: dict[str, Any]
) -> tuple[Any, bool]:
    """Return (mask of cells counted for the field mean, all_touched_fallback used).

    Cell centres inside the polygon are preferred (native-support honest).
    Sub-grid fields fall back to all cells touching the boundary and are
    flagged, never silently widened.
    """
    import numpy as np

    mask = _field_mask(data, transform, geometry_geojson, all_touched=False)
    if int(mask.sum()) == 0:
        mask = _field_mask(data, transform, geometry_geojson, all_touched=True)
        if int(mask.sum()) == 0:
            return None, False
        return mask, True
    return mask, False


def _mean_of_masked(data, mask) -> float | None:
    import numpy as np

    values = data[mask]
    # NB: np.asarray on a masked array silently drops the mask and exposes the
    # nodata sentinel — always compress first.
    values = values.compressed() if np.ma.isMaskedArray(values) else values
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    return float(np.mean(values))


class SoilGridsProvider:
    """Optional SoilGrids WCS client implementing the provider contract."""

    provider_code = PROVIDER_CODE

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base_url = base_url or settings.soilgrids_wcs_base_url
        self._timeout = timeout or settings.soilgrids_timeout_seconds

    def supported_variables(self) -> list[str]:
        return list(SUPPORTED_VARIABLES)

    def fetch_observations(
        self,
        *,
        area_of_interest: AreaOfInterest,
        variables: list[str],
        start: datetime,
        end: datetime,
        options: dict[str, Any] | None = None,
    ) -> ProviderFetchResult:
        options = options or {}
        validate_provider_request(variables, start, end)

        requested = sorted(set(variables))
        supported = [v for v in requested if v in COVERAGE_BY_VARIABLE]
        unsupported = [v for v in requested if v not in COVERAGE_BY_VARIABLE]
        if not supported:
            raise UnsupportedVariable(
                "None of the requested variables are provided by SoilGrids.",
                details=[{"field": "variables", "reason": f"supported: {', '.join(SUPPORTED_VARIABLES)}"}],
            )

        warnings: list[str] = []
        if unsupported:
            warnings.append(f"Variables not provided by SoilGrids were skipped: {', '.join(unsupported)}.")
        warnings.append(
            "SoilGrids values are model predictions with uncertainty over ~250 m cells — "
            "they are not soil samples and never replace laboratory analysis."
        )

        geom = shape(area_of_interest.geometry_geojson)
        bbox = _coverage_bbox(geom)
        provenance = _provenance()

        observations: list[CanonicalObservation] = []
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                for vcode in supported:
                    obs = self._fetch_variable(
                        client, vcode=vcode, geometry_geojson=area_of_interest.geometry_geojson,
                        bbox=bbox, warnings=warnings,
                    )
                    if obs is not None:
                        observations.append(obs)
        except httpx.HTTPError as exc:
            # Optional provider: degrade gracefully, never block other providers.
            raise ProviderUnavailable(
                "SoilGrids WCS is unreachable (optional provider; other providers are unaffected).",
                details=[{"field": "upstream", "reason": f"{type(exc).__name__}: {exc}"}],
            ) from exc

        return ProviderFetchResult(
            provider_code=PROVIDER_CODE,
            provenance=provenance,
            observations=observations,
            warnings=warnings,
            coverage={
                "depth": DEPTH,
                "snapshot": "2020 release",
                "bbox": list(bbox),
                "response_crs": "EPSG:4326",
                "unsupported_variables_requested": unsupported,
            },
            provider_request_id=f"soilgrids:{DEPTH}:{round(bbox[0], 4)},{round(bbox[1], 4)}",
            raw_reference=self._base_url,
        )

    # -------------------------------------------------------------- internals
    def _fetch_variable(
        self,
        client: httpx.Client,
        *,
        vcode: str,
        geometry_geojson: dict[str, Any],
        bbox: tuple[float, float, float, float],
        warnings: list[str],
    ) -> CanonicalObservation | None:
        coverage_family, map_stem, native_unit, conversion = COVERAGE_BY_VARIABLE[vcode]
        vdef = variable_definition(vcode)

        quantile_means: dict[str, float | None] = {}
        raster_meta: dict[str, Any] | None = None
        cell_stats: dict[str, Any] = {}
        all_touched_used = False

        for suffix in COVERAGE_SUFFIXES:
            coverage_id = f"{coverage_family}_{DEPTH}_{suffix}"
            data, meta = _get_coverage_raster(
                client, map_stem=map_stem, coverage_id=coverage_id, bbox=bbox
            )
            # Recreate the affine transform from the reported bounds/shape so the
            # field mask lines up with the served grid exactly.
            from rasterio.transform import from_bounds

            transform = from_bounds(
                meta["bounds"][0], meta["bounds"][1], meta["bounds"][2], meta["bounds"][3],
                width=meta["width"], height=meta["height"],
            )
            mask, all_touched_used = _extract_field_values(data, transform, geometry_geojson)
            if mask is None:
                warnings.append(
                    f"{vcode}: the field does not overlap any cell of the served raster; "
                    "no value recorded (no fabrication)."
                )
                return None
            total_cells = int(mask.sum())
            quantile_means[suffix] = _mean_of_masked(data, mask)
            import numpy as np

            field_values = data[mask]
            field_values = field_values.compressed() if np.ma.isMaskedArray(field_values) else field_values
            field_values = np.asarray(field_values, dtype=float)
            valid_in_field = int(np.isfinite(field_values).sum())
            nodata_in_field = total_cells - valid_in_field
            cell_stats = {
                "cell_selection": "all_touched (sub-grid field)" if all_touched_used else "cell_centre_in_polygon",
                "cells_in_field": total_cells,
                "valid_cells": valid_in_field,
                "nodata_cells": max(0, nodata_in_field),
                "valid_cell_ratio": round(valid_in_field / max(1, total_cells), 4),
                "field_mean_method": "unweighted mean of valid native cells selected by the field mask",
            }
            if suffix == "mean":
                raster_meta = meta

        mean_value = quantile_means.get("mean")
        if mean_value is None:
            warnings.append(
                f"{vcode}: all raster cells over the field are nodata; "
                "no value recorded (no fabrication)."
            )
            return None

        value = float(mean_value)
        conversion_desc = "identity"
        if conversion is not None:
            op, factor = conversion
            if op == "div":
                value = value / factor
                conversion_desc = f"{native_unit} -> {vdef.unit if vdef else vcode}: divide by {factor}"

        uncertainty: float | None = None
        low, high = quantile_means.get("Q0.05"), quantile_means.get("Q0.95")
        if low is not None and high is not None:
            if conversion is not None:
                low = low / conversion[1]
                high = high / conversion[1]
            uncertainty = round((high - low) / 2.0, 4)

        flags: list[dict[str, Any]] = []
        if all_touched_used:
            warnings.append(
                f"{vcode}: the field is smaller than one native ~250 m cell; the mean uses all "
                "cells touching the boundary (SOILGRIDS_SUBCELL_FIELD)."
            )
            flags.append(
                {
                    "flag_code": "SOILGRIDS_SUBCELL_FIELD",
                    "severity": "warning",
                    "message": (
                        "Field is smaller than the native ~250 m grid cell; the value averages "
                        "every cell touching the boundary, including area outside the field."
                    ),
                    "details": dict(cell_stats),
                }
            )
        ratio = cell_stats.get("valid_cell_ratio", 0.0)
        if ratio < 0.5:
            flags.append(
                {
                    "flag_code": "SOILGRIDS_LOW_CELL_COVERAGE",
                    "severity": "warning",
                    "message": (
                        f"Only {cell_stats.get('valid_cells')} of {cell_stats.get('cells_in_field')} "
                        f"cells over the field were valid ({ratio:.0%}); the field mean is less representative."
                    ),
                    "details": dict(cell_stats),
                }
            )

        return CanonicalObservation(
            variable_code=vcode,
            value=round(value, 4),
            unit=vdef.unit if vdef else "unknown",
            observed_at=SNAPSHOT_DATE,
            period_start=SNAPSHOT_DATE,
            period_end=SNAPSHOT_DATE + timedelta(seconds=1) - timedelta(seconds=1),
            time_support=TimeSupport.instant,
            spatial_support_type=SpatialSupportType.grid_cell,
            spatial_resolution_m=SPATIAL_RESOLUTION_M,
            quality_status=QualityStatus.valid,
            uncertainty_value=uncertainty,
            uncertainty_type=(
                "prediction_interval_90_halfwidth" if uncertainty is not None else "unknown"
            ),
            evidence_class=EvidenceClass.global_soil_prediction,
            is_synthetic=False,
            processing_version="soilgrids-wcs-normalizer-v2",
            metadata={
                "property_coverage": coverage_family,
                "map_file": f"/map/{map_stem}.map",
                "coverage_ids": [
                    f"{coverage_family}_{DEPTH}_{suffix}" for suffix in COVERAGE_SUFFIXES
                ],
                "depth": DEPTH,
                "quantiles_used": {k: v for k, v in COVERAGE_SUFFIXES.items() if v is not None},
                "quantile_means": {
                    k: (None if v is None else round(v, 4)) for k, v in quantile_means.items()
                },
                "native_unit": native_unit,
                "conversion": conversion_desc,
                "cells": cell_stats,
                "native_crs": NATIVE_CRS_TEXT,
                "snapshot": "SoilGrids 2.0 static prediction (2020 release), not a time series",
                "raster": raster_meta or {},
                "bbox": list(bbox),
            },
            quality_flags=flags,
        )


def health_probe() -> dict[str, Any]:
    """DescribeCoverage probe; the optional provider degrades gracefully."""
    started = datetime.now(UTC)
    try:
        response = httpx.get(
            settings.soilgrids_wcs_base_url,
            params={
                "map": "/map/soc.map",
                "SERVICE": "WCS",
                "VERSION": "2.0.1",
                "REQUEST": "DescribeCoverage",
                "COVERAGEID": f"soc_{DEPTH}_mean",
            },
            timeout=settings.provider_probe_timeout_seconds,
        )
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        if response.status_code == 200 and "CoverageDescription" in response.text:
            return {"status": "ok", "latency_ms": latency, "detail": "WCS responded"}
        return {
            "status": "degraded",
            "latency_ms": latency,
            "detail": f"HTTP {response.status_code}",
        }
    except Exception:  # noqa: BLE001 — probe must never raise
        return {
            "status": "unreachable",
            "latency_ms": None,
            "detail": "SoilGrids WCS unreachable — optional provider; other providers unaffected",
        }
