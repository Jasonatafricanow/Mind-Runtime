"""TypeSafe System One backend for the generic DecisionModelPort."""

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
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise DecisionModelUnavailable("TypeSafe request failed") from exc
    if not isinstance(decoded, dict):
        raise DecisionModelInvalidResponse("TypeSafe response must be an object")
    return cast(dict[str, object], decoded)


def _question_payload(question: DecisionQuestion) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "noul" if question.kind is DecisionKind.BOOLEAN else question.kind.value,
        "instructions": question.instructions,
    }
    if question.kind is DecisionKind.CHOICE:
        payload["criteria"] = {option: None for option in question.options}
    elif question.kind is DecisionKind.SCORE:
        payload["criteria"] = list(question.options)
    return payload


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError
    return result


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
        if not api_key.strip() or not model.strip():
            raise ValueError("api_key and model must be nonempty")
        if not endpoint.startswith(("https://", "http://")):
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
                item.question_id: _question_payload(item) for item in request.questions
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
            model = response["model"]
            raw_answers = response["answers"]
            if not isinstance(model, str) or not isinstance(raw_answers, Mapping):
                raise ValueError

            answers = tuple(
                self._answer(question, raw_answers[question.question_id])
                for question in request.questions
            )
            usage = response.get("usage")
            input_tokens = output_tokens = None
            if isinstance(usage, Mapping):
                raw_input, raw_output = usage.get("input_tokens"), usage.get("output_tokens")
                if type(raw_input) is int and raw_input >= 0:
                    input_tokens = raw_input
                if type(raw_output) is int and raw_output >= 0:
                    output_tokens = raw_output
            return DecisionResult(
                backend=self.backend_name,
                model_version=model,
                answers=answers,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except (DecisionModelUnavailable, DecisionModelInvalidResponse):
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionModelInvalidResponse("invalid TypeSafe response") from exc
        except Exception as exc:
            raise DecisionModelUnavailable("TypeSafe transport failed") from exc

    @staticmethod
    def _answer(question: DecisionQuestion, raw: object) -> DecisionAnswer:
        if not isinstance(raw, Mapping):
            raise ValueError
        if question.kind is DecisionKind.BOOLEAN:
            if raw.get("type") != "noul":
                raise ValueError
            yes = _probability(raw.get("noul"))
            return DecisionAnswer(
                question.question_id,
                question.kind,
                {"false": 1.0 - yes, "true": yes},
                selected="true" if yes >= 0.5 else "false",
            )

        if raw.get("type") != question.kind.value:
            raise ValueError
        probabilities = raw.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise ValueError
        if question.kind is DecisionKind.CHOICE:
            mapped = {option: _probability(probabilities.get(option)) for option in question.options}
            selected = raw.get("choice")
            confidence = _probability(raw.get("confidence"))
            if not isinstance(selected, str):
                raise ValueError
            return DecisionAnswer(
                question.question_id,
                question.kind,
                mapped,
                selected=selected,
                confidence=confidence,
            )

        mapped = {
            level: _probability(probabilities.get(str(index)))
            for index, level in enumerate(question.options)
        }
        return DecisionAnswer(
            question.question_id,
            question.kind,
            mapped,
            score=float(raw["score"]),
            confidence=_probability(raw.get("confidence")),
        )
