"""Bounded semantic routing inside the single emotional-transition step."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    AppraisalPath,
    AppraisalRouteDecision,
    Observation,
    Scope,
    SemanticEventCandidate,
    SemanticRoutingResult,
    Situation,
)
from mind_runtime.contracts.telemetry import TelemetrySinkProtocol, TelemetryStage


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    """Non-authoritative runtime telemetry and candidates from a semantic provider.

    Contains no mutable state; safe for multi-turn concurrency.
    """

    candidates: tuple[SemanticEventCandidate, ...]
    provider_name: str
    model: str
    latency_ms: float
    success: bool
    explicit_abstain: bool = False
    error: str | None = None
    raw_output: str | None = None


@runtime_checkable
class SemanticCandidateProvider(Protocol):
    """Optional language provider that can propose typed events only."""

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        """Return bounded semantic candidates without affect or action values."""
        ...


class SemanticRouter:
    """Prefer trusted typed events and abstain on uncertain language."""

    def __init__(
        self,
        *,
        provider: SemanticCandidateProvider | None = None,
        minimum_confidence: float = 0.75,
        conflict_margin: float = 0.1,
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> None:
        for value, name in (
            (minimum_confidence, "minimum_confidence"),
            (conflict_margin, "conflict_margin"),
        ):
            if isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        self._provider = provider
        self._minimum_confidence = minimum_confidence
        self._conflict_margin = conflict_margin
        self._telemetry_sink = telemetry_sink

    def route(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        supplied_candidates: tuple[SemanticEventCandidate, ...],
        telemetry_sink: TelemetrySinkProtocol | None = None,
    ) -> SemanticRoutingResult:
        if any(observation.scope != context.scope for observation in observations):
            raise ValueError("observation scope must match context scope")

        sink = telemetry_sink or self._telemetry_sink
        interaction_id = (
            observations[0].interaction_id
            if observations
            else (context.situation_id or "unknown")
        )
        occ_at = (
            observations[0].observed_at
            if observations
            else datetime.now(timezone.utc)
        )

        if supplied_candidates:
            candidates = self._ordered(supplied_candidates)
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="SKIPPED",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_not_called",
                            "execution_state": "provider_not_called",
                            "reason": "supplied_semantic_candidates",
                            "candidate_count": len(candidates),
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
            return self._result(
                context=context,
                path=AppraisalPath.TYPED_MAPPING,
                candidates=candidates,
                provider_call_count=0,
                ambiguity_score=0.0,
                reason_codes=("supplied_semantic_candidates",),
            )

        typed = tuple(
            self._candidate_from_typed_observation(observation, context.scope)
            for observation in observations
            if observation.key == "typed_event.observed"
        )
        if typed:
            candidates = self._ordered(typed)
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="SKIPPED",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_not_called",
                            "execution_state": "provider_not_called",
                            "reason": "trusted_typed_event",
                            "candidate_count": len(candidates),
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
            return self._result(
                context=context,
                path=AppraisalPath.TYPED_MAPPING,
                candidates=candidates,
                provider_call_count=0,
                ambiguity_score=0.0,
                reason_codes=("trusted_typed_event",),
            )

        if not observations:
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="SKIPPED",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_not_called",
                            "execution_state": "provider_not_called",
                            "reason": "no_observations",
                            "candidate_count": 0,
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
            return self._result(
                context=context,
                path=AppraisalPath.DETERMINISTIC,
                candidates=(),
                provider_call_count=0,
                ambiguity_score=0.0,
                reason_codes=("no_semantic_event",),
            )

        if self._provider is None:
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="SKIPPED",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_not_called",
                            "execution_state": "provider_not_called",
                            "reason": "semantic_provider_unavailable",
                            "candidate_count": 0,
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
            return self._result(
                context=context,
                path=AppraisalPath.LLM,
                candidates=(),
                provider_call_count=0,
                ambiguity_score=1.0,
                reason_codes=("unmapped_language", "semantic_provider_unavailable"),
                forced_abstentions=("semantic_provider_unavailable",),
            )

        exec_res: ProviderExecutionResult | None = None
        if hasattr(self._provider, "propose_with_telemetry"):
            t0 = time.perf_counter()
            try:
                exec_res = self._provider.propose_with_telemetry(
                    observations=observations,
                    context=context,
                    scope=context.scope,
                    telemetry_sink=sink,
                )
                raw_candidates = exec_res.candidates
            except Exception as exc:
                lat = (time.perf_counter() - t0) * 1000
                p_name = getattr(self._provider, "__class__", type(self._provider)).__name__
                p_model = getattr(self._provider, "_model", getattr(self._provider, "model", "unknown"))
                if sink is not None:
                    try:
                        sink.record(
                            interaction_id=interaction_id,
                            stage=TelemetryStage.SEMANTIC_EXECUTION,
                            status="ERROR",
                            occurred_at=occ_at,
                            payload={
                                "state": "provider_unavailable",
                                "execution_state": "provider_unavailable",
                                "provider": p_name,
                                "model": p_model,
                                "latency_ms": round(lat, 2),
                                "error": str(exc),
                                "reason": str(exc),
                            },
                            source_refs=(),
                        )
                    except Exception:
                        pass
                raise
        else:
            t0 = time.perf_counter()
            try:
                raw_cand = self._provider.propose(
                    observations=observations,
                    context=context,
                    scope=context.scope,
                )
                lat = (time.perf_counter() - t0) * 1000
                raw_candidates = tuple(raw_cand)
                exec_res = ProviderExecutionResult(
                    candidates=raw_candidates,
                    provider_name=getattr(self._provider, "__class__", type(self._provider)).__name__,
                    model=getattr(self._provider, "_model", "unknown"),
                    latency_ms=lat,
                    success=True,
                    explicit_abstain=len(raw_candidates) == 0,
                )
            except Exception as exc:
                lat = (time.perf_counter() - t0) * 1000
                p_name = getattr(self._provider, "__class__", type(self._provider)).__name__
                p_model = getattr(self._provider, "_model", "unknown")
                if sink is not None:
                    try:
                        sink.record(
                            interaction_id=interaction_id,
                            stage=TelemetryStage.SEMANTIC_EXECUTION,
                            status="ERROR",
                            occurred_at=occ_at,
                            payload={
                                "state": "provider_unavailable",
                                "execution_state": "provider_unavailable",
                                "provider": p_name,
                                "model": p_model,
                                "latency_ms": round(lat, 2),
                                "error": str(exc),
                                "reason": str(exc),
                            },
                            source_refs=(),
                        )
                    except Exception:
                        pass
                raise

        candidates = self._ordered(raw_candidates)

        # Record 1 of the remaining 4 mutually exclusive states
        if not exec_res.success:
            # State 2: provider_unavailable
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="ERROR",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_unavailable",
                            "execution_state": "provider_unavailable",
                            "provider": exec_res.provider_name,
                            "model": exec_res.model,
                            "latency_ms": round(exec_res.latency_ms, 2),
                            "error": exec_res.error or "provider_error",
                            "reason": exec_res.error or "provider_error",
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
        elif not candidates:
            # State 3: provider_returned_no_candidates
            if sink is not None:
                try:
                    sink.record(
                        interaction_id=interaction_id,
                        stage=TelemetryStage.SEMANTIC_EXECUTION,
                        status="ABSTAINED",
                        occurred_at=occ_at,
                        payload={
                            "state": "provider_returned_no_candidates",
                            "execution_state": "provider_returned_no_candidates",
                            "provider": exec_res.provider_name,
                            "model": exec_res.model,
                            "latency_ms": round(exec_res.latency_ms, 2),
                            "explicit_abstain": exec_res.explicit_abstain,
                            "error": exec_res.error,
                        },
                        source_refs=(),
                    )
                except Exception:
                    pass
        else:
            abstentions = self._candidate_abstentions(candidates)
            if abstentions:
                # State 4: candidates_rejected_by_semantic_router
                if sink is not None:
                    try:
                        sink.record(
                            interaction_id=interaction_id,
                            stage=TelemetryStage.SEMANTIC_EXECUTION,
                            status="REJECTED",
                            occurred_at=occ_at,
                            payload={
                                "state": "candidates_rejected_by_semantic_router",
                                "execution_state": "candidates_rejected_by_semantic_router",
                                "provider": exec_res.provider_name,
                                "model": exec_res.model,
                                "latency_ms": round(exec_res.latency_ms, 2),
                                "reason": abstentions[0],
                                "abstention_reasons": list(abstentions),
                                "minimum_confidence": self._minimum_confidence,
                                "rejected_candidates": [
                                    {
                                        "candidate_id": c.candidate_id,
                                        "kind": c.kind,
                                        "confidence": c.confidence,
                                    }
                                    for c in candidates
                                ],
                            },
                            source_refs=(),
                        )
                    except Exception:
                        pass
            else:
                # State 5: candidate_accepted_by_semantic_router
                if sink is not None:
                    try:
                        sink.record(
                            interaction_id=interaction_id,
                            stage=TelemetryStage.SEMANTIC_EXECUTION,
                            status="ACCEPTED",
                            occurred_at=occ_at,
                            payload={
                                "state": "candidate_accepted_by_semantic_router",
                                "execution_state": "candidate_accepted_by_semantic_router",
                                "provider": exec_res.provider_name,
                                "model": exec_res.model,
                                "latency_ms": round(exec_res.latency_ms, 2),
                                "candidate": {
                                    "candidate_id": candidates[0].candidate_id,
                                    "kind": candidates[0].kind,
                                    "confidence": candidates[0].confidence,
                                },
                                "accepted_candidate": {
                                    "candidate_id": candidates[0].candidate_id,
                                    "kind": candidates[0].kind,
                                    "confidence": candidates[0].confidence,
                                },
                            },
                            source_refs=candidates[0].evidence_refs,
                        )
                    except Exception:
                        pass

        return self._result(
            context=context,
            path=AppraisalPath.LLM,
            candidates=candidates,
            provider_call_count=1,
            ambiguity_score=1.0,
            reason_codes=("unmapped_language", "provider_candidate"),
        )

    @staticmethod
    def _candidate_from_typed_observation(
        observation: Observation, scope: Scope
    ) -> SemanticEventCandidate:
        if not isinstance(observation.value, Mapping):
            raise ValueError("typed event value must be a mapping")
        kind = observation.value.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("typed event kind must be non-empty")
        raw_attributes = observation.value.get("attributes", {})
        if not isinstance(raw_attributes, Mapping):
            raise ValueError("typed event attributes must be a mapping")
        attributes: list[tuple[str, str]] = []
        for key, value in raw_attributes.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("typed event attributes must contain strings")
            attributes.append((key, value))
        return SemanticEventCandidate(
            candidate_id=f"semantic-{observation.id}",
            scope=scope,
            origin_runtime_id=observation.origin_runtime_id,
            kind=kind,
            attributes=tuple(sorted(attributes)),
            confidence=observation.confidence,
            evidence_refs=observation.evidence_refs,
        )

    @staticmethod
    def _ordered(
        candidates: tuple[SemanticEventCandidate, ...],
    ) -> tuple[SemanticEventCandidate, ...]:
        return tuple(sorted(candidates, key=lambda item: (-item.confidence, item.candidate_id)))

    def _result(
        self,
        *,
        context: Situation,
        path: AppraisalPath,
        candidates: tuple[SemanticEventCandidate, ...],
        provider_call_count: int,
        ambiguity_score: float,
        reason_codes: tuple[str, ...],
        forced_abstentions: tuple[str, ...] = (),
    ) -> SemanticRoutingResult:
        abstentions = forced_abstentions or self._candidate_abstentions(candidates)
        confidence = candidates[0].confidence if candidates else 0.0
        return SemanticRoutingResult(
            route=AppraisalRouteDecision(
                route_id=f"route-{context.situation_id}",
                scope=context.scope,
                path=path,
                ambiguity_score=ambiguity_score,
                confidence=confidence,
                reason_codes=reason_codes,
            ),
            candidates=candidates,
            provider_call_count=provider_call_count,
            abstention_reasons=abstentions,
        )

    def _candidate_abstentions(
        self, candidates: tuple[SemanticEventCandidate, ...]
    ) -> tuple[str, ...]:
        if not candidates:
            return ()
        if (
            len(candidates) > 1
            and candidates[0].kind != candidates[1].kind
            and candidates[0].confidence - candidates[1].confidence <= self._conflict_margin
        ):
            return ("conflicting_candidates",)
        if candidates[0].confidence < self._minimum_confidence:
            return ("low_confidence",)
        return ()
