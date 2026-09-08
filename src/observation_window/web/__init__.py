"""OW-UI-1: bounded in-memory live trace ring buffer.

This is a process-local, debug-only, non-authoritative cache of the
most recent `ObservedTurnSnapshot` records produced by
`OWLiveTraceSource.observe(...)`.

Hard rules (per OW-UI-1 spec §13):
- Bounded: at most ``maxlen`` snapshots; oldest are dropped on overflow.
- Non-authoritative: this cache is **never** the source of truth. The
  durable `StateBackend` / `FactBackend` are the source of truth for
  persistent data. The cache only buffers the *live* tail.
- Process-local: lost on process restart; that is acceptable and
  expected.
- Never wrapped as MR canonical trace store.

The buffer is owned by OW-UI-1, not by MR. MR does not import
`observation_window`; missing OW consumers change nothing.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, Optional

from observation_window.causal_contracts import ObservedTurnSnapshot


class LiveTraceCache:
    """Thread-safe(ish) ring buffer of `ObservedTurnSnapshot`.

    Concurrency: simple GIL-guarded append is fine for the OW use
    case (a few HTTP requests per second). No external locks.
    """

    def __init__(self, maxlen: int = 200) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be at least 1")
        self._buf: Deque[ObservedTurnSnapshot] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    def append(self, snap: ObservedTurnSnapshot) -> None:
        self._buf.append(snap)

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

    def __iter__(self) -> Iterable[ObservedTurnSnapshot]:
        return iter(list(self._buf))

    def snapshot_all(self) -> tuple[ObservedTurnSnapshot, ...]:
        """Return all snapshots oldest-first."""
        return tuple(self._buf)

    def snapshot_recent(self, n: int) -> tuple[ObservedTurnSnapshot, ...]:
        """Return the most recent n snapshots, oldest-first."""
        if n < 0:
            raise ValueError("n must be non-negative")
        items = list(self._buf)[-n:] if n > 0 else []
        return tuple(items)

    def find_by_interaction_id(
        self, interaction_id: str
    ) -> Optional[ObservedTurnSnapshot]:
        for snap in reversed(list(self._buf)):
            if snap.interaction_id == interaction_id:
                return snap
        return None

    @property
    def maxlen(self) -> int:
        return self._maxlen
