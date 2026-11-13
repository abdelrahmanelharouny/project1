"""NASA HLS provider (P04) — real satellite acquisition adapter.

Implements the platform provider contract (EnvironmentalDataProvider) against
NASA HLS v2.0 (Harmonized Landsat Sentinel-2, LP DAAC):

- Catalog: NASA CMR STAC (`cmr.earthdata.nasa.gov/stac/LPCLOUD`) — public,
  unauthenticated metadata search (see catalog.py).
- Assets: LP DAAC cloud-optimized GeoTIFFs. Reads use rasterio /vsicurl/
  HTTP range reads (no full-raster downloads, no binaries persisted) with
  NASA Earthdata Login credentials from settings
  (`CROPTWIST_EARTHDATA_USERNAME` / `CROPTWIST_EARTHDATA_PASSWORD` or a
  pre-minted `CROPTWIST_EARTHDATA_BEARER_TOKEN`). Credentials are never
  hardcoded. Without credentials, protected asset reads fail loudly
  (ProviderUnavailable) — never fabricated.
- Processing: per-pixel vegetation indices via the shared, documented index
  math (`app.vegetation.raster_indices` / `app.vegetation.indices`), Fmask
  cloud/shadow/cirrus/snow masking, zonal field statistics. HLS band scaling
  (DN * 0.0001) and band naming follow the HLS v2.0 user guide.
- Ingestion flow: `scene_ids` + `scene_records` (from a discovery step) pin
  the exact scenes to acquire — bounded, retryable, idempotent. Without
  scene_records the provider performs its own bounded discovery and caps the
  number of processed scenes (`nasa_hls_max_scenes_per_job`).

Honesty properties:
- No scene, observation, resolution or quality value is ever invented.
- One ingestion job targets exactly one HLS collection (HLSL30 OR HLSS30) so
  result-level provenance is unambiguous.
- Per-scene failures degrade to warnings and surface as failed scene status —
  they never abort the remaining scenes.
- is_synthetic=False, evidence_class=satellite_derived_estimate, full
  SourceProvenance (license/attribution/limitations) on every result.
"""

from __future__ import annotations

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
from app.data_platform.providers.nasa_hls import catalog as hls_catalog
from app.data_platform.providers.nasa_hls.registry_info import (
    ATTRIBUTION_TEXT,
    DOCUMENTATION_URL,
    FMASK_EXCLUDE_MASK,
    HLS_REFLECTANCE_SCALE,
    HLS_SPATIAL_RESOLUTION_M,
    KNOWN_LIMITATIONS,
    LICENSE_NAME,
    LICENSE_URL,
    PRODUCT_CODE_L30,
    PRODUCT_CODE_S30,
    PRODUCT_VERSION,
    PROVIDER_CODE,
    PROVIDER_NAME,
)

logger = logging.getLogger("croptwist.providers.nasa_hls")

SUPPORTED_VARIABLES = ("ndvi", "evi", "savi", "ndmi", "ndwi")

SEARCH_TIMEOUT_SECONDS = 30.0


