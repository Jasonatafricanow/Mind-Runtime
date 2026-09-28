"""Narrow proactive cognition material contract.

The contract intentionally exposes only an opaque handle plus self-contained
content. Discovery kind, Line topology, provenance and confidence remain behind
the cognition boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.contracts.common import require_non_empty


@dataclass(frozen=True, slots=True)
class InspirationMaterial:
    """One downstream-consumable proactive cognition material."""

    material_id: str
    content: str

    def __post_init__(self) -> None:
        require_non_empty(self.material_id, "material_id")
        require_non_empty(self.content, "content")
