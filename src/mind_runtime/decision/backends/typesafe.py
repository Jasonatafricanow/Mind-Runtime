"""TypeSafe System One backend for the generic DecisionModelPort.

The integration uses the HTTP API directly so MR does not require the TypeSafe
SDK at import time. The backend is optional and all transport or response
failures are translated into DecisionModelError subclasses for fail-open
composition.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mind_runtime.decision.contracts import (
    DecisionAnswer,
    DecisionKind,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.decision.port import (
    DecisionModelInvalidResponse,
    DecisionModelUnavailable,
)

DEFAULT_TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JsonPost(Protocol):
    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]: ...


def _http_post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> Mapping[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DecisionModelUnavailable("TypeSafe System One request failed") from exc
    try:
        decoded: object = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise DecisionModelInvalidResponse("TypeSafe response was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise DecisionModelInvalidResponse("TypeSafe response must be a JSON object")
    return cast(dict[str, object], decoded)


def _question_payload(question: DecisionQuestion) -> dict[str, object]:
    if question.kind is DecisionKind.BOOLEAN:
        return {
            "type": "noul",
            "instructions": question.instructions,
        }
    if question.kind is DecisionKind.CHOICE:
        return {
            "type": "choice",
            "instructions": question.instructions,
            "criteria": {option: None for option in question.options},
        }
    return {
        "type": "score",
        "instructions": question.instructions,
        "criteria": list(question.options),
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DecisionModelInvalidResponse(f"{name} must be an object")
    for key in value:
        if not isinstance(key, str):
            raise DecisionModelInvalidResponse(f"{name} keys must be strings")
    return cast(Mapping[str, object], value)


def _probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionModelInvalidResponse(f"{name} must be numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise DecisionModelInvalidResponse(f"{name} must be in [0, 1]")
    return result


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionModelInvalidResponse(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise DecisionModelInvalidResponse(f"{name} must be finite")
    return result


def _usage(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise DecisionModelInvalidResponse(f"{name} must be a nonnegative integer")
    return value


class TypeSafeDecisionBackend:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "jev-1.13.0",
        endpoint: str = DEFAULT_TYPESAFE_ENDPOINT,
        timeout_seconds: float = 8.0,
        post_json: JsonPost | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be nonempty")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be nonempty")
        if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://")):
            raise ValueError("endpoint must be an http(s) URL")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._endpoint = endpoint
        self._timeout = float(timeout_seconds)
        self._post_json = post_json or _http_post_json

    @property
    def backend_name(self) -> str:
        return "typesafe"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        payload: dict[str, object] = {
            "state": dict(request.state),
            "model": self._model,
            "questions": {
                question.question_id: _question_payload(question)
                for question in request.questions
            },
        }
        try:
            response = self._post_json(
                self._endpoint,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                payload,
                self._timeout,
            )
        except DecisionModelUnavailable:
            raise
        except DecisionModelInvalidResponse:
            raise
        except Exception as exc:
            raise DecisionModelUnavailable("TypeSafe transport failed") from exc

        model = response.get("model")
        if not isinstance(model, str) or not model.strip():
            raise DecisionModelInvalidResponse("TypeSafe response is missing model")
        raw_answers = _mapping(response.get("answers"), "answers")
        answers: list[DecisionAnswer] = []
        for question in request.questions:
            raw = _mapping(raw_answers.get(question.question_id), question.question_id)
            raw_type = raw.get("type")
            if question.kind is DecisionKind.BOOLEAN:
                if raw_type != "noul":
                    raise DecisionModelInvalidResponse("Noul answer type mismatch")
                yes = _probability(raw.get("noul"), f"{question.question_id}.noul")
                answers.append(
                    DecisionAnswer(
                        question_id=question.question_id,
                        kind=question.kind,
                        probabilities={"false": 1.0 - yes, "true": yes},
                        selected="true" if yes >= 0.5 else "false",
                    )
                )
                continue

            if question.kind is DecisionKind.CHOICE:
                if raw_type != "choice":
                    raise DecisionModelInvalidResponse("Choice answer type mismatch")
                raw_probabilities = _mapping(
                    raw.get("probabilities"),
                    f"{question.question_id}.probabilities",
                )
                probabilities = {
                    option: _probability(
                        raw_probabilities.get(option),
                        f"{question.question_id}.probabilities[{option}]",
                    )
                    for option in question.options
                }
                selected = raw.get("choice")
                if not isinstance(selected, str):
                    raise DecisionModelInvalidResponse("Choice answer is missing selected option")
                confidence = _probability(
                    raw.get("confidence"),
                    f"{question.question_id}.confidence",
                )
                answers.append(
                    DecisionAnswer(
                        question_id=question.question_id,
                        kind=question.kind,
                        probabilities=probabilities,
                        selected=selected,
                        confidence=confidence,
                    )
                )
                continue

            if raw_type != "score":
                raise DecisionModelInvalidResponse("Score answer type mismatch")
            raw_probabilities = _mapping(
                raw.get("probabilities"),
                f"{question.question_id}.probabilities",
            )
            probabilities = {
                level: _probability(
                    raw_probabilities.get(str(index)),
                    f"{question.question_id}.probabilities[{index}]",
                )
                for index, level in enumerate(question.options)
            }
            confidence = _probability(
                raw.get("confidence"),
                f"{question.question_id}.confidence",
            )
            score = _finite_number(raw.get("score"), f"{question.question_id}.score")
            answers.append(
                DecisionAnswer(
                    question_id=question.question_id,
                    kind=question.kind,
                    probabilities=probabilities,
                    score=score,
                    confidence=confidence,
                )
            )

        usage = response.get("usage")
        input_tokens: int | None = None
        output_tokens: int | None = None
        if usage is not None:
            usage_map = _mapping(usage, "usage")
            input_tokens = _usage(usage_map.get("input_tokens"), "usage.input_tokens")
            output_tokens = _usage(usage_map.get("output_tokens"), "usage.output_tokens")
        return DecisionResult(
            backend=self.backend_name,
            model_version=model,
            answers=tuple(answers),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
