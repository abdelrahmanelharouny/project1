"""Integration tests for Milestone 3 endpoints: CSV import, CHIRPS extraction,
provider health, per-field data coverage."""

import io
from datetime import date

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.data_platform.imports.csv_service import template_csv

pytestmark = pytest.mark.usefixtures("client")


def _tiff_bytes(value: float = 5.0, epsg: int = 4326, west: float = 31.40, north: float = 31.12) -> bytes:
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="float32",
            crs=f"EPSG:{epsg}",
            transform=from_origin(west, north, 0.002, 0.002),
            nodata=-9999.0,
        ) as dst:
            dst.write(np.full((10, 10), value, dtype=np.float32), 1)
        return memfile.read()


class TestProvidersHealthEndpoint:
    def test_lists_all_milestone3_providers(self, client, auth_headers):
        resp = client.get("/api/v1/data/providers/health", headers=auth_headers[0])
        assert resp.status_code == 200
        providers = {p["provider_code"]: p for p in resp.json()["providers"]}
        assert set(providers) == {"synthetic", "open_meteo", "chirps_import", "soilgrids", "farmer_csv"}
        assert providers["open_meteo"]["kind"] == "api"
        assert providers["open_meteo"]["details"]["models"]
        assert providers["soilgrids"]["status"] == "optional"
        assert providers["farmer_csv"]["kind"] == "file_import"
        assert providers["chirps_import"]["details"]["rasterio_available"] is True

    def test_probes_can_be_disabled(self, client, auth_headers):
        resp = client.get(
            "/api/v1/data/providers/health?with_probes=false", headers=auth_headers[0]
        )
        assert resp.status_code == 200
        assert all("probe" not in p for p in resp.json()["providers"])


class TestCsvImportEndpoint:
    def test_template_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/data/imports/observations-csv/template", headers=auth_headers[0])
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert resp.text.startswith("date,variable_code,value,unit,notes")

    def test_upload_ingests_farmer_reported_observations(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("rain-log.csv", template_csv().encode("utf-8"), "text/csv")}
        resp = client.post(
            f"/api/v1/fields/{field_id}/imports/observations-csv", headers=headers, files=files
        )
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["job_type"] == "csv_import"
        assert job["status"] == "succeeded"
        assert job["records_received"] == 3
        assert job["records_rejected"] == 0

        obs = client.get(
            f"/api/v1/fields/{field_id}/observations",
            headers=headers,
        ).json()
        assert obs["total"] == 3
        first = obs["items"][0]
        assert first["metadata"]["import_kind"] == "observations_csv"
        assert first["metadata"]["file_name"] == "rain-log.csv"

    def test_bad_rows_are_counted_and_warned(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        csv_text = (
            "date,variable_code,value,unit\n"
            "2024-03-01,precipitation,5,mm\n"
            "2024-03-02,unknown_var,5,mm\n"
            "2024-03-03,precipitation,5,cm\n"
        )
        files = {"file": ("mixed.csv", csv_text.encode("utf-8"), "text/csv")}
        resp = client.post(
            f"/api/v1/fields/{field_id}/imports/observations-csv", headers=headers, files=files
        )
        assert resp.status_code == 202
        job = resp.json()
        assert job["status"] == "succeeded"
        assert job["records_received"] == 3
        assert job["records_rejected"] == 2
        assert any("unknown variable_code" in w for w in job["warnings"])

    def test_wrong_header_is_422(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("bad.csv", b"a,b,c\n1,2,3\n", "text/csv")}
        resp = client.post(
            f"/api/v1/fields/{field_id}/imports/observations-csv", headers=headers, files=files
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_FAILED"

    def test_reupload_does_not_duplicate(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("rain-log.csv", template_csv().encode("utf-8"), "text/csv")}
        for _ in range(2):
            resp = client.post(
                f"/api/v1/fields/{field_id}/imports/observations-csv", headers=headers, files=files
            )
            assert resp.status_code == 202
        obs = client.get(f"/api/v1/fields/{field_id}/observations", headers=headers).json()
        assert obs["total"] == 3

    def test_non_utf8_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("bad.csv", b"\xff\xfe\x00bad", "application/octet-stream")}
        resp = client.post(
            f"/api/v1/fields/{field_id}/imports/observations-csv", headers=headers, files=files
        )
        assert resp.status_code == 422


class TestChirpsEndpoint:
    def test_extract_from_uploaded_geotiff(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("chirps-v3.0-daily.2024-01-31.tif", _tiff_bytes(7.5), "application/x-geotiff")}
        data = {"observed_at": "2024-01-31", "period_kind": "daily", "product_status": "final"}
        resp = client.post(
            f"/api/v1/fields/{field_id}/chirps-extractions", headers=headers, files=files, data=data
        )
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["job_type"] == "chirps_raster_import"
        assert job["status"] == "succeeded"
        assert job["records_received"] == 1

        obs = client.get(
            f"/api/v1/fields/{field_id}/observations?variable_code=precipitation", headers=headers
        ).json()
        assert obs["total"] == 1
        item = obs["items"][0]
        assert item["value"] == pytest.approx(7.5, abs=1e-4)
        assert item["metadata"]["product_status"] == "final"
        assert item["metadata"]["valid_cells"] == 100
        assert item["spatial_support_type"] == "polygon_average"

    def test_wrong_crs_fails_with_structured_error(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        files = {"file": ("utm.tif", _tiff_bytes(epsg=32633), "application/x-geotiff")}
        data = {"observed_at": "2024-01-31"}
        resp = client.post(
            f"/api/v1/fields/{field_id}/chirps-extractions", headers=headers, files=files, data=data
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_FAILED"


class TestDataCoverageEndpoint:
    def test_coverage_after_synthetic_ingestion(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        resp = client.post(
            f"/api/v1/fields/{field_id}/data-jobs",
            headers=headers,
            json={
                "provider_code": "synthetic",
                "variables": ["precipitation", "air_temperature_mean"],
                "start_date": "2023-01-01",
                "end_date": "2023-01-31",
                "profile": "semi_arid",
                "seed": 9,
            },
        )
        assert resp.status_code == 202, resp.text

        cov = client.get(f"/api/v1/fields/{field_id}/data-coverage", headers=headers).json()
        assert cov["field_id"] == field_id
        by_var = {v["variable_code"]: v for v in cov["variables"]}
        assert set(by_var) == {"precipitation", "air_temperature_mean"}
        for entry in by_var.values():
            assert entry["total"] == 31
            provs = entry["providers"]
            assert len(provs) == 1
            assert provs[0]["provider_code"] == "synthetic"
            assert provs[0]["first"] == "2023-01-01"
            assert provs[0]["last"] == "2023-01-31"
            assert provs[0]["last_retrieval"]

    def test_coverage_empty_field(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        cov = client.get(f"/api/v1/fields/{field_id}/data-coverage", headers=headers).json()
        assert cov["variables"] == []
