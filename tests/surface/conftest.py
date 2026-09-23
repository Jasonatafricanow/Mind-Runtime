"""Test fixtures for Surface Affect W3-B0.

RED binding only. Production seam remains intentionally missing until W3-B/C/D.
"""

from typing import Any

import pytest


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "reference_only: mark test as historical reference fixture only"
    )


@pytest.fixture
def surface() -> Any:
    class Unbound:
        def __getattr__(self, name: str) -> Any:
            pytest.fail(
                f"RED BY DESIGN: Surface production adapter intentionally absent; requested {name}"
            )

    return Unbound()
