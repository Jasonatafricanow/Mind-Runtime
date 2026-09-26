"""Fail-open composition for the optional parallel decision capability."""

from __future__ import annotations

from time import perf_counter

from mind_runtime.decision.contracts import (
    DecisionKind,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.decision.port import (
    DecisionModelError,
    DecisionModelInvalidResponse,
    DecisionModelPort,
)
from mind_runtime.decision.telemetry import (
    DecisionCallStatus,
    DecisionTelemetrySink,
    DecisionTrace,
    NullDecisionTelemetry,
)


def _validate_result(request: DecisionRequest, result: DecisionResult) -> None:
    if not isinstance(result, DecisionResult):
        raise DecisionModelInvalidResponse("backend must return DecisionResult")
    by_id = {answer.question_id: answer for answer in result.answers}
    expected_ids = {question.question_id for question in request.questions}
    if set(by_id) != expected_ids:
        raise DecisionModelInvalidResponse("backend answers do not match request questions")
    for question in request.questions:
        answer = by_id[question.question_id]
        if answer.kind is not question.kind:
            raise DecisionModelInvalidResponse("backend answer kind mismatch")
        keys = set(answer.probabilities)
        if question.kind is DecisionKind.BOOLEAN:
            if keys != {"false", "true"}:
                raise DecisionModelInvalidResponse(
                    "BOOLEAN answers require false/true probabilities"
                )
        elif keys != set(question.options):
            raise DecisionModelInvalidResponse(
                "CHOICE/SCORE probabilities must match request options"
            )


class DecisionCapability:
    """One shared optional decision-model capability.

    Absence or backend failure returns None. Callers must preserve their
    original baseline path when this happens.
    """

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

    def evaluate(self, request: DecisionRequest) -> DecisionResult | None:
        if not isinstance(request, DecisionRequest):
            raise TypeError("request must be DecisionRequest")
        started = perf_counter()
        if self._backend is None:
            self._telemetry.record(
                DecisionTrace(
                    feature=request.feature,
                    projection_version=request.projection_version,
                    request_fingerprint=request.fingerprint,
                    status=DecisionCallStatus.ABSENT,
                    backend=None,
                    model_version=None,
                    latency_ms=(perf_counter() - started) * 1000,
                )
            )
            return None
        try:
            result = self._backend.evaluate(request)
            _validate_result(request, result)
        except DecisionModelError as exc:
            self._telemetry.record(
                DecisionTrace(
                    feature=request.feature,
                    projection_version=request.projection_version,
                    request_fingerprint=request.fingerprint,
                    status=DecisionCallStatus.UNAVAILABLE,
                    backend=self._backend.backend_name,
                    model_version=None,
                    latency_ms=(perf_counter() - started) * 1000,
                    error_type=type(exc).__name__,
                )
            )
            return None
        self._telemetry.record(
            DecisionTrace(
                feature=request.feature,
                projection_version=request.projection_version,
                request_fingerprint=request.fingerprint,
                status=DecisionCallStatus.SUCCESS,
                backend=result.backend,
                model_version=result.model_version,
                latency_ms=(perf_counter() - started) * 1000,
            )
        )
        return result
