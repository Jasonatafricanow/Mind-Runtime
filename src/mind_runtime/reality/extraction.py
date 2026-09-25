"""Bounded raw user-text extraction for MR Reality/Input.

Adapted from StateBar-MCP ``FastOverlayExtractor`` and its deterministic
structured-output validator.  The adapted layer returns proposals; it never
owns canonical state, persistence, lifecycle, or authority.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from mind_runtime.contracts import Evidence, Observation
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    FactIngestPort,
    RealityAdmissionPort,
    RealityAdmissionRequest,
)
from mind_runtime.reality.temporal import normalize_temporal

_logger = logging.getLogger(__name__)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_REALITY_SYSTEM_PROMPT = """You extract only facts the user stated about their current reality.
Return JSON array only. Each item must contain type, key, value, certainty,
time_expression, and confidence. Never infer facts from an assistant message.
Allowed types: plan, activity, symptom, sleep, awake, resolve.
For terminal plan operations, key must be the concrete plan dimension and value
must be cancelled, completed, or resolved; never choose a target from omitted
context.
Use stable lowercase English keys and confidence between 0 and 1.
"""


_TYPES = frozenset({"plan", "activity", "symptom", "sleep", "awake", "resolve"})
_CERTAINTIES = frozenset({"confirmed", "planned", "tentative", "estimated", "inferred"})
_TIME_EXPRESSIONS = frozenset(
    {"morning", "afternoon", "evening", "tonight", "now", "today", "tomorrow", "unspecified"}
)
_SLUG_RE = re.compile(r"[^a-z0-9_]+")
_KNOWN_KEYS = {
    "书法": "calligraphy",
    "写字": "calligraphy",
    "游泳": "swimming",
    "跑步": "running",
    "健身": "gym",
    "锻炼": "exercise",
    "吃药": "medication",
    "胃": "stomach_pain",
    "胃疼": "stomach_pain",
    "头疼": "headache",
    "头痛": "headache",
    "睡觉": "sleep",
}


@dataclass(frozen=True, slots=True)
class RealityCandidate:
    """Validated, bounded proposal before MR factual admission."""

    kind: str
    key: str
    value: str
    confidence: float
    certainty: str
    time_expression: str
    source_text: str
    lifecycle: str | None = None

    @property
    def dimension(self) -> str:
        if self.kind in {"sleep", "awake"}:
            return "user.sleep.phase"
        if self.kind == "symptom" or self.kind == "resolve":
            return f"user.health.{self.key}"
        if self.kind == "activity":
            return f"user.activity.{self.key}"
        return f"user.plan.{self.key}"

    @property
    def observation_key(self) -> str:
        suffix = self.lifecycle or "observed"
        return f"{self.dimension}.{suffix}"


@runtime_checkable
class PersistentRealityExtractor(Protocol):
    """Optional provider seam; implementations return JSON-like proposals."""

    def extract(self, text: str) -> object:
        ...


class OpenAICompatRealityExtractor:
    """Optional OpenAI-compatible structured reality extractor.

    It is inert unless explicitly constructed by ``build_reality_input``
    with an operator opt-in and complete endpoint/model configuration.
    Provider failures degrade to the deterministic fast path.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def extract(self, text: str) -> object:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _REALITY_SYSTEM_PROMPT},
                {"role": "user", "content": f"User message: {text}\n\nJSON array only:"},
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            content = response_payload["choices"][0]["message"]["content"]
            text_payload = str(content).strip()
            fence = re.search(r"```(?:json)?\s*(.*?)```", text_payload, re.DOTALL)
            if fence:
                text_payload = fence.group(1).strip()
            if not text_payload.startswith("["):
                start, end = text_payload.find("["), text_payload.rfind("]")
                if start < 0 or end <= start:
                    return ()
                text_payload = text_payload[start : end + 1]
            return json.loads(text_payload)
        except (
            urllib.error.URLError,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            _logger.warning("reality structured extraction unavailable: %s", type(exc).__name__)
            return ()


def build_reality_input() -> RealityInputService:
    """Build the production seam with explicit-off degradation semantics."""
    enabled = os.environ.get("MR_REALITY_LLM_ENABLED", "").strip().lower() in _TRUE_VALUES
    base_url = os.environ.get("MR_REALITY_LLM_BASE_URL", "").strip()
    model = os.environ.get("MR_REALITY_LLM_MODEL", "").strip()
    api_key = os.environ.get("MR_REALITY_LLM_API_KEY", "")
    if not enabled or not base_url or not model:
        return RealityInputService()
    try:
        timeout = float(os.environ.get("MR_REALITY_LLM_TIMEOUT", "30"))
    except ValueError:
        timeout = 30.0
    return RealityInputService(
        persistent=OpenAICompatRealityExtractor(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
        )
    )


def _normalize_key(raw: object, kind: str) -> str:
    text = str(raw or "").strip()
    if text in _KNOWN_KEYS:
        return _KNOWN_KEYS[text]
    slug = _SLUG_RE.sub("_", text.lower()).strip("_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", slug or ""):
        return ""
    return slug


def validate_reality_payload(payload: object, *, source_text: str) -> tuple[RealityCandidate, ...]:
    """Convert structured provider output into fail-closed MR proposals."""
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        return ()
    candidates: list[RealityCandidate] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("type", "")).strip().lower()
        if kind not in _TYPES:
            continue
        certainty = str(raw.get("certainty", "confirmed")).strip().lower()
        time_expression = str(raw.get("time_expression", "unspecified")).strip().lower()
        if certainty not in _CERTAINTIES or time_expression not in _TIME_EXPRESSIONS:
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            continue
        key = _normalize_key(raw.get("key", ""), kind)
        if kind in {"sleep", "awake"}:
            key = "phase"
        if kind not in {"sleep", "awake"} and not key:
            continue
        value = str(raw.get("value", "")).strip()
        if kind == "awake":
            value = "awake"
        elif kind == "sleep" and not value:
            value = "sleeping"
        elif not value:
            continue
        lifecycle = None
        if kind == "resolve":
            lifecycle = "resolved"
        elif kind == "activity" and value.lower() in {"completed", "done"}:
            lifecycle = "completed"
        elif kind == "plan" and value.lower() in {"cancelled", "cancel"}:
            lifecycle = "cancelled"
        return_value = RealityCandidate(
            kind=kind,
            key=key,
            value=value,
            confidence=confidence,
            certainty=certainty,
            time_expression=time_expression,
            source_text=source_text,
            lifecycle=lifecycle,
        )
        candidates.append(return_value)
    return tuple(candidates)


