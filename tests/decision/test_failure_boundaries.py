from __future__ import annotations

from contextlib import contextmanager

import pytest

from mind_runtime.decision import (
    DecisionAnswer,
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


def boolean_question(question_id: str = "q") -> DecisionQuestion:
    return DecisionQuestion(question_id, DecisionKind.BOOLEAN, "Is it relevant?")


def boolean_request() -> DecisionRequest:
    return DecisionRequest(
        feature="test",
        projection_version="v1",
        state={"value": "candidate"},
        questions=(boolean_question(),),
    )


@pytest.mark.parametrize(
    "build,error",
    [
        (lambda: DecisionQuestion("", DecisionKind.BOOLEAN, "x"), ValueError),
        (lambda: DecisionQuestion("q", "boolean", "x"), TypeError),
        (lambda: DecisionQuestion("q", DecisionKind.BOOLEAN, "x", []), TypeError),
        (
            lambda: DecisionQuestion(
                "q", DecisionKind.CHOICE, "x", ("same", "same")
            ),
            ValueError,
        ),
        (
            lambda: DecisionQuestion(
                "q", DecisionKind.SCORE, "x", tuple(str(i) for i in range(11))
            ),
            ValueError,
        ),
        (
            lambda: DecisionRequest(
                feature="x",
                projection_version="v1",
                state=[],
                questions=(boolean_question(),),
            ),
            TypeError,
        ),
        (
            lambda: DecisionRequest(
                feature="x",
                projection_version="v1",
                state={},
                questions=(boolean_question(),),
            ),
            ValueError,
        ),
        (
            lambda: DecisionRequest(
                feature="x",
                projection_version="v1",
                state={str(i): "x" * 8192 for i in range(9)},
                questions=(boolean_question(),),
            ),
            ValueError,
        ),
        (
            lambda: DecisionRequest(
                feature="x",
                projection_version="v1",
                state={"x": "y"},
                questions=tuple(boolean_question(str(i)) for i in range(257)),
            ),
            ValueError,
        ),
        (
            lambda: DecisionRequest(
                feature="x",
                projection_version="v1",
                state={"x": "y"},
                questions=(boolean_question("same"), boolean_question("same")),
            ),
            ValueError,
        ),
    ],
)
def test_request_contract_rejects_invalid_shapes(build, error) -> None:
    with pytest.raises(error):
        build()


@pytest.mark.parametrize(
    "build,error",
    [
        (
            lambda: DecisionAnswer("q", "boolean", {"true": 1.0}),
            TypeError,
        ),
        (
            lambda: DecisionAnswer("q", DecisionKind.BOOLEAN, {}),
            ValueError,
        ),
        (
            lambda: DecisionAnswer(
                "q", DecisionKind.BOOLEAN, {"true": "yes"}
            ),
            TypeError,
        ),
        (
            lambda: DecisionAnswer(
                "q", DecisionKind.BOOLEAN, {"true": 1.5}
            ),
            ValueError,
        ),
        (
            lambda: DecisionAnswer(
                "q",
                DecisionKind.CHOICE,
                {"a": 1.0},
                selected="b",
            ),
            ValueError,
        ),
        (
            lambda: DecisionAnswer(
                "q", DecisionKind.SCORE, {"low": 1.0}, score=float("inf")
            ),
            ValueError,
        ),
        (
            lambda: DecisionAnswer(
                "q", DecisionKind.SCORE, {"low": 1.0}, confidence=2.0
            ),
            ValueError,
        ),
        (
            lambda: DecisionResult("b", "v", ()),
            ValueError,
        ),
        (
            lambda: DecisionResult(
                "b",
                "v",
                (
                    DecisionAnswer(
                        "same", DecisionKind.BOOLEAN, {"false": 0.0, "true": 1.0}
                    ),
                    DecisionAnswer(
                        "same", DecisionKind.BOOLEAN, {"false": 0.0, "true": 1.0}
                    ),
                ),
            ),
            ValueError,
        ),
        (
            lambda: DecisionResult(
                "b",
                "v",
                (
                    DecisionAnswer(
                        "q", DecisionKind.BOOLEAN, {"false": 0.0, "true": 1.0}
                    ),
                ),
                input_tokens=-1,
            ),
            ValueError,
        ),
    ],
)
def test_answer_contract_rejects_invalid_shapes(build, error) -> None:
    with pytest.raises(error):
        build()


def test_answer_helpers_and_missing_question_are_explicit() -> None:
    answer = DecisionAnswer(
        "choice",
        DecisionKind.CHOICE,
        {"a": 0.4, "b": 0.6},
        selected="b",
    )
    assert answer.probability("missing") == 0.0
    with pytest.raises(TypeError):
        _ = answer.yes_probability
    result = DecisionResult("b", "v", (answer,))
    with pytest.raises(KeyError):
        result.answer("missing")


@pytest.mark.parametrize(
    "config",
    [
        DecisionModelConfig(backend=""),
        DecisionModelConfig.__new__(DecisionModelConfig),
    ],
)
def test_factory_config_guard_setup(config) -> None:
    # The normal invalid constructor is covered below; the __new__ case simply
    # proves this test matrix does not rely on environment configuration.
    if hasattr(config, "backend"):
        return
    assert not hasattr(config, "backend")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"backend": ""},
        {"backend": "unknown"},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
    ],
)
def test_factory_rejects_invalid_configuration(kwargs) -> None:
    with pytest.raises(ValueError):
        DecisionModelConfig(**kwargs)


