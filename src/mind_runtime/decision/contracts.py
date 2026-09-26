"""Provider-neutral contracts for optional bounded semantic judgment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType


class DecisionKind(StrEnum):
    BOOLEAN = "boolean"
    CHOICE = "choice"
    SCORE = "score"


def _required_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} characters")
    return value.strip()


@dataclass(frozen=True, slots=True)
class DecisionQuestion:
    question_id: str
    kind: DecisionKind
    instructions: str
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "question_id", _required_text(self.question_id, "question_id", 128)
        )
        object.__setattr__(
            self, "instructions", _required_text(self.instructions, "instructions", 4096)
        )
        if not isinstance(self.kind, DecisionKind):
            raise TypeError("kind must be DecisionKind")
        if not isinstance(self.options, tuple):
            raise TypeError("options must be a tuple")
        options = tuple(_required_text(value, "option", 512) for value in self.options)
        if len(options) != len(set(options)):
            raise ValueError("options must be unique")
        if self.kind is DecisionKind.BOOLEAN:
            if options:
                raise ValueError("BOOLEAN questions do not accept options")
        else:
            maximum = 255 if self.kind is DecisionKind.CHOICE else 10
            if not 2 <= len(options) <= maximum:
                raise ValueError(f"{self.kind.value} requires 2..{maximum} options")
        object.__setattr__(self, "options", options)


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    feature: str
    projection_version: str
    state: Mapping[str, str]
    questions: tuple[DecisionQuestion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature", _required_text(self.feature, "feature", 128))
        object.__setattr__(
            self,
            "projection_version",
            _required_text(self.projection_version, "projection_version", 64),
        )
        if not isinstance(self.state, Mapping) or not 1 <= len(self.state) <= 256:
            raise ValueError("state must be a mapping with 1..256 entries")
        frozen = {
            _required_text(key, "state key", 128): _required_text(
                value, "state value", 8192
            )
            for key, value in self.state.items()
        }
        if sum(len(key) + len(value) for key, value in frozen.items()) > 65536:
            raise ValueError("state exceeds 65536 characters")
        if (
            not isinstance(self.questions, tuple)
            or not 1 <= len(self.questions) <= 256
            or any(not isinstance(item, DecisionQuestion) for item in self.questions)
        ):
            raise ValueError("questions must contain 1..256 DecisionQuestion values")
        ids = tuple(item.question_id for item in self.questions)
        if len(ids) != len(set(ids)):
            raise ValueError("question_id values must be unique")
        object.__setattr__(self, "state", MappingProxyType(frozen))

    @property
    def fingerprint(self) -> str:
        payload = {
            "feature": self.feature,
            "projection_version": self.projection_version,
            "state": dict(self.state),
            "questions": [
                (item.question_id, item.kind.value, item.instructions, item.options)
                for item in self.questions
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()


def _probabilities(values: Mapping[str, float]) -> MappingProxyType[str, float]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError("probabilities must be a nonempty mapping")
    normalized: dict[str, float] = {}
    for key, raw in values.items():
        key = _required_text(key, "probability key", 512)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("probabilities must be numeric")
        value = float(raw)
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("probabilities must be finite values in [0, 1]")
        normalized[key] = value
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class DecisionAnswer:
    question_id: str
    kind: DecisionKind
    probabilities: Mapping[str, float]
    selected: str | None = None
    score: float | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "question_id", _required_text(self.question_id, "question_id", 128)
        )
        if not isinstance(self.kind, DecisionKind):
            raise TypeError("kind must be DecisionKind")
        probabilities = _probabilities(self.probabilities)
        object.__setattr__(self, "probabilities", probabilities)
        if self.selected is not None and self.selected not in probabilities:
            raise ValueError("selected must name one probability option")
        for value, name in ((self.score, "score"), (self.confidence, "confidence")):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
            ):
                raise ValueError(f"{name} must be finite when supplied")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def probability(self, option: str) -> float:
        return self.probabilities.get(option, 0.0)

    @property
    def yes_probability(self) -> float:
        if self.kind is not DecisionKind.BOOLEAN:
            raise TypeError("yes_probability requires a BOOLEAN answer")
        return self.probability("true")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    backend: str
    model_version: str
    answers: tuple[DecisionAnswer, ...]
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend", _required_text(self.backend, "backend", 128))
        object.__setattr__(
            self, "model_version", _required_text(self.model_version, "model_version", 128)
        )
        if not self.answers or any(
            not isinstance(answer, DecisionAnswer) for answer in self.answers
        ):
            raise ValueError("answers must be a nonempty DecisionAnswer tuple")
        if len({answer.question_id for answer in self.answers}) != len(self.answers):
            raise ValueError("answer question_id values must be unique")
        for value in (self.input_tokens, self.output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("token counts must be nonnegative integers")

    def answer(self, question_id: str) -> DecisionAnswer:
        for answer in self.answers:
            if answer.question_id == question_id:
                return answer
        raise KeyError(question_id)
