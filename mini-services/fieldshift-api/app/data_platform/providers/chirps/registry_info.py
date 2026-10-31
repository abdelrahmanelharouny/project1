"""CHIRPS v3 registry metadata shared by the extractor, registry and health views."""

from typing import Any

PROVIDER_CODE = "chirps_import"
PROVIDER_NAME = "CHIRPS v3 (file import + field extraction)"
PRODUCT_FAMILY = "chirps_v3"
SPATIAL_RESOLUTION_M = 5566.0  # 0.05 degree grid, ~5.6 km


def documented_limitations(period_kind: str = "daily") -> str:
    base = (
        "CHIRPS v3 is a quasi-global land rainfall product covering roughly 60N-60S "
        "on a 0.05-degree grid; it has no coverage over oceans and is not global. "
        "Values are estimates blended from satellite imagery and gauge stations."
    )
    if period_kind == "daily":
        return base + (
            " Daily products (especially downscaled fields) must not be used as "
            " unquestioned evidence for daily rainfall extremes; prefer pentadal or "
            " monthly products for climate summaries."
            " Dependency structure (CHC documentation): CHIRPS v3 daily fields may be"
            " produced by distributing pentad rainfall totals using daily information"
            " from models such as ERA5 or IMERG. CHIRPS daily and ERA5 daily are"
            " therefore NOT fully independent evidence — agreement between them must"
            " not be read as independent validation, and overlapping precipitation"
            " products are never blended in one feature calculation."
        )
    return base


def stub_fetch_message() -> str:
    return (
        "CHIRPS v3 is a file-import workflow: upload a CHIRPS GeoTIFF via "
        "POST /fields/{field_id}/chirps-extractions to extract a field-mean "
        "rainfall observation. It is not a fetch-style API provider."
    )
