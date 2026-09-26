"""Provider-neutral contracts for optional bounded semantic judgment.

Decision models are optimization-only capabilities. They never own canonical
state, Memory, Thread, LCE Baseline acceptance, or action authority.
"""

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


def _text(value: str, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return value.strip()


@dataclass(frozen=True, slots=True)
class DecisionQuestion:
    question_id: str
    kind: DecisionKind
    instructions: str
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question_id",
            _text(self.question_id, "question_id", maximum=128),
        )
        if not isinstance(self.kind, DecisionKind):
            raise TypeError("kind must be DecisionKind")
        object.__setattr__(
            self,
            "instructions",
            _text(self.instructions, "instructions", maximum=4096),
        )
        if not isinstance(self.options, tuple):
            raise TypeError("options must be a tuple")
        normalized = tuple(_text(value, "option", maximum=512) for value in self.options)
        if len(normalized) != len(set(normalized)):
            raise ValueError("options must be unique")
        if self.kind is DecisionKind.BOOLEAN and normalized:
            raise ValueError("BOOLEAN questions do not accept options")
        if self.kind is DecisionKind.CHOICE and not 2 <= len(normalized) <= 255:
            raise ValueError("CHOICE questions require 2..255 options")
        if self.kind is DecisionKind.SCORE and not 2 <= len(normalized) <= 10:
            raise ValueError("SCORE questions require 2..10 ordered levels")
        object.__setattr__(self, "options", normalized)


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    feature: str
    projection_version: str
    state: Mapping[str, str]
    questions: tuple[DecisionQuestion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature", _text(self.feature, "feature", maximum=128))
        object.__setattr__(
            self,
            "projection_version",
            _text(self.projection_version, "projection_version", maximum=64),
        )
        if not isinstance(self.state, Mapping):
            raise TypeError("state must be a mapping")
        if not 1 <= len(self.state) <= 256:
            raise ValueError("state must contain 1..256 entries")
        frozen: dict[str, str] = {}
        total = 0
        for key, value in self.state.items():
            clean_key = _text(key, "state key", maximum=128)
            clean_value = _text(value, f"state[{clean_key}]", maximum=8192)
            total += len(clean_key) + len(clean_value)
            frozen[clean_key] = clean_value
        if total > 65536:
            raise ValueError("state exceeds 65536 characters")
        object.__setattr__(self, "state", MappingProxyType(frozen))
        if not isinstance(self.questions, tuple) or not self.questions:
            raise ValueError("questions must be a nonempty tuple")
        if len(self.questions) > 256:
            raise ValueError("questions exceeds 256 entries")
        if any(not isinstance(question, DecisionQuestion) for question in self.questions):
            raise TypeError("questions must contain DecisionQuestion values")
        ids = tuple(question.question_id for question in self.questions)
        if len(ids) != len(set(ids)):
            raise ValueError("question_id values must be unique")

    @property
    def fingerprint(self) -> str:
        payload = {
            "feature": self.feature,
            "projection_version": self.projection_version,
            "state": dict(self.state),
            "questions": [
                {
                    "id": question.question_id,
                    "kind": question.kind.value,
                    "instructions": question.instructions,
                    "options": question.options,
                }
                for question in self.questions
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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
            self,
            "question_id",
            _text(self.question_id, "question_id", maximum=128),
        )
        if not isinstance(self.kind, DecisionKind):
            raise TypeError("kind must be DecisionKind")
        if not isinstance(self.probabilities, Mapping) or not self.probabilities:
            raise ValueError("probabilities must be a nonempty mapping")
        frozen: dict[str, float] = {}
        for key, raw in self.probabilities.items():
            clean_key = _text(key, "probability key", maximum=512)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise TypeError("probabilities must be numeric")
            value = float(raw)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("probabilities must be finite values in [0, 1]")
            frozen[clean_key] = value
        object.__setattr__(self, "probabilities", MappingProxyType(frozen))
        if self.selected is not None and self.selected not in frozen:
            raise ValueError("selected must name one probability option")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not isfinite(float(self.score))
        ):
            raise ValueError("score must be finite when supplied")
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be in [0, 1] when supplied")

    def probability(self, option: str) -> float:
        return self.probabilities.get(option, 0.0)

    @property
    def yes_probability(self) -> float:
        if self.kind is not DecisionKind.BOOLEAN:
            raise TypeError("yes_probability is only valid for BOOLEAN answers")
        return self.probability("true")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    backend: str
    model_version: str
    answers: tuple[DecisionAnswer, ...]
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend", _text(self.backend, "backend", maximum=128))
        object.__setattr__(
            self,
            "model_version",
            _text(self.model_version, "model_version", maximum=128),
        )
        if not isinstance(self.answers, tuple) or not self.answers:
            raise ValueError("answers must be a nonempty tuple")
        if any(not isinstance(answer, DecisionAnswer) for answer in self.answers):
            raise TypeError("answers must contain DecisionAnswer values")
        ids = tuple(answer.question_id for answer in self.answers)
        if len(ids) != len(set(ids)):
            raise ValueError("answer question_id values must be unique")
        for value, name in (
            (self.input_tokens, "input_tokens"),
            (self.output_tokens, "output_tokens"),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer when supplied")

    def answer(self, question_id: str) -> DecisionAnswer:
        for answer in self.answers:
            if answer.question_id == question_id:
                return answer
        raise KeyError(question_id)
