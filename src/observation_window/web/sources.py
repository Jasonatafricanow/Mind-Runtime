"""OW-UI-1: read-only data sources for the Web API.

The API layer is a thin adapter over the existing OW read model:

  - Durable data:  ObservationQueryService (OW-P1) over StateBackend + FactBackend
  - Live data:     OWLiveTraceSource (OW-3) on a caller-supplied turn provider,
                   cached in a process-local LiveTraceCache (OW-UI-1)

OW-UI-1 has no dependency on any MR orchestrator, dynamics engine,
appraisal provider, or memory system. The data sources are passed in
at composition root. If OW-UI-1 is unavailable, MR still runs; if
the Web API crashes, MR still runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Optional

from observation_window.causal_contracts import (
    CausalChainLink,
    ObservedTurnSnapshot,
    ResolvedCausalChain,
)
from observation_window.causal_trace import CausalChainBuilder
from observation_window.live_trace import OWLiveTraceSource
from observation_window.query_service import ObservationQueryService
from observation_window.web import LiveTraceCache


# ---------------------------------------------------------------------------
# Turn provider: caller (composition root) wires this.
# ---------------------------------------------------------------------------


class TurnProvider(Protocol):
    """How the Web API obtains live turn snapshots.

    The default OW-UI-1 standalone mode uses a `StubTurnProvider` that
    takes snapshots from the `LiveTraceCache`. Future integration can
    wire this to a real MR composition root without changing the API.
    """

    def recent_turns(self, n: int) -> tuple[ObservedTurnSnapshot, ...]: ...

    def get_turn(self, interaction_id: str) -> Optional[ObservedTurnSnapshot]: ...


class CacheTurnProvider:
    """Default `TurnProvider` backed by a `LiveTraceCache`."""

    def __init__(self, cache: LiveTraceCache) -> None:
        self._cache = cache

    def recent_turns(self, n: int) -> tuple[ObservedTurnSnapshot, ...]:
        return self._cache.snapshot_recent(n)

    def get_turn(self, interaction_id: str) -> Optional[ObservedTurnSnapshot]:
        return self._cache.find_by_interaction_id(interaction_id)


# ---------------------------------------------------------------------------
# Bundled data sources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OWDashboardDataSources:
    """All read-only sources the Web API consumes.

    None of these are write-capable. The composition root is responsible
    for constructing the backends; OW-UI-1 just consumes them.
    """

    query_service: ObservationQueryService
    live_source: OWLiveTraceSource
    chain_builder: CausalChainBuilder
    turn_provider: TurnProvider

    def current_states(self) -> tuple[ObservedTurnSnapshot, ...]:
        """Snapshot of current states (from durable). Empty if no backends."""
        return ()

    def recent_turns(self, n: int = 50) -> tuple[ObservedTurnSnapshot, ...]:
        return self.turn_provider.recent_turns(n)

    def get_turn(self, interaction_id: str) -> Optional[ObservedTurnSnapshot]:
        return self.turn_provider.get_turn(interaction_id)

    def chains_for_turn(
        self, interaction_id: str
    ) -> Optional[tuple[ResolvedCausalChain, ...]]:
        snap = self.get_turn(interaction_id)
        if snap is None:
            return None
        return self.chain_builder.build_for_all_changed_dimensions(snap)
