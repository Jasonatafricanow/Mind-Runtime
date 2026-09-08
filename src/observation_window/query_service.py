"""OW-P1 read-only query service.

Implements the Gate 3 query surface. All methods are read-only — they
invoke only the load/find/read methods of the underlying durable backends.

No write methods on the backends are called. No runtime command
construction. No state mutation.
"""

from datetime import datetime
from typing import Annotated, Literal

from mind_runtime.contracts.state import RuntimeState, StateDefinition
from mind_runtime.contracts.transition import StateTransition
from mind_runtime.contracts.evidence import Evidence
from mind_runtime.contracts.scope import Scope
from mind_runtime.state.lifecycle import (
    StateLifecycle,
    CURRENT_LIKE_LIFECYCLES,
    TERMINAL_LIFECYCLES,
    _coerce,
)
from mind_runtime.state.persistence import StateBackend, CommitMarkerStore
from mind_runtime.facts.persistence import FactBackend

from observation_window.contracts import (
    # Types
    ObservedStateRow,
    ObservedStateChange,
    ObservedEvidenceRef,
    ObservedObservationRow,
    ObservedInteractionRow,
    ProvenanceNode,
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNodeKind,
    EvidenceSourceKind,
    ObservedLifecycleStatus,
    # Identifiers
    StateId,
    TransitionId,
    EvidenceId,
    ObservationId,
    InteractionId,
)


def _classify_lifecycle(status: str) -> ObservedLifecycleStatus:
    """Classify a RuntimeState.status string into a lifecycle class."""
    coerced = _coerce(status)
    if coerced is None:
        return "unknown"
    if coerced in CURRENT_LIKE_LIFECYCLES:
        return "current_like"
    if coerced in TERMINAL_LIFECYCLES:
        return "terminal"
    # EXPIRED and any future values
    return "validity_outcome"


def _classify_evidence_source(source_type: str) -> EvidenceSourceKind:
    """Classify an Evidence.source_type string."""
    mapping = {
        "user_statement": EvidenceSourceKind.USER_STATEMENT,
        "assistant_statement": EvidenceSourceKind.ASSISTANT_STATEMENT,
        "inference": EvidenceSourceKind.INFERENCE,
        "observation": EvidenceSourceKind.OBSERVATION,
        "external": EvidenceSourceKind.EXTERNAL,
    }
    return mapping.get(source_type, EvidenceSourceKind.UNKNOWN)


def _classify_provenance_kind(kind_str: str) -> ProvenanceNodeKind:
    """Classify a TraceKind string or 'state'/'evidence' into a node kind."""
    mapping: dict[str, ProvenanceNodeKind] = {
        "state": ProvenanceNodeKind.STATE,
        "evidence": ProvenanceNodeKind.EVIDENCE,
        "transition": ProvenanceNodeKind.TRANSITION,
        "appraisal": ProvenanceNodeKind.APPRAISAL,
        "action": ProvenanceNodeKind.ACTION,
        "interaction": ProvenanceNodeKind.INTERACTION,
        "observation": ProvenanceNodeKind.OBSERVATION,
    }
    return mapping.get(kind_str, ProvenanceNodeKind.UNKNOWN)


# ---------------------------------------------------------------------------
# State filter options
# ---------------------------------------------------------------------------

StateFilterScope = Scope | None  # None = all scopes
StateFilterDimension = str | None  # None = all dimensions
StateFilterLifecycle = Literal["current_like", "terminal", "validity_outcome", "unknown", None]
StateFilterStatus = str | None  # None = all statuses


