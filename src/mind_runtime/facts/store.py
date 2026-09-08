"""Append-only idempotent stores for Evidence and Observation."""

from mind_runtime.contracts import Evidence, Observation, Scope

type _Entry = Evidence | Observation


class _AppendOnlyStore[T: _Entry]:
    """Append-only store keyed by (scope, object_id); no update/delete."""

    def __init__(self) -> None:
        self._entries: dict[tuple[Scope, str], T] = {}

    def append(self, entry: T) -> bool:
        key = (entry.scope, entry.id)
        if key in self._entries:
            return False
        self._entries[key] = entry
        return True

    def get(self, scope: Scope, object_id: str) -> T | None:
        return self._entries.get((scope, object_id))

    def all(self) -> tuple[T, ...]:
        return tuple(self._entries.values())

    def count(self) -> int:
        return len(self._entries)


class EvidenceStore(_AppendOnlyStore[Evidence]):
    """Append-only Evidence store with (scope, id) idempotency."""


class ObservationStore(_AppendOnlyStore[Observation]):
    """Append-only Observation store with (scope, id) idempotency."""