class FastRealityExtractor:
    """Synchronous, deterministic high-confidence overlay rules."""

    _AWAKE = re.compile(r"刚睡醒|刚醒(?:了|过来)?|睡醒了|刚起床|一觉醒来")
    _SLEEP = re.compile(r"准备睡(?:觉)?|要睡(?:觉)?了|去睡(?:觉)?了|困了.{0,6}睡")
    _POOR_SLEEP = re.compile(r"昨(?:晚|天晚上|夜)(?:没睡好|失眠|睡得不好)")
    _SYMPTOM = re.compile(
        r"(胃|肚子|头|嗓子|喉咙|牙|腰|背|腿|脚|手|膝盖)(?:有点|有些|很)?(?:疼|痛|不舒服|难受)"
    )
    _RESOLVE = re.compile(
        r"(胃|肚子|头|嗓子|喉咙|牙|腰|背|腿|脚|手|膝盖)(?:有点)?(?:不疼了|不痛了|好了|好多了|不难受了)"
    )
    _MEDICATION = re.compile(r"吃(?:了点?|过|完)?药(?:了)?|刚(?:才)?吃药|服药了")
    _TERMINAL_PLAN = re.compile(
        r"(书法|写字|游泳|跑步|健身|锻炼)(?:计划)?(?:我)?(?:不去了|不去|取消了|取消)"
    )

    def extract(self, text: str) -> tuple[RealityCandidate, ...]:
        if not text.strip():
            return ()
        found: list[RealityCandidate] = []
        remaining = text

        poor_sleep = self._POOR_SLEEP.search(remaining)
        if poor_sleep:
            found.append(
                RealityCandidate(
                    "sleep", "phase", "poor_sleep", 1.0, "confirmed", "yesterday_night", text
                )
            )
            remaining = self._mask(remaining, poor_sleep.span())

        awake = self._AWAKE.search(remaining)
        if awake:
            found.append(
                RealityCandidate("awake", "phase", "awake", 1.0, "confirmed", "now", text)
            )
            remaining = self._mask(remaining, awake.span())

        sleep = self._SLEEP.search(remaining)
        if sleep:
            found.append(
                RealityCandidate(
                    "sleep", "phase", "preparing_sleep", 1.0, "confirmed", "now", text
                )
            )
            remaining = self._mask(remaining, sleep.span())

        terminal_plan = self._TERMINAL_PLAN.search(remaining)
        if terminal_plan:
            found.append(
                RealityCandidate(
                    "plan",
                    _KNOWN_KEYS[terminal_plan.group(1)],
                    "cancelled",
                    1.0,
                    "confirmed",
                    "now",
                    text,
                    "cancelled",
                )
            )
            remaining = self._mask(remaining, terminal_plan.span())

        resolved = self._RESOLVE.search(remaining)
        if resolved:
            found.append(
                RealityCandidate(
                    "resolve",
                    self._symptom_key(resolved.group(1)),
                    "resolved",
                    1.0,
                    "confirmed",
                    "now",
                    text,
                    "resolved",
                )
            )
            remaining = self._mask(remaining, resolved.span())

        symptom = self._SYMPTOM.search(remaining)
        if symptom:
            found.append(
                RealityCandidate(
                    "symptom",
                    self._symptom_key(symptom.group(1)),
                    "active",
                    1.0,
                    "confirmed",
                    "now",
                    text,
                )
            )
            remaining = self._mask(remaining, symptom.span())

        medication = self._MEDICATION.search(remaining)
        if medication:
            found.append(
                RealityCandidate(
                    "activity", "medication", "taken", 1.0, "confirmed", "today", text
                )
            )
        return tuple(found)

    @staticmethod
    def _mask(text: str, span: tuple[int, int]) -> str:
        start, end = span
        return text[:start] + " " * (end - start) + text[end:]

    @staticmethod
    def _symptom_key(body: str) -> str:
        return {
            "胃": "stomach_pain",
            "肚子": "abdominal_pain",
            "头": "headache",
            "嗓子": "sore_throat",
            "喉咙": "sore_throat",
            "牙": "toothache",
            "腰": "back_pain",
            "背": "back_pain",
            "腿": "leg_pain",
            "脚": "foot_pain",
            "手": "hand_pain",
            "膝盖": "knee_pain",
        }[body]


