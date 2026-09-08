from datetime import UTC, datetime, timedelta

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.providers.clock import Clock


def test_fake_clock_satisfies_clock_protocol_and_advances() -> None:
    start = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    clock = FakeClock(start)

    assert isinstance(clock, Clock)
    assert clock.now() == start

    clock.advance(timedelta(minutes=15))

    assert clock.now() == datetime(2026, 8, 19, 12, 15, tzinfo=UTC)


def test_fake_clock_normalizes_aware_values_to_utc() -> None:
    clock = FakeClock(datetime.fromisoformat("2026-08-19T14:00:00+02:00"))

    assert clock.now() == datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def test_fake_clock_rejects_naive_values_on_init_and_set() -> None:
    naive = datetime(2026, 8, 19, 12, 0)

    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(naive)

    clock = FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(naive)


def test_fake_clock_set_replaces_current_instant() -> None:
    clock = FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))

    clock.set(datetime.fromisoformat("2026-08-20T01:30:00+02:00"))

    assert clock.now() == datetime(2026, 8, 19, 23, 30, tzinfo=UTC)


def test_fake_clock_fixture_starts_at_frozen_instant(fake_clock: FakeClock) -> None:
    assert fake_clock.now() == datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
