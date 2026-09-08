"""D6.1 TemporalSemantics tests: daypart derivation is deterministic."""

from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.situation.temporal import Daypart, TemporalSemantics, daypart

NOW = datetime(2026, 8, 22, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, Daypart.NIGHT),
        (2, Daypart.NIGHT),
        (5, Daypart.NIGHT),
        (6, Daypart.MORNING),
        (8, Daypart.MORNING),
        (11, Daypart.MORNING),
        (12, Daypart.AFTERNOON),
        (17, Daypart.AFTERNOON),
        (18, Daypart.EVENING),
        (23, Daypart.EVENING),
    ],
)
def test_daypart_boundaries(hour: int, expected: Daypart) -> None:
    instant = datetime(2026, 8, 22, hour, 30, tzinfo=UTC)
    assert daypart(instant) is expected


def test_daypart_is_replayable() -> None:
    """Same instant -> same daypart, always."""
    instant = datetime(2026, 8, 22, 2, 30, tzinfo=UTC)
    assert daypart(instant) == daypart(instant) == Daypart.NIGHT


def test_temporal_semantics_at_instant() -> None:
    semantics = TemporalSemantics.at(NOW)
    assert semantics.now == NOW
    assert semantics.daypart is Daypart.AFTERNOON


def test_elapsed_since() -> None:
    semantics = TemporalSemantics.at(NOW)
    assert semantics.elapsed_since(NOW - timedelta(minutes=20)) == timedelta(minutes=20)
    assert semantics.elapsed_since(NOW) == timedelta(0)


def test_elapsed_since_unknown() -> None:
    semantics = TemporalSemantics.at(NOW)
    assert semantics.elapsed_since(None) is None


def test_daypart_requires_aware_utc() -> None:
    with pytest.raises(ValueError):
        daypart(datetime(2026, 8, 22, 2, 30))  # naive
