"""OW-3 read-model contracts: production causal chain types.

These contracts model the J8-E3 Gate 8 production causal chain for the
read-only Observation Window. They are **outside** the MR runtime
(observation_window package) and are immutable value objects.

The data they describe lives in the live `AppraisalAffectTransitionResult`
returned by `EngineEmotionalTransitionPort.transition()` — specifically:
- `AppraisalAffectDecision` per-rule decisions
- `AppraisalResult` and `ResolvedAppraisal` (the appraisal source output)
- `AssessmentTrace` (state_before, state_after, contributions, abstention_reasons)
- `AssessmentContribution` (per-dimension contribution with `source_kind` + `source_ref`)

OW-3 does NOT persist any of this. It reads the live object via the
``OWLiveTraceSource`` adapter and produces immutable snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType

from mind_runtime.contracts.scope import Scope

# ---------------------------------------------------------------------------
# Opaque identifiers
# ---------------------------------------------------------------------------

AppraisalId = NewType("AppraisalId", str)
RuleId = NewType("RuleId", str)
InteractionId = NewType("InteractionId", str)
TraceId = NewType("TraceId", str)
SourceRef = NewType("SourceRef", str)  # canonical token, e.g. "appraisal:<id>:<rule>:state:<ref>"

# ---------------------------------------------------------------------------
# Composition status
# ---------------------------------------------------------------------------

class AppraisalCompositionStatus(StrEnum):
    """Whether the J8-E3 appraisal-affect composition is active.

    OFF is a **legitimate production configuration** — not an error.
    It is determined by inspecting the orchestrator's wiring at
    observation time (whether `transition_result` is an instance of
    `AppraisalAffectTransitionResult` with non-None `appraisal_result`,
    OR whether the `NullAppraisalResultSource` is in use).
    """

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedAppraisalDecision:
    """One ``AppraisalAffectDecision`` as seen by the Observation Window.

    Mirrors the production contract field-by-field. The reason_code and
    abstention_reason fields are the **runtime's** reasons, surfaced
    verbatim — OW-3 does NOT invent its own reason taxonomy.
    """

    decision_index: int        # ordinal within the decisions tuple
    appraisal_id: AppraisalId
    rule_id: RuleId
    matched_state_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    provider_confidence: float
    applied: bool
    reason_code: str | None
    abstention_reason: str | None

    # Derived for UI clarity
    effective_dimension: str | None  # resolved from the matched state_refs (rule_id → state_ref → dimension)
    source_ref: SourceRef           # canonical token, f"appraisal:{appraisal_id}:{rule_id}:state:{state_ref}"


# ---------------------------------------------------------------------------
# Appraisal source
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedAppraisal:
    """One ``ResolvedAppraisal`` as seen by the Observation Window.

    Carries the appraisal_id, polarity, confidence, and the evidence
    refs that justified it. This is the link from the orchestrator's
    appraised input to the per-rule decisions below it.
    """

    appraisal_id: AppraisalId
    polarity: str            # AppraisalPolarity value
    authority: str           # AppraisalAuthority value
    causal_status: str       # CausalStatus value
    provider_confidence: float
    primary_evidence_refs: tuple[str, ...]
    secondary_evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservedAppraisalSourceOutput:
    """The output of the appraisal source (one ``AppraisalResult``).

    Carries the source's candidates/rejected split plus the abstention
    reason if any. Mirrors the production contract field-by-field.
    """

    abstention_reason: str | None
    reject_reason: str | None
    candidate_count: int
    rejected_count: int
    provenance_ref: str | None
    created_at: datetime | None


# ---------------------------------------------------------------------------
# Trace (the assessment that produced the state change)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedContribution:
    """One ``AssessmentContribution`` as seen by the Observation Window.

    Joins back to ``ObservedAppraisalDecision`` via ``source_ref`` —
    the canonical token `appraisal:<id>:<rule>:state:<ref>` appears
    on both sides.
    """

    dimension: str
    source_kind: str   # "appraisal" | "event" | "history" | "recovery" | etc.
    source_ref: SourceRef
    amount: float
    confidence: float
    applied: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class ObservedAssessmentTrace:
    """One ``AssessmentTrace`` as seen by the Observation Window.

    Provides the dimension-level before/after state map plus the
    contributions and abstention reasons.
    """

    trace_id: TraceId
    scope: Scope
    origin_runtime_id: str
    context_ref: str
    persona_id: str
    persona_version: int
    state_before: dict[str, float]
    state_after: dict[str, float]
    contributions: tuple[ObservedContribution, ...]
    evidence_refs: tuple[str, ...]
    history_refs: tuple[str, ...]
    abstention_reasons: tuple[str, ...]
    created_at: datetime

    def delta_for(self, dimension: str) -> float | None:
        """Return before→after delta for a dimension, or None if missing."""
        before = self.state_before.get(dimension)
        after = self.state_after.get(dimension)
        if before is None or after is None:
            return None
        return after - before


# ---------------------------------------------------------------------------
# Turn-level snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObservedTurnSnapshot:
    """The OW-3 snapshot of one turn's J8-E3 production causal chain.

    The full chain visible in one snapshot:

        Appraisals (resolved from source)
            ↓ (matched_state_refs)
        Decisions (per-rule applied/abstained)
            ↓ (canonical source_ref)
        Contributions (per-dimension amount, confidence)
            ↓ (state_before / state_after)
        Affect state delta

    Composition status (`ON`/`OFF`) is recorded so the UI can
    render a legitimate "OFF" configuration without alarm.
    """

    interaction_id: InteractionId
    scope: Scope
    origin_runtime_id: str
    composition: AppraisalCompositionStatus

    # Appraisal source output
    appraisal_source: ObservedAppraisalSourceOutput | None
    appraisals: tuple[ObservedAppraisal, ...]

    # Per-rule decisions
    decisions: tuple[ObservedAppraisalDecision, ...]

    # The engine trace
    assessment_trace: ObservedAssessmentTrace

    # Timing
    trace_created_at: datetime
    snapshot_at: datetime

    # Provenance cross-link
    transitions: tuple[str, ...] = ()  # state_ids that were committed in this turn (if available)


# ---------------------------------------------------------------------------
# Causal-chain join result (per-affect-dimension)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CausalChainLink:
    """One link in the resolved causal chain for a single dimension.

    Each link carries a `kind` that names what it represents and a
    `source_ref` that joins it to upstream / downstream links.
    No timing inference — only real ID references.
    """

    kind: str   # "appraisal" | "rule" | "decision" | "contribution" | "evidence"
    identifier: str
    label: str
    amount: float | None      # for rule/decision/contribution
    confidence: float | None  # for appraisal/rule/decision/contribution
    source_ref: SourceRef | None
    applied: bool | None
    reason_code: str | None
    extra: dict[str, object]


@dataclass(frozen=True, slots=True)
class ResolvedCausalChain:
    """The fully-resolved causal chain for one dimension in one turn.

    Built by joining the live trace (appraisal → rule → decision →
    contribution) by canonical source_ref tokens.
    """

    interaction_id: InteractionId
    dimension: str
    state_before: float
    state_after: float
    delta: float
    chain: tuple[CausalChainLink, ...]

    # Signal flags (driven by real trace data, not inferred)
    has_appraisal: bool
    has_applied_decision: bool
    has_abstention: bool
    abstention_reasons: tuple[str, ...]