class RealityInputService:
    """Extract raw user text and admit typed observations through MR facts."""

    def __init__(
        self,
        *,
        fast: FastRealityExtractor | None = None,
        persistent: PersistentRealityExtractor | None = None,
        default_timezone: ZoneInfo | None = None,
    ) -> None:
        self.fast = fast or FastRealityExtractor()
        self.persistent = persistent
        self.default_timezone = default_timezone

    @property
    def persistent_available(self) -> bool:
        return self.persistent is not None

    def extract_candidates(self, text: str) -> tuple[RealityCandidate, ...]:
        fast = self.fast.extract(text)
        if fast:
            return fast
        if self.persistent is None:
            return ()
        try:
            payload = self.persistent.extract(text)
        except Exception:
            return ()
        return validate_reality_payload(payload, source_text=text)

    def extract_and_admit(
        self,
        evidence: Evidence,
        *,
        reality_admission: RealityAdmissionPort | None = None,
        fact_ingest: FactIngestPort | None = None,
        interaction_id: str | None = None,
        writing_runtime: str | None = None,
        writing_persona_id: str | None = None,
        include_replays: bool = False,
        timezone: ZoneInfo | None = None,
    ) -> tuple[Observation, ...]:
        if evidence.source_type != "user_message":
            return ()
        payload = evidence.payload
        text = payload.get("text") if isinstance(payload, Mapping) else None
        if not isinstance(text, str):
            return ()
        candidates = self.extract_candidates(text)
        admission_port = reality_admission
        if admission_port is None and isinstance(fact_ingest, RealityAdmissionPort):
            admission_port = fact_ingest
        if admission_port is None:
            return ()
        if interaction_id is None or writing_runtime is None:
            raise ValueError("reality admission requires interaction_id and writing_runtime")
        observations: list[Observation] = []
        effective_tz = timezone or self.default_timezone
        for index, candidate in enumerate(candidates):
            temporal = normalize_temporal(
                candidate.source_text,
                anchor=evidence.received_at,
                timezone=effective_tz,
                certainty_hint=candidate.certainty,
                time_expression_hint=candidate.time_expression,
            )
            req = RealityAdmissionRequest(
                source_evidence=evidence,
                interaction_id=interaction_id,
                writing_runtime=writing_runtime,
                writing_persona_id=writing_persona_id,
                observation_id=f"reality-observation-{evidence.id}-{index}",
                key=candidate.observation_key,
                value=candidate.value,
                confidence=candidate.confidence,
                modality=temporal.modality,
                semantic_time=temporal.semantic_time,
                effective_window=temporal.effective_window,
            )
            result = admission_port.admit_reality(req)
            if result.disposition is not FactAdmissionDisposition.REPLAY or include_replays:
                observations.append(result.observation)
        return tuple(observations)


__all__ = [
    "FastRealityExtractor",
    "OpenAICompatRealityExtractor",
    "PersistentRealityExtractor",
    "RealityCandidate",
    "RealityInputService",
    "build_reality_input",
    "validate_reality_payload",
]
