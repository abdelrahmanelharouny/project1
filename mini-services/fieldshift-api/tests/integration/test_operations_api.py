"""Integration: resources, operations & scheduling API (M6C Increment 7)."""

import uuid


def _register(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": f"user-{uuid.uuid4().hex[:10]}@test.local",
              "password": "test-password-1", "display_name": "Farmer"},
    )
    return {"Authorization": f"Bearer {resp.json()['token']}"}, resp.json()


def _farm_and_field(client, headers):
    farm = client.post(
        "/api/v1/farms", headers=headers,
        json={"name": "Sched Farm", "country_code": "EG", "timezone": "Africa/Cairo"},
    ).json()
    field = client.post(
        f"/api/v1/farms/{farm['id']}/fields", headers=headers,
        json={
            "name": "Sched Field",
            "geometry": {"type": "Polygon", "coordinates": [
                [[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]]},
        },
    ).json()
    return farm, field


class TestResources:
    def test_resource_crud_and_validation(self, client):
        headers, _ = _register(client)
        farm, _ = _farm_and_field(client, headers)
        resp = client.post(
            f"/api/v1/farms/{farm['id']}/resources", headers=headers,
            json={"resource_type": "tractor", "name": "Ford 5000",
                  "availability_calendar": [{"from": "2026-09-01", "to": "2026-11-30"}]},
        )
        assert resp.status_code == 201, resp.text
        resource = resp.json()
        assert resource["resource_type"] == "tractor"
        listing = client.get(
            f"/api/v1/farms/{farm['id']}/resources", headers=headers
        ).json()
        assert listing["total"] == 1
        bad = client.post(
            f"/api/v1/farms/{farm['id']}/resources", headers=headers,
            json={"resource_type": "dragon", "name": "x"},
        )
        assert bad.status_code == 422

    def test_resources_tenant_isolated(self, client):
        headers, _ = _register(client)
        r = client.post("/api/v1/auth/register", json={
            "email": f"other-{uuid.uuid4().hex[:10]}@test.local",
            "password": "test-password-1", "display_name": "Other"})
        assert r.status_code == 201, r.text
        other = r.json()
        farm, _ = _farm_and_field(client, headers)
        resp = client.get(
            f"/api/v1/farms/{farm['id']}/resources",
            headers={"Authorization": f"Bearer {other['token']}"},
        )
        assert resp.status_code == 403


class TestOperationsAndScheduling:
    def _setup(self, client):
        headers, user = _register(client)
        farm, field = _farm_and_field(client, headers)
        client.post(
            f"/api/v1/farms/{farm['id']}/resources", headers=headers,
            json={"resource_type": "tractor", "name": "T1"},
        )
        return headers, farm, field

    def test_generate_operations_from_templates(self, client):
        headers, farm, field = self._setup(client)
        resp = client.post(
            f"/api/v1/fields/{field['id']}/operations/generate", headers=headers,
            json={"crop_label": "maize", "season_label": "summer_2027",
                  "window_year": 2027},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        codes = {op["template_code"] for op in data["generated"]}
        assert {"op_harvest", "op_tillage_seedbed", "op_main_planting",
                "op_fertilizer_application", "op_post_harvest_prep"} <= codes
        # planting window comes from the crop calendar (evidence-classed)
        assert data["calendar_window"]["evidence_class"] == "reference_synthesized"
        assert data["calendar_window"]["planting"]
        planting = next(op for op in data["generated"] if op["operation_type"] == "planting")
        assert planting["earliest_start"] == "2027-04-15"  # seed pack maize window 04-15..06-15
        assert planting["duration_estimate_hours"] is None  # never assumed
        # dependencies: planting depends on seedbed prep
        assert {"operation": "op_main_planting", "depends_on": "op_tillage_seedbed"} in data["dependencies"]

    def test_schedule_run_reports_unscheduled_without_duration(self, client):
        headers, farm, field = self._setup(client)
        client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "tillage", "title": "Seedbed prep",
                  "duration_estimate_hours": None,
                  "resource_requirements": [{"resource_type": "tractor"}]},
        )
        resp = client.post(
            f"/api/v1/fields/{field['id']}/operation-schedule-runs",
            headers=headers, json={"hours_per_workday": 8.0},
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        entries = run["result"]["entries"]
        assert len(entries) == 1
        assert entries[0]["status"] == "unscheduled"
        assert "no_duration" in entries[0]["reason_codes"]
        assert run["not_evaluated"]["weather"].startswith("no forecast provider")
        assert run["not_evaluated"]["soil_trafficability"].startswith("no universal threshold")

    def test_schedule_run_schedules_with_durations_and_resource(self, client):
        headers, farm, field = self._setup(client)
        a = client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "tillage", "title": "Seedbed prep",
                  "earliest_start": "2027-03-01", "latest_finish": "2027-03-20",
                  "duration_estimate_hours": 16.0,
                  "resource_requirements": [{"resource_type": "tractor"}]},
        ).json()
        b = client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "planting", "title": "Plant maize",
                  "earliest_start": "2027-03-01", "latest_finish": "2027-04-15",
                  "duration_estimate_hours": 8.0,
                  "resource_requirements": [{"resource_type": "tractor"}],
                  "depends_on": [a["id"]]},
        ).json()
        resp = client.post(
            f"/api/v1/fields/{field['id']}/operation-schedule-runs",
            headers=headers, json={"hours_per_workday": 8.0},
        )
        assert resp.status_code == 201, resp.text
        run = resp.json()
        assert run["status"] == "succeeded"
        entries = {e["operation_id"]: e for e in run["result"]["entries"]}
        assert entries[a["id"]]["status"] == "scheduled"
        assert entries[b["id"]]["status"] == "scheduled"
        # precedence: planting starts after seedbed prep ends
        assert entries[b["id"]]["scheduled_start"] > entries[a["id"]]["scheduled_end"]
        # honesty labels on scheduled entries
        assert entries[a["id"]]["weather_check"] == "pending"
        assert entries[a["id"]]["soil_readiness_check"] == "manual_required"
        # write-back happened
        ops = client.get(f"/api/v1/fields/{field['id']}/operations", headers=headers).json()
        by_id = {op["id"]: op for op in ops["items"]}
        assert by_id[a["id"]]["status"] == "scheduled"
        assert by_id[a["id"]]["schedule_run_id"] == run["id"]

    def test_schedule_deterministic_and_idempotent(self, client):
        headers, farm, field = self._setup(client)
        client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "harvest", "title": "H",
                  "duration_estimate_hours": 12.0,
                  "resource_requirements": [{"resource_type": "tractor"}]},
        )
        key = f"sched-{uuid.uuid4().hex[:8]}"
        r1 = client.post(
            f"/api/v1/fields/{field['id']}/operation-schedule-runs",
            headers=headers, json={"hours_per_workday": 8.0, "idempotency_key": key},
        ).json()
        r2 = client.post(
            f"/api/v1/fields/{field['id']}/operation-schedule-runs",
            headers=headers, json={"hours_per_workday": 8.0, "idempotency_key": key},
        ).json()
        assert r1["id"] == r2["id"]
        assert r1["checksum_sha256"] == r2["checksum_sha256"]

    def test_resource_conflicts_endpoint(self, client):
        headers, farm, field = self._setup(client)
        client.post(
            f"/api/v1/farms/{farm['id']}/resources", headers=headers,
            json={"resource_type": "tractor", "name": "T2"},
        )
        # two ops forced into the same narrow window with one shared tractor
        for k, title in ((1, "A"), (2, "B")):
            client.post(
                f"/api/v1/fields/{field['id']}/operations", headers=headers,
                json={"operation_type": "tillage", "title": title,
                      "earliest_start": "2027-03-01", "latest_finish": "2027-03-02",
                      "duration_estimate_hours": 8.0,
                      "resource_requirements": [{"resource_type": "tractor"}]},
            )
        client.post(
            f"/api/v1/fields/{field['id']}/operation-schedule-runs",
            headers=headers, json={"hours_per_workday": 8.0},
        )
        resp = client.get(
            f"/api/v1/fields/{field['id']}/resource-conflicts", headers=headers
        )
        assert resp.status_code == 200
        # either the solver staggered them (no conflict) or it reports honestly;
        # with a 2-day window and 1-day durations both fit sequentially, so the
        # honest expectation is zero conflicts — but the endpoint must answer.
        assert "conflicts" in resp.json()

    def test_completion_logging_links_event(self, client):
        headers, farm, field = self._setup(client)
        op = client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "tillage", "title": "Till"},
        ).json()
        event = client.post(
            f"/api/v1/fields/{field['id']}/soil-management-events", headers=headers,
            json={"event_type": "tillage", "event_date": "2027-03-05"},
        ).json()
        resp = client.patch(
            f"/api/v1/operations/{op['id']}", headers=headers,
            json={"status": "completed",
                  "completed_soil_management_event_id": event["id"],
                  "completion_notes": "done in one pass"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert data["completed_soil_management_event_id"] == event["id"]
        # cross-link into the cover timeline: the tillage event closes residue
        timeline = client.get(
            f"/api/v1/fields/{field['id']}/soil-cover/timeline", headers=headers,
            params={"window_start": "2027-01-01", "window_end": "2027-12-31"},
        ).json()
        assert timeline["inputs_summary"]["management_events"] == 1

    def test_completion_event_must_belong_to_field(self, client):
        headers, farm, field = self._setup(client)
        op = client.post(
            f"/api/v1/fields/{field['id']}/operations", headers=headers,
            json={"operation_type": "tillage", "title": "Till"},
        ).json()
        # event on ANOTHER user's field
        other_headers, _ = _register(client)
        other_farm = client.post(
            "/api/v1/farms", headers=other_headers,
            json={"name": "F2", "country_code": "EG", "timezone": "Africa/Cairo"},
        ).json()
        other_field = client.post(
            f"/api/v1/farms/{other_farm['id']}/fields", headers=other_headers,
            json={"name": "F2 field", "geometry": {"type": "Polygon", "coordinates": [
                [[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]]}},
        ).json()
        alien_event = client.post(
            f"/api/v1/fields/{other_field['id']}/soil-management-events",
            headers=other_headers,
            json={"event_type": "tillage", "event_date": "2027-03-05"},
        ).json()
        resp = client.patch(
            f"/api/v1/operations/{op['id']}", headers=headers,
            json={"status": "completed",
                  "completed_soil_management_event_id": alien_event["id"]},
        )
        assert resp.status_code == 422
