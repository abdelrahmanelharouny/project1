"""Unified map layer catalog (P07 A2).

Single source of truth for "which layers exist for this field". Every layer
entry reports honest availability: a layer whose real dataset or processing
product does not exist is listed with ``available: false`` and a concrete
``unavailable_reason`` — the catalog never invents placeholder layers.

Layer groups:
- ``vegetation``   — derived satellite index products (ndvi/evi/ndmi/ndwi/bsi)
  rendered from stored COGs via the tile service; available only when the
  P05 pipeline has actually produced assets for the field.
- ``environment``  — field-level observation series (precipitation, soil
  moisture, air temperature, reference ET0) from real ingested providers;
  each is available only when observations exist. ECOSTRESS LST and terrain
  elevation/slope have NO provider in the platform yet and are always
  reported unavailable with that explicit reason.
- ``infrastructure`` — farm/field boundaries (from registered geometry) and
  the statistical tercile zones of the latest processed product.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger("croptwist.geospatial.layer_catalog")

LAYER_CATALOG_VERSION = "map-layer-catalog-1.0.0"

VEGETATION_LAYER_CODES: tuple[str, ...] = ("ndvi", "evi", "ndmi", "ndwi", "bsi")

# Environmental observation variables the platform can actually ingest today
# (data-platform registry). Each maps to a field-level series layer.
ENVIRONMENTAL_VARIABLES: tuple[dict[str, str], ...] = (
    {"code": "precipitation", "unit": "mm", "label": "Precipitation (observation series)"},
    {"code": "soil_moisture_surface", "unit": "m3/m3", "label": "Soil moisture surface (observation series)"},
    {"code": "air_temperature_mean", "unit": "degC", "label": "Air temperature mean (observation series)"},
    {"code": "air_temperature_max", "unit": "degC", "label": "Air temperature max (observation series)"},
    {"code": "reference_et0", "unit": "mm", "label": "Reference ET0 (observation series)"},
)

# Declared-but-unimplemented environmental rasters. Honest unavailability:
# there is no ECOSTRESS/terrain ingestion pipeline in the platform, so these
# layers are ALWAYS unavailable until a real provider lands.
UNAVAILABLE_RASTER_LAYERS: tuple[dict[str, str], ...] = (
    {
        "code": "land_surface_temperature",
        "label": "Land surface temperature (ECOSTRESS)",
        "unavailable_reason": "no ECOSTRESS ingestion pipeline in the platform; no observations exist",
    },
    {
        "code": "terrain_elevation",
        "label": "Terrain elevation",
        "unavailable_reason": "no terrain DEM ingestion pipeline in the platform; no raster source connected",
    },
    {
        "code": "terrain_slope",
        "label": "Terrain slope",
        "unavailable_reason": "no terrain DEM ingestion pipeline in the platform; no raster source connected",
    },
)

NASA_HLS_ATTRIBUTION = (
    "NASA HLS (HLSL30/HLSS30) courtesy of NASA LP DAAC; contains Landsat "
    "(USGS) and modified Copernicus Sentinel-2 (ESA) data harmonized by NASA."
)


def field_map_layers(db: Session, field: Any) -> dict[str, Any]:
    """Catalog of every map layer for one field with honest availability."""
    from app.db.models import Observation
    from app.db.models_p2 import RasterAsset
    from app.vegetation.indices import INDEX_FORMULAS

    # ---- vegetation products grouped by index
    veg_rows = db.execute(
        select(
            RasterAsset.index_code,
            func.count(RasterAsset.id),
            func.max(RasterAsset.acquired_at),
        )
        .where(RasterAsset.field_id == field.id, RasterAsset.asset_kind == "derived")
        .group_by(RasterAsset.index_code)
    ).all()
    veg_counts = {row[0]: (int(row[1]), row[2]) for row in veg_rows}

    latest_products = _latest_products_by_index(db, field.id)
    dates_by_index = _available_dates_by_index(db, field.id, cap=60)

    vegetation_layers: list[dict[str, Any]] = []
    for code in VEGETATION_LAYER_CODES:
        count, latest_acquired = veg_counts.get(code, (0, None))
        product = latest_products.get(code)
        available = count > 0 and product is not None
        layer: dict[str, Any] = {
            "id": f"vegetation:{code}",
            "group": "vegetation",
            "code": code,
            "kind": "raster",
            "label": code.upper(),
            "index_formula": INDEX_FORMULAS.get(code),
            "available": available,
            "product_count": count,
            "dates_available": dates_by_index.get(code, []),
        }
        if available:
            layer.update(
                {
                    "render": {"type": "xyz_tiles", "tile_size": 256},
                    "latest": product,
                    "colormap": "fixed_documented_range",
                    "nodata_style": "transparent",
                    "source_attribution": NASA_HLS_ATTRIBUTION,
                    "provider_code": product.get("provider_code"),
                    "is_synthetic": product.get("is_synthetic"),
                }
            )
        else:
            layer["unavailable_reason"] = (
                "no processed derived products for this index — process a scene first"
                if count == 0
                else "derived product registry row lacks preview metadata"
            )
        vegetation_layers.append(layer)

    # ---- environmental observation series (honest availability)
    env_rows = db.execute(
        select(
            Observation.variable_code,
            func.count(Observation.id),
            func.max(Observation.observed_at),
        )
        .where(Observation.field_id == field.id)
        .where(Observation.variable_code.in_([v["code"] for v in ENVIRONMENTAL_VARIABLES]))
        .group_by(Observation.variable_code)
    ).all()
    env_counts = {row[0]: (int(row[1]), row[2]) for row in env_rows}

    environmental_layers: list[dict[str, Any]] = []
    for spec in ENVIRONMENTAL_VARIABLES:
        code = spec["code"]
        count, latest_obs = env_counts.get(code, (0, None))
        available = count > 0
        layer = {
            "id": f"environment:{code}",
            "group": "environment",
            "code": code,
            "kind": "field_series",
            "label": spec["label"],
            "unit": spec["unit"],
            "available": available,
            "observation_count": count,
            "latest_observed_at": latest_obs.isoformat() if latest_obs else None,
            "render": {"type": "field_timeseries"},
        }
        if not available:
            layer["unavailable_reason"] = (
                "no ingested observations for this variable on this field"
            )
        environmental_layers.append(layer)
    for spec in UNAVAILABLE_RASTER_LAYERS:
        environmental_layers.append(
            {
                "id": f"environment:{spec['code']}",
                "group": "environment",
                "code": spec["code"],
                "kind": "raster",
                "label": spec["label"],
                "available": False,
                "unavailable_reason": spec["unavailable_reason"],
                "render": None,
            }
        )

    # ---- infrastructure layers
    zone_capable = False
    for product in latest_products.values():
        if product.get("zone_summary") and product["zone_summary"].get("zones"):
            zone_capable = True
            break
    infrastructure_layers = [
        {
            "id": "infrastructure:field_boundary",
            "group": "infrastructure",
            "code": "field_boundary",
            "kind": "vector",
            "label": "Field boundary",
            "available": True,
            "render": {"type": "geojson"},
            "boundary_version": getattr(field, "boundary_version", None),
        },
        {
            "id": "infrastructure:statistical_zones",
            "group": "infrastructure",
            "code": "statistical_zones",
            "kind": "vector",
            "label": "Statistical tercile zones",
            "available": zone_capable,
            "render": {"type": "geojson"} if zone_capable else None,
            "zone_note": (
                "Rank-based statistical terciles — not agronomic management zones"
            ),
        },
    ]

    return {
        "catalog_version": LAYER_CATALOG_VERSION,
        "field_id": str(field.id),
        "layers": {
            "vegetation": vegetation_layers,
            "environment": environmental_layers,
            "infrastructure": infrastructure_layers,
        },
        "notes": [
            "Layers are listed only when their real datasets or processing products exist.",
            "Environmental layers are field-level observation series, not rasters.",
            "Statistical tercile zones are data-description strata, not agronomic zones.",
        ],
    }


def _latest_products_by_index(db: Session, field_id: Any) -> dict[str, dict[str, Any]]:
    """Latest derived + preview asset pair per index with map metadata."""
    from app.db.models_p2 import RasterAsset

    derived = db.scalars(
        select(RasterAsset)
        .where(RasterAsset.field_id == field_id, RasterAsset.asset_kind == "derived")
        .order_by(RasterAsset.acquired_at.desc(), RasterAsset.created_at.desc())
        .limit(400)
    ).all()
    previews = {
        (p.index_code, p.scene_id, p.processing_version): p
        for p in db.scalars(
            select(RasterAsset)
            .where(RasterAsset.field_id == field_id, RasterAsset.asset_kind == "preview")
            .order_by(RasterAsset.acquired_at.desc())
            .limit(400)
        ).all()
    }
    seen: set[str] = set()
    latest: dict[str, dict[str, Any]] = {}
    for asset in derived:
        if asset.index_code in seen:
            continue
        seen.add(asset.index_code)
        preview = previews.get((asset.index_code, asset.scene_id, asset.processing_version))
        stats = asset.stats_json or {}
        latest[asset.index_code] = {
            "asset_id": str(asset.id),
            "preview_asset_id": str(preview.id) if preview else None,
            "scene_id": asset.scene_id,
            "acquired_at": asset.acquired_at.isoformat() if asset.acquired_at else None,
            "processing_version": asset.processing_version,
            "spatial_resolution_m": asset.spatial_resolution_m,
            "crs": asset.crs,
            "bbox_wgs84": (preview.bbox_json if preview else None),
            "valid_pixel_fraction": asset.valid_pixel_fraction,
            "zonal": stats.get("zonal"),
            "zone_summary": stats.get("zone_summary"),
            "storage_backend": asset.storage_backend,
            "checksum_sha256": asset.checksum_sha256,
            "is_synthetic": None,  # resolved from the scene by the API layer
        }
    return latest


def _available_dates_by_index(db: Session, field_id: Any, *, cap: int) -> dict[str, list[dict[str, Any]]]:
    """Distinct acquisition dates per index (newest first, bounded)."""
    from app.db.models_p2 import RasterAsset

    rows = db.execute(
        select(
            RasterAsset.index_code,
            RasterAsset.scene_id,
            RasterAsset.acquired_at,
            RasterAsset.processing_version,
            RasterAsset.valid_pixel_fraction,
        )
        .where(RasterAsset.field_id == field_id, RasterAsset.asset_kind == "derived")
        .order_by(RasterAsset.acquired_at.desc())
        .limit(cap * len(VEGETATION_LAYER_CODES))
    ).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for index_code, scene_id, acquired_at, version, vpf in rows:
        bucket = out.setdefault(index_code, [])
        if len(bucket) >= cap:
            continue
        bucket.append(
            {
                "date": acquired_at.date().isoformat() if acquired_at else None,
                "acquired_at": acquired_at.isoformat() if acquired_at else None,
                "scene_id": scene_id,
                "processing_version": version,
                "valid_pixel_fraction": vpf,
            }
        )
    return out
