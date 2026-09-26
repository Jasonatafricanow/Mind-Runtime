"""Fail-open composition for the optional parallel decision capability."""

from __future__ import annotations

from time import perf_counter

from mind_runtime.decision.contracts import DecisionKind, DecisionRequest, DecisionResult
from mind_runtime.decision.port import DecisionModelPort
from mind_runtime.decision.telemetry import (
    DecisionCallStatus,
    DecisionTelemetrySink,
    DecisionTrace,
    NullDecisionTelemetry,
)


def _valid_result(request: DecisionRequest, result: object) -> bool:
    if not isinstance(result, DecisionResult):
        return False
    expected = {item.question_id: item for item in request.questions}
    actual = {item.question_id: item for item in result.answers}
    if set(actual) != set(expected):
        return False
    for question_id, question in expected.items():
        answer = actual[question_id]
        if answer.kind is not question.kind:
            return False
        allowed = {"false", "true"} if question.kind is DecisionKind.BOOLEAN else set(
            question.options
        )
        if set(answer.probabilities) != set(allowed):
            return False
    return True


class DecisionCapability:
    """Shared optional model capability; every failure falls back to baseline."""

    def __init__(
        self,
        backend: DecisionModelPort | None = None,
        *,
        telemetry: DecisionTelemetrySink | None = None,
    ) -> None:
        self._backend = backend
        self._telemetry = telemetry or NullDecisionTelemetry()

    @property
    def available(self) -> bool:
        return self._backend is not None

    def _record(self, trace: DecisionTrace) -> None:
        try:
            self._telemetry.record(trace)
        except Exception:
            pass

    def evaluate(self, request: DecisionRequest) -> DecisionResult | None:
        if not isinstance(request, DecisionRequest):
            raise TypeError("request must be DecisionRequest")
        started = perf_counter()
        if self._backend is None:
            self._record(
                DecisionTrace(
                    request.feature,
                    request.projection_version,
                    request.fingerprint,
                    DecisionCallStatus.ABSENT,
                    None,
                    None,
                    (perf_counter() - started) * 1000,
                )
            )
            return None

        backend_name: str | None = None
        try:
            backend_name = self._backend.backend_name
            result = self._backend.evaluate(request)
            if not _valid_result(request, result):
                raise ValueError("decision backend returned an incompatible result")
        except Exception as exc:
            self._record(
                DecisionTrace(
                    request.feature,
                    request.projection_version,
                    request.fingerprint,
                    DecisionCallStatus.UNAVAILABLE,
                    backend_name,
                    None,
                    (perf_counter() - started) * 1000,
                    type(exc).__name__,
                )
            )
            return None

        self._record(
            DecisionTrace(
                request.feature,
                request.projection_version,
                request.fingerprint,
                DecisionCallStatus.SUCCESS,
                result.backend,
                result.model_version,
                (perf_counter() - started) * 1000,
            )
        )
        return result
