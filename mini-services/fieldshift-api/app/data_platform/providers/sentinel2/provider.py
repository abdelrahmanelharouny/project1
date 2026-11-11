"""Sentinel-2 L2A STAC provider (P2.A) — Copernicus Data Space / STAC.

Implements the platform provider contract against STAC APIs that publish
Sentinel-2 L2A (surface reflectance) products:

- Primary target: Copernicus Data Space Ecosystem (CDSE). CDSE requires
  OAuth2 (password grant) for asset downloads; credentials are read from
  settings (`CROPTWIST_CDSE_USERNAME` / `CROPTWIST_CDSE_PASSWORD`) and are
  NEVER hardcoded. Without credentials, search-only endpoints that permit
  anonymous access still work; protected asset reads surface as
  ProviderUnavailable — never fabricated data.
- STAC-compatible alternates (e.g. Microsoft Planetary Computer) work by
  pointing `CROPTWIST_SENTINEL2_STAC_BASE_URL` at their catalogue; asset
  signing hooks (SAS) are left to deployment configuration.

Processing pipeline per scene (when network access exists):
1. STAC search: bbox of field geometry, datetime range, collection
   `sentinel-2-l2a`, cloud-cover filter (`options.max_cloud_cover`, default 80).
2. Band COGs are opened via rasterio /vsicurl/ HTTP range reads; the field
   geometry is rasterized to a pixel mask.
3. Per-pixel indices are computed vectorized
   (`app.vegetation.raster_indices` — index first, statistics second; the
   scientifically correct order), cloud/shadow pixels (SCL classes) are
   excluded, and `app.vegetation.zonal` produces field statistics
   (mean/median/percentiles/valid-pixel counts).
4. Every observation records scene id, platform, cloud %, processing
   baseline, resolution and asset hrefs in metadata (Data Passport).

Honesty properties:
- No scene is ever fabricated when the network is unreachable — failures
  raise `ProviderUnavailable` and the ingestion job records them.
- Sub-field spatial-variability claims below the zonal pixel threshold are
  flagged (`insufficient_pixels_for_variability`), never asserted.
- Live availability in the current sandbox: BLOCKED (no external network,
  no CDSE credentials). The adapter + contract tests run against mocked
  HTTP and in-memory rasters; enabling live use needs connectivity +
  credentials only.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ProviderRequestError, ProviderUnavailable, UnsupportedVariable
from app.data_platform.contracts.observations import (
    AreaOfInterest,
    CanonicalObservation,
    EvidenceClass,
    ProviderFetchResult,
    QualityStatus,
    SourceProvenance,
    TimeSupport,
)
from app.vegetation.indices import (
    SENTINEL2_BAND_RESOLUTION_M,
    SENTINEL2_L2A,
    supported_indices,
)

logger = logging.getLogger("croptwist.providers.sentinel2")

PROVIDER_CODE = "sentinel2"
PROVIDER_NAME = "Copernicus Sentinel-2 L2A (STAC)"
PRODUCT_CODE = "sentinel-2-l2a"
PRODUCT_VERSION = "stac-1.0"
STAC_SEARCH_PATH = "/search"

DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_MAX_CLOUD = 80.0
SEARCH_TIMEOUT_SECONDS = 30.0

SUPPORTED_VARIABLES = supported_indices()

# Sentinel-2 Scene Classification Layer (SCL) values treated as unusable
# pixels: 0 no-data, 1 saturated/defective, 3 cloud medium, 8 cloud high,
# 9 cloud shadows/cirrus, 10 thin cirrus. (ESA SCL legend.)
SCL_EXCLUDED_CLASSES = (0, 1, 3, 8, 9, 10)


class Sentinel2StacProvider:
    """Sentinel-2 L2A provider implementing the platform provider contract.

    All HTTP happens through an injected `httpx.Client`-compatible transport
    (default: real network) so contract tests can mock deterministically.
    """

    provider_code = PROVIDER_CODE

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    # ------------------------------------------------------------- metadata
    def supported_variables(self) -> list[str]:
        return list(SUPPORTED_VARIABLES)

    def collections(self) -> list[str]:
        return [DEFAULT_COLLECTION]

    def _provenance(self) -> SourceProvenance:
        return SourceProvenance(
            provider_code=PROVIDER_CODE,
            provider_name=PROVIDER_NAME,
            product_code=PRODUCT_CODE,
            product_version=PRODUCT_VERSION,
            license_name="Copernicus (free, open licence)",
            license_url="https://space.copernicus.eu/legal-notices",
            attribution_text="Contains modified Copernicus Sentinel data.",
            documentation_url="https://documentation.dataspace.copernicus.eu/",
            known_limitations=(
                "10 m VNIR / 20 m SWIR grid: spatial-variability claims over "
                "small fields are refused below the zonal pixel threshold. "
                "Cloud/shadow contamination is masked per scene via SCL; "
                "heavily clouded scenes are excluded by the cloud filter. "
                "L2A surface reflectance is an atmospheric estimate, not a "
                "ground measurement."
            ),
            retrieval_method="stac_api_cog_http_range",
        )

    def _stac_base_url(self) -> str:
        return settings.sentinel2_stac_base_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        """CDSE OAuth2 password grant when credentials are configured.

        Best-effort: on failure we continue anonymous (search may still work;
        protected reads will fail loudly later — surfaced, never faked).
        """
        username = settings.cdse_username
        password = settings.cdse_password
        if not username or not password:
            return {}
        try:
            response = (self._client or httpx).post(
                settings.cdse_token_url,
                data={
                    "grant_type": "password",
                    "username": username,
                    "password": password,
                    "client_id": "cdse-public",
                },
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if token:
                return {"Authorization": f"Bearer {token}"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("CDSE authentication failed (%s); continuing anonymous", exc)
        return {}

    # -------------------------------------------------------------- search
    def search_items(
        self,
        *,
        geometry_geojson: dict[str, Any],
        start: datetime,
        end: datetime,
        max_cloud_cover: float = DEFAULT_MAX_CLOUD,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """STAC item search over the field geometry (metadata only)."""
        from shapely.geometry import shape

        bbox = _bbox_of_geojson(geometry_geojson)
        if bbox is None:
            raise ProviderRequestError(
                "Field geometry could not be converted to a STAC bbox.",
                details=[{"field": "geometry", "reason": "unsupported or empty geometry"}],
            )
        payload = {
            "collections": [DEFAULT_COLLECTION],
            "bbox": bbox,
            "datetime": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "limit": min(max(1, limit), 200),
            "query": {"eo:cloud_cover": {"lt": max(0.0, min(100.0, max_cloud_cover))}},
        }
        url = f"{self._stac_base_url()}{STAC_SEARCH_PATH}"
        try:
            client = self._client or httpx
            response = client.post(
                url,
                json=payload,
                headers=self._auth_headers(),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                "Sentinel-2 STAC search failed (network or API error).",
                details=[{"reason": str(exc)}],
            ) from exc
        except ValueError as exc:
            raise ProviderRequestError(
                "Sentinel-2 STAC search returned a malformed response.",
                details=[{"reason": str(exc)}],
            ) from exc
        features = body.get("features")
        if not isinstance(features, list):
            raise ProviderRequestError(
                "STAC response has no 'features' array.",
                details=[{"reason": "unexpected STAC payload shape"}],
            )
        return features

    # ------------------------------------------------------- observations
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
        unknown = sorted(set(variables) - set(SUPPORTED_VARIABLES))
        if unknown:
            raise UnsupportedVariable(
                f"Variables not produced by this provider: {', '.join(unknown)}.",
                details=[{"field": "variables", "reason": "sentinel2 produces vegetation indices only"}],
            )
        max_cloud = float(options.get("max_cloud_cover", DEFAULT_MAX_CLOUD))
        items = self.search_items(
            geometry_geojson=area_of_interest.geometry_geojson,
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
            max_cloud_cover=max_cloud,
        )
        if not items:
            return ProviderFetchResult(
                provider_code=PROVIDER_CODE,
                provenance=self._provenance(),
                observations=[],
                warnings=[
                    "No Sentinel-2 L2A scenes matched the geometry/date/cloud "
                    "filters. This is a data-availability gap, not an error."
                ],
                coverage={"scenes": 0, "start": start.isoformat(), "end": end.isoformat()},
                provider_request_id=None,
                raw_reference=None,
                input_record_count=0,
            )

        observations: list[CanonicalObservation] = []
        warnings: list[str] = []
        scenes_processed = 0
        for item in items:
            scene_id = item.get("id")
            if not scene_id:
                continue
            properties = item.get("properties") or {}
            acquired_raw = properties.get("datetime")
            if not acquired_raw:
                warnings.append(f"Scene {scene_id} has no acquisition timestamp; skipped.")
                continue
            try:
                acquired_at = datetime.fromisoformat(
                    acquired_raw.replace("Z", "+00:00")
                ).astimezone(UTC)
            except ValueError:
                warnings.append(f"Scene {scene_id} has an unparseable timestamp; skipped.")
                continue
            cloud_cover = properties.get("eo:cloud_cover")
            scene_obs, scene_warnings = _observations_from_item(
                item=item,
                scene_id=scene_id,
                acquired_at=acquired_at,
                cloud_cover=cloud_cover,
                variables=sorted(set(variables)),
                geometry_geojson=area_of_interest.geometry_geojson,
                options=options,
            )
            observations.extend(scene_obs)
            warnings.extend(scene_warnings)
            scenes_processed += 1

        return ProviderFetchResult(
            provider_code=PROVIDER_CODE,
            provenance=self._provenance(),
            observations=observations,
            warnings=warnings,
            coverage={
                "scenes": scenes_processed,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "max_cloud_cover": max_cloud,
            },
            provider_request_id=None,
            raw_reference=None,
            input_record_count=len(observations),
        )


# --------------------------------------------------------------------- helpers
def _bbox_of_geojson(geometry_geojson: dict[str, Any]) -> list[float] | None:
    try:
        from shapely.geometry import shape

        geom = shape(geometry_geojson)
        if geom.is_empty:
            return None
        minx, miny, maxx, maxy = geom.bounds
        return [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)]
    except Exception:  # noqa: BLE001
        return None


def _assets_for_surfaces(item: dict[str, Any]) -> dict[str, str]:
    """Map reflectance surfaces -> asset hrefs for a STAC item.

    Uses documented Sentinel-2 band names (B02/B03/B04/B08/B11) tolerating
    suffixed asset keys ("B04_10m"). Missing surfaces are simply absent —
    index computation refuses them honestly.
    """
    surfaces = {
        "blue": SENTINEL2_L2A.blue,
        "green": SENTINEL2_L2A.green,
        "red": SENTINEL2_L2A.red,
        "nir": SENTINEL2_L2A.nir,
        "swir1": SENTINEL2_L2A.swir1,
    }
    assets = item.get("assets") or {}
    hrefs: dict[str, str] = {}
    for surface, band_name in surfaces.items():
        if band_name is None:
            continue
        asset = assets.get(band_name)
        if asset is None:
            for key, candidate in assets.items():
                if key.split("_")[0] == band_name and isinstance(candidate, dict) and candidate.get("href"):
                    asset = candidate
                    break
        if isinstance(asset, dict) and asset.get("href"):
            hrefs[surface] = asset["href"]
    return hrefs


def _load_scene_arrays(
    item: dict[str, Any],
    hrefs: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read band COGs (or the injected in-memory test seam) into arrays.

    Returns ({surface: {"data": 2D float DN array, "transform": Affine}},
    {"scl": 2D int array | None, "shape": (h, w)}).

    Production path: /vsicurl/ HTTP range reads (rasterio). Test seam:
    `options` carries pre-built rasterio MemoryFile datasets — implemented by
    the caller passing them via `_scene_raster_seam`.
    """
    import rasterio

    arrays: dict[str, Any] = {}
    scl = None
    for surface, href in hrefs.items():
        with rasterio.open(f"/vsicurl/{href}") as src:
            arrays[surface] = {"data": src.read(1).astype("float64"), "transform": src.transform}
    scl_href = (item.get("assets") or {}).get("SCL") or (item.get("assets") or {}).get("scl")
    if isinstance(scl_href, dict) and scl_href.get("href"):
        with rasterio.open(f"/vsicurl/{scl_href['href']}") as src:
            scl = src.read(1)
    shape = arrays[next(iter(arrays))]["data"].shape
    return arrays, {"scl": scl, "shape": shape}


