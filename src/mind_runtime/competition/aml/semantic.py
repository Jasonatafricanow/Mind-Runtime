"""Host-owned semantic seam for the AML adapter.

The competition module may ask a Body/Host implementation for bounded typed
semantic events. MR core never constructs a second online semantic model here.
"""

from __future__ import annotations

from typing import Protocol

from mind_runtime.competition.aml.contracts import AmlMessage
from mind_runtime.contracts import Scope, SemanticEventCandidate
from mind_runtime.memory.product import MemoryThread


class AmlHostSemanticPort(Protocol):
    def events(
        self,
        *,
        message: AmlMessage,
        visible_messages: tuple[AmlMessage, ...],
        active_threads: tuple[MemoryThread, ...],
        scope: Scope,
        origin_runtime_id: str,
        evidence_ref: str,
    ) -> tuple[SemanticEventCandidate, ...]:
        """Return bounded proposals already owned by the AML Host/Body."""
        ...
