"""SoilGrids 2.0 optional WCS provider (Master §11.1-C, Milestone 3).

ISRIC's SoilGrids REST API is documented as paused; the supported access path
is the OGC WCS on maps.isric.org. This provider is *optional infrastructure*:

- It is never required for core availability; when the WCS is unreachable the
  ingestion job fails with a structured PROVIDER_UNAVAILABLE error and every
  other provider keeps working (Master acceptance for Milestone 3).
- Values are model predictions with uncertainty, never lab measurements:
  evidence class `global_soil_prediction`, 90% prediction interval recorded
  from the Q0.05/Q0.95 quantile coverages.
- Property, depth, quantile, units, source version and spatial support are
  recorded per observation (Master §11.1-C).

Slice-2 scope: the six standard SoilGrids depths arrive with Milestone 4 soil
measurement history; this provider ingests the 0-5 cm depth only, which keeps
the observation natural key collision-free.
"""

import io
import logging
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
GRID_CELL_DEG = 0.0025  # ~250 m in latitude degrees

# canonical variable -> (WCS coverage family, native unit, conversion rule)
COVERAGE_BY_VARIABLE: dict[str, tuple[str, str, tuple[str, float] | None]] = {
    "soil_ph": ("phhkg", "pH*10", ("div", 10.0)),
    "soil_organic_carbon": ("soc", "g/kg", None),
    "soil_sand_content": ("sand", "g/kg", None),
    "soil_clay_content": ("clay", "g/kg", None),
    "soil_bulk_density": ("bdod", "cg/cm3", ("div", 100.0)),
}

SUPPORTED_VARIABLES = sorted(COVERAGE_BY_VARIABLE.keys())
QUANTILES = {"Qmean": None, "Q005": 0.005, "Q095": 0.095}


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
            "time series. REST API paused; WCS access used."
        ),
        retrieval_method="ogc_wcs_getcoverage",
    )


def _expanded_bbox(geom) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = geom.bounds
    pad = GRID_CELL_DEG  # guarantee at least one 250 m cell per side
    return (minx - pad, miny - pad, maxx + pad, maxy + pad)


def _coverage_url(coverage_id: str, bbox: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bbox
    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage_id,
        "format": "image/tiff; subtype=geotiff",
    }
    return f"{settings.soilgrids_wcs_base_url}?{httpx.QueryParams(params)}&subset=Lat({miny},{maxy})&subset=Long({minx},{maxx})"


def _get_coverage_raster(
    client: httpx.Client, coverage_id: str, bbox: tuple[float, float, float, float]
):
    """Fetch one coverage as GeoTIFF bytes and return (masked ndarray, metadata)."""
    import rasterio
    from rasterio.io import MemoryFile

    url = _coverage_url(coverage_id, bbox)
    response = client.get(url)
    if response.status_code in (400, 404):
        raise ProviderRequestError(
            f"SoilGrids WCS rejected coverage '{coverage_id}' (HTTP {response.status_code}).",
            details=[{"field": "upstream", "reason": response.text[:200]}],
        )
    if response.status_code != 200:
        raise ProviderUnavailable(
            f"SoilGrids WCS returned HTTP {response.status_code} for '{coverage_id}'.",
            details=[{"field": "upstream", "reason": response.text[:200]}],
        )
    content_type = response.headers.get("content-type", "")
    if "tiff" not in content_type and "octet-stream" not in content_type:
        raise ProviderRequestError(
            f"SoilGrids WCS returned unexpected content type for '{coverage_id}'.",
            details=[{"field": "upstream", "reason": content_type}],
        )
    with MemoryFile(io.BytesIO(response.content)) as memfile:
        with memfile.open() as dataset:
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
                "nodata": None if dataset.nodata is None else float(dataset.nodata),
                "scale": float(_scales[0] if _scales else 1.0),
                "offset": float(_offsets[0] if _offsets else 0.0),
            }
            import numpy as np

            data = band.compressed() if np.ma.isMaskedArray(band) else np.asarray(band)
            valid = data[np.isfinite(data)]
    return valid, meta


def _mean_of(valid) -> float | None:
    import numpy as np

    if valid.size == 0:
        return None
    return float(np.mean(valid))


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
        bbox = _expanded_bbox(geom)
        provenance = _provenance()

        observations: list[CanonicalObservation] = []
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                for vcode in supported:
                    coverage_family, native_unit, conversion = COVERAGE_BY_VARIABLE[vcode]
                    vdef = variable_definition(vcode)
                    means: dict[str, float | None] = {}
                    raster_meta: dict[str, Any] | None = None
                    for suffix, _quantile in QUANTILES.items():
                        coverage_id = f"{coverage_family}_{DEPTH}{suffix}"
                        valid, meta = _get_coverage_raster(client, coverage_id, bbox)
                        means[suffix] = _mean_of(valid)
                        if suffix == "Qmean":
                            raster_meta = meta

                    mean_value = means.get("Qmean")
                    if mean_value is None:
                        warnings.append(
                            f"{vcode}: all raster cells over the field extent are nodata; "
                            "no value recorded (no fabrication)."
                        )
                        continue

                    value = float(mean_value)
                    conversion_desc = "identity"
                    if conversion is not None:
                        op, factor = conversion
                        if op == "div":
                            value = value / factor
                            conversion_desc = f"{native_unit} -> {vdef.unit if vdef else vcode}: divide by {factor}"

                    uncertainty: float | None = None
                    low, high = means.get("Q005"), means.get("Q095")
                    if low is not None and high is not None:
                        if conversion is not None:
                            low = low / conversion[1]
                            high = high / conversion[1]
                        uncertainty = round((high - low) / 2.0, 4)

                    observations.append(
                        CanonicalObservation(
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
                            processing_version="soilgrids-wcs-normalizer-v1",
                            metadata={
                                "property_coverage": coverage_family,
                                "depth": DEPTH,
                                "quantiles_used": sorted(QUANTILES.keys()),
                                "quantile_means": {
                                    k: (None if v is None else round(v, 4)) for k, v in means.items()
                                },
                                "native_unit": native_unit,
                                "conversion": conversion_desc,
                                "snapshot": "SoilGrids 2.0 static prediction (2020 release), not a time series",
                                "raster": raster_meta or {},
                                "bbox": list(bbox),
                            },
                            quality_flags=[],
                        )
                    )
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
                "unsupported_variables_requested": unsupported,
            },
            provider_request_id=f"soilgrids:{DEPTH}:{round(bbox[0], 4)},{round(bbox[1], 4)}",
            raw_reference=self._base_url,
        )


def health_probe() -> dict[str, Any]:
    """DescribeCoverage probe; the optional provider degrades gracefully."""
    started = datetime.now(UTC)
    try:
        response = httpx.get(
            settings.soilgrids_wcs_base_url,
            params={
                "service": "WCS",
                "version": "2.0.1",
                "request": "DescribeCoverage",
                "coverageId": f"soc_{DEPTH}Qmean",
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
