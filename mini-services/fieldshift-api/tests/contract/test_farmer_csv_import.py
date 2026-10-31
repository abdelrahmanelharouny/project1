"""Contract + integration tests for the farmer CSV observations import (M3)."""

from datetime import UTC, datetime

import pytest

from app.data_platform.imports.csv_service import (
    PROVIDER_CODE,
    parse_csv_observations,
    template_csv,
)
from app.data_platform.ingestion.service import create_import_job

VALID_CSV = (
    "date,variable_code,value,unit,notes\n"
    "2024-03-01,precipitation,12.5,mm,heavy overnight rain\n"
    "2024-03-02,precipitation,0,mm,dry day\n"
    "2024-03-03,air_temperature_mean,,degC,sensor offline\n"
)


class TestCsvParsing:
    def test_valid_rows_become_canonical_observations(self):
        result = parse_csv_observations(VALID_CSV, file_name="log.csv")
        assert len(result.observations) == 3
        assert result.provenance.provider_code == PROVIDER_CODE
        assert result.provenance.known_limitations
        first = result.observations[0]
        assert first.variable_code == "precipitation"
        assert first.value == 12.5
        assert first.unit == "mm"
        assert first.evidence_class == "farmer_reported_record"
        assert first.is_synthetic is False
        assert first.spatial_support_type == "point"
        assert first.observed_at == datetime(2024, 3, 1, tzinfo=UTC)
        assert first.metadata["file_name"] == "log.csv"
        assert first.metadata["file_sha256"]
        assert first.metadata["source_row"] == 2  # line 2 = first data row under the header
        assert first.metadata["notes"] == "heavy overnight rain"

    def test_blank_value_is_missing_not_zero(self):
        result = parse_csv_observations(VALID_CSV, file_name="log.csv")
        blanks = [o for o in result.observations if o.value is None]
        assert len(blanks) == 1
        assert blanks[0].quality_status == "missing"
        assert blanks[0].quality_flags[0]["flag_code"] == "FARMER_BLANK"

    def test_zero_is_a_valid_value(self):
        result = parse_csv_observations(VALID_CSV, file_name="log.csv")
        zeros = [o for o in result.observations if o.value == 0.0]
        assert len(zeros) == 1
        assert zeros[0].quality_status == "valid"

    def test_unknown_variable_rejected_with_reason(self):
        csv_text = "date,variable_code,value,unit\n2024-03-01,rainfall_mm,5,mm\n"
        result = parse_csv_observations(csv_text, file_name="x.csv")
        assert result.observations == []
        assert any("unknown variable_code 'rainfall_mm'" in w for w in result.warnings)

    def test_unit_mismatch_rejected(self):
        csv_text = "date,variable_code,value,unit\n2024-03-01,precipitation,5,cm\n"
        result = parse_csv_observations(csv_text, file_name="x.csv")
        assert result.observations == []
        assert any("does not match catalog unit 'mm'" in w for w in result.warnings)

    def test_duplicate_within_file_rejected(self):
        csv_text = (
            "date,variable_code,value,unit\n"
            "2024-03-01,precipitation,5,mm\n"
            "2024-03-01,precipitation,7,mm\n"
        )
        result = parse_csv_observations(csv_text, file_name="x.csv")
        assert len(result.observations) == 1
        assert result.observations[0].value == 5.0
        assert any("duplicate" in w for w in result.warnings)

    def test_bad_header_is_structured_error(self):
        from app.core.errors import ValidationFailed

        with pytest.raises(ValidationFailed):
            parse_csv_observations("a,b,c\n1,2,3\n", file_name="x.csv")

    def test_bad_date_and_non_numeric_value_rejected(self):
        csv_text = (
            "date,variable_code,value,unit\n"
            "01/03/2024,precipitation,5,mm\n"
            "2024-03-02,precipitation,not-a-number,mm\n"
        )
        result = parse_csv_observations(csv_text, file_name="x.csv")
        assert result.observations == []
        assert any("invalid date '01/03/2024'" in w for w in result.warnings)
        assert any("not a number" in w for w in result.warnings)
        assert any("2 of 2 rows were rejected" in w for w in result.warnings)

    def test_template_matches_parser(self):
        result = parse_csv_observations(template_csv(), file_name="template.csv")
        assert len(result.observations) == 3

    def test_idempotent_parse(self):
        r1 = parse_csv_observations(VALID_CSV, file_name="log.csv")
        r2 = parse_csv_observations(VALID_CSV, file_name="log.csv")
        assert [o.model_dump() for o in r1.observations] == [o.model_dump() for o in r2.observations]


