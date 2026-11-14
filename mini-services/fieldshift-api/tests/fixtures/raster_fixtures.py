"""Deterministic raster fixtures for P05 geospatial tests.

These are TEST FIXTURES — small synthetic GeoTIFFs with known expected
outputs. They are explicitly NOT production imagery and never enter
production storage: fixture paths live under tmp_path only, and the
processing service refuses synthetic scenes (the nasa_hls +
is_synthetic=False gate keeps fixtures out of the production pipeline).

Each fixture scene is written in a REAL UTM CRS (EPSG:32636, the common
HLS zone) so CRS handling is exercised honestly — the field geometry
reprojects from EPSG:4326 into the raster grid exactly like a real HLS
scene would require.
"""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin

# Fixture scene: 40x40 pixels at 30 m in EPSG:32636.
FIXTURE_CRS = "EPSG:32636"
FIXTURE_WIDTH = 40
FIXTURE_HEIGHT = 40
FIXTURE_RES = 30.0
FIXTURE_LEFT = 500000.0
FIXTURE_TOP = 3800000.0

# Known DN values (HLS v2.0 scale 0.0001 -> surface reflectance below).
VEGETATED_DN = {"red": 1000, "nir": 5000, "blue": 800, "green": 1200, "swir1": 2000, "swir2": 1500}
STRESSED_DN = {"red": 3000, "nir": 2500, "blue": 1000, "green": 1500, "swir1": 3500, "swir2": 3000}
NODATA_DN = -9999

# Expected indices from the documented formulas (surface reflectance):
EXPECTED_VEGETATED = {
    "ndvi": (0.50 - 0.10) / (0.50 + 0.10),
    "evi": 2.5 * (0.50 - 0.10) / (0.50 + 6.0 * 0.10 - 7.5 * 0.08 + 1.0),
    "savi": 1.5 * (0.50 - 0.10) / (0.50 + 0.10 + 0.5),
    "ndmi": (0.50 - 0.20) / (0.50 + 0.20),
    "ndwi": (0.12 - 0.50) / (0.12 + 0.50),
    "bsi": ((0.20 + 0.10) - (0.50 + 0.08)) / ((0.20 + 0.10) + (0.50 + 0.08)),
}
EXPECTED_STRESSED = {
    "ndvi": (0.25 - 0.30) / (0.25 + 0.30),
    "evi": 2.5 * (0.25 - 0.30) / (0.25 + 6.0 * 0.30 - 7.5 * 0.10 + 1.0),
    "savi": 1.5 * (0.25 - 0.30) / (0.25 + 0.30 + 0.5),
    "ndmi": (0.25 - 0.35) / (0.25 + 0.35),
    "ndwi": (0.15 - 0.25) / (0.15 + 0.25),
    "bsi": ((0.35 + 0.30) - (0.25 + 0.10)) / ((0.35 + 0.30) + (0.25 + 0.10)),
}

FMASK_CLOUD = 0b000010   # bit 1
FMASK_SHADOW = 0b001000  # bit 3
FMASK_CIRRUS = 0b000001  # bit 0
FMASK_SNOW = 0b010000    # bit 4
FMASK_WATER = 0b100000   # bit 5 (recorded, NOT excluded)


