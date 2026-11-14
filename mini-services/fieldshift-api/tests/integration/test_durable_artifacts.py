"""Targeted integration coverage for bounded PostgreSQL artifact storage.

These tests are intentionally database-only.  Run them only against the
local disposable ``CROPTWIST_TEST_DB_URL`` database; provider transports are
already disabled/faked by the shared test conftest.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.db.models import Organization
from app.geospatial.objectstore import AssetValidationError, KeyConflictError, StorageError
from app.geospatial.postgres_objectstore import PostgresStorage


@pytest.fixture()
def report_access(client, auth_headers, monkeypatch, tmp_path):
    """Provision the existing sandbox capability in a disposable test tenant."""
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports"))
    headers, user = auth_headers
    response = client.post(
        "/api/v1/billing/subscription", headers=headers,
        json={"organization_id": user["organization"]["id"],
              "plan_code": "starter", "billing_period": "monthly"},
    )
    assert response.status_code == 200, response.text
    return headers, user


def _key(org_id: uuid.UUID, name: str = "artifact.bin") -> str:
    return f"org/{org_id}/reports/{name}"


class TestPostgresArtifactStorage:
    def test_round_trip_survives_new_adapter_instance(self, db):
        org_id = uuid.uuid4()
        db.add(Organization(id=org_id, name="artifact-test-org"))
        db.commit()
        key = _key(org_id)
        first = PostgresStorage(max_object_bytes=32, total_budget_bytes=128)
        stored = first.put_bytes(key, b"durable", content_type="application/octet-stream")
        second = PostgresStorage(max_object_bytes=32, total_budget_bytes=128)
        assert second.read_bytes(key) == b"durable"
        assert second.stat(key).checksum_sha256 == stored.checksum_sha256

    def test_same_write_is_idempotent_but_changed_write_conflicts(self, db):
        org_id = uuid.uuid4()
        db.add(Organization(id=org_id, name="conflict-test-org"))
        db.commit()
        key = _key(org_id, "same.bin")
        store = PostgresStorage(max_object_bytes=32, total_budget_bytes=128)
        first = store.put_bytes(key, b"same", content_type="application/octet-stream")
        retry = store.put_bytes(key, b"same", content_type="application/octet-stream")
        assert retry.checksum_sha256 == first.checksum_sha256
        with pytest.raises(KeyConflictError):
            store.put_bytes(key, b"changed", content_type="application/octet-stream")
        store.put_bytes(key, b"changed", content_type="application/octet-stream", overwrite=True)
        assert store.read_bytes(key) == b"changed"

    def test_tenant_key_and_path_validation(self):
        store = PostgresStorage(max_object_bytes=32, total_budget_bytes=128)
        with pytest.raises(StorageError):
            store.put_bytes("../escape", b"x", content_type="application/octet-stream")
        with pytest.raises(StorageError):
            store.put_bytes("org/not-a-uuid/reports/x", b"x", content_type="application/octet-stream")

    def test_object_and_total_budget_are_bounded(self, db):
        org_id = uuid.uuid4()
        db.add(Organization(id=org_id, name="budget-test-org"))
        db.commit()
        store = PostgresStorage(max_object_bytes=6, total_budget_bytes=10)
        store.put_bytes(_key(org_id, "a"), b"123456", content_type="application/octet-stream")
        with pytest.raises(AssetValidationError):
            store.put_bytes(_key(org_id, "too-large"), b"1234567", content_type="application/octet-stream")
        with pytest.raises(AssetValidationError):
            store.put_bytes(_key(org_id, "over-total"), b"12345", content_type="application/octet-stream")
        store.delete(_key(org_id, "a"))
        store.put_bytes(_key(org_id, "after-delete"), b"12345", content_type="application/octet-stream")


class TestPostgresReportArtifacts:
    def test_report_generation_and_authenticated_download_use_database(self, client, report_access, monkeypatch):
        monkeypatch.setattr(settings, "reports_storage_backend", "postgres", raising=False)
        headers, user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["status"] == "succeeded"
        download = client.get(f"/api/v1/reports/{job['id']}/download", headers=headers)
        assert download.status_code == 200
        assert download.content.startswith(b"\xef\xbb\xbf")
        key = f"org/{user['organization']['id']}/reports/{job['id']}.csv"
        assert PostgresStorage().read_bytes(key) == download.content
        assert not (Path(settings.reports_dir) / f"{job['id']}.csv").exists()
