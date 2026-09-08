"""OW-UI-1 R1: Real-runtime wiring helpers.

These are the small composition-root helpers that bind an actual MR
``TurnOrchestrator`` (with its real ``StateBackend``,
``FactBackend``, and ``CommitMarkerStore``) to an
``OWDashboardDataSources`` for the Web console.

Hard rules (per OW-UI-1-R1 spec):

- The wiring lives in the OW-UI-1 package — MR does not import
  ``observation_window``. The caller invokes the wiring at
  composition root.
- Zero changes to MR cognitive logic. Zero changes to MR
  persistence. Zero changes to MR contracts.
- Live trace data flows one way: ``transition_result`` is observed
  by ``OWLiveTraceSource`` and appended to a ``LiveTraceCache``.
  No feedback loop, no write back.
- OW crash is isolated: the ``LiveTraceCache`` lives in OW-UI-1
  process memory. If OW dies, the next start shows an empty
  ``/api/turns``; the durable backend (read via
  ``ObservationQueryService``) is unaffected.
- MR crash is isolated: the Web API process can keep running;
  the next turn will simply not produce a new snapshot until MR
  is restored.
"""

from __future__ import annotations

from typing import Iterable, Optional

from mind_runtime.contracts.emotional_transition import EmotionalTransitionResult
from mind_runtime.contracts.scope import Scope
from mind_runtime.facts.persistence import FactBackend
from mind_runtime.state.persistence import (
    CommitMarkerStore,
    StateBackend,
)

from observation_window.causal_trace import CausalChainBuilder
from observation_window.live_trace import OWLiveTraceSource
from observation_window.query_service import ObservationQueryService
from observation_window.web import LiveTraceCache
from observation_window.web.sources import (
    CacheTurnProvider,
    OWDashboardDataSources,
    TurnProvider,
)


class OrchestratorLiveTraceSink:
    """Composition-root helper that turns MR ``transition_result`` into
    immutable ``ObservedTurnSnapshot`` records stored in a bounded
    process-local ``LiveTraceCache``.

    This is a *caller-side* observer. The host (Hermes / agent / a
    small wrapper) calls :meth:`submit` after each turn commits.
    The OW-UI-1 Web API reads the same cache via the
    ``CacheTurnProvider``.

    The sink holds no MR references that would create a feedback loop.
    The only data dependency is the immutable ``transition_result``
    value the host passes in.
    """

    def __init__(
        self,
        cache: LiveTraceCache,
        live_source: OWLiveTraceSource,
    ) -> None:
        self._cache = cache
        self._live_source = live_source

    def submit(
        self,
        *,
        interaction_id: str,
        result: EmotionalTransitionResult,
    ) -> None:
        """Append a snapshot of the given transition result."""
        snap = self._live_source.observe(
            interaction_id=interaction_id, result=result,
        )
        self._cache.append(snap)

    def snapshot_count(self) -> int:
        return len(self._cache)


def build_dashboard_data_sources(
    *,
    state_backend: StateBackend,
    fact_backend: FactBackend,
    commit_markers: CommitMarkerStore | None,
    sink: OrchestratorLiveTraceSink,
    cache: LiveTraceCache | None = None,
) -> OWDashboardDataSources:
    """Bind a real durable MR stack to OW-UI-1's read-only data sources."""
    cache = cache if cache is not None else sink._cache
    query = ObservationQueryService(
        state_backend=state_backend,
        fact_backend=fact_backend,
        commit_marker_store=commit_markers,
    )
    return OWDashboardDataSources(
        query_service=query,
        live_source=sink._live_source,
        chain_builder=CausalChainBuilder(),
        turn_provider=CacheTurnProvider(cache),
    )


def wire_live_trace_after_turn(
    # String-annotation to avoid static orchestrator import
    # (the OW module-isolation contract).
    orchestrator: "TurnOrchestrator",  # noqa: F821
    sink: OrchestratorLiveTraceSink,
    interaction_id: str,
) -> bool:
    """Read ``orchestrator.transition_result`` and feed it to the sink."""
    result = orchestrator.transition_result
    if result is None:
        return False
    sink.submit(interaction_id=interaction_id, result=result)
    return True


def wire_live_trace_for_orchestrator(
    # String-annotation to avoid static orchestrator import
    # (the OW module-isolation contract).
    orchestrator: "TurnOrchestrator",  # type: ignore[name-defined]  # noqa: F821
    sink: OrchestratorLiveTraceSink,
    interaction_id_getter=None,
) -> "LiveTraceHook":  # type: ignore[name-defined]
    """Return a hook that, on each call, submits the current
    ``orchestrator.transition_result`` to the sink.
    """
    counter = {"n": 0}

    def hook() -> bool:
        counter["n"] += 1
        ix = interaction_id_getter() if interaction_id_getter is not None else f"ix-{counter['n']}"
        return wire_live_trace_after_turn(orchestrator, sink, interaction_id=ix)

    return hook  # type: ignore[return-value]


class LiveTraceHook:
    """A callable observer for a single orchestrator's transition_result."""

    def __init__(self, hook) -> None:  # type: ignore[no-untyped-def]
        self._hook = hook

    def __call__(self) -> bool:
        return self._hook()
