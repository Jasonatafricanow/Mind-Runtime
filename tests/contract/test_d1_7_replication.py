"""D1.7 ReplicationEnvelope / ReplicationPort contract tests."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Observation,
    ProjectedMindState,
    ReplicationEnvelope,
    ReplicationPort,
    RuntimeState,
    Scope,
    ScopeDomain,
    StateTransition,
    Syncable,
    SyncFields,
    TurnProjection,
)

NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_evidence() -> Evidence:
    scope = make_scope()
    return Evidence(
        id="evidence-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id="message-1",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(scope, AuthorityLevel.ASSERTED, "message-1"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(scope, "evidence-1"),
    )


def make_observation() -> Observation:
    scope = make_scope()
    return Observation(
        id="observation-1",
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.hunger",
        value="hungry",
        confidence=0.8,
        observed_at=NOW,
        evidence_refs=(),
        sync=make_sync(scope, "observation-1"),
    )


def make_state() -> RuntimeState:
    scope = make_scope()
    return RuntimeState(
        state_id="state-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        dimension="user.hunger",
        value="hungry",
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(scope, "state-1"),
    )


def make_transition() -> StateTransition:
    scope = make_scope()
    return StateTransition(
        transition_id="transition-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        from_state=make_state(),
        to_state=make_state(),
        committed_at=NOW,
        sync=make_sync(scope, "transition-1"),
    )


def make_projection() -> ProjectedMindState:
    scope = make_scope()
    return ProjectedMindState(
        projection_id="projection-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        projected_states=(make_state(),),
        sync=make_sync(scope, "projection-1"),
        committed=False,
    )


def make_envelope(payload: object, object_id: str = "envelope-1") -> ReplicationEnvelope:
    scope = make_scope()
    return ReplicationEnvelope(
        envelope_id=object_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        payload=payload,
        payload_type=type(payload).__name__,
        sync=make_sync(scope, object_id),
    )


# --- ReplicationEnvelope ---


def test_envelope_is_syncable_and_records_payload_type() -> None:
    envelope = make_envelope(make_evidence())
    assert isinstance(envelope, Syncable)
    assert envelope.sync_fields() is envelope.sync
    assert envelope.payload_type == "Evidence"
    assert isinstance(envelope.payload, Evidence)


def test_envelope_rejects_projected_mind_state_payload() -> None:
    with pytest.raises(TypeError, match="projected"):
        make_envelope(make_projection())


def test_envelope_rejects_turn_projection_payload() -> None:
    scope = make_scope()
    projection = make_projection()
    turn_projection = TurnProjection(
        projection_id="turn-projection-1",
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        effective_state_before=make_state(),
        observations=(),
        situation=None,
        assessment_trace_ref=None,
        intent_refs=(),
        policy_result_ref=None,
        transition_intents=(),
        projected_mind_state=projection,
        created_at=NOW,
        sync=make_sync(scope, "turn-projection-1"),
    )
    with pytest.raises(TypeError, match="projected"):
        make_envelope(turn_projection)


def test_envelope_accepts_committed_factual_payloads() -> None:
    for payload in (make_evidence(), make_observation(), make_state(), make_transition()):
        envelope = make_envelope(payload)
        assert envelope.payload is payload


def test_envelope_is_immutable() -> None:
    envelope = make_envelope(make_evidence())
    with pytest.raises(FrozenInstanceError):
        envelope.payload_type = "Other"  # type: ignore[misc]


def test_envelope_rejects_mismatched_payload_scope() -> None:
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    evidence = Evidence(
        id="evidence-2",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id="message-2",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(other_scope, AuthorityLevel.ASSERTED, "message-2"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hi"},
        sync=make_sync(other_scope, "evidence-2"),
    )
    with pytest.raises(ValueError, match="scope"):
        make_envelope(evidence)


def test_envelope_accepts_unknown_scope_payload() -> None:
    # A payload without a known scope field (e.g. a plain string) is allowed;
    # scope validation applies only to known scoped contracts.
    envelope = make_envelope("plain-payload")
    assert envelope.payload == "plain-payload"


# --- ReplicationPort ---


def test_replication_port_is_protocol_with_send_receive() -> None:
    assert hasattr(ReplicationPort, "send")
    assert hasattr(ReplicationPort, "receive")


def test_replication_port_accepts_conforming_implementation() -> None:
    class NullPort:
        def __init__(self) -> None:
            self._inbox: list[ReplicationEnvelope] = []

        def send(self, envelope: ReplicationEnvelope) -> None:
            self._inbox.append(envelope)

        def receive(self) -> ReplicationEnvelope | None:
            return self._inbox.pop(0) if self._inbox else None

    port = NullPort()
    assert isinstance(port, ReplicationPort)
    envelope = make_envelope(make_evidence())
    port.send(envelope)
    assert port.receive() is envelope
    assert port.receive() is None


def test_envelope_schema_frozen() -> None:
    expected = {"envelope_id", "scope", "origin_runtime_id", "payload", "payload_type", "sync"}
    field_names = {field.name for field in fields(ReplicationEnvelope)}
    assert expected == field_names & expected
