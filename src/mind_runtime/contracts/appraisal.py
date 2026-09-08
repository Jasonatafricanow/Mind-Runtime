"""Bounded semantic interpretation contracts."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope


class AppraisalPath(StrEnum):
    """Explicit appraisal route (DECISION-025)."""

    DETERMINISTIC = "deterministic"
    TYPED_MAPPING = "typed_mapping"
    LLM = "llm"


@dataclass(frozen=True, slots=True)
class AppraisalRouteDecision:
    """The explicit routing decision for one appraisal (DECISION-025)."""

    route_id: str
    scope: Scope
    path: AppraisalPath
    ambiguity_score: float | None
    confidence: float
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.route_id, "route_id")
        if not isinstance(self.path, AppraisalPath):
            raise ValueError("path must be an AppraisalPath")
        if self.ambiguity_score is not None and not 0 <= self.ambiguity_score <= 1:
            raise ValueError("ambiguity_score must be in [0, 1]")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        for code in self.reason_codes:
            require_non_empty(code, "reason_codes entries")


@dataclass(frozen=True, slots=True)
class AmbiguityAssessment:
    """Signals of genuine semantic ambiguity; no small-model central router."""

    ambiguous: bool
    score: float
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.ambiguous, bool):
            raise ValueError("ambiguous must be a bool")
        if isinstance(self.score, bool) or not 0 <= self.score <= 1:
            raise ValueError("score must be in [0, 1]")
        for reason in self.reasons:
            require_non_empty(reason, "reasons entries")


@dataclass(frozen=True, slots=True)
class SemanticAppraisal:
    """Semantic interpretation only; never carries final affect numbers.

    Per ADR-0016, salience is the authoritative appraisal of what this event
    means for the current Agent, considering persona, relationship, history,
    and current context. None = unavailable / not appraised. 0.0 = authoritative
    appraisal result: negligible. Values must be in [0, 1].
    """

    appraisal_id: str
    scope: Scope
    origin_runtime_id: str
    situation_ref: str
    meanings: tuple[str, ...]
    valence: str
    relationship_relevance: str
    confidence: float
    evidence_refs: tuple[str, ...]
    salience: float | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.appraisal_id, "appraisal_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.situation_ref, "situation_ref")
        for meaning in self.meanings:
            require_non_empty(meaning, "meanings entries")
        require_non_empty(self.valence, "valence")
        require_non_empty(self.relationship_relevance, "relationship_relevance")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        for ref in self.evidence_refs:
            require_non_empty(ref, "evidence_refs entries")
        if self.salience is not None:
            if isinstance(self.salience, bool) or not 0 <= self.salience <= 1:
                raise ValueError("salience must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SemanticEventCandidate:
    """A provider-neutral typed event candidate; never an affect or action verdict.

    Per C10-SALIENCE-IMPL-R2: this contract does NOT own salience, evidence_refs,
    or any appraisal. Appraisal is a separate object (SemanticAppraisal)
    carried in the SemanticRoutingResult.appraisals_by_candidate_id map,
    not embedded in the candidate. Candidate is the subject of appraisal,
    not its container.
    """

    candidate_id: str
    scope: Scope
    origin_runtime_id: str
    kind: str
    attributes: tuple[tuple[str, str], ...]
    confidence: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.candidate_id, "candidate_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.kind, "kind")
        for key, value in self.attributes:
            require_non_empty(key, "attribute keys")
            require_non_empty(value, "attribute values")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        for ref in self.evidence_refs:
            require_non_empty(ref, "evidence_refs entries")


@dataclass(frozen=True, slots=True)
class SemanticRoutingResult:
    """One bounded semantic route and its auditable candidate set.

    Per C10-SALIENCE-IMPL-R2: appraisals_by_candidate_id is the independent
    carrier for SemanticAppraisal objects. Each candidate_id maps to its
    associated appraisal (the judgment about that candidate). Candidate and
    appraisal are separate objects at different layers.
    """

    route: AppraisalRouteDecision
    candidates: tuple[SemanticEventCandidate, ...]
    provider_call_count: int
    abstention_reasons: tuple[str, ...]
    appraisals_by_candidate_id: dict[str, SemanticAppraisal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.provider_call_count, bool) or self.provider_call_count < 0:
            raise ValueError("provider_call_count must be non-negative")
        seen: set[str] = set()
        for candidate in self.candidates:
            if candidate.scope != self.route.scope:
                raise ValueError("semantic candidate scope must match route scope")
            if candidate.candidate_id in seen:
                raise ValueError("semantic candidate ids must be unique")
            seen.add(candidate.candidate_id)
        for reason in self.abstention_reasons:
            require_non_empty(reason, "abstention_reasons entries")


@dataclass(frozen=True, slots=True)
class AppraisalModelProposal:
    """Non-authoritative model output; producer validates and assembles.

    Per ADR-0019-R4 §2.4, §4: exactly six fields. Five model-estimated fields
    plus a non-authoritative evidence selector. The model proposes semantic
    estimates; the producer binds system fields and validates the proposal
    against the trusted_evidence_pool.
    """

    meanings: tuple[str, ...]
    valence: str
    relationship_relevance: str
    salience: float | None
    appraisal_confidence: float
    supporting_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.meanings:
            raise ValueError("meanings must not be empty")
        for meaning in self.meanings:
            require_non_empty(meaning, "meanings entries")
        require_non_empty(self.valence, "valence")
        require_non_empty(self.relationship_relevance, "relationship_relevance")
        if self.salience is not None:
            if isinstance(self.salience, bool) or not 0 <= self.salience <= 1:
                raise ValueError("salience must be in [0, 1]")
        if (
            isinstance(self.appraisal_confidence, bool)
            or not 0 <= self.appraisal_confidence <= 1
        ):
            raise ValueError("appraisal_confidence must be in [0, 1]")
        for ref in self.supporting_evidence_refs:
            require_non_empty(ref, "supporting_evidence_refs entries")


@dataclass(frozen=True, slots=True)
class SemanticAppraisalContext:
    """Explicit context passed to SemanticAppraisalProducer and its model estimator.

    Per ADR-0019-R4 §4:
    - REQUIRED: candidate, situation, persona, history
    - OPTIONAL: current_affect
    - NOT AUTHORIZED IN V1: slow state, full memory dump, unrestricted persona,
      DecisionContext, Body/LLM output, ResolvedAppraisal, host appraisal,
      EventEffectRule values.
    """

    candidate: SemanticEventCandidate
    situation: object  # Situation
    persona: tuple[object, ...]  # tuple[AffectiveDimensionProfile, ...]
    history: object | None  # HistoricalContextBundle | None
    current_affect: tuple[object, ...] = ()  # tuple[RuntimeState, ...]


@runtime_checkable
class SemanticAppraisalModelPort(Protocol):
    """Bounded model estimator for appraisal-semantic fields (ADR-0019-R4 APPRAISAL-4).

    The model proposes estimates for the five model-estimated fields plus a
    non-authoritative evidence selector. System-authored identity and system-bound
    fields are NEVER proposed by the model.
    """

    def propose(
        self,
        *,
        candidate: SemanticEventCandidate,
        context: SemanticAppraisalContext,
        trusted_evidence_pool: tuple[str, ...],
    ) -> AppraisalModelProposal:
        """Propose estimates for model-estimated fields."""
        ...
