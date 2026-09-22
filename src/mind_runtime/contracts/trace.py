"""Trace and evidence reference contracts."""

from dataclasses import dataclass
from enum import StrEnum

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.scope import Scope


class TraceKind(StrEnum):
    """The causal-chain object kind a trace ref points at."""

    EVIDENCE = "evidence"
    OBSERVATION = "observation"
    TRANSITION = "transition"
    APPRAISAL = "appraisal"
    ACTION = "action"
    INTERACTION = "interaction"


@dataclass(frozen=True, slots=True)
class TraceRef:
    """A link to one causal-chain object for replay and provenance."""

    ref_id: str
    scope: Scope
    origin_runtime_id: str
    kind: TraceKind
    target_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.ref_id, "ref_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.kind, TraceKind):
            raise ValueError("kind must be a TraceKind")
        require_non_empty(self.target_id, "target_id")



@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Provenance boundary: a reference to verbatim Evidence."""

    ref_id: str
    scope: Scope
    origin_runtime_id: str
    evidence_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.ref_id, "ref_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.evidence_id, "evidence_id")


class SourceKind(StrEnum):
    """Origin kind of an evidence/observation source."""

    USER_REPORT = "user_report"
    EXTERNAL_OBSERVATION = "external_observation"
    SELF_ACTION = "self_action"
    BODY_OUTPUT = "body_output"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class EpistemicMode(StrEnum):
    """Epistemic status of a source."""

    REPORTED = "reported"
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """The resolved authoritative provenance of a source reference."""

    ref: str
    root_evidence_id: str | None
    admitted_observation_id: str | None
    scope: Scope
    origin_runtime_id: str
    source_kind: SourceKind
    epistemic_mode: EpistemicMode
    is_admitted: bool
    is_valid_for_longitudinal_support: bool
    denial_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.ref, "ref")
        if not isinstance(self.source_kind, SourceKind):
            raise ValueError("source_kind must be a SourceKind")
        if not isinstance(self.epistemic_mode, EpistemicMode):
            raise ValueError("epistemic_mode must be an EpistemicMode")

