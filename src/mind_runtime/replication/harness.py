"""Replication harness: Null/InMemory ports and payload allowlist (D5.7).

The baseline forbids physical outbox/inbox tables: replication flows only
through ``ReplicationPort`` implementations. The payload allowlist accepts
committed facts (Evidence/Observation/RuntimeState/StateTransition) and
rejects projected state — the D1 ``ReplicationEnvelope`` contract already
blocks projected payloads at construction; the receive-side check is a
defensive second gate.
"""

from mind_runtime.contracts import (
    Evidence,
    Observation,
    ReplicationEnvelope,
    RuntimeState,
    StateTransition,
)

_ALLOWED_PAYLOAD_TYPES = (
    Evidence,
    Observation,
    RuntimeState,
    StateTransition,
)


def is_allowed_payload(envelope: ReplicationEnvelope) -> bool:
    """Defensive receive-side allowlist check (projected state rejected)."""
    return isinstance(envelope.payload, _ALLOWED_PAYLOAD_TYPES)


class NullReplicationPort:
    """A transport that sends nowhere and receives nothing."""

    def send(self, envelope: ReplicationEnvelope) -> None:
        """No-op transport (harness default)."""

    def receive(self) -> ReplicationEnvelope | None:
        return None


class InMemoryReplicationPort:
    """In-process transport simulating remote delivery (no physical tables)."""

    def __init__(self) -> None:
        self._inbound: list[ReplicationEnvelope] = []
        self._outbound: list[ReplicationEnvelope] = []

    def send(self, envelope: ReplicationEnvelope) -> None:
        self._outbound.append(envelope)

    def receive(self) -> ReplicationEnvelope | None:
        if not self._inbound:
            return None
        return self._inbound.pop(0)

    def deliver(self, envelope: ReplicationEnvelope) -> None:
        """Simulate an envelope arriving from the remote side."""
        self._inbound.append(envelope)

    def outbound(self) -> tuple[ReplicationEnvelope, ...]:
        return tuple(self._outbound)

    def inbound_count(self) -> int:
        return len(self._inbound)

    def outbound_count(self) -> int:
        return len(self._outbound)

    def clear(self) -> None:
        self._inbound.clear()
        self._outbound.clear()
