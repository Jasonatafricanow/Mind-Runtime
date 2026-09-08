"""D5.7 replication harness tests: Null/InMemory ports and allowlist."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    Observation,
    ProjectedMindState,
    ReplicationEnvelope,
    SyncFields,
    TransitionIntent,
    TurnProjection,
)
from mind_runtime.replication import (
    InMemoryReplicationPort,
    NullReplicationPort,
    is_allowed_payload,
)
from tests.golden.fixtures.common import make_evidence, make_scope, make_state

NOW = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)


def make_envelope(payload: object, payload_type: str) -> ReplicationEnvelope:
    scope = getattr(payload, "scope", make_scope())
    return ReplicationEnvelope(
        envelope_id="envelope-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        payload=payload,
        payload_type=payload_type,
        sync=SyncFields(scope, "runtime-1", "envelope-1", 1, "idem"),
    )


def make_observation() -> Observation:
    scope = make_scope()
    return Observation(
        id="observation-1",
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user_message.observed",
        value={"text": "x"},
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("evidence-1",),
        sync=SyncFields(scope, "runtime-1", "observation-1", 1, "idem"),
    )


def test_null_port_receives_nothing() -> None:
    port = NullReplicationPort()
    port.send(make_envelope(make_evidence(text="x"), "Evidence"))
    assert port.receive() is None


def test_in_memory_port_round_trip_order() -> None:
    port = InMemoryReplicationPort()
    first = make_envelope(make_evidence(text="a", evidence_id="e-1"), "Evidence")
    second = make_envelope(make_evidence(text="b", evidence_id="e-2"), "Evidence")
    port.deliver(first)
    port.deliver(second)
    assert port.inbound_count() == 2
    assert port.receive() is first
    assert port.receive() is second
    assert port.receive() is None
    assert port.inbound_count() == 0


def test_in_memory_port_outbound() -> None:
    port = InMemoryReplicationPort()
    envelope = make_envelope(make_evidence(text="x"), "Evidence")
    port.send(envelope)
    assert port.outbound() == (envelope,)
    assert port.outbound_count() == 1
    port.clear()
    assert port.outbound_count() == 0


def test_allowlist_accepts_committed_facts() -> None:
    for payload, payload_type in (
        (make_evidence(text="x"), "Evidence"),
        (make_observation(), "Observation"),
        (make_state(dimension="user.sleep.phase", value="awake"), "RuntimeState"),
    ):
        envelope = make_envelope(payload, payload_type)
        assert is_allowed_payload(envelope) is True


def test_envelope_rejects_projected_state_at_construction() -> None:
    """The D1 contract already blocks projected payloads."""
    from mind_runtime.contracts import Scope, ScopeDomain

    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    state = make_state(dimension="agent.affect.longing", value=0.55, status="active", scope=scope)
    projected = ProjectedMindState(
        projection_id="projection-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        projected_states=(state,),
        sync=SyncFields(scope, "runtime-1", "projection-1", 1, "idem"),
        committed=False,
    )
    with pytest.raises(TypeError, match="projected"):
        ReplicationEnvelope(
            envelope_id="envelope-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            payload=projected,
            payload_type="ProjectedMindState",
            sync=SyncFields(scope, "runtime-1", "envelope-1", 1, "idem"),
        )


def test_envelope_rejects_turn_projection_at_construction() -> None:
    scope = make_scope()
    effective = make_state(dimension="user.sleep.phase", value="awake", status="active")
    with pytest.raises(TypeError, match="projected"):
        ReplicationEnvelope(
            envelope_id="envelope-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            payload=TurnProjection(
                projection_id="projection-1",
                interaction_id="interaction-1",
                scope=scope,
                origin_runtime_id="runtime-1",
                effective_state_before=effective,
                observations=(),
                situation=None,
                assessment_trace_ref=None,
                intent_refs=(),
                policy_result_ref=None,
                transition_intents=(),
                projected_mind_state=ProjectedMindState(
                    projection_id="p",
                    scope=scope,
                    origin_runtime_id="runtime-1",
                    projected_states=(effective,),
                    sync=SyncFields(scope, "runtime-1", "p", 1, "idem"),
                    committed=False,
                ),
                created_at=NOW,
                sync=SyncFields(scope, "runtime-1", "projection-1", 1, "idem"),
            ),
            payload_type="TurnProjection",
            sync=SyncFields(scope, "runtime-1", "envelope-1", 1, "idem"),
        )


def test_allowlist_rejects_non_fact_payloads() -> None:
    # An intent is not a committable fact payload for replication.
    scope = make_scope()
    before = make_state(dimension="user.sleep.phase", value="a", status="active")
    after = make_state(dimension="user.sleep.phase", value="b", status="active")
    intent = TransitionIntent(
        intent_id="intent-1",
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        target_dimension="user.sleep.phase",
        before=before,
        proposed_after=after,
        cause_refs=(),
        policy="reconciler",
        confidence=1.0,
        commit_phase="ingest",
    )
    envelope = make_envelope(intent, "TransitionIntent")
    assert is_allowed_payload(envelope) is False


def test_allowlist_requires_matching_scope() -> None:
    """D1 contract: envelope scope must match payload scope."""
    evidence = make_evidence(text="x", scope=make_scope(user_id="user-a"))
    with pytest.raises(ValueError, match="scope"):
        ReplicationEnvelope(
            envelope_id="envelope-1",
            scope=make_scope(),  # different user -> mismatch
            origin_runtime_id="runtime-1",
            payload=evidence,
            payload_type="Evidence",
            sync=SyncFields(make_scope(), "runtime-1", "envelope-1", 1, "idem"),
        )
