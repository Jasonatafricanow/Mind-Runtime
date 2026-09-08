"""Deployment-time runtime behavior configuration (C6B-Config).

Configuration is a separate concern from Persona/Affect dimensions.
This module loads typed runtime behavior config files (e.g.
configs/runtime/kayla.json) and produces the frozen
CognitiveTickConfig that governs proactive tick behavior.

Design principles:
- Generic loader: no Kayla-specific function names
- Fail-closed validation: invalid values are refused, not coerced
- No production defaults from config: missing/None means feature off
- Config location is deployment choice (not kernel assumption)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mind_runtime.cognition.tick import CognitiveTickConfig


@dataclass(frozen=True)
class ProactiveRuntimeConfig:
    """Typed proactive runtime behavior settings."""

    photo_cadence_threshold: int | None = None

    def __post_init__(self) -> None:
        threshold = self.photo_cadence_threshold
        if threshold is not None:
            if isinstance(threshold, bool) or not isinstance(threshold, int):
                raise ValueError("photo_cadence_threshold must be a positive integer or null")
            if threshold < 1:
                raise ValueError("photo_cadence_threshold must be >= 1")


@dataclass(frozen=True)
class RuntimeBehaviorConfig:
    """Deployment-specific runtime behavior, not persona-affect."""

    proactive: ProactiveRuntimeConfig

    @classmethod
    def from_json(cls, data: dict[str, object]) -> RuntimeBehaviorConfig:
        """Construct from already-parsed JSON dict."""
        if not isinstance(data, dict):
            raise ValueError("runtime behavior config must be a JSON object")
        proactive_raw = data.get("proactive", {})
        if not isinstance(proactive_raw, dict):
            raise ValueError("proactive must be an object")
        return cls(
            proactive=ProactiveRuntimeConfig(
                photo_cadence_threshold=proactive_raw.get("photo_cadence_threshold"),
            ),
        )

    def to_cognitive_tick_config(self) -> CognitiveTickConfig:
        """Translate into CognitiveTicker's required configuration."""
        return CognitiveTickConfig(
            photo_cadence_threshold=self.proactive.photo_cadence_threshold,
        )


class RuntimeBehaviorLoadError(RuntimeError):
    """Fail-closed runtime behavior config loading failure."""


def load_runtime_behavior(path: str | Path) -> RuntimeBehaviorConfig:
    """Load and validate one runtime behavior config file.

    Args:
        path: Path to a JSON file with the runtime behavior structure.

    Returns:
        A validated RuntimeBehaviorConfig.

    Raises:
        RuntimeBehaviorLoadError: file not found, invalid JSON, or structure error.
    """
    file = Path(path)
    if not file.is_file():
        raise RuntimeBehaviorLoadError(f"runtime behavior config not found: {file}")

    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeBehaviorLoadError(f"cannot read runtime behavior config: {exc}") from exc

    try:
        return RuntimeBehaviorConfig.from_json(raw)
    except ValueError as exc:
        raise RuntimeBehaviorLoadError(str(exc)) from exc


def default_runtime_behavior_path() -> Path:
    """Default path for the production Kayla runtime behavior config."""
    return Path(__file__).resolve().parents[2] / "configs" / "runtime" / "kayla.json"