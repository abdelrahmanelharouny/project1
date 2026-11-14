"""Integration: P3 notification center + user preferences + report jobs.

Mirrors the shared integration conventions (client/auth_headers fixtures,
plain pytest classes). The reports artifact directory is redirected to a
per-test tmp_path so no test writes into the real reports_storage; the
delete test additionally verifies its artifact is removed.

Coverage:
- notifications: DB-level dedupe via dedupe_key (unique), list filters
  (unread_only / category / severity), mark read + unread, mark-all,
  unread-count, per-category preferences GET/PUT (+ invalid category 422)
- user preferences: defaults, partial update, validation rejections
- reports: queued job lifecycle, inline csv execution (BOM magic bytes),
  pdf execution via service.execute_report_job (%PDF magic bytes), file
  written under settings.reports_dir, org-scoped listing (org B cannot see
  org A's reports), download + delete removes row AND artifact
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models_p3 import ReportJob
from app.notifications import service as notifications_service
from app.reports import service as reports_service


def _register(client, display_name: str) -> tuple[dict, dict]:
    email = f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


@pytest.fixture(autouse=True)
def _reports_dir_tmp(monkeypatch, tmp_path):
    """Every artifact in this module lands in a throwaway directory."""
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports_storage"))
    return tmp_path / "reports_storage"


@pytest.fixture()
def report_access(client, auth_headers):
    """Start the local sandbox trial for positive report-capability tests."""
    headers, user = auth_headers
    response = client.post(
        "/api/v1/billing/subscription",
        headers=headers,
        json={
            "organization_id": user["organization"]["id"],
            "plan_code": "starter",
            "billing_period": "monthly",
        },
    )
    assert response.status_code == 200, response.text
    return headers, user


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------
class TestNotificationCenter:
    def _emit(self, db, org, **kwargs):
        notification = notifications_service.create_notification(
            db, organization_id=uuid.UUID(org), **kwargs
        )
        assert notification is not None
        return notification

    def test_dedupe_key_is_unique_per_org(self, client, auth_headers, db):
        headers, user = auth_headers
        org = user["organization"]["id"]
        first = self._emit(
            db,
            org,
            category="system",
            title="Backup finished",
            dedupe_key="system:backup:weekly",
        )
        second = self._emit(
            db,
            org,
            category="system",
            title="Backup finished",
            dedupe_key="system:backup:weekly",
        )
        assert second.id == first.id  # idempotent emission — existing row wins
        listed = client.get("/api/v1/notifications", headers=headers).json()
        assert listed["total"] == 1

    def test_same_dedupe_key_in_another_org_is_fine(self, client, auth_headers, db):
        _headers, user = auth_headers
        org_a = user["organization"]["id"]
        other_headers, other_user = _register(client, "Other")
        org_b = other_user["organization"]["id"]
        a = self._emit(db, org_a, category="system", title="A", dedupe_key="k:1")
        b = self._emit(db, org_b, category="system", title="B", dedupe_key="k:1")
        assert a.id != b.id  # dedupe scope is (organization_id, dedupe_key)

    def test_list_filters_unread_category_severity(self, client, auth_headers, db):
        headers, user = auth_headers
        org = user["organization"]["id"]
        self._emit(db, org, category="billing", title="Invoice paid", severity="info")
        self._emit(db, org, category="system", title="Maintenance", severity="warning")
        self._emit(
            db, org, category="agronomic_alert", title="Frost risk", severity="critical"
        )

        everything = client.get("/api/v1/notifications", headers=headers).json()
        assert everything["total"] == 3
        assert everything["unread"] == 3

        unread = client.get(
            "/api/v1/notifications", headers=headers, params={"unread_only": "true"}
        ).json()
        assert unread["total"] == 3

        by_category = client.get(
            "/api/v1/notifications", headers=headers, params={"category": "system"}
        ).json()
        assert by_category["total"] == 1
        assert by_category["items"][0]["title"] == "Maintenance"

        by_severity = client.get(
            "/api/v1/notifications", headers=headers, params={"severity": "critical"}
        ).json()
        assert by_severity["total"] == 1
        assert by_severity["items"][0]["severity"] == "critical"

        invalid = client.get(
            "/api/v1/notifications", headers=headers, params={"severity": "loud"}
        )
        assert invalid.status_code == 422

    def test_mark_read_unread_and_read_all(self, client, auth_headers, db):
        headers, user = auth_headers
        org = user["organization"]["id"]
        n1 = self._emit(db, org, category="billing", title="One")
        n2 = self._emit(db, org, category="billing", title="Two")
        n3 = self._emit(db, org, category="system", title="Three")

        marked = client.post(
            f"/api/v1/notifications/{n1.id}/read", headers=headers, json={"read": True}
        )
        assert marked.status_code == 200
        assert marked.json()["read"] is True

        listed = client.get("/api/v1/notifications", headers=headers).json()
        assert listed["unread"] == 2
        count = client.get("/api/v1/notifications/unread-count", headers=headers).json()
        assert count["unread"] == 2

        # mark back to unread
        unmarked = client.post(
            f"/api/v1/notifications/{n1.id}/read", headers=headers, json={"read": False}
        )
        assert unmarked.status_code == 200
        assert unmarked.json()["read"] is False

        read_all = client.post("/api/v1/notifications/read-all", headers=headers)
        assert read_all.status_code == 200
        assert read_all.json()["marked"] == 3
        assert client.get("/api/v1/notifications/unread-count", headers=headers).json()[
            "unread"
        ] == 0

        # unknown notification id -> 404 (not another org's data)
        missing = client.post(
            f"/api/v1/notifications/{uuid.uuid4()}/read", headers=headers, json={"read": True}
        )
        assert missing.status_code == 404
        assert n2 and n3  # silence linters — ids used for counts only

    def test_notification_preferences_default_and_update(self, client, auth_headers):
        headers, _user = auth_headers
        prefs = client.get("/api/v1/notifications/preferences", headers=headers).json()
        assert len(prefs["items"]) == 8  # the full fixed category list
        by_cat = {p["category"]: p for p in prefs["items"]}
        assert set(by_cat) == set(notifications_service.CATEGORIES)
        assert all(p["in_app_enabled"] is True for p in prefs["items"])
        assert all(p["email_enabled"] is False for p in prefs["items"])

        updated = client.put(
            "/api/v1/notifications/preferences",
            headers=headers,
            json={"category": "billing", "email_enabled": True},
        )
        assert updated.status_code == 200
        assert updated.json() == {
            "category": "billing",
            "in_app_enabled": True,
            "email_enabled": True,
        }
        refetched = client.get("/api/v1/notifications/preferences", headers=headers).json()
        billing = [p for p in refetched["items"] if p["category"] == "billing"][0]
        assert billing["email_enabled"] is True

        bad = client.put(
            "/api/v1/notifications/preferences",
            headers=headers,
            json={"category": "spam", "in_app_enabled": False},
        )
        assert bad.status_code == 422


class TestUserPreferences:
    def test_defaults_created_on_first_access(self, client, auth_headers):
        headers, _user = auth_headers
        prefs = client.get("/api/v1/preferences", headers=headers).json()
        assert prefs["locale"] == "en"
        assert prefs["timezone"] == "UTC"
        assert prefs["unit_system"] == "metric"
        assert prefs["currency_code"] == "USD"
        assert prefs["week_start"] == "monday"
        assert prefs["agricultural_calendar"] is None
        assert prefs["notifications"] == {"in_app": True, "email": False}

    def test_partial_update_roundtrip(self, client, auth_headers):
        headers, _user = auth_headers
        updated = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={
                "locale": "ar",
                "unit_system": "imperial",
                "week_start": "sunday",
                "currency_code": "egp",
                "country_code": "EG",
                "agricultural_calendar": "coptic",
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["locale"] == "ar"
        assert body["unit_system"] == "imperial"
        assert body["week_start"] == "sunday"
        assert body["currency_code"] == "EGP"  # normalized
        assert body["country_code"] == "EG"
        assert body["agricultural_calendar"] == "coptic"
        # untouched fields keep their defaults
        assert body["timezone"] == "UTC"

        cleared = client.put(
            "/api/v1/preferences",
            headers=headers,
            json={"agricultural_calendar": None, "country_code": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["agricultural_calendar"] is None
        assert cleared.json()["country_code"] is None

    def test_invalid_values_rejected(self, client, auth_headers):
        headers, _user = auth_headers
        for payload, field in (
            ({"locale": "fr"}, "locale"),
            ({"unit_system": "parsecs"}, "unit_system"),
            ({"week_start": "funday"}, "week_start"),
            ({"currency_code": "DOLLAR"}, "currency_code"),
        ):
            resp = client.put("/api/v1/preferences", headers=headers, json=payload)
            assert resp.status_code == 422, f"{field} should be rejected"
        # pydantic pattern enforcement for week_start happens before the service
        assert (
            client.put(
                "/api/v1/preferences", headers=headers, json={"currency_code": "US"}
            ).status_code
            == 422
        )


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
class TestReportJobs:
    def test_free_plan_cannot_create_report(self, client, auth_headers):
        headers, _user = auth_headers
        response = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "pdf"},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_create_job_starts_queued(self, client, report_access):
        headers, user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "pdf"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "queued"
        assert body["report_type"] == "org_executive"
        assert body["output_format"] == "pdf"
        assert body["organization_id"] == user["organization"]["id"]
        assert body["_links"]["download"].endswith(f"/api/v1/reports/{body['id']}/download")

        fetched = client.get(f"/api/v1/reports/{body['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "queued"

    def test_sync_csv_renders_with_bom_magic_bytes(self, client, report_access):
        headers, user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["status"] == "succeeded"
        assert job["file_size_bytes"] > 0

        download = client.get(f"/api/v1/reports/{job['id']}/download", headers=headers)
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
        assert download.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM (Excel)
        assert b"# " in download.content[:200]  # header comment lines

    def test_sync_rejected_for_pdf(self, client, auth_headers):
        headers, _user = auth_headers
        resp = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "pdf", "sync": True},
        )
        assert resp.status_code == 422

    def test_pdf_job_executes_via_service_and_writes_artifact(
        self, client, report_access, db
    ):
        headers, user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "pdf"},
        )
        job_id = uuid.UUID(created.json()["id"])

        success, error = reports_service.execute_report_job(db, job_id)
        assert success is True, error
        assert error is None

        row = db.get(ReportJob, job_id)
        db.refresh(row)
        assert row.status == "succeeded"
        assert row.file_size_bytes and row.file_size_bytes > 0
        artifact = settings.reports_dir + f"/{job_id}.pdf"
        with open(artifact, "rb") as fh:
            magic = fh.read(5)
        assert magic == b"%PDF-"  # real PDF, not a text stub

        # status endpoint reflects the executed job; download serves the file
        status = client.get(f"/api/v1/reports/{job_id}/status", headers=headers).json()
        assert status["status"] == "succeeded"
        assert status["file_size_bytes"] == row.file_size_bytes
        download = client.get(f"/api/v1/reports/{job_id}/download", headers=headers)
        assert download.status_code == 200
        assert download.content.startswith(b"%PDF-")
        assert "attachment" in download.headers["content-disposition"]

    def test_unknown_report_type_rejected(self, client, auth_headers):
        headers, _user = auth_headers
        resp = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "magic_quad", "format": "csv", "sync": True},
        )
        assert resp.status_code == 422

    def test_bad_date_range_rejected(self, client, auth_headers):
        headers, _user = auth_headers
        resp = client.post(
            "/api/v1/reports",
            headers=headers,
            json={
                "report_type": "org_executive",
                "format": "csv",
                "sync": True,
                "date_from": "2024-05-01",
                "date_to": "2024-04-01",
            },
        )
        assert resp.status_code == 422

    def test_reports_list_scoped_to_own_org(self, client, report_access):
        headers, _user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        job_id = created.json()["id"]

        other_headers, _other = _register(client, "Malory")
        # org B sees an empty library and cannot touch org A's report
        listed = client.get("/api/v1/reports", headers=other_headers).json()
        assert listed["total"] == 0
        assert client.get(f"/api/v1/reports/{job_id}", headers=other_headers).status_code == 403
        assert (
            client.get(f"/api/v1/reports/{job_id}/download", headers=other_headers).status_code
            == 403
        )
        assert (
            client.get(f"/api/v1/reports/{job_id}/status", headers=other_headers).status_code
            == 403
        )
        assert client.delete(f"/api/v1/reports/{job_id}", headers=other_headers).status_code == 403
        # owner still sees it
        assert client.get(f"/api/v1/reports/{job_id}", headers=headers).status_code == 200

    def test_regenerate_rerenders_job(self, client, report_access):
        headers, _user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        job_id = created.json()["id"]
        regenerated = client.post(f"/api/v1/reports/{job_id}/regenerate", headers=headers)
        assert regenerated.status_code == 200
        body = regenerated.json()
        assert body["rendered"] is True
        assert body["status"] == "succeeded"

    def test_delete_removes_row_and_artifact(self, client, report_access, db):
        headers, _user = report_access
        created = client.post(
            "/api/v1/reports",
            headers=headers,
            json={"report_type": "org_executive", "format": "csv", "sync": True},
        )
        job_id = uuid.UUID(created.json()["id"])
        row = db.get(ReportJob, job_id)
        db.refresh(row)
        artifact = row.file_path
        assert artifact  # succeeded jobs store their artifact path

        deleted = client.delete(f"/api/v1/reports/{job_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.get(f"/api/v1/reports/{job_id}", headers=headers).status_code == 404
        assert db.scalar(select(ReportJob).where(ReportJob.id == job_id)) is None

        import os

        assert not os.path.exists(artifact)  # the artifact was cleaned up too