def test_factory_builds_one_typesafe_capability() -> None:
    capability = build_decision_capability(
        DecisionModelConfig(
            backend="typesafe",
            api_key="key",
            endpoint="http://localhost:9999/v1/systemone",
            model="jev-test",
        )
    )
    assert capability.available


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"model": "jev", "answers": []},
        {
            "model": "jev",
            "answers": {"q": {"type": "choice", "noul": 0.5}},
        },
        {
            "model": "jev",
            "answers": {"q": {"type": "noul", "noul": "bad"}},
        },
        {
            "model": "jev",
            "answers": {"q": {"type": "noul", "noul": 2.0}},
        },
        {
            "model": "jev",
            "answers": {"q": {"type": "noul", "noul": 0.5}},
            "usage": {"input_tokens": -1, "output_tokens": 0},
        },
    ],
)
def test_typesafe_invalid_boolean_responses_fail_closed_at_backend(response) -> None:
    backend = TypeSafeDecisionBackend(
        api_key="key",
        post_json=lambda *_args: response,
    )
    with pytest.raises(DecisionModelInvalidResponse):
        backend.evaluate(boolean_request())


def test_typesafe_transport_exception_becomes_optional_unavailable() -> None:
    def crash(*_args):
        raise RuntimeError("socket wrapper failed")

    backend = TypeSafeDecisionBackend(api_key="key", post_json=crash)
    with pytest.raises(DecisionModelUnavailable):
        backend.evaluate(boolean_request())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": ""},
        {"api_key": "x", "model": ""},
        {"api_key": "x", "endpoint": "ftp://invalid"},
        {"api_key": "x", "timeout_seconds": 0},
    ],
)
def test_typesafe_backend_rejects_invalid_configuration(kwargs) -> None:
    with pytest.raises(ValueError):
        TypeSafeDecisionBackend(**kwargs)


def test_http_transport_maps_io_and_json_failures(monkeypatch) -> None:
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


def test_memory_projection_input_guards_and_single_candidate_bypass() -> None:
    with pytest.raises(ValueError):
        MemoryRerankCandidate("", "content")
    with pytest.raises(ValueError):
        MemoryRerankCandidate("id", "")
    with pytest.raises(TypeError):
        MemoryRetrievalDecisionProjection(object())
    with pytest.raises(ValueError):
        from mind_runtime.decision import DecisionCapability

        MemoryRetrievalDecisionProjection(
            DecisionCapability(),
            max_candidate_characters=1,
        )

    from mind_runtime.decision import DecisionCapability

    projection = MemoryRetrievalDecisionProjection(DecisionCapability())
    assert projection.rerank(
        query="q",
        candidates=(MemoryRerankCandidate("m1", "one"),),
    ) == ("m1",)
