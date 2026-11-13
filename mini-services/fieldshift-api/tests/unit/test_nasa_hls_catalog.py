"""Unit tests: NASA CMR STAC item/response parsing (P04).

Pure-function tests with fixture dictionaries — no HTTP transport involved.
Fixtures reflect the documented HLS v2.0 / CMR STAC shapes; they are
test-only and never presented as live data.
"""

from datetime import UTC, datetime

import pytest

from app.core.errors import ProviderRequestError
from app.data_platform.providers.nasa_hls import catalog
from app.data_platform.providers.nasa_hls.registry_info import (
    HLS_SPATIAL_RESOLUTION_M,
    PRODUCT_CODE_L30,
    PRODUCT_CODE_S30,
)

L30_ITEM = {
    "id": "HLS.L30.T16SDC.2024189T164537.v2.0",
    "collection": "HLSL30_2.0",
    "bbox": [31.4, 31.1, 31.42, 31.12],
    "geometry": {"type": "Polygon", "coordinates": [[[31.4, 31.1], [31.42, 31.1], [31.42, 31.12], [31.4, 31.12], [31.4, 31.1]]]},
    "properties": {
        "datetime": "2024-07-07T16:45:37Z",
        "eo:cloud_cover": 12.5,
        "platform": ["LANDSAT-8"],
    },
    "assets": {
        "B02": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B02.tif"},
        "B03": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B03.tif"},
        "B04": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B04.tif"},
        "B05": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B05.tif"},
        "B06": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B06.tif"},
        "B07": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.B07.tif"},
        "Fmask": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.L30.T16SDC.2024189T164537.v2.0.Fmask.tif"},
    },
}

S30_ITEM = {
    "id": "HLS.S30.T16SDC.2024191T160801.v2.0",
    "collection": "HLSS30_2.0",
    "bbox": [31.4, 31.1, 31.42, 31.12],
    "geometry": {"type": "Polygon", "coordinates": [[[31.4, 31.1], [31.42, 31.1], [31.42, 31.12], [31.4, 31.12], [31.4, 31.1]]]},
    "properties": {
        "datetime": "2024-07-09T16:08:01Z",
        "eo:cloud_cover": 41.2,
        "platform": ["SENTINEL-2B"],
    },
    "assets": {
        "B02": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.S30.T16SDC.2024191T160801.v2.0.B02.tif"},
        "B04": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.S30.T16SDC.2024191T160801.v2.0.B04.tif"},
        "B08": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.S30.T16SDC.2024191T160801.v2.0.B08.tif"},
        "B11": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.S30.T16SDC.2024191T160801.v2.0.B11.tif"},
        "Fmask": {"href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLS.S30.T16SDC.2024191T160801.v2.0.Fmask.tif"},
    },
}


def test_parse_l30_item_preserves_source_metadata():
    record, warnings = catalog.parse_stac_item(L30_ITEM)
    assert warnings == []
    assert record is not None
    assert record.scene_id == "HLS.L30.T16SDC.2024189T164537.v2.0"
    assert record.collection == PRODUCT_CODE_L30
    assert record.collection_id == "HLSL30_2.0"
    assert record.acquired_at == datetime(2024, 7, 7, 16, 45, 37, tzinfo=UTC)
    assert record.cloud_cover_pct == 12.5
    assert record.platform == "LANDSAT-8"
    assert record.spatial_resolution_m == HLS_SPATIAL_RESOLUTION_M == 30.0
    # Landsat band naming: nir is B05, swir1 is B06.
    assert record.band_mapping == {
        "blue": "B02",
        "green": "B03",
        "red": "B04",
        "nir": "B05",
        "swir1": "B06",
        "swir2": "B07",
        "fmask": "Fmask",
    }
    assert "red" in record.asset_refs and "nir" in record.asset_refs
    assert record.asset_refs["fmask"].endswith("Fmask.tif")
    assert record.processing_version == "2.0"
    assert record.footprint_geojson["type"] == "Polygon"


def test_parse_s30_item_uses_sentinel2_band_naming():
    record, warnings = catalog.parse_stac_item(S30_ITEM)
    assert warnings == []
    assert record is not None
    assert record.collection == PRODUCT_CODE_S30
    # Sentinel-2 naming inside the NASA-harmonized product: nir is B08, swir1 B11.
    assert record.band_mapping["nir"] == "B08"
    assert record.band_mapping["swir1"] == "B11"
    assert record.band_mapping["red"] == "B04"


def test_parse_item_tolerates_suffixed_asset_keys():
    item = dict(L30_ITEM)
    item["assets"] = {f"{k}_30m": v for k, v in L30_ITEM["assets"].items()}
    record, warnings = catalog.parse_stac_item(item)
    assert warnings == []
    assert record is not None
    assert "red" in record.asset_refs


def test_parse_item_skips_non_hls_collection():
    item = {**L30_ITEM, "collection": "VNP13A1.1"}
    record, warnings = catalog.parse_stac_item(item)
    assert record is None
    assert warnings and "not an HLS product" in warnings[0]


def test_parse_item_skips_missing_identity_honestly():
    record, warnings = catalog.parse_stac_item({"collection": "HLSL30_2.0", "properties": {}})
    assert record is None
    assert warnings
    record2, warnings2 = catalog.parse_stac_item({**L30_ITEM, "properties": {"eo:cloud_cover": 1}})
    assert record2 is None
    assert any("timestamp" in w for w in warnings2)


def test_parse_item_normalizes_platform_shapes():
    as_str = {**L30_ITEM, "properties": {**L30_ITEM["properties"], "platform": "LANDSAT_9"}}
    record, _ = catalog.parse_stac_item(as_str)
    assert record.platform == "LANDSAT_9"
    none_platform = {**L30_ITEM, "properties": {**L30_ITEM["properties"], "platform": None}}
    record2, _ = catalog.parse_stac_item(none_platform)
    assert record2.platform is None


def test_parse_search_response_follows_next_marker_dict_body():
    body = {
        "features": [L30_ITEM],
        "links": [
            {"rel": "next", "method": "POST", "body": {"searchAfter": ["abc"]}},
            {"rel": "self"},
        ],
    }
    records, warnings, marker = catalog.parse_search_response(body)
    assert [r.scene_id for r in records] == [L30_ITEM["id"]]
    assert warnings == []
    assert marker == {"searchAfter": ["abc"]}


def test_parse_search_response_handles_string_body():
    import json as _json

    body = {
        "features": [],
        "links": [{"rel": "next", "method": "POST", "body": _json.dumps({"page": 2})}],
    }
    _, warnings, marker = catalog.parse_search_response(body)
    assert marker == {"page": 2}
    assert warnings == []


def test_parse_search_response_requires_features():
    with pytest.raises(ProviderRequestError):
        catalog.parse_search_response({"nope": True})


def test_search_scenes_requires_convertible_geometry():
    start = datetime(2024, 6, 1, tzinfo=UTC)
    end = datetime(2024, 6, 10, tzinfo=UTC)
    with pytest.raises(ProviderRequestError):
        catalog.search_scenes(geometry_geojson={}, start=start, end=end)