def write_fixture_scene(
    directory,
    *,
    scene_id: str,
    with_cloud_block: bool = False,
    with_nodata_patch: bool = False,
    left: float = FIXTURE_LEFT,
    top: float = FIXTURE_TOP,
    width: int = FIXTURE_WIDTH,
    height: int = FIXTURE_HEIGHT,
    crs: str = FIXTURE_CRS,
) -> dict[str, str]:
    """Write band + fmask GeoTIFFs for one fixture scene; returns hrefs.

    Layout: top half vegetated (EXPECTED_VEGETATED reflectances), bottom
    half stressed (EXPECTED_STRESSED) — a spatial contrast zones/trends can
    be verified against. Cloud block and nodata patch scale with the grid
    (fixed 8x8 / 6x6 pixel sizes anchored near the upper-left / lower-right).
    ``left``/``top``/``width``/``height``/``crs`` allow positioning a fixture
    over arbitrary locations (demo seeding) while keeping the same known
    reflectance values.
    """
    paths: dict[str, str] = {}
    transform = from_origin(left, top, FIXTURE_RES, FIXTURE_RES)
    for surface in ("blue", "green", "red", "nir", "swir1", "swir2"):
        arr = np.full((height, width), VEGETATED_DN[surface], dtype="float64")
        arr[height // 2 :, :] = STRESSED_DN[surface]
        if with_cloud_block:
            arr[4:12, 4:12] = 0  # DN zero is in-range; the fmask marks it cloudy
        if with_nodata_patch:
            arr[height - 10 : height - 4, width - 12 : width - 6] = NODATA_DN
        path = str(directory / f"{scene_id}.{surface}.tif")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float64",
            crs=crs,
            transform=transform,
            nodata=float(NODATA_DN),
        ) as dst:
            dst.write(arr, 1)
        paths[surface] = path

    fmask = np.zeros((height, width), dtype="uint8")
    if with_cloud_block:
        fmask[4:12, 4:12] = FMASK_CLOUD | FMASK_CIRRUS | FMASK_SHADOW
    # The nodata patch intentionally remains Fmask-clear so nodata tests can
    # distinguish source-band validity from cloud masking.
    fmask_path = str(directory / f"{scene_id}.fmask.tif")
    with rasterio.open(
        fmask_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(fmask, 1)
    paths["fmask"] = fmask_path
    return paths


def field_local_utm_scene_params(geometry_geojson: dict) -> dict:
    """Position a fixture scene over an arbitrary field polygon (EPSG:4326).

    Picks the local UTM zone from the centroid, projects the field bbox,
    and returns left/top/width/height/crs covering it with margin. Used by
    the demo seeder so fixture scenes genuinely intersect real field rows.
    """
    from pyproj import CRS, Transformer
    from shapely.geometry import shape

    geom = shape(geometry_geojson)
    minx, miny, maxx, maxy = geom.bounds
    lon = (minx + maxx) / 2
    zone = int((lon + 180) / 6) + 1
    crs = f"EPSG:326{zone:02d}" if miny >= 0 else f"EPSG:327{zone:02d}"
    transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_string(crs), always_xy=True)
    corners = [
        transformer.transform(minx, miny),
        transformer.transform(maxx, miny),
        transformer.transform(minx, maxy),
        transformer.transform(maxx, maxy),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    span_x = max(maxx - minx, 0)
    margin = 1.5
    need_w = int((max(xs) - min(xs)) * margin / FIXTURE_RES) + 8
    need_h = int((max(ys) - min(ys)) * margin / FIXTURE_RES) + 8
    width = max(40, min(need_w, 240))
    height = max(40, min(need_h, 240))
    left = (min(xs) + max(xs)) / 2 - width * FIXTURE_RES / 2
    top = (min(ys) + max(ys)) / 2 + height * FIXTURE_RES / 2
    return {"left": left, "top": top, "width": width, "height": height, "crs": crs}


def fixture_field_geojson() -> dict:
    """Field polygon inside the fixture scene (EPSG:4326).

    Covers rows ~6..34, cols ~5..35 — overlaps the cloud block (when
    present), both reflectance halves and the nodata patch.
    """
    from pyproj import CRS, Transformer

    transformer = Transformer.from_crs(CRS.from_epsg(32636), CRS.from_epsg(4326), always_xy=True)
    left = FIXTURE_LEFT + 5 * FIXTURE_RES
    right = FIXTURE_LEFT + 35 * FIXTURE_RES
    top = FIXTURE_TOP - 6 * FIXTURE_RES
    bottom = FIXTURE_TOP - 34 * FIXTURE_RES
    corners = [
        transformer.transform(left, bottom),
        transformer.transform(right, bottom),
        transformer.transform(right, top),
        transformer.transform(left, top),
        transformer.transform(left, bottom),
    ]
    return {
        "type": "Polygon",
        "coordinates": [[list(c) for c in corners]],
    }