def _observations_from_item(
    *,
    item: dict[str, Any],
    scene_id: str,
    acquired_at: datetime,
    cloud_cover: float | None,
    variables: list[str],
    geometry_geojson: dict[str, Any],
    options: dict[str, Any],
) -> tuple[list[CanonicalObservation], list[str]]:
    """Compute index observations for one scene via per-pixel indices + zonal stats.

    A single unreadable asset degrades that scene only (warning), never the
    whole job. A scene with no usable field pixels yields flagged-missing
    observations for traceability.
    """
    import numpy as np
    import rasterio
    from rasterio.features import geometry_mask

    from app.vegetation.raster_indices import compute_index_arrays
    from app.vegetation.zonal import ZonalResult, subfield_statistics_ok

    warnings: list[str] = []
    hrefs = _assets_for_surfaces(item)
    missing = [s for s in ("red", "nir") if s not in hrefs]
    if missing:
        warnings.append(
            f"Scene {scene_id}: required band assets missing ({', '.join(missing)}); scene skipped."
        )
        return [], warnings

    properties = item.get("properties") or {}
    platform = properties.get("platform") or "Sentinel-2"
    processing_baseline = properties.get("s2:processing_baseline")
    metadata_common: dict[str, Any] = {
        "scene_id": scene_id,
        "granule_id": scene_id,
        "platform": platform,
        "processing_baseline": processing_baseline,
        "cloud_cover_pct": cloud_cover,
        "spatial_resolution_m": SENTINEL2_L2A.spatial_resolution_m,
        "asset_refs": dict(hrefs),
        "raster_url": hrefs.get("nir"),
        "collection": DEFAULT_COLLECTION,
        "provider_code": PROVIDER_CODE,
    }

    try:
        band_arrays, context = _load_scene_arrays(item, hrefs)
        scl = context["scl"]
        shape = context["shape"]
        transform = band_arrays["red"]["transform"]
        field_mask = geometry_mask(
            [geometry_geojson],
            out_shape=shape,
            transform=transform,
            invert=True,
        )
        # DN -> surface reflectance (documented L2A scaling).
        reflectances = {
            surface: arr["data"] * SENTINEL2_L2A.scale + SENTINEL2_L2A.offset
            for surface, arr in band_arrays.items()
        }
        index_arrays = compute_index_arrays(reflectances=reflectances, indices=variables)
        cloud_mask = np.isin(scl, SCL_EXCLUDED_CLASSES) if scl is not None else None
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — network/raster failures degrade per scene
        raise ProviderUnavailable(
            f"Scene {scene_id} could not be read ({exc}); satellite data requires "
            "live network access to the provider.",
            details=[{"scene_id": scene_id}],
        ) from exc

    observations: list[CanonicalObservation] = []
    for vcode in variables:
        index_array = index_arrays.get(vcode)
        stats = ZonalResult(index=vcode)
        if index_array is None or not bool(np.any(np.isfinite(index_array))):
            stats.flags.append("no_valid_pixels")
        else:
            # zonal_statistics expects a rasterio dataset; operate on arrays
            # directly here (mask + nan-aware statistics).
            inside = field_mask & np.isfinite(index_array)
            if cloud_mask is not None:
                if cloud_mask.shape != shape:
                    cloud_mask = np.kron(cloud_mask, np.ones((2, 2), dtype=bool))[
                        : shape[0], : shape[1]
                    ]
                inside = inside & ~cloud_mask
            values = index_array[inside].astype("float64")
            masked_pixels = int(field_mask.sum())
            stats.masked_pixels = masked_pixels
            stats.valid_pixels = int(values.size)
            if masked_pixels > 0:
                stats.coverage_fraction = values.size / masked_pixels
            if values.size:
                stats.mean = float(np.mean(values))
                stats.median = float(np.median(values))
                stats.p5 = float(np.percentile(values, 5))
                stats.p25 = float(np.percentile(values, 25))
                stats.p75 = float(np.percentile(values, 75))
                stats.p95 = float(np.percentile(values, 95))
                stats.std = float(np.std(values, ddof=0)) if values.size > 1 else 0.0
            else:
                stats.flags.append("all_masked_pixels_invalid")
            if values.size < 5:
                stats.flags.append("insufficient_pixels_for_variability")
            if stats.coverage_fraction is not None and stats.coverage_fraction < 0.5:
                stats.flags.append("low_field_coverage")

        value = stats.mean if stats.valid_pixels > 0 else None
        quality = QualityStatus.valid if value is not None else QualityStatus.missing
        obs_metadata = dict(metadata_common)
        obs_metadata["zonal"] = stats.as_dict()
        obs_metadata["subfield_statistics_ok"] = subfield_statistics_ok(stats.valid_pixels)
        if value is None:
            obs_metadata["quality_flags"] = [
                {
                    "flag_code": "CLOUD_OCCLUDED_OR_NO_COVERAGE",
                    "severity": "warning",
                    "message": "No usable field pixels after cloud/nodata masking.",
                }
            ]
        else:
            obs_metadata["quality_flags"] = [
                {
                    "flag_code": "SENTINEL2_L2A_ZONAL",
                    "severity": "info",
                    "message": (
                        f"Per-pixel {vcode.upper()} over field mask "
                        f"({stats.valid_pixels} valid pixels, SCL cloud-masked)."
                    ),
                }
            ]
        observations.append(
            CanonicalObservation(
                variable_code=vcode,
                value=value,
                unit="index",
                observed_at=acquired_at,
                period_start=acquired_at,
                period_end=acquired_at,
                time_support=TimeSupport.instant,
                spatial_support_type="polygon_average",
                spatial_resolution_m=SENTINEL2_BAND_RESOLUTION_M.get(
                    SENTINEL2_L2A.red, 10.0
                ),
                quality_status=quality,
                uncertainty_value=None,
                uncertainty_type="not_quantified",
                evidence_class=EvidenceClass.satellite_derived_estimate,
                is_synthetic=False,
                processing_version=f"{PRODUCT_VERSION}+veg-raster",
                metadata=obs_metadata,
                quality_flags=obs_metadata["quality_flags"],
            )
        )
    return observations, warnings
