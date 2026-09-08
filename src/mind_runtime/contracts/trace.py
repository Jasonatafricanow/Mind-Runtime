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
