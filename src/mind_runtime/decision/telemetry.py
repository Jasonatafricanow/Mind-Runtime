"""Uniform observability for optional decision-model calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class DecisionCallStatus(StrEnum):
    SUCCESS = "success"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    feature: str
    projection_version: str
    request_fingerprint: str
    status: DecisionCallStatus
    backend: str | None
    model_version: str | None
    latency_ms: float
    error_type: str | None = None


@runtime_checkable
class DecisionTelemetrySink(Protocol):
    def record(self, trace: DecisionTrace) -> None: ...


class NullDecisionTelemetry:
    def record(self, trace: DecisionTrace) -> None:
        del trace


class InMemoryDecisionTelemetry:
    def __init__(self) -> None:
        self.traces: list[DecisionTrace] = []

    def record(self, trace: DecisionTrace) -> None:
        self.traces.append(trace)
