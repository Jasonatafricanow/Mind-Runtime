from __future__ import annotations

from collections.abc import Mapping

import pytest

from mind_runtime.decision import (
    DecisionAnswer,
    DecisionCapability,
    DecisionKind,
    DecisionModelUnavailable,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.decision.backends.typesafe import TypeSafeDecisionBackend
from mind_runtime.decision.factory import DecisionModelConfig, build_decision_capability
from mind_runtime.decision.telemetry import (
    DecisionCallStatus,
    InMemoryDecisionTelemetry,
)


def request() -> DecisionRequest:
    return DecisionRequest(
        feature="test.feature",
        projection_version="v1",
        state={"query": "which candidate matters?"},
        questions=(
            DecisionQuestion("useful", DecisionKind.BOOLEAN, "Is this useful?"),
            DecisionQuestion(
                "choice",
                DecisionKind.CHOICE,
                "Which option fits?",
                ("a", "b"),
            ),
            DecisionQuestion(
                "score",
                DecisionKind.SCORE,
                "How strong is it?",
                ("low", "high"),
            ),
        ),
    )


class GoodBackend:
    @property
    def backend_name(self) -> str:
        return "good"

    def evaluate(self, value: DecisionRequest) -> DecisionResult:
        assert value.feature == "test.feature"
        return DecisionResult(
            backend="good",
            model_version="v1",
            answers=(
                DecisionAnswer(
                    "useful",
                    DecisionKind.BOOLEAN,
                    {"false": 0.1, "true": 0.9},
                    selected="true",
                ),
                DecisionAnswer(
                    "choice",
                    DecisionKind.CHOICE,
                    {"a": 0.2, "b": 0.8},
                    selected="b",
                    confidence=0.6,
                ),
                DecisionAnswer(
                    "score",
                    DecisionKind.SCORE,
                    {"low": 0.25, "high": 0.75},
                    score=0.75,
                    confidence=0.5,
                ),
            ),
        )


class DownBackend:
    @property
    def backend_name(self) -> str:
        return "down"

    def evaluate(self, value: DecisionRequest) -> DecisionResult:
        del value
        raise DecisionModelUnavailable("offline")


class BadBackend:
    @property
    def backend_name(self) -> str:
        return "bad"

    def evaluate(self, value: DecisionRequest) -> DecisionResult:
        del value
        return DecisionResult(
            backend="bad",
            model_version="v1",
            answers=(
                DecisionAnswer(
                    "wrong-id",
                    DecisionKind.BOOLEAN,
                    {"false": 0.5, "true": 0.5},
                ),
            ),
        )


def test_optional_capability_absence_and_outage_are_fail_open() -> None:
    telemetry = InMemoryDecisionTelemetry()
    absent = DecisionCapability(telemetry=telemetry)
    assert absent.evaluate(request()) is None
    assert telemetry.traces[-1].status is DecisionCallStatus.ABSENT

    down = DecisionCapability(DownBackend(), telemetry=telemetry)
    assert down.evaluate(request()) is None
    assert telemetry.traces[-1].status is DecisionCallStatus.UNAVAILABLE
    assert telemetry.traces[-1].backend == "down"


def test_capability_validates_backend_shape_once_for_all_features() -> None:
    telemetry = InMemoryDecisionTelemetry()
    capability = DecisionCapability(GoodBackend(), telemetry=telemetry)
    result = capability.evaluate(request())
    assert result is not None
    assert result.answer("useful").yes_probability == pytest.approx(0.9)
    assert result.answer("choice").selected == "b"
    assert result.answer("score").probability("high") == pytest.approx(0.75)
    assert telemetry.traces[-1].status is DecisionCallStatus.SUCCESS

    invalid = DecisionCapability(BadBackend(), telemetry=telemetry)
    assert invalid.evaluate(request()) is None
    assert telemetry.traces[-1].status is DecisionCallStatus.UNAVAILABLE


def test_contracts_are_bounded_and_fingerprinted() -> None:
    first = request()
    second = request()
    assert first.fingerprint == second.fingerprint
    assert first.state["query"] == "which candidate matters?"
    with pytest.raises(ValueError):
        DecisionQuestion("q", DecisionKind.CHOICE, "pick", ("only",))
    with pytest.raises(ValueError):
        DecisionQuestion("q", DecisionKind.BOOLEAN, "yes?", ("bad",))
    with pytest.raises(ValueError):
        DecisionRequest(
            feature="x",
            projection_version="v1",
            state={"x": "y"},
            questions=(),
        )


def test_single_factory_defaults_to_no_backend() -> None:
    assert not build_decision_capability().available
    assert not build_decision_capability(DecisionModelConfig()).available
    with pytest.raises(ValueError, match="api_key"):
        build_decision_capability(DecisionModelConfig(backend="typesafe"))


def test_typesafe_backend_maps_generic_primitives_without_sdk_dependency() -> None:
    calls: list[tuple[str, Mapping[str, str], Mapping[str, object], float]] = []

    def post_json(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        calls.append((url, headers, payload, timeout))
        return {
            "model": "jev-1.13.0",
            "answers": {
                "useful": {"type": "noul", "noul": 0.9},
                "choice": {
                    "type": "choice",
                    "choice": "b",
                    "probabilities": {"a": 0.2, "b": 0.8},
                    "confidence": 0.6,
                },
                "score": {
                    "type": "score",
                    "score": 0.75,
                    "legend": {"0": "low", "1": "high"},
                    "probabilities": {"0": 0.25, "1": 0.75},
                    "confidence": 0.5,
                },
            },
            "usage": {"input_tokens": 123, "output_tokens": 7},
        }

    backend = TypeSafeDecisionBackend(
        api_key="secret",
        model="jev-1.13.0",
        post_json=post_json,
    )
    result = backend.evaluate(request())
    assert result.backend == "typesafe"
    assert result.model_version == "jev-1.13.0"
    assert result.input_tokens == 123
    assert result.answer("useful").yes_probability == pytest.approx(0.9)
    assert result.answer("choice").probability("b") == pytest.approx(0.8)
    assert result.answer("score").probability("high") == pytest.approx(0.75)

    assert len(calls) == 1
    _, headers, payload, timeout = calls[0]
    assert headers["Authorization"] == "Bearer secret"
    assert timeout == 8.0
    assert payload["model"] == "jev-1.13.0"
    questions = payload["questions"]
    assert isinstance(questions, dict)
    assert questions["useful"]["type"] == "noul"
    assert questions["choice"]["type"] == "choice"
    assert questions["score"]["type"] == "score"
