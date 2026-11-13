"""NASA CMR STAC catalog discovery for HLS (P04 Workstream C-A).

Standards-based discovery against the NASA Common Metadata Repository (CMR)
STAC API (LPCLOUD provider). CMR STAC search is UNAUTHENTICATED — discovery
never requires credentials, so catalog browsing is verifiable without a
NASA Earthdata Login.

Contract honoured here:
- Spatial + temporal filtering via the STAC `bbox` / `datetime` params.
- Pagination via STAC `links[rel=next]` (CMR search-after) with hard caps.
- Provider errors surface as structured CropTwist errors — never fabricated
  results, never silently empty.
- Source identifiers and acquisition metadata are preserved verbatim.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import ProviderRequestError, ProviderUnavailable
from app.data_platform.providers.nasa_hls.registry_info import (
    HLS_SPATIAL_RESOLUTION_M,
    PRODUCT_CODE_L30,
    PRODUCT_CODE_S30,
    SURFACE_ASSETS_BY_COLLECTION,
)

logger = logging.getLogger("croptwist.providers.nasa_hls.catalog")

STAC_SEARCH_PATH = "/search"
DEFAULT_MAX_CLOUD = 80.0
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 0.5
PAGE_SIZE_CAP = 100
MAX_PAGES_CAP = 10


@dataclass
class HlsSceneRecord:
    """One discovered HLS scene — metadata only (no pixels, no downloads)."""

    scene_id: str
    collection: str  # short product code: HLSL30 | HLSS30
    collection_id: str  # versioned CMR STAC collection id, e.g. HLSL30.2
    acquired_at: datetime
    cloud_cover_pct: float | None
    platform: str | None
    spatial_resolution_m: float
    bbox: list[float] | None
    footprint_geojson: dict[str, Any] | None
    asset_refs: dict[str, str]  # surface -> href, plus "fmask"
    band_mapping: dict[str, str]  # surface -> asset key
    processing_version: str = "2.0"


def collection_id_for(short_code: str) -> str:
    if short_code == PRODUCT_CODE_L30:
        return settings.nasa_hls_l30_collection_id
    if short_code == PRODUCT_CODE_S30:
        return settings.nasa_hls_s30_collection_id
    raise ProviderRequestError(
        f"Unknown HLS collection '{short_code}'.",
        details=[{"field": "collection", "reason": "expected HLSL30 or HLSS30"}],
    )


def _normalize_platform(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or None
    return str(value)


def _asset_href(assets: dict[str, Any], key: str) -> str | None:
    """STAC asset lookup tolerating suffixed keys (e.g. 'B04_30m')."""
    asset = assets.get(key)
    if asset is None:
        for asset_key, candidate in assets.items():
            if asset_key.split("_")[0] == key and isinstance(candidate, dict):
                asset = candidate
                break
    if isinstance(asset, dict):
        href = asset.get("href")
        if isinstance(href, str) and href:
            return href
    return None


def parse_stac_item(item: dict[str, Any]) -> tuple[HlsSceneRecord | None, list[str]]:
    """Parse one CMR STAC feature into a scene record (metadata only).

    Returns (record | None, warnings). Items missing required identity
    (id / collection / datetime) are skipped with a warning — never guessed.
    """
    warnings: list[str] = []
    scene_id = item.get("id")
    collection_raw = item.get("collection")
    if not scene_id or not isinstance(scene_id, str):
        warnings.append("STAC item without an 'id' was skipped.")
        return None, warnings
    if not collection_raw or not isinstance(collection_raw, str):
        warnings.append(f"Scene {scene_id}: no 'collection'; skipped.")
        return None, warnings
    collection_upper = collection_raw.upper()
    if collection_upper.startswith(PRODUCT_CODE_L30):
        short_code = PRODUCT_CODE_L30
    elif collection_upper.startswith(PRODUCT_CODE_S30):
        short_code = PRODUCT_CODE_S30
    else:
        short_code = collection_upper
    if short_code not in (PRODUCT_CODE_L30, PRODUCT_CODE_S30):
        warnings.append(
            f"Scene {scene_id}: collection '{collection_raw}' is not an HLS "
            "product; skipped."
        )
        return None, warnings

    properties = item.get("properties") or {}
    acquired_raw = properties.get("datetime")
    if not acquired_raw or not isinstance(acquired_raw, str):
        warnings.append(f"Scene {scene_id}: no acquisition timestamp; skipped.")
        return None, warnings
    try:
        acquired_at = datetime.fromisoformat(acquired_raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        warnings.append(f"Scene {scene_id}: unparseable timestamp; skipped.")
        return None, warnings

    cloud_cover = properties.get("eo:cloud_cover")
    if cloud_cover is not None and not isinstance(cloud_cover, (int, float)):
        warnings.append(f"Scene {scene_id}: non-numeric cloud cover ignored.")
        cloud_cover = None

    surface_assets = SURFACE_ASSETS_BY_COLLECTION[short_code]
    assets = item.get("assets") or {}
    asset_refs: dict[str, str] = {}
    band_mapping: dict[str, str] = {}
    for surface, asset_key in surface_assets.items():
        href = _asset_href(assets, asset_key)
        if href:
            asset_refs[surface] = href
            band_mapping[surface] = asset_key
    fmask_href = _asset_href(assets, "Fmask")
    if fmask_href:
        asset_refs["fmask"] = fmask_href
        band_mapping["fmask"] = "Fmask"

    bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
    geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else None

    record = HlsSceneRecord(
        scene_id=scene_id,
        collection=short_code,
        collection_id=collection_raw,
        acquired_at=acquired_at,
        cloud_cover_pct=float(cloud_cover) if cloud_cover is not None else None,
        platform=_normalize_platform(properties.get("platform")),
        spatial_resolution_m=HLS_SPATIAL_RESOLUTION_M,
        bbox=bbox,
        footprint_geojson=geometry,
        asset_refs=asset_refs,
        band_mapping=band_mapping,
        processing_version=str(properties.get("hls:processing_version") or "2.0"),
    )
    return record, warnings


def parse_search_response(body: dict[str, Any]) -> tuple[list[HlsSceneRecord], list[str], dict[str, Any] | None]:
    """Parse a CMR STAC search page: records, warnings, next-page marker."""
    features = body.get("features")
    if not isinstance(features, list):
        raise ProviderRequestError(
            "NASA CMR STAC response has no 'features' array.",
            details=[{"reason": "unexpected STAC payload shape"}],
        )
    records: list[HlsSceneRecord] = []
    warnings: list[str] = []
    for item in features:
        if not isinstance(item, dict):
            warnings.append("Non-object STAC feature ignored.")
            continue
        record, item_warnings = parse_stac_item(item)
        warnings.extend(item_warnings)
        if record is not None:
            records.append(record)

    next_marker: dict[str, Any] | None = None
    for link in body.get("links") or []:
        if not isinstance(link, dict) or link.get("rel") != "next":
            continue
        raw_body = link.get("body")
        if isinstance(raw_body, str):
            try:
                raw_body = json.loads(raw_body)
            except ValueError:
                warnings.append("Unparseable STAC next-page body ignored.")
                raw_body = None
        if isinstance(raw_body, dict):
            next_marker = raw_body
        break
    return records, warnings, next_marker


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


def search_scenes(
    *,
    geometry_geojson: dict[str, Any],
    start: datetime,
    end: datetime,
    collections: list[str] | None = None,
    max_cloud_cover: float | None = DEFAULT_MAX_CLOUD,
    page_size: int | None = None,
    max_pages: int | None = None,
    client: httpx.Client | None = None,
) -> tuple[list[HlsSceneRecord], list[str]]:
    """Discover HLS scenes for a geometry/date range (metadata only).

    Never downloads scene assets — discovery is STAC metadata only, so it
    stays cheap and works unauthenticated. Follows CMR search-after pages up
    to `max_pages`; retries transient network/5xx failures with backoff.
    """
    bbox = _bbox_of_geojson(geometry_geojson)
    if bbox is None:
        raise ProviderRequestError(
            "Field geometry could not be converted to a STAC bbox.",
            details=[{"field": "geometry", "reason": "unsupported or empty geometry"}],
        )

    base_url = settings.nasa_hls_stac_base_url.rstrip("/")
    url = f"{base_url}{STAC_SEARCH_PATH}"
    page_size = min(max(1, int(page_size or settings.nasa_hls_search_page_size)), PAGE_SIZE_CAP)
    max_pages = min(max(1, int(max_pages or settings.nasa_hls_max_pages)), MAX_PAGES_CAP)
    payload: dict[str, Any] = {
        "bbox": bbox,
        "datetime": (
            f"{start.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}/"
            f"{end.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        ),
        "limit": page_size,
    }
    if collections:
        payload["collections"] = list(collections)
    if max_cloud_cover is not None:
        payload["query"] = {
            "eo:cloud_cover": {"lte": max(0.0, min(100.0, float(max_cloud_cover)))}
        }

    http = client or httpx
    records: list[HlsSceneRecord] = []
    warnings: list[str] = []
    pages = 0
    while pages < max_pages:
        body = _post_search(http, url, payload)
        page_records, page_warnings, next_marker = parse_search_response(body)
        records.extend(page_records)
        warnings.extend(page_warnings)
        pages += 1
        if next_marker is None or not page_records:
            break
        payload = {**payload, **next_marker}
    return records, warnings


def _post_search(http: Any, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST one search request with retries; maps failures to provider errors."""
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = http.post(
                url,
                json=payload,
                headers=_search_headers(),
                timeout=settings.nasa_hls_timeout_seconds,
            )
            if response.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            else:
                if response.status_code >= 400:
                    raise ProviderRequestError(
                        "NASA CMR STAC search rejected the request.",
                        details=[
                            {"reason": f"HTTP {response.status_code}", "url": url},
                        ],
                    )
                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderRequestError(
                        "NASA CMR STAC search returned a malformed response.",
                        details=[{"reason": str(exc)}],
                    ) from exc
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_BASE * (2**attempt))
    raise ProviderUnavailable(
        "NASA CMR STAC search failed (network or API error) after retries.",
        details=[{"reason": str(last_exc)}],
    ) from last_exc


def _search_headers() -> dict[str, str]:
    """Search headers — CMR STAC discovery is unauthenticated by design."""
    return {"Accept": "application/geo+json, application/json"}
