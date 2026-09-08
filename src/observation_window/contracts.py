"""OW-P1 read-model contracts.

These are **outside** the MR runtime. They are immutable value objects
produced by the Observation Window's query service from the durable
read methods on ``StateBackend`` and ``FactBackend``. They carry no
authority and cannot be round-tripped back into MR to mutate runtime state.

All types are frozen dataclasses so they are safe to pass through a UI
layer without side-effect risk.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, NewType

from mind_runtime.contracts.scope import Scope

# ---------------------------------------------------------------------------
# Primitive identifiers (opaque string aliases for type safety)
# ---------------------------------------------------------------------------

StateId = NewType("StateId", str)
TransitionId = NewType("TransitionId", str)
EvidenceId = NewType("EvidenceId", str)
ObservationId = NewType("ObservationId", str)
InteractionId = NewType("InteractionId", str)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class LifecycleStatus(StrEnum):
    """Observed lifecycle status of a canonical state row.

    Mirrors the seven ``StateLifecycle`` values that can appear in the
    ``RuntimeState.status`` field. No new statuses are invented here.

    ``CURRENT_LIKE`` marks the two statuses that can represent the
    current value of a dimension (ACTIVE, IMPROVING). ``TERMINAL``
    marks the four statuses that answer "what happened?" and never
    become CURRENT_LIKE (RESOLVED, COMPLETED, CANCELLED, SUPERSEDED).
    ``VALIDITY_OUTCOME`` marks EXPIRED (a validity outcome, not a
    lifecycle terminal — per D4.1 baseline).
    """

    CURRENT_LIKE = "current_like"  # ACTIVE, IMPROVING
    TERMINAL = "terminal"          # RESOLVED, COMPLETED, CANCELLED, SUPERSEDED
    VALIDITY_OUTCOME = "validity_outcome"  # EXPIRED
    UNKNOWN = "unknown"            # any other string — pass-through only


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceSourceKind(StrEnum):
    """Observed source kinds for Evidence rows.

    These mirror the values that appear in ``Evidence.source_type``.
    Unrecognised strings are surfaced as the literal value with a
    ``UNKNOWN`` flag so the UI never silently drops them.
    """

    USER_STATEMENT = "user_statement"
    ASSISTANT_STATEMENT = "assistant_statement"
    INFERENCE = "inference"
    OBSERVATION = "observation"
    EXTERNAL = "external"
    # Future J8-E3 / C10 provenance targets can be added here without
    # changing the read-model contract — only the renderer changes.
    UNKNOWN = "unknown"  # any other source_type not listed above


# ---------------------------------------------------------------------------
# State read-model
# ---------------------------------------------------------------------------

ObservedLifecycleStatus = Literal[
    "current_like", "terminal", "validity_outcome", "unknown"
]


@dataclass(frozen=True, slots=True)
class ObservedStateRow:
    """A snapshot of one canonical state row for the Observation Window.

    Produced by ``ObservationQueryService.list_current_states()`` and
    ``get_state()``. Immutable — never round-tripped into MR.
    """

    # Core identity
    state_id: StateId
    scope: Scope
    dimension: str
    value: object

    # Lifecycle
    status: str          # raw string from RuntimeState.status
    lifecycle_class: ObservedLifecycleStatus  # derived classification

    # Timestamps
    valid_from: datetime
    valid_until: datetime | None
    relevant_until: datetime | None
    last_observed_at: datetime
    updated_at: datetime

    # Provenance refs (opaque IDs, not dereferenced)
    evidence_refs: tuple[str, ...]
    transition_refs: tuple[str, ...]

    # Sync identity
    origin_runtime_id: str
    version: int


@dataclass(frozen=True, slots=True)
class ObservedStateChange:
    """One state transition as seen by the Observation Window.

    ``before`` and ``after`` are raw values; the Observation Window
    does NOT compute the delta — it shows what the backend recorded.
    If the backend has no previous-state record for this dimension,
    ``before`` is ``None`` and the change is labelled
    ``diff_available: False``.
    """

    transition_id: TransitionId
    dimension: str
    scope: Scope
    before_value: object | None          # None when previous not found
    after_value: object | None
    status_before: str | None
    status_after: str
    committed_at: datetime
    intent_id: str
    origin_runtime_id: str
    diff_available: bool                # False when before_value is None


# ---------------------------------------------------------------------------
# Evidence read-model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedEvidenceRef:
    """A reference to one durable Evidence row for the Observation Window.

    ``source_kind`` is the derived classification (not the raw
    ``source_type`` string). ``payload`` is the raw frozen payload from
    ``Evidence.payload`` and is shown verbatim — OW-P1 does NOT
    interpret or transform it.
    """

    evidence_id: EvidenceId
    scope: Scope
    source_kind: EvidenceSourceKind
    source_id: str           # raw Evidence.source_id
    source_type: str         # raw source_type string (for forward compat)
    occurred_at: datetime
    received_at: datetime
    payload: object          # verbatim; OW-P1 does not interpret
    origin_runtime_id: str


@dataclass(frozen=True, slots=True)
class ObservedObservationRow:
    """A reference to one durable Observation row for the Observation Window.

    The schema fields carried on durable Observation rows are:
    ``id``, ``interaction_id``, ``scope``, ``type``, ``key``, ``value``,
    ``confidence``, ``observed_at``, ``evidence_refs``, ``origin_runtime_id``.

    ``evidence_refs`` is the explicit list of evidence IDs the
    observation was admitted from. This is the **only** durable
    provenance edge OW-P1 draws from an observation to evidence.
    """

    observation_id: ObservationId
    interaction_id: str
    scope: Scope
    observation_type: str
    key: str
    value: object
    confidence: float
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    origin_runtime_id: str


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedInteractionRow:
    """A reference to one durable Interaction row for the Observation Window."""

    interaction_id: InteractionId
    scope: Scope
    occurred_at: datetime
    received_at: datetime
    status: str
    origin_runtime_id: str


# ---------------------------------------------------------------------------
# Provenance graph node
# ---------------------------------------------------------------------------

class ProvenanceNodeKind(StrEnum):
    """The kinds of node the Observation Window can render in a provenance graph.

    These mirror the frozen ``TraceKind`` enum plus the four additional
    kinds that appear in durable state rows: STATE, EVIDENCE, TRANSITION,
    INTERACTION.

    Future J8-E3 provenance targets (AppraisalAffectDecision, etc.) do
    NOT require a new node kind here — they will surface as
    ``kind=TraceKind.APPRAISAL`` with a label indicating the sub-type.
    """

    STATE = "state"
    EVIDENCE = "evidence"
    TRANSITION = "transition"
    APPRAISAL = "appraisal"
    ACTION = "action"
    INTERACTION = "interaction"
    # The following cover TraceKind items (EVIDENCE, OBSERVATION) that
    # appear in durable stores as named references, plus any future
    # targets. OW-P1 labels each node with its concrete identifier so
    # the UI can render whatever the backend actually stored.
    OBSERVATION = "observation"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    """One node in the observed provenance graph.

    ``provenance_kind`` is the TraceKind-derived classification.
    ``raw_id`` is the concrete identifier from the durable row.
    ``label`` is a human-readable one-line description suitable for a
    tree or graph renderer.
    ``extra`` carries domain-specific fields verbatim — OW-P1 does NOT
    interpret them, it just passes them through.
    ``upstream`` lists the IDs this node explicitly references (real
    provenance edges only; never inferred from timestamps).
    ``lifecycle_note`` describes the lifecycle class (current-like / terminal /
    validity-outcome) for STATE nodes; absent for other kinds.
    """

    node_id: str
    provenance_kind: ProvenanceNodeKind
    raw_id: str
    label: str
    extra: dict[str, object]
    upstream: tuple[str, ...]   # explicit refs only; empty if none
    lifecycle_note: str | None  # "current_like" / "terminal" / etc.; None for non-state nodes


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """One provenance edge between two nodes.

    ``source`` and ``target`` are concrete identifiers that map to
    ``ProvenanceNode.node_id``.

    ``relation`` is a human-readable label describing the nature of the
    edge (e.g. "evidence → state", "transition → evidence_ref"). OW-P1
    does NOT invent relations — it derives them from the concrete field
    names in the source row.
    """

    source_id: str
    target_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    """The complete provenance graph for one state or evidence ID.

    Produced by ``ObservationQueryService.get_provenance()``.
    """

    root_id: str
    root_kind: ProvenanceNodeKind
    nodes: tuple[ProvenanceNode, ...]
    edges: tuple[ProvenanceEdge, ...]

    # Signal that upstream exploration hit a limit or missing record.
    # When True, the graph is real but incomplete — some edges could
    # not be followed because the referenced record is absent from
    # the durable stores.
    incomplete: bool