class ObservationQueryService:
    """Read-only query service for the Observation Window.

    Parameters
    ----------
    state_backend:
        A durable ``StateBackend`` (e.g. ``SqliteStateBackend``).
        Must only be used for load/find methods.
    fact_backend:
        A durable ``FactBackend`` (e.g. ``SqliteFactBackend``).
        Must only be used for load/find methods.
    commit_marker_store:
        Optional ``CommitMarkerStore`` for commit-probe queries.
        If None, commit probes return False.

    The service does NOT hold a reference to any MR orchestrator, dynamics
    engine, appraisal provider, or memory system. It is safe to instantiate
    in a separate process from the runtime.
    """

    def __init__(
        self,
        state_backend: StateBackend,
        fact_backend: FactBackend,
        commit_marker_store: CommitMarkerStore | None = None,
    ) -> None:
        self._state = state_backend
        self._fact = fact_backend
        self._commits = commit_marker_store

    # ------------------------------------------------------------------
    # A. Current State
    # ------------------------------------------------------------------

    def list_current_states(
        self,
        scope: StateFilterScope = None,
        dimension: StateFilterDimension = None,
        status_filter: StateFilterLifecycle = None,
        raw_status: StateFilterStatus = None,
    ) -> tuple[ObservedStateRow, ...]:
        """Return all canonical state rows matching the filters.

        Filters are applied after loading from the backend — OW-P1 does
        not delegate filtering to the backend so that every backend method
        call remains a pure read.

        Parameters
        ----------
        scope:
            If provided, restrict to states matching this Scope.
            None means all scopes.
        dimension:
            If provided, restrict to states whose dimension starts with
            this string prefix (e.g. ``"agent.affect"``). None means all.
        status_filter:
            Classification filter: "current_like", "terminal",
            "validity_outcome", or "unknown". None means all.
        raw_status:
            If provided, restrict to states whose ``status`` string equals
            this value exactly. None means all.
        """
        rows = self._state.load_states()
        result: list[ObservedStateRow] = []

        for s in rows:
            # Scope filter
            if scope is not None and s.scope != scope:
                continue
            # Dimension prefix filter
            if dimension is not None and not s.dimension.startswith(dimension):
                continue
            # Lifecycle classification filter
            if status_filter is not None:
                classified = _classify_lifecycle(s.status)
                if classified != status_filter:
                    continue
            # Raw status filter
            if raw_status is not None and s.status != raw_status:
                continue

            result.append(
                ObservedStateRow(
                    state_id=StateId(s.state_id),
                    scope=s.scope,
                    dimension=s.dimension,
                    value=s.value,
                    status=s.status,
                    lifecycle_class=_classify_lifecycle(s.status),
                    valid_from=s.valid_from,
                    valid_until=s.valid_until,
                    relevant_until=s.relevant_until,
                    last_observed_at=s.last_observed_at,
                    updated_at=s.updated_at,
                    evidence_refs=s.evidence_refs,
                    transition_refs=s.transition_refs,
                    origin_runtime_id=s.origin_runtime_id,
                    version=s.version,
                )
            )

        return tuple(result)

    def get_state(self, state_id: str) -> ObservedStateRow | None:
        """Return the single canonical state row with the given state_id.

        Returns ``None`` if no matching row exists. Fails closed on
        unknown identifiers.
        """
        rows = self._state.load_states()
        for s in rows:
            if s.state_id == state_id:
                return ObservedStateRow(
                    state_id=StateId(s.state_id),
                    scope=s.scope,
                    dimension=s.dimension,
                    value=s.value,
                    status=s.status,
                    lifecycle_class=_classify_lifecycle(s.status),
                    valid_from=s.valid_from,
                    valid_until=s.valid_until,
                    relevant_until=s.relevant_until,
                    last_observed_at=s.last_observed_at,
                    updated_at=s.updated_at,
                    evidence_refs=s.evidence_refs,
                    transition_refs=s.transition_refs,
                    origin_runtime_id=s.origin_runtime_id,
                    version=s.version,
                )
        return None

    # ------------------------------------------------------------------
    # B. Recent Changes
    # ------------------------------------------------------------------

    def list_recent_changes(
        self,
        limit: int = 50,
        scope: StateFilterScope = None,
        dimension: StateFilterDimension = None,
    ) -> tuple[ObservedStateChange, ...]:
        """Return the most recent state transitions.

        Parameters
        ----------
        limit:
            Maximum number of changes to return, ordered by committed_at
            descending. Defaults to 50.
        scope:
            Restrict to this scope. None means all.
        dimension:
            Restrict to dimensions starting with this prefix. None means all.
        """
        transitions = self._state.load_transitions()
        states_by_id = {s.state_id: s for s in self._state.load_states()}

        # Build from_state / to_state lookup
        changes: list[ObservedStateChange] = []
        for t in transitions:
            if scope is not None and t.scope != scope:
                continue
            # Dimension filter uses to_state
            if dimension is not None and not t.to_state.dimension.startswith(dimension):
                continue

            before_state = states_by_id.get(t.from_state.state_id)
            after_state = states_by_id.get(t.to_state.state_id)

            changes.append(
                ObservedStateChange(
                    transition_id=TransitionId(t.transition_id),
                    dimension=t.to_state.dimension,
                    scope=t.scope,
                    before_value=before_state.value if before_state else None,
                    after_value=after_state.value if after_state else t.to_state.value,
                    status_before=before_state.status if before_state else None,
                    status_after=t.to_state.status,
                    committed_at=t.committed_at,
                    intent_id=t.intent_id,
                    origin_runtime_id=t.origin_runtime_id,
                    diff_available=before_state is not None,
                )
            )

        # Sort descending by committed_at
        changes.sort(key=lambda c: c.committed_at, reverse=True)
        return tuple(changes[:limit])

    # ------------------------------------------------------------------
    # C. Pending vs Canonical
    # ------------------------------------------------------------------

    def list_definitions(self) -> tuple[StateDefinition, ...]:
        """Return all registered state definitions from the state backend."""
        return self._state.load_definitions()

    def was_turn_committed(self, interaction_id: str, scope: Scope) -> bool:
        """Return True if the given turn (interaction_id, scope) was committed.

        Returns False if no commit marker exists or if
        ``commit_marker_store`` was not provided at construction.
        """
        if self._commits is None:
            return False
        return self._commits.has_commit(interaction_id=interaction_id, scope=scope)

    # ------------------------------------------------------------------
    # D. Evidence / Factual plane
    # ------------------------------------------------------------------

    def list_evidence(
        self,
        scope: StateFilterScope = None,
        source_type: str | None = None,
    ) -> tuple[ObservedEvidenceRef, ...]:
        """Return evidence rows matching the filters.

        The ``SqliteFactBackend.load_evidence()`` method returns
        ``(Evidence, interaction_id)`` pairs — the interaction_id is
        the durable binding from the fact-plane admission record.

        Parameters
        ----------
        scope:
            Restrict to this scope. None means all.
        source_type:
            Restrict to rows with this exact ``source_type`` string.
            None means all.
        """
        rows = self._fact.load_evidence()
        result: list[ObservedEvidenceRef] = []

        for ev, interaction_id in rows:
            if scope is not None and ev.scope != scope:
                continue
            if source_type is not None and ev.source_type != source_type:
                continue

            result.append(
                ObservedEvidenceRef(
                    evidence_id=EvidenceId(ev.id),
                    scope=ev.scope,
                    source_kind=_classify_evidence_source(ev.source_type),
                    source_id=ev.source_id,
                    source_type=ev.source_type,
                    occurred_at=ev.occurred_at,
                    received_at=ev.received_at,
                    payload=ev.payload,
                    origin_runtime_id=ev.origin_runtime_id,
                )
            )

        return tuple(result)

    def get_evidence(self, evidence_id: str) -> ObservedEvidenceRef | None:
        """Return a single evidence row by ID, or None if not found.

        Searches across all scopes; if the evidence is bound to a
        specific scope, the caller should know it. Returns the first
        match. Backends do not currently expose an unscoped lookup;
        OW-P1 uses load_evidence and filters.
        """
        rows = self._fact.load_evidence()
        for ev, _interaction_id in rows:
            if ev.id == evidence_id:
                return ObservedEvidenceRef(
                    evidence_id=EvidenceId(ev.id),
                    scope=ev.scope,
                    source_kind=_classify_evidence_source(ev.source_type),
                    source_id=ev.source_id,
                    source_type=ev.source_type,
                    occurred_at=ev.occurred_at,
                    received_at=ev.received_at,
                    payload=ev.payload,
                    origin_runtime_id=ev.origin_runtime_id,
                )
        return None

    def list_observations(
        self,
        scope: StateFilterScope = None,
    ) -> tuple[ObservedObservationRow, ...]:
        """Return all observation rows.

        The durable Observation schema carries ``evidence_refs`` as
        the explicit provenance edge from an observation back to its
        source evidence. That is the only edge OW-P1 draws from
        observation → evidence; no other relationship is recorded.
        """
        rows = self._fact.load_observations()
        result: list[ObservedObservationRow] = []

        for o in rows:
            if scope is not None and o.scope != scope:
                continue
            result.append(
                ObservedObservationRow(
                    observation_id=ObservationId(o.id),
                    interaction_id=o.interaction_id,
                    scope=o.scope,
                    observation_type=o.type,
                    key=o.key,
                    value=o.value,
                    confidence=o.confidence,
                    observed_at=o.observed_at,
                    evidence_refs=o.evidence_refs,
                    origin_runtime_id=o.origin_runtime_id,
                )
            )

        return tuple(result)

    def list_interactions(
        self,
        scope: StateFilterScope = None,
    ) -> tuple[ObservedInteractionRow, ...]:
        """Return all interaction rows."""
        rows = self._fact.load_interactions()
        result: list[ObservedInteractionRow] = []

        for i in rows:
            if scope is not None and i.scope != scope:
                continue
            result.append(
                ObservedInteractionRow(
                    interaction_id=InteractionId(i.id),
                    scope=i.scope,
                    occurred_at=i.occurred_at,
                    received_at=i.received_at,
                    status=i.status,
                    origin_runtime_id=i.origin_runtime_id,
                )
            )

        return tuple(result)
