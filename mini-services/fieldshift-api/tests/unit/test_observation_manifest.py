"""Unit: deterministic observation manifest (M7.1 H-02/F-31).

Covers the spec's manifest requirements: stable ordering, stable timestamp
serialization, explicit null handling, versioned format, reproducible
checksums, change detection, and synthetic/real separation.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.field_state.manifest import (
    MANIFEST_FORMAT_VERSION,
    build_manifest,
    canonical_json,
    iso_utc,
    sha256_of_document,
)


def _obs(**overrides):
    base = {
        "id": "0b8fd7e7-6f5d-4a1c-9f3e-000000000001",
        "variable_code": "precipitation",
        "dataset_product_id": "11111111-1111-1111-1111-111111111111",
        "observed_at": datetime(2015, 3, 2, 0, 0, tzinfo=timezone.utc),
        "period_start": datetime(2015, 3, 2, 0, 0, tzinfo=timezone.utc),
        "period_end": datetime(2015, 3, 2, 23, 59, 59, tzinfo=timezone.utc),
        "time_support": "daily",
        "value": 4.5,
        "unit": "mm",
        "quality_status": "valid",
        "spatial_support_type": "grid_cell",
        "spatial_resolution_m": 11195.0,
        "evidence_class": "modeled_prediction",
        "is_synthetic": False,
        "uncertainty_value": None,
        "uncertainty_type": None,
        "metadata": {},
        "processing_version": "v1",
    }
    base.update(overrides)
    return base


def _manifest(observations, **kwargs):
    params = dict(
        field_id="f-1",
        purpose="feature_run_resolved_inputs",
        window_start=datetime(2015, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2015, 12, 31, tzinfo=timezone.utc),
        variables=["precipitation"],
        source_products=[{"variable": "precipitation", "product_code": "synthetic"}],
        processing_configuration={"feature_engine_version": "feature-engine-1.0.0"},
    )
    params.update(kwargs)
    return build_manifest(observations, **params)


class TestDeterminism:
    def test_same_rows_different_query_order_identical_hash(self):
        rows = [_obs(), _obs(id="...2".replace("...2", "000000000002"), observed_at=datetime(2015, 3, 1, tzinfo=timezone.utc))]
        doc_a = _manifest(list(rows))
        shuffled = [rows[1], rows[0]]
        doc_b = _manifest(shuffled)
        assert doc_a == doc_b
        assert sha256_of_document(doc_a) == sha256_of_document(doc_b)

    def test_manifest_entry_is_idempotent_over_json_safe_values(self):
        # The stored document contains JSON-safe scalars only; re-running the
        # entry builder over such values must reproduce them exactly.
        from app.field_state.manifest import manifest_entry

        first = manifest_entry(_obs())
        second = manifest_entry(first)
        assert first == second

    def test_canonical_json_is_sorted_and_tight(self):
        text = canonical_json({"b": 1, "a": {"d": 2, "c": [3, 4]}})
        assert text == '{"a":{"c":[3,4],"d":2},"b":1}'

    def test_empty_manifest_deterministic(self):
        a = _manifest([])
        b = _manifest([])
        assert a == b and a["observation_count"] == 0
        assert sha256_of_document(a) == sha256_of_document(b)


class TestTimestampSerialization:
    def test_naive_utc_offset_and_z_all_serialize_identically(self):
        naive = datetime(2015, 3, 2, 0, 0)
        utc = datetime(2015, 3, 2, 0, 0, tzinfo=timezone.utc)
        offset = datetime(2015, 3, 2, 2, 0, tzinfo=timezone(timedelta(hours=2)))
        assert iso_utc(naive) == iso_utc(utc) == iso_utc(offset)
        assert iso_utc(utc) == "2015-03-02T00:00:00+00:00"

    def test_iso_string_input_accepted(self):
        assert iso_utc("2015-03-02T00:00:00+00:00") == "2015-03-02T00:00:00+00:00"


class TestNullHandling:
    def test_nulls_are_explicit_not_omitted_not_zero(self):
        entry = build_manifest(
            [_obs(value=None, spatial_resolution_m=None, uncertainty_value=None, uncertainty_type=None, evidence_class=None)],
            field_id="f-1",
            purpose="p",
        )["observations"][0]
        assert entry["value"] is None
        assert entry["spatial_resolution_m"] is None
        assert entry["evidence_class"] is None
        assert entry["uncertainty"] is None
        for key in ("value", "spatial_resolution_m", "evidence_class"):
            assert key in entry  # explicit nulls are preserved, never dropped


class TestFormatAndContext:
    def test_format_version_present(self):
        doc = _manifest([_obs()])
        assert doc["format_version"] == MANIFEST_FORMAT_VERSION
        assert doc["format_version"] == "field-observation-manifest-1"

    def test_context_is_hashed_too(self):
        doc = _manifest([_obs()])
        modified_context = deepcopy(doc)
        modified_context["context"]["purpose"] = "something_else"
        assert sha256_of_document(doc) != sha256_of_document(modified_context)

    def test_asset_refs_promoted_from_metadata(self):
        doc = _manifest(
            [
                _obs(
                    metadata={
                        "asset": "chirps-v2.0-daily",
                        "granule_id": "g.2015.03.02",
                        "internal_note": "not an asset ref",
                    }
                )
            ]
        )
        entry = doc["observations"][0]
        assert entry["asset_refs"] == {"asset": "chirps-v2.0-daily", "granule_id": "g.2015.03.02"}


class TestChangeDetection:
    def test_value_change_changes_hash(self):
        doc_a = _manifest([_obs(value=4.5)])
        doc_b = _manifest([_obs(value=9.9)])
        assert sha256_of_document(doc_a) != sha256_of_document(doc_b)

    def test_quality_status_change_changes_hash(self):
        doc_a = _manifest([_obs(quality_status="valid")])
        doc_b = _manifest([_obs(quality_status="suspect")])
        assert sha256_of_document(doc_a) != sha256_of_document(doc_b)

    def test_new_observation_changes_hash_and_count(self):
        doc_a = _manifest([_obs()])
        doc_b = _manifest([_obs(), _obs(id="00000000000000000000000000000002")])
        assert doc_b["observation_count"] == doc_a["observation_count"] + 1
        assert sha256_of_document(doc_a) != sha256_of_document(doc_b)


class TestEvidenceSeparation:
    def test_synthetic_flag_and_counts(self):
        rows = [_obs(), _obs(id="00000000000000000000000000000003", is_synthetic=True)]
        doc = _manifest(rows)
        assert doc["synthetic_observation_count"] == 1
        assert doc["observation_count"] == 2
        flags = {e["is_synthetic"] for e in doc["observations"]}
        assert flags == {True, False}

    def test_spatial_support_preserved_per_entry(self):
        doc = _manifest(
            [
                _obs(spatial_support_type="grid_cell", spatial_resolution_m=11195.0),
                _obs(id="00000000000000000000000000000004", spatial_support_type="point", spatial_resolution_m=None),
            ]
        )
        supports = {e["spatial_support_type"] for e in doc["observations"]}
        assert supports == {"grid_cell", "point"}

    def test_ordering_is_by_observed_at_then_id(self):
        rows = [
            _obs(id="aaaa", observed_at=datetime(2015, 3, 2, tzinfo=timezone.utc)),
            _obs(id="0000", observed_at=datetime(2015, 3, 1, tzinfo=timezone.utc)),
            _obs(id="zzzz", observed_at=datetime(2015, 3, 2, tzinfo=timezone.utc)),
        ]
        doc = _manifest(rows)
        ids = [e["id"] for e in doc["observations"]]
        assert ids == ["0000", "aaaa", "zzzz"]
