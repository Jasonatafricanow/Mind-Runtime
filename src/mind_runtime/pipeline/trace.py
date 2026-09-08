"""Trace recorder: per-interaction stage log for inspect/replay."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TraceEntry:
    """One recorded pipeline stage for an interaction."""

    interaction_id: str
    stage: str
    ref: str | None
    outcome: str
    at: datetime


class TraceRecorder:
    """Appends stage entries and serves them back per interaction."""

    def __init__(self) -> None:
        self._entries: list[TraceEntry] = []

    def record(
        self,
        interaction_id: str,
        stage: str,
        *,
        ref: str | None = None,
        outcome: str = "ok",
        at: datetime,
    ) -> None:
        self._entries.append(
            TraceEntry(
                interaction_id=interaction_id,
                stage=stage,
                ref=ref,
                outcome=outcome,
                at=at,
            )
        )

    def trace(self, interaction_id: str) -> tuple[TraceEntry, ...]:
        return tuple(entry for entry in self._entries if entry.interaction_id == interaction_id)
