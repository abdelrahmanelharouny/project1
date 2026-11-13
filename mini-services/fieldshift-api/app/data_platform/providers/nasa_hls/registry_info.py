"""Provider/product identity for the NASA HLS acquisition adapter (P04).

NASA HLS (Harmonized Landsat Sentinel-2) surface reflectance, distributed by
NASA LP DAAC and discoverable through the NASA CMR STAC API.

Product facts (documented — never invented):
- HLSL30: Landsat 8/9 OLI/OLI-SR harmonized to 30 m (v2.0).
- HLSS30: Sentinel-2 MSI L2A harmonized to 30 m (v2.0). Sentinel-2 itself is
  an ESA/Copernicus mission — HLS is the NASA harmonized product that ingests
  it; Sentinel-2 is never described here as a NASA satellite.
- Spatial resolution: 30 m (both collections are resampled to the 30 m grid).
- Reflectance scale factor: 0.0001 (DN -> surface reflectance [0,1]).
- Combined effective revisit: ~2-4 days (subject to clouds and latitude).
- Access: CMR STAC search is unauthenticated; asset downloads require a free
  NASA Earthdata Login (bearer token or basic auth over the URS redirect).
- License: NASA data is open (no restrictions on use); attribution requested.

Source attribution (condensed LP DAAC wording):
"Harmonized Landsat Sentinel-2 surface reflectance product maintained by
NASA LP DAAC; contains Landsat data (USGS) and modified Copernicus Sentinel-2
data harmonized by NASA."
"""

PROVIDER_CODE = "nasa_hls"
PROVIDER_NAME = "NASA HLS (Harmonized Landsat Sentinel-2, LP DAAC)"

# Product codes must match the DatasetProduct rows seeded in seed_sources.py
# AND the collection short names parsed from CMR STAC items.
PRODUCT_CODE_L30 = "HLSL30"
PRODUCT_CODE_S30 = "HLSS30"
PRODUCT_VERSION = "2.0"

# Full (versioned) CMR STAC collection identifiers, overridable via settings.
DEFAULT_COLLECTION_ID_L30 = "HLSL30_2.0"
DEFAULT_COLLECTION_ID_S30 = "HLSS30_2.0"

HLS_SPATIAL_RESOLUTION_M = 30.0
HLS_REFLECTANCE_SCALE = 0.0001

LICENSE_NAME = "NASA open data (no restrictions on use)"
LICENSE_URL = "https://earthdata.nasa.gov/earth-observation-data/data-use-policy"
ATTRIBUTION_TEXT = (
    "NASA Harmonized Landsat Sentinel-2 (HLS) surface reflectance courtesy of "
    "NASA LP DAAC; contains Landsat data (USGS) and modified Copernicus "
    "Sentinel-2 data (ESA) harmonized by NASA."
)
DOCUMENTATION_URL = "https://lpdaac.usgs.gov/products/hlsl30v2.0/"

KNOWN_LIMITATIONS = (
    "30 m harmonized surface reflectance: sub-field variability claims below "
    "the zonal pixel threshold are refused, never asserted. Cloud, shadow, "
    "cirrus and snow/ice pixels are masked via the HLS Fmask layer; masking "
    "is imperfect and heavily clouded periods can leave long data gaps. "
    "HLS is an atmospheric-corrected ESTIMATE, not a ground measurement. "
    "HLS is a vegetation/land product: it does NOT provide parcel-level soil "
    "moisture (coarse-resolution SMAP data, when integrated later, must never "
    "be presented as field-scale soil moisture)."
)

# Fmask (HLS v2 QA) bit assignments, from the HLS v2.0 user guide.
FMASK_BIT_CIRRUS = 0
FMASK_BIT_CLOUD = 1
FMASK_BIT_ADJACENT_TO_CLOUD = 2
FMASK_BIT_CLOUD_SHADOW = 3
FMASK_BIT_SNOW_ICE = 4
FMASK_BIT_WATER = 5
# Bits excluded from vegetation statistics: cirrus, cloud, shadow, snow/ice.
# (Adjacent-to-cloud and water bits are recorded but not excluded.)
FMASK_EXCLUDE_MASK = 0b011011  # bits 0,1,3,4

# Surface -> asset key per collection (HLS v2.0 asset naming).
HLS_L30_SURFACE_ASSETS = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "nir": "B05",
    "swir1": "B06",
    "swir2": "B07",
}
HLS_S30_SURFACE_ASSETS = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "nir": "B08",
    "swir1": "B11",
    "swir2": "B12",
}

SURFACE_ASSETS_BY_COLLECTION = {
    PRODUCT_CODE_L30: HLS_L30_SURFACE_ASSETS,
    PRODUCT_CODE_S30: HLS_S30_SURFACE_ASSETS,
}


def documented_limitations() -> str:
    return KNOWN_LIMITATIONS