@pytest.fixture()
def seeded_registry(db):
    from app.data_platform.registry.seed_sources import seed_data_registry

    seed_data_registry(db)
    return db


class TestCsvImportEndToEnd:
    def test_import_via_job_persists_farmer_reported_rows(self, seeded_registry, farm_with_field):
        field = farm_with_field["field"]
        from app.db.models import Field as FieldModel

        fm = seeded_registry.get(FieldModel, field["id"])
        result = parse_csv_observations(VALID_CSV, file_name="log.csv")
        job = create_import_job(
            seeded_registry,
            field=fm,
            provider_code=PROVIDER_CODE,
            job_type="csv_import",
            result=result,
            created_by=None,
        )
        assert job.status == "succeeded"
        assert job.records_received == 3
        assert job.records_rejected == 0

        from sqlalchemy import select

        from app.db.models import Observation

        rows = seeded_registry.scalars(
            select(Observation).where(Observation.field_id == fm.id).order_by(Observation.observed_at)
        ).all()
        assert len(rows) == 3
        assert all(r.metadata["import_kind"] == "observations_csv" for r in rows)
        assert rows[2].value is None and rows[2].quality_status == "missing"

    def test_rerun_is_idempotent_via_natural_key(self, seeded_registry, farm_with_field):
        field = farm_with_field["field"]
        from app.db.models import Field as FieldModel

        fm = seeded_registry.get(FieldModel, field["id"])
        for _ in range(2):
            result = parse_csv_observations(VALID_CSV, file_name="log.csv")
            job = create_import_job(
                seeded_registry,
                field=fm,
                provider_code=PROVIDER_CODE,
                job_type="csv_import",
                result=result,
                created_by=None,
            )
        assert job.status == "succeeded"
        assert job.records_received == 3  # rows parsed again
        from sqlalchemy import func, select

        from app.db.models import Observation

        total = seeded_registry.scalar(
            select(func.count()).select_from(Observation).where(Observation.field_id == fm.id)
        )
        assert total == 3  # but no duplicates stored

class TestCsvDateBasis:
    """Audit regression: farmer dates are local calendar dates. Timestamps are
    rejected (ambiguous without a zone) and the interpretation basis is
    recorded so M4 aggregation can apply the farm calendar explicitly."""

    def test_timestamp_rows_rejected(self):
        csv_text = (
            "date,variable_code,value,unit\n"
            "2024-03-01T10:30:00,precipitation,12.5,mm\n"
            "2024-03-02,precipitation,0,mm\n"
        )
        result = parse_csv_observations(csv_text, file_name="log.csv")
        assert len(result.observations) == 1  # only the plain-date row survives
        assert result.coverage["rows_rejected"] == 1
        assert any("time component" in w for w in result.warnings)

    def test_space_separated_datetime_rejected(self):
        csv_text = (
            "date,variable_code,value,unit\n"
            "2024-03-01 10:30,precipitation,12.5,mm\n"
        )
        result = parse_csv_observations(csv_text, file_name="log.csv")
        assert result.observations == []
        assert result.coverage["rows_rejected"] == 1

    def test_date_interpretation_recorded(self):
        result = parse_csv_observations(VALID_CSV, file_name="log.csv")
        obs = result.observations[0]
        assert obs.metadata["date_interpretation"] == "calendar_date_anchored_utc_midnight"
        assert obs.metadata["original_date"] == "2024-03-01"
        # anchored at UTC midnight: the calendar day is unambiguous
        assert obs.observed_at == datetime(2024, 3, 1, tzinfo=UTC)
        assert obs.period_start == obs.observed_at
