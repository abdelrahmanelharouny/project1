"""Integration: farms + fields CRUD, geometry validation over HTTP,
boundary versioning, map payload, PostGIS area cross-check."""

import json


class TestFarmCrud:
    def test_create_and_get_farm(self, client, auth_headers):
        headers, _ = auth_headers
        created = client.post(
            "/api/v1/farms",
            headers=headers,
            json={"name": "My Farm", "country_code": "eg", "timezone": "Africa/Cairo",
                  "currency_code": "egp"},
        )
        assert created.status_code == 201
        farm = created.json()
        assert farm["country_code"] == "EG"  # normalized
        assert farm["currency_code"] == "EGP"
        fetched = client.get(f"/api/v1/farms/{farm['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "My Farm"

    def test_patch_farm(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        farm_id = farm_with_field["farm"]["id"]
        patched = client.patch(
            f"/api/v1/farms/{farm_id}", headers=headers, json={"name": "Renamed Farm"}
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed Farm"

    def test_list_includes_field_aggregates(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        farms = client.get("/api/v1/farms", headers=headers).json()
        assert farms["items"][0]["field_count"] == 1
        assert farms["items"][0]["total_area_ha"] > 0

    def test_invalid_country_code_rejected(self, client, auth_headers):
        headers, _ = auth_headers
        resp = client.post(
            "/api/v1/farms", headers=headers, json={"name": "X", "country_code": "EGY"}
        )
        assert resp.status_code == 422


class TestFieldGeometry:
    def test_create_field_returns_geodesic_area(self, client, farm_with_field):
        field = farm_with_field["field"]
        # 0.02 deg x 0.02 deg at lat 31 ≈ 423 ha.
        assert 410 < field["area_ha"] < 440
        assert field["boundary_version"] == 1
        assert field["geometry_valid"] is True

    def test_postgis_area_matches_geodesic_area(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field = client.get(f"/api/v1/fields/{farm_with_field['field']['id']}", headers=headers).json()
        assert field["postgis_geodesic_area_ha"] is not None
        delta = abs(field["postgis_geodesic_area_ha"] - field["area_ha"])
        assert delta / field["area_ha"] < 0.005  # <0.5% difference

    def test_invalid_geometry_rejected_with_structure(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        farm_id = farm_with_field["farm"]["id"]
        resp = client.post(
            f"/api/v1/farms/{farm_id}/fields",
            headers=headers,
            json={"name": "Bad", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}},
        )
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "INVALID_GEOMETRY"
        assert err["request_id"]

    def test_point_geometry_rejected(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        resp = client.post(
            f"/api/v1/farms/{farm_with_field['farm']['id']}/fields",
            headers=headers,
            json={"name": "Point", "geometry": {"type": "Point", "coordinates": [31.4, 31.1]}},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_GEOMETRY"

    def test_boundary_versioning(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        new_geom = {
            "type": "Polygon",
            "coordinates": [[[31.44, 31.20], [31.46, 31.20], [31.46, 31.22], [31.44, 31.22], [31.44, 31.20]]],
        }
        updated = client.post(
            f"/api/v1/fields/{field_id}/boundary-versions",
            headers=headers,
            json={"geometry": new_geom, "change_reason": "resurveyed"},
        )
        assert updated.status_code == 201
        assert updated.json()["boundary_version"] == 2

        field = client.get(f"/api/v1/fields/{field_id}", headers=headers).json()
        assert field["boundary_version"] == 2

        versions = client.get(f"/api/v1/fields/{field_id}/boundary-versions", headers=headers).json()
        assert versions["total"] == 2
        assert [v["version_number"] for v in versions["items"]] == [1, 2]
        assert versions["items"][1]["change_reason"] == "resurveyed"

    def test_map_payload(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        resp = client.get(f"/api/v1/fields/{farm_with_field['field']['id']}/map", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["crs"] == "EPSG:4326"
        assert payload["bbox"] == [31.40, 31.10, 31.42, 31.12]
        assert payload["boundary_geojson"]["type"] == "MultiPolygon"
        assert "geodesic" in payload["area_method"]

    def test_field_patch_name(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        field_id = farm_with_field["field"]["id"]
        patched = client.patch(f"/api/v1/fields/{field_id}", headers=headers, json={"name": "Renamed Field"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed Field"

    def test_field_list_geojson_shape(self, client, farm_with_field):
        headers = farm_with_field["headers"]
        fields = client.get(f"/api/v1/farms/{farm_with_field['farm']['id']}/fields", headers=headers).json()
        assert fields["total"] == 1
        geo = fields["items"][0]["boundary_geojson"]
        assert geo["type"] == "MultiPolygon"
        assert json.dumps(geo)  # serializable