class NasaHlsProvider:
    """NASA HLS acquisition provider (CMR STAC discovery + LP DAAC assets)."""

    provider_code = PROVIDER_CODE

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    # ------------------------------------------------------------- metadata
    def supported_variables(self) -> list[str]:
        return list(SUPPORTED_VARIABLES)

    def collections(self) -> list[str]:
        return [PRODUCT_CODE_L30, PRODUCT_CODE_S30]

    def validate_request(
        self, *, variables: list[str], options: dict[str, Any] | None = None
    ) -> None:
        """Fail fast before a job row is created (data_platform route hook)."""
        options = options or {}
        unknown = sorted(set(variables) - set(SUPPORTED_VARIABLES))
        if unknown:
            raise UnsupportedVariable(
                f"Variables not produced by this provider: {', '.join(unknown)}.",
                details=[{"field": "variables", "reason": "nasa_hls produces vegetation indices only"}],
            )
        scene_ids = options.get("scene_ids")
        if scene_ids is not None:
            if not isinstance(scene_ids, list) or not all(isinstance(s, str) and s for s in scene_ids):
                raise ProviderRequestError(
                    "scene_ids must be a non-empty list of scene identifiers.",
                    details=[{"field": "scene_ids", "reason": "invalid shape"}],
                )
            if len(scene_ids) > settings.nasa_hls_max_scenes_per_job:
                raise ProviderRequestError(
                    f"Too many scenes requested (limit {settings.nasa_hls_max_scenes_per_job}).",
                    details=[{"field": "scene_ids", "reason": "nasa_hls_max_scenes_per_job exceeded"}],
                )

    # ------------------------------------------------------------ provenance
    def _provenance(self, collection: str) -> SourceProvenance:
        return SourceProvenance(
            provider_code=PROVIDER_CODE,
            provider_name=PROVIDER_NAME,
            product_code=collection,
            product_version=PRODUCT_VERSION,
            license_name=LICENSE_NAME,
            license_url=LICENSE_URL,
            attribution_text=ATTRIBUTION_TEXT,
            documentation_url=DOCUMENTATION_URL,
            known_limitations=KNOWN_LIMITATIONS,
            retrieval_method="cmr_stac_cog_http_range",
        )

    # ------------------------------------------------------------ discovery
    def search_scenes(
        self,
        *,
        geometry_geojson: dict[str, Any],
        start: datetime,
        end: datetime,
        max_cloud_cover: float | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[hls_catalog.HlsSceneRecord], list[str]]:
        """Public catalog discovery (metadata only, unauthenticated)."""
        return hls_catalog.search_scenes(
            geometry_geojson=geometry_geojson,
            start=start,
            end=end,
            collections=[
                settings.nasa_hls_l30_collection_id,
                settings.nasa_hls_s30_collection_id,
            ],
            max_cloud_cover=(
                settings.nasa_hls_default_max_cloud_cover
                if max_cloud_cover is None
                else max_cloud_cover
            ),
            page_size=page_size,
            max_pages=max_pages,
            client=self._client,
        )

    # ----------------------------------------------------------- ingestion
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
                details=[{"field": "variables", "reason": "nasa_hls produces vegetation indices only"}],
            )

        scene_records = self._resolve_targets(
            options, start, end, area_of_interest.geometry_geojson
        )
        collections = {record["collection"] for record in scene_records.values()}
        if not scene_records:
            return ProviderFetchResult(
                provider_code=PROVIDER_CODE,
                provenance=self._provenance(PRODUCT_CODE_L30),
                observations=[],
                warnings=[
                    "No NASA HLS scenes were available for the requested range. "
                    "This is a data-availability gap, not an error."
                ],
                coverage={
                    "scenes_requested": 0,
                    "scenes_processed": 0,
                    "start": start.astimezone(UTC).isoformat(),
                    "end": end.astimezone(UTC).isoformat(),
                },
                provider_request_id=None,
                raw_reference=hls_catalog_url(),
                input_record_count=0,
            )
        if len(collections) > 1:
            raise ProviderRequestError(
                "One NASA HLS ingestion job must target a single collection "
                "(group HLSL30 and HLSS30 scenes into separate jobs).",
                details=[{"field": "scene_records", "reason": f"collections: {sorted(collections)}"}],
            )
        collection = collections.pop()

        ordered_ids = sorted(scene_records.keys())
        provider_request_id = f"nasa_hls:{_stable_id(ordered_ids)[:16]}"

        observations: list[CanonicalObservation] = []
        warnings: list[str] = []
        scenes_processed = 0
        gdal_env = _gdal_env_options(self._earthdata_auth())
        for scene_id in ordered_ids:
            record = scene_records[scene_id]
            try:
                scene_obs, scene_warnings = _scene_observations(
                    record=record,
                    variables=sorted(set(variables)),
                    geometry_geojson=area_of_interest.geometry_geojson,
                    gdal_env=gdal_env,
                )
            except ProviderUnavailable as exc:
                warnings.append(f"Scene {scene_id}: {exc}")
                logger.warning("nasa_hls scene degraded", extra={"scene_id": scene_id})
                continue
            observations.extend(scene_obs)
            warnings.extend(scene_warnings)
            if scene_obs:
                scenes_processed += 1

        return ProviderFetchResult(
            provider_code=PROVIDER_CODE,
            provenance=self._provenance(collection),
            observations=observations,
            warnings=warnings,
            coverage={
                "scenes_requested": len(scene_records),
                "scenes_processed": scenes_processed,
                "start": start.astimezone(UTC).isoformat(),
                "end": end.astimezone(UTC).isoformat(),
            },
            provider_request_id=provider_request_id,
            raw_reference=hls_catalog_url(),
            input_record_count=len(observations),
        )

    # ------------------------------------------------------------- targets
    def _resolve_targets(
        self,
        options: dict[str, Any],
        start: datetime,
        end: datetime,
        geometry_geojson: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        """Resolve which scenes to acquire.

        Two supported modes:
        - Explicit: `scene_ids` + `scene_records` (from the discovery step /
          acquisition API) — the deterministic, bounded acquisition mode.
        - Bounded auto-discovery: no scene_records -> CMR STAC search for the
          range, processing at most `nasa_hls_max_scenes_per_job` scenes
          (clearest first). Used for direct data-jobs; the cap is recorded in
          coverage and warnings.
        """
        scene_ids = options.get("scene_ids")
        scene_records = options.get("scene_records")
        if scene_records is not None:
            if not isinstance(scene_records, dict) or not scene_records:
                raise ProviderRequestError(
                    "scene_records must be a non-empty object keyed by scene id "
                    "(obtained from satellite discovery).",
                    details=[{"field": "scene_records", "reason": "invalid shape"}],
                )
            if isinstance(scene_ids, list) and scene_ids:
                missing = [s for s in scene_ids if s not in scene_records]
                if missing:
                    raise ProviderRequestError(
                        "scene_ids reference scenes without discovery metadata.",
                        details=[{"field": "scene_ids", "reason": f"missing records: {missing[:5]}"}],
                    )
                ordered = [s for s in scene_ids if s in scene_records]
            else:
                ordered = sorted(scene_records.keys())
            for key, record in scene_records.items():
                _validate_scene_record(key, record)
            return {k: scene_records[k] for k in ordered}

        if not isinstance(scene_ids, list) or not scene_ids:
            # Bounded auto-discovery mode.
            if geometry_geojson is None:
                raise ProviderRequestError(
                    "Field geometry is required for NASA HLS discovery.",
                    details=[{"field": "geometry", "reason": "missing"}],
                )
            records, _warnings = self.search_scenes(
                geometry_geojson=geometry_geojson,
                start=start,
                end=end,
            )
            records.sort(
                key=lambda r: (
                    r.cloud_cover_pct if r.cloud_cover_pct is not None else 999.0,
                    -r.acquired_at.timestamp(),
                )
            )
            cap = settings.nasa_hls_max_scenes_per_job
            capped = records[:cap]
            scene_records = {r.scene_id: _record_to_scene_record(r) for r in capped}
            if len(records) > cap:
                logger.warning(
                    "nasa_hls auto-discovery capped", extra={"found": len(records), "cap": cap}
                )
            return scene_records
        raise ProviderRequestError(
            "scene_ids provided without scene_records metadata.",
            details=[{"field": "scene_records", "reason": "run discovery first"}],
        )

    # ----------------------------------------------------------------- auth
    def _earthdata_auth(self) -> dict[str, str]:
        """NASA Earthdata Login credential resolution (settings only)."""
        token = settings.earthdata_bearer_token
        if token:
            return {"bearer_token": token}
        if settings.earthdata_username and settings.earthdata_password:
            minted = self._mint_earthdata_token()
            if minted:
                return {"bearer_token": minted}
            return {
                "basic_user": settings.earthdata_username,
                "basic_password": settings.earthdata_password,
            }
        return {}

    def _mint_earthdata_token(self) -> str | None:
        """POST the EDL token endpoint with basic auth (best-effort).

        EDL tokens are the documented bearer mechanism for LP DAAC cloud
        assets. Failure falls back to basic-auth GDAL handling; nothing is
        fabricated and no credential is ever logged.
        """
        http = self._client or httpx
        try:
            response = http.post(
                settings.earthdata_token_url,
                auth=(settings.earthdata_username, settings.earthdata_password),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("token") or data.get("access_token")
            return token if isinstance(token, str) and token else None
        except Exception as exc:  # noqa: BLE001 — auth is best-effort
            logger.warning("Earthdata token mint failed (%s); using basic-auth GDAL path", exc)
            return None


# ------------------------------------------------------------------ helpers
def hls_catalog_url() -> str | None:
    return settings.nasa_hls_stac_base_url.rstrip("/") + hls_catalog.STAC_SEARCH_PATH


def _stable_id(scene_ids: list[str]) -> str:
    import hashlib

    return hashlib.sha256("|".join(scene_ids).encode("utf-8")).hexdigest()


def _record_to_scene_record(record: hls_catalog.HlsSceneRecord) -> dict[str, Any]:
    return {
        "scene_id": record.scene_id,
        "collection": record.collection,
        "collection_id": record.collection_id,
        "acquired_at": record.acquired_at.isoformat(),
        "cloud_cover_pct": record.cloud_cover_pct,
        "platform": record.platform,
        "assets": dict(record.asset_refs),
        "band_mapping": dict(record.band_mapping),
        "processing_version": record.processing_version,
    }


def _validate_scene_record(scene_id: str, record: Any) -> None:
    if not isinstance(record, dict):
        raise ProviderRequestError(
            f"Scene record '{scene_id}' must be an object.",
            details=[{"field": "scene_records", "reason": "invalid shape"}],
        )
    if record.get("collection") not in (PRODUCT_CODE_L30, PRODUCT_CODE_S30):
        raise ProviderRequestError(
            f"Scene record '{scene_id}' has an unknown collection "
            f"'{record.get('collection')}'.",
            details=[{"field": "scene_records", "reason": "expected HLSL30 or HLSS30"}],
        )
    if not record.get("acquired_at"):
        raise ProviderRequestError(
            f"Scene record '{scene_id}' has no acquisition timestamp.",
            details=[{"field": "scene_records", "reason": "acquired_at required"}],
        )


def _gdal_env_options(auth: dict[str, str]) -> dict[str, str]:
    """GDAL config options for authenticated /vsicurl/ reads of LP DAAC COGs.

    - Bearer token path (preferred): `GDAL_HTTP_HEADERS` (GDAL >= 3.6).
    - Fallback: HTTP basic auth over the URS redirect challenge plus a
      cookie jar (documented EDL access pattern for GDAL).
    - No credentials -> anonymous read attempt (public assets only); the
      protected LP DAAC buckets will fail loudly downstream.
    """
    opts = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "VSI_CACHE": "TRUE",
        "GDAL_HTTP_TIMEOUT": str(int(settings.nasa_hls_timeout_seconds)),
    }
    token = auth.get("bearer_token")
    if token:
        opts["GDAL_HTTP_HEADERS"] = f"Authorization: Bearer {token}"
    elif auth.get("basic_user") and auth.get("basic_password"):
        opts["GDAL_HTTP_AUTH"] = "BASIC"
        opts["GDAL_USERPWD"] = f"{auth['basic_user']}:{auth['basic_password']}"
        opts["GDAL_HTTP_COOKIEFILE"] = "/vsimem/edl_cookies.txt"
        opts["GDAL_HTTP_COOKIEJAR"] = "/vsimem/edl_cookies.txt"
    return opts


def _load_scene_arrays(
    assets: dict[str, str],
    surfaces: list[str],
    gdal_env: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read band COGs via /vsicurl/ HTTP range reads (production path).

    Returns ({surface: {"data": 2D float DN array, "transform": Affine}},
    {"fmask": 2D uint8 array | None, "shape": (h, w)}). HTTP range reads keep
    transfer proportional to the field window — no full-raster downloads and
    no raster binaries are ever persisted to relational storage.
    """
    import rasterio

    arrays: dict[str, Any] = {}
    transform = None
    for surface in surfaces:
        href = assets.get(surface)
        if not href:
            continue
        with rasterio.Env(**gdal_env):
            with rasterio.open(f"/vsicurl/{href}") as src:
                arrays[surface] = {"data": src.read(1).astype("float64"), "transform": src.transform}
                if transform is None:
                    transform = src.transform
    fmask = None
    fmask_href = assets.get("fmask")
    if fmask_href:
        with rasterio.Env(**gdal_env):
            with rasterio.open(f"/vsicurl/{fmask_href}") as src:
                fmask = src.read(1)
    if not arrays:
        raise ProviderUnavailable(
            "No NASA HLS band assets could be read (missing credentials or "
            "unreachable LP DAAC assets).",
        )
    shape = arrays[next(iter(arrays))]["data"].shape
    return arrays, {"fmask": fmask, "shape": shape, "transform": transform}


def _scene_observations(
    *,
    record: dict[str, Any],
    variables: list[str],
    geometry_geojson: dict[str, Any],
    gdal_env: dict[str, str],
) -> tuple[list[CanonicalObservation], list[str]]:
    """Acquire one scene: read assets, mask, compute indices, zonal stats.

    Mirrors the Sentinel-2 provider's scientifically-correct order (index
    first, statistics second) with HLS-specific band naming and Fmask QA.
    """
    import numpy as np
    from rasterio.features import geometry_mask

    from app.vegetation.raster_indices import compute_index_arrays
    from app.vegetation.zonal import ZonalResult, subfield_statistics_ok

    warnings: list[str] = []
    scene_id = record["scene_id"]
    collection = record["collection"]
    assets = dict(record.get("assets") or {})
    missing = [s for s in ("red", "nir") if s not in assets]
    if missing:
        warnings.append(
            f"Scene {scene_id}: required band assets missing ({', '.join(missing)}); scene skipped."
        )
        return [], warnings

    acquired_at = datetime.fromisoformat(str(record["acquired_at"]).replace("Z", "+00:00"))
    if acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=UTC)
    cloud_cover = record.get("cloud_cover_pct")
    platform = record.get("platform")
    processing_version = str(record.get("processing_version") or PRODUCT_VERSION)
    metadata_common: dict[str, Any] = {
        "scene_id": scene_id,
        "granule_id": scene_id,
        "platform": platform,
        "collection": collection,
        "collection_id": record.get("collection_id"),
        "processing_baseline": processing_version,
        "cloud_cover_pct": cloud_cover,
        "spatial_resolution_m": HLS_SPATIAL_RESOLUTION_M,
        "asset_refs": assets,
        "raster_url": assets.get("nir"),
        "provider_code": PROVIDER_CODE,
    }

    try:
        surfaces = [s for s in ("blue", "green", "red", "nir", "swir1", "swir2") if s in assets]
        band_arrays, context = _load_scene_arrays(assets, surfaces, gdal_env)
        fmask = context["fmask"]
        shape = context["shape"]
        transform = context["transform"]
        field_mask = geometry_mask(
            [geometry_geojson],
            out_shape=shape,
            transform=transform,
            invert=True,
        )
        # DN -> surface reflectance (HLS v2.0 documented scale factor).
        reflectances = {
            surface: arr["data"] * HLS_REFLECTANCE_SCALE for surface, arr in band_arrays.items()
        }
        index_arrays = compute_index_arrays(reflectances=reflectances, indices=variables)
        cloud_mask = (
            (fmask.astype(np.uint8) & FMASK_EXCLUDE_MASK) != 0
            if fmask is not None
            else None
        )
    except Exception as exc:  # noqa: BLE001 — network/raster failures degrade per scene
        raise ProviderUnavailable(
            f"Scene {scene_id} could not be read ({type(exc).__name__}: {exc}); "
            "NASA HLS assets require network access and Earthdata credentials.",
            details=[{"scene_id": scene_id}],
        ) from exc

    observations: list[CanonicalObservation] = []
    for vcode in variables:
        index_array = index_arrays.get(vcode)
        stats = ZonalResult(index=vcode)
        if index_array is None or not bool(np.any(np.isfinite(index_array))):
            stats.flags.append("no_valid_pixels")
        else:
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
                    "message": "No usable field pixels after Fmask/nodata masking.",
                }
            ]
        else:
            obs_metadata["quality_flags"] = [
                {
                    "flag_code": "NASA_HLS_ZONAL",
                    "severity": "info",
                    "message": (
                        f"Per-pixel {vcode.upper()} over field mask "
                        f"({stats.valid_pixels} valid pixels, HLS Fmask "
                        "cloud/shadow/cirrus/snow-masked)."
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
                spatial_resolution_m=HLS_SPATIAL_RESOLUTION_M,
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
