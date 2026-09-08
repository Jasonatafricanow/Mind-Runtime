"""Telemetry sink protocol and stage definitions for Mind Runtime observability.

HARD AUTHORITY BOUNDARY (TICKET: OW-TRANSIENT-TRACE-JOURNAL-V1):
This protocol defines an observer-only write sink.
Mind Runtime components (SituationBuilder, HistoricalContextProvider,
SemanticAppraisalProducer, DecisionContextCompiler, DynamicsEngine,
HomeostasisGate, SlowPlasticityWriter, memory retrieval, persona/self
accumulation) MUST NEVER read from observer telemetry.

Dependency direction is strictly:
  MR / Gateway runtime -> observer telemetry journal -> Observation Window
NEVER:
  observer telemetry -> MR
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class TelemetryStage:
    USER_INGRESS = "USER_INGRESS"
    SEMANTIC_CANDIDATE = "SEMANTIC_CANDIDATE"
    SEMANTIC_ABSTAIN = "SEMANTIC_ABSTAIN"
    SEMANTIC_ERROR = "SEMANTIC_ERROR"
    APPRAISAL = "APPRAISAL"
    APPRAISAL_ERROR = "APPRAISAL_ERROR"
    EFFECT = "EFFECT"
    IMPULSE = "IMPULSE"
    HOMEOSTASIS = "HOMEOSTASIS"
    SLOW_DECISION = "SLOW_DECISION"
    SLOW_WRITE = "SLOW_WRITE"
    STATE_TRANSITION = "STATE_TRANSITION"
    ASSISTANT_RESPONSE = "ASSISTANT_RESPONSE"
    TURN_COMMIT = "TURN_COMMIT"
    TURN_ABORT = "TURN_ABORT"
    SEMANTIC_EXECUTION = "SEMANTIC_EXECUTION"
    AFFECT_CONTRIBUTION = "AFFECT_CONTRIBUTION"


class TelemetrySinkProtocol(Protocol):
    """Observer sink protocol implemented by external telemetry journals.
    
    Fail-open requirement: implementations must never propagate exceptions to
    the calling runtime.
    """

    def record(
        self,
        interaction_id: str,
        stage: str,
        status: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        source_refs: tuple[str, ...] = (),
    ) -> None:
        """Append one non-authoritative telemetry event."""
        ...

    def record_llm_usage(
        self,
        *,
        interaction_id: str,
        stage: str,
        provider: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        usage_source: str,
        latency_ms: float | None = None,
        success: bool = True,
        retry_count: int = 0,
        error_message: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """Record an LLM call token usage and execution event (fail-open)."""
        ...
