"""Measure preprocessing time + peak memory on representative raster fixtures.

P05 verification helper (Section 10). Runs the REAL preprocessing pipeline
(windowed COG read -> scale -> Fmask -> indices -> zonal -> COG+PNG) against
deterministic 40x40 fixture scenes (tests/fixtures/raster_fixtures.py) and
reports wall time and tracemalloc peak. These are TEST FIXTURES, not
satellite imagery; the numbers characterize per-window processing cost, not
full-scene throughput.

Usage:
    .venv/bin/python scripts/measure_processing_perf.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixtures.raster_fixtures import (  # noqa: E402
    fixture_field_geojson,
    write_fixture_scene,
)
from app.geospatial import preprocessing as pre  # noqa: E402

INDICES = ["ndvi", "evi", "ndmi", "ndwi", "bsi"]
SCALES = {"hls_scale": 0.0001}
FMASK_EXCLUDE = 0b010111  # cirrus|cloud|shadow|snow (HLS Fmask bits 0,1,3,4)


def run_once(with_cloud: bool) -> dict[str, object]:
    geojson = fixture_field_geojson()
    with tempfile.TemporaryDirectory(prefix="ct-perf-") as tmp:
        assets = write_fixture_scene(
            Path(tmp), scene_id="PERF-CASE", with_cloud_block=with_cloud
        )
        tracemalloc.start()
        t0 = time.perf_counter()
        reading = pre.read_scene_window(
            assets=assets,
            surfaces=pre.required_surfaces_for_indices(INDICES),
            geometry_geojson=geojson,
            gdal_env=None,
        )
        t_read = time.perf_counter() - t0
        t1 = time.perf_counter()
        products, prov = pre.derive_index_products(
            reading=reading,
            geometry_geojson=geojson,
            indices=INDICES,
            reflectance_scale=SCALES["hls_scale"],
            fmask_exclude_mask=FMASK_EXCLUDE,
        )
        t_derive = time.perf_counter() - t1
        t2 = time.perf_counter()
        for product in products:
            pre.write_index_cog(
                array=product.array,
                transform=reading.transform,
                crs_string=reading.crs,
                path=str(Path(tmp) / f"{product.index_code}.tif"),
            )
            pre.render_preview_png(
                index_array=product.array,
                index_code=product.index_code,
            )
        t_write = time.perf_counter() - t2
        _, peak_kb = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        valid = sum(1 for p in products if p.array is not None)
        masked_total = int(prov.get("field_mask_pixels", 0) or 0)
        masked_pixels = int((reading.fmask == 0).sum()) if reading.fmask is not None else None
        return {
            "cloud_block": with_cloud,
            "grid": f"{reading.width}x{reading.height} @30m EPSG:32636 window",
            "indices": [p.index_code for p in products[:valid]],
            "read_s": round(t_read, 3),
            "derive_s": round(t_derive, 3),
            "write_cog_png_s": round(t_write, 3),
            "total_s": round(t_read + t_derive + t_write, 3),
            "peak_python_mem_mb": round(peak_kb / 1024, 1),
            "field_mask_pixels": masked_total,
            "fmask_clear_pixels_in_window": masked_pixels,
        }


def main() -> int:
    print(json.dumps({
        "note": "deterministic 40x40 fixture scenes (test fixtures, not imagery)",
        "cases": [run_once(False), run_once(True)],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
