"""Shared deterministic test fixtures."""

import re
from datetime import UTC, datetime

import pytest

from tests.support.fake_clock import FakeClock

# Every golden-scenario xfail must name its future owner:
#   MR-D<digit>(.<digit>)?P?(W<digit>)? not implemented
_XFAIL_OWNER_RE = re.compile(r"^MR-D\d+(?:\.\d+)?P?(?:W\d+)? not implemented$")


@pytest.fixture
def fake_clock() -> FakeClock:
    """Return a clock frozen at the D0 deterministic test instant."""
    return FakeClock(datetime(2026, 8, 19, 12, 0, tzinfo=UTC))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:  # pragma: no cover - exercised by every collection
    """Audit every xfail in the golden suite: reason must name a future owner."""
    for item in items:
        marker = item.get_closest_marker("xfail")
        if marker is None:
            continue
        reason = marker.kwargs.get("reason") or marker.args[0] if marker.args else None
        if reason is None:
            reason = marker.kwargs.get("reason")
        if not reason or not _XFAIL_OWNER_RE.match(reason):
            raise pytest.UsageError(
                f"xfail without an owner binding: {item.nodeid} reason={reason!r}; "
                "use reason='MR-Dx(.y)(Wz) not implemented'"
            )
