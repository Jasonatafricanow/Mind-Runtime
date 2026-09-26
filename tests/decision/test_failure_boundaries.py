from __future__ import annotations

from contextlib import contextmanager
from typing import cast

import pytest

from mind_runtime.decision import (
    DecisionAnswer,
    DecisionCapability,
    DecisionKind,
    DecisionModelInvalidResponse,
    DecisionModelUnavailable,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.decision.backends import typesafe
from mind_runtime.decision.backends.typesafe import TypeSafeDecisionBackend
from mind_runtime.decision.factory import DecisionModelConfig, build_decision_capability
from mind_runtime.memory.decision_projection import (
    MemoryRerankCandidate,
    MemoryRetrievalDecisionProjection,
)


def _boolean_request() -> DecisionRequest:
    return DecisionRequest(
        "test",
        "v1",
        {"value": "candidate"},
        (DecisionQuestion("q", DecisionKind.BOOLEAN, "Relevant?"),),
    )


def test_contract_boundary_rejects_malformed_values() -> None:
    with pytest.raises(ValueError):
        DecisionQuestion("", DecisionKind.BOOLEAN, "x")
    with pytest.raises(TypeError):
        DecisionQuestion("q", cast(DecisionKind, "boolean"), "x")
    with pytest.raises(ValueError):
        DecisionQuestion("q", DecisionKind.CHOICE, "x", ("only",))
    with pytest.raises(ValueError):
        DecisionRequest("x", "v1", {}, (_boolean_request().questions[0],))
    with pytest.raises(ValueError):
        DecisionRequest("x", "v1", {"x": "y"}, ())
    with pytest.raises(ValueError):
        DecisionAnswer("q", DecisionKind.BOOLEAN, {"true": 2.0})
    with pytest.raises(ValueError):
        DecisionAnswer(
            "q",
            DecisionKind.SCORE,
            {"low": 1.0},
            confidence=2.0,
        )
    with pytest.raises(ValueError):
        DecisionResult("b", "v", (), input_tokens=-1)


def test_result_helpers_are_explicit() -> None:
    answer = DecisionAnswer(
        "choice",
        DecisionKind.CHOICE,
        {"a": 0.4, "b": 0.6},
        selected="b",
    )
    assert answer.probability("missing") == 0.0
    with pytest.raises(TypeError):
        _ = answer.yes_probability
    with pytest.raises(KeyError):
        DecisionResult("b", "v", (answer,)).answer("missing")


def test_factory_is_off_by_default_and_validates_configuration() -> None:
    assert not build_decision_capability().available
    with pytest.raises(ValueError):
        DecisionModelConfig(backend="unknown")
    with pytest.raises(ValueError):
        DecisionModelConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        build_decision_capability(DecisionModelConfig(backend="typesafe"))
    assert build_decision_capability(
        DecisionModelConfig(backend="typesafe", api_key="key")
    ).available


def test_typesafe_rejects_bad_payloads_and_wraps_transport_failures() -> None:
    invalid = [
        {},
        {"model": "jev", "answers": []},
        {"model": "jev", "answers": {"q": {"type": "choice", "noul": 0.5}}},
        {"model": "jev", "answers": {"q": {"type": "noul", "noul": 2.0}}},
    ]
    for response in invalid:
        backend = TypeSafeDecisionBackend(
            api_key="key",
            post_json=lambda *_args, response=response: response,
        )
        with pytest.raises(DecisionModelInvalidResponse):
            backend.evaluate(_boolean_request())

    def crash(*_args):
        raise RuntimeError("transport wrapper failed")

    with pytest.raises(DecisionModelUnavailable):
        TypeSafeDecisionBackend(api_key="key", post_json=crash).evaluate(
            _boolean_request()
        )


def test_typesafe_http_boundary_maps_io_and_invalid_json(monkeypatch) -> None:
    def io_failure(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(typesafe, "urlopen", io_failure)
    with pytest.raises(DecisionModelUnavailable):
        typesafe._http_post_json("http://x", {}, {}, 1.0)

    class Response:
        def read(self):
            return b"not-json"

    @contextmanager
    def invalid_json(*_args, **_kwargs):
        yield Response()

    monkeypatch.setattr(typesafe, "urlopen", invalid_json)
    with pytest.raises(DecisionModelInvalidResponse):
        typesafe._http_post_json("http://x", {}, {}, 1.0)


def test_memory_projection_guards_do_not_expand_the_model_boundary() -> None:
    with pytest.raises(ValueError):
        MemoryRerankCandidate("", "content")
    with pytest.raises(ValueError):
        MemoryRerankCandidate("id", "")
    with pytest.raises(TypeError):
        MemoryRetrievalDecisionProjection(cast(DecisionCapability, object()))
    projection = MemoryRetrievalDecisionProjection(DecisionCapability())
    assert projection.rerank(
        query="q",
        candidates=(MemoryRerankCandidate("m1", "one"),),
    ) == ("m1",)


def test_remaining_generic_boundary_guards() -> None:
    with pytest.raises(ValueError):
        DecisionQuestion("q", DecisionKind.CHOICE, "x", ("same", "same"))
    with pytest.raises(ValueError):
        DecisionQuestion("q", DecisionKind.BOOLEAN, "x", ("bad",))
    with pytest.raises(ValueError):
        DecisionRequest(
            "x",
            "v1",
            {str(i): "x" * 8192 for i in range(9)},
            (_boolean_request().questions[0],),
        )
    with pytest.raises(ValueError):
        DecisionAnswer(
            "q",
            DecisionKind.BOOLEAN,
            {"true": cast(float, "bad")},
        )
    with pytest.raises(ValueError):
        DecisionAnswer(
            "q",
            DecisionKind.CHOICE,
            {"a": 1.0},
            selected="missing",
        )
    with pytest.raises(ValueError):
        DecisionAnswer(
            "q",
            DecisionKind.SCORE,
            {"low": 1.0},
            score=float("inf"),
        )
    valid = DecisionAnswer(
        "q",
        DecisionKind.BOOLEAN,
        {"false": 0.0, "true": 1.0},
    )
    with pytest.raises(ValueError):
        DecisionResult("b", "v", (valid,), input_tokens=-1)
    with pytest.raises(KeyError):
        DecisionResult("b", "v", (valid,)).answer("missing")
    with pytest.raises(ValueError):
        DecisionModelConfig(backend="")
    with pytest.raises(ValueError):
        MemoryRetrievalDecisionProjection(
            DecisionCapability(),
            max_candidate_characters=1,
        )
    with pytest.raises(ValueError):
        MemoryRetrievalDecisionProjection(
            DecisionCapability(),
            max_candidates=1,
        )


def test_typesafe_concrete_boundary_guards() -> None:
    with pytest.raises(ValueError):
        TypeSafeDecisionBackend(api_key="", model="jev")
    with pytest.raises(ValueError):
        TypeSafeDecisionBackend(api_key="key", model="")
    with pytest.raises(ValueError):
        TypeSafeDecisionBackend(api_key="key", endpoint="ftp://invalid")
    with pytest.raises(ValueError):
        TypeSafeDecisionBackend(api_key="key", timeout_seconds=0)

    choice = DecisionRequest(
        "test",
        "v1",
        {"value": "candidate"},
        (
            DecisionQuestion(
                "choice",
                DecisionKind.CHOICE,
                "Which?",
                ("a", "b"),
            ),
        ),
    )
    backend = TypeSafeDecisionBackend(
        api_key="key",
        post_json=lambda *_args: {
            "model": "jev",
            "answers": {
                "choice": {
                    "type": "choice",
                    "choice": 1,
                    "probabilities": {"a": 0.5, "b": 0.5},
                    "confidence": 0.5,
                }
            },
        },
    )
    with pytest.raises(DecisionModelInvalidResponse):
        backend.evaluate(choice)
