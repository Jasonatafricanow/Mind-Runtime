"""Ports for the D3 factual plane admission path (ADR-0009 dispositions)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    EffectiveWindow,
    Evidence,
    Observation,
    ObservationModality,
    SemanticTime,
)


class FactAdmissionDisposition(StrEnum):
    """The backend-arbitrated admission outcome for one Evidence (ADR-0009).

    - ``NEW``: Evidence and derived Observation were newly admitted
      atomically; the turn consumes the new Observation once (causal).
    - ``REPAIRED``: the exact Evidence already existed but its derived
      Observation was missing; the repair turn consumes the repaired
      Observation exactly once (causal, labeled repaired).
    - ``REPLAY``: the exact Evidence and derived Observation already exist;
      the turn does not consume them again (non-causal audit only).

    The disposition is decided by the durable backend transaction, never
    inferred from schedule IDs, Interaction IDs, payload text, validation
    fixtures, or Dynamics output.
    """

    NEW = "new"
    REPAIRED = "repaired"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class FactAdmissionResult:
    """One admission outcome: the authoritative Observation plus disposition."""

    observation: Observation
    disposition: FactAdmissionDisposition


class FactAdmissionObserver(Protocol):
    """Post-admission consumer; grants no factual authority (ADR-0023)."""

    def after_admission(self, evidence: Evidence, result: FactAdmissionResult) -> None:
        ...


@runtime_checkable
class FactIngestPort(Protocol):
    """Admit Evidence into the factual plane after authority/ownership gates.

    The canonical pipeline consumes facts only through this port: no other
    code path may construct an Observation from raw Evidence. Implementations
    must be append-only, idempotent, and fail closed on authority/ownership
    violations. Idempotency ownership lives here — validation never detects
    duplicates.
    """

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        """Return the admission result (Observation + disposition) for ``evidence``.

        Raises AuthorityError when the evidence cannot become a user fact,
        OwnershipError when the writing runtime/Persona does not own the scope, and
        FactAdmissionConflictError for same ``(scope, id)`` with different
        immutable bytes or an impossible partial pair.
        """
        ...


@dataclass(frozen=True, slots=True)
class RealityAdmissionRequest:
    """Explicit typed request for admitting an Evidence-derived Reality Observation."""

    source_evidence: Evidence
    interaction_id: str
    writing_runtime: str
    writing_persona_id: str | None
    observation_id: str
    key: str
    value: object
    confidence: float
    modality: ObservationModality = ObservationModality.ASSERTED
    semantic_time: SemanticTime = SemanticTime()
    effective_window: EffectiveWindow | None = None


@runtime_checkable
class RealityAdmissionPort(Protocol):
    """Narrow port for admitting typed Reality proposals into the factual plane."""

    def admit_reality(
        self,
        request: RealityAdmissionRequest,
    ) -> FactAdmissionResult:
        """Admit a typed Reality proposition after namespace, provenance,
        and conflict validation.
        """
        ...
