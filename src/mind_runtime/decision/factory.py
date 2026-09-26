"""Single composition point for the optional parallel decision backend."""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.decision.composition import DecisionCapability
from mind_runtime.decision.telemetry import DecisionTelemetrySink


@dataclass(frozen=True, slots=True)
class DecisionModelConfig:
    backend: str = "none"
    api_key: str | None = None
    endpoint: str | None = None
    model: str | None = None
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        if not isinstance(self.backend, str) or not self.backend.strip():
            raise ValueError("backend must be nonempty")
        normalized = self.backend.strip().casefold()
        if normalized not in {"none", "typesafe"}:
            raise ValueError(f"unsupported decision backend: {self.backend}")
        object.__setattr__(self, "backend", normalized)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < float(self.timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")


def build_decision_capability(
    config: DecisionModelConfig | None = None,
    *,
    telemetry: DecisionTelemetrySink | None = None,
) -> DecisionCapability:
    chosen = config or DecisionModelConfig()
    if chosen.backend == "none":
        return DecisionCapability(telemetry=telemetry)
    if chosen.api_key is None or not chosen.api_key.strip():
        raise ValueError("typesafe decision backend requires api_key")

    # Keep concrete providers outside the default MR import graph.
    from mind_runtime.decision.backends.typesafe import (
        DEFAULT_TYPESAFE_ENDPOINT,
        TypeSafeDecisionBackend,
    )

    backend = TypeSafeDecisionBackend(
        api_key=chosen.api_key,
        endpoint=chosen.endpoint or DEFAULT_TYPESAFE_ENDPOINT,
        model=chosen.model or "jev-1.13.0",
        timeout_seconds=chosen.timeout_seconds,
    )
    return DecisionCapability(backend, telemetry=telemetry)
