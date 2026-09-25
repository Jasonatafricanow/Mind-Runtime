"""Compressed emotional-transition input, result, and causal trace contracts."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from mind_runtime.contracts.affect import AffectiveDimensionProfile
from mind_runtime.contracts.appraisal import AppraisalRouteDecision, SemanticEventCandidate
from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.historical import HistoricalContextBundle
from mind_runtime.contracts.late_projection import AcceptedAppraisal
from mind_runtime.contracts.observation import Observation
from mind_runtime.contracts.projection import ProjectedMindState
from mind_runtime.contracts.scope import Scope
from mind_runtime.contracts.situation import Situation
from mind_runtime.contracts.state import RuntimeState


def _validate_dimension_values(values: tuple[tuple[str, float], ...], field_name: str) -> None:
    seen: set[str] = set()
    for dimension, value in values:
        require_non_empty(dimension, f"{field_name} dimensions")
        if dimension in seen:
            raise ValueError(f"{field_name} dimensions must be unique")
        if isinstance(value, bool):
            raise ValueError(f"{field_name} values must be numeric")
        seen.add(dimension)


@dataclass(frozen=True, slots=True)
class AssessmentContribution:
    """One bounded, inspectable contribution to an affect transition.

    Per C10-ASSESSMENT-CONFIDENCE-SCHEMA: confidence is the per-row audit
    value, owned by the row's source authority. Per R3 §7 (frozen
    provenance table): impulse contributions have an upstream confidence
    (provider / rule); recovery, coupling, and relationship contributions
    have NO upstream confidence column. The audit must honestly reflect
    this absence: confidence=None for non-impulse rows.

    None is the structural "no upstream authority for this row" signal,
    NOT a fabricated zero. (Zero would collapse two distinct authorities
    — provider confidence and the absence-of-authority — into one
    scalar, violating R3 §8's separation.)
    """

    dimension: str
    source_kind: str
    source_ref: str
    amount: float
    confidence: float | None
    applied: bool
    reason_code: str | None

    def __post_init__(self) -> None:
        require_non_empty(self.dimension, "dimension")
        require_non_empty(self.source_kind, "source_kind")
        require_non_empty(self.source_ref, "source_ref")
        if isinstance(self.amount, bool):
            raise ValueError("amount must be numeric")
        if self.confidence is not None and (
            isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be in [0, 1] or None")
        if not isinstance(self.applied, bool):
            raise ValueError("applied must be a bool")
        if self.reason_code is not None:
            require_non_empty(self.reason_code, "reason_code")


@dataclass(frozen=True, slots=True)
class AssessmentTrace:
    """Immutable explanation of one deterministic emotional-state step."""

    trace_id: str
    scope: Scope
    origin_runtime_id: str
    context_ref: str
    persona_id: str
    persona_version: int
    state_before: tuple[tuple[str, float], ...]
    contributions: tuple[AssessmentContribution, ...]
    state_after: tuple[tuple[str, float], ...]
    evidence_refs: tuple[str, ...]
    history_refs: tuple[str, ...]
    abstention_reasons: tuple[str, ...]
    route_decision: AppraisalRouteDecision
    created_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.trace_id, "trace_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.context_ref, "context_ref")
        require_non_empty(self.persona_id, "persona_id")
        if isinstance(self.persona_version, bool) or self.persona_version < 1:
            raise ValueError("persona_version must be at least 1")
        _validate_dimension_values(self.state_before, "state_before")
        _validate_dimension_values(self.state_after, "state_after")
        for ref in self.evidence_refs:
            require_non_empty(ref, "evidence_refs entries")
        for ref in self.history_refs:
            require_non_empty(ref, "history_refs entries")
        for reason in self.abstention_reasons:
            require_non_empty(reason, "abstention_reasons entries")
        if self.route_decision.scope != self.scope:
            raise ValueError("route_decision.scope must match scope")
        require_aware_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class EmotionalTransitionInput:
    """All explicit inputs to one emotional transition; no policy authority."""

    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    context: Situation
    current_affect: tuple[RuntimeState, ...]
    elapsed: timedelta
    persona_id: str
    persona_version: int
    persona: tuple[AffectiveDimensionProfile, ...]
    observations: tuple[Observation, ...]
    semantic_candidates: tuple[SemanticEventCandidate, ...]
    history_context: HistoricalContextBundle | None
    clock: datetime
    projection_scope: Scope | None

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.persona_id, "persona_id")
        if self.context.scope != self.scope:
            raise ValueError("context.scope must match scope")
        if isinstance(self.persona_version, bool) or self.persona_version < 1:
            raise ValueError("persona_version must be at least 1")
        if self.elapsed < timedelta(0):
            raise ValueError("elapsed must not be negative")
        seen_affect: set[str] = set()
        affect_scope = self.projection_scope or self.scope
        for state in self.current_affect:
            if state.scope != affect_scope:
                raise ValueError("current affect scope must match projection scope")
            if state.dimension in seen_affect:
                raise ValueError("current affect dimensions must be unique")
            if not isinstance(state.value, (int, float)) or isinstance(state.value, bool):
                raise ValueError("current affect values must be numeric")
            seen_affect.add(state.dimension)
        for observation in self.observations:
            if observation.scope != self.scope:
                raise ValueError("observation scope must match scope")
        for candidate in self.semantic_candidates:
            if candidate.scope != self.scope:
                raise ValueError("semantic candidate scope must match scope")
        if self.history_context is not None and self.history_context.scope != self.scope:
            raise ValueError("history context scope must match scope")
        require_aware_utc(self.clock, "clock")


@dataclass(frozen=True, slots=True)
class EmotionalTransitionResult:
    """Projected state, accepted typed events, and trace from one affect step."""

    projected: ProjectedMindState
    accepted_events: tuple[SemanticEventCandidate, ...]
    assessment_trace: AssessmentTrace
    accepted_appraisals: tuple[AcceptedAppraisal, ...] = ()
    projection_refs: tuple[str, ...] = ()
    legacy_no_appraisal: bool = False

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for event in self.accepted_events:
            if event.scope != self.assessment_trace.scope:
                raise ValueError("accepted event scope must match assessment trace scope")
            if event.candidate_id in seen:
                raise ValueError("accepted event ids must be unique")
            seen.add(event.candidate_id)
        if len(self.accepted_appraisals) != len(self.projection_refs):
            raise ValueError("accepted appraisals and projection refs must align")
        for acceptance in self.accepted_appraisals:
            if acceptance.status != "ACCEPTED":
                raise ValueError("accepted_appraisals must contain ACCEPTED records")
            if acceptance.candidate.scope != self.assessment_trace.scope:
                raise ValueError("accepted appraisal scope must match assessment trace")
