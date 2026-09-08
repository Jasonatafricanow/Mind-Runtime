"""Provider-neutral wall-clock contract."""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Supply the current aware UTC instant."""

    def now(self) -> datetime:
        """Return the current aware UTC instant."""
        ...
