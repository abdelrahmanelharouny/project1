from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.data_platform.contracts.observations import CanonicalObservation, QualityStatus


def _record(**overrides):
    base = {
        "variable_code": "precipitation",
        "value": 1.0,
        "unit": "mm",
        "observed_at": datetime(2024, 1, 1, tzinfo=UTC),
        "period_start": datetime(2024, 1, 1, tzinfo=UTC),
        "period_end": datetime(2024, 1, 1, 23, 59, tzinfo=UTC),
    }
    base.update(overrides)
    return CanonicalObservation(**base)


def test_canonical_observation_rejects_non_finite_measurements():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            _record(value=value)


def test_missing_status_requires_null_and_null_requires_missing_status():
    with pytest.raises(ValidationError):
        _record(value=None, quality_status=QualityStatus.valid)
    with pytest.raises(ValidationError):
        _record(value=0.0, quality_status=QualityStatus.missing)
    assert _record(value=None, quality_status=QualityStatus.missing).value is None


def test_period_must_be_ordered_and_uncertainty_nonnegative():
    with pytest.raises(ValidationError):
        _record(period_end=datetime(2023, 12, 31, tzinfo=UTC))
    with pytest.raises(ValidationError):
        _record(uncertainty_value=-0.1)


def test_all_timestamps_are_normalized_to_utc():
    offset = datetime.fromisoformat("2024-01-01T02:00:00+02:00")
    record = _record(observed_at=offset, period_start=offset, period_end=offset + timedelta(hours=1))
    assert record.observed_at.tzinfo == UTC
    assert record.observed_at.hour == 0
