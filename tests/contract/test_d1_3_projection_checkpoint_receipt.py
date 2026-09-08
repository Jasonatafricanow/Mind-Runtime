"""D1.3 Projection / Checkpoint / Receipt contract tests."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    ActionReceipt,
    DeliveryReceipt,
    DeliveryStatus,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    Syncable,
    SyncFields,
    TransitionIntent,
    TurnCheckpoint,
    TurnProjection,
    TurnStage,
)

NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_sync(scope: Scope, object_id: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}")


def make_state(state_id: str = "state-1", dimension: str = "user.hunger") -> RuntimeState:
    scope = make_scope()
    return RuntimeState(
        state_id=state_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value={"status": "hungry"},
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(scope, state_id),
    )


def make_intent(intent_id: str = "intent-1") -> TransitionIntent:
    before = make_state(state_id="state-before", dimension="user.hunger")
    after = make_state(state_id="state-after", dimension="user.hunger")
    return TransitionIntent(
        intent_id=intent_id,
        interaction_id="interaction-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        target_dimension="user.hunger",
        before=before,
        proposed_after=after,
        cause_refs=(),
        policy="test_policy",
        confidence=0.9,
        commit_phase="turn_commit",
    )


def make_projection(projection_id: str = "projection-1") -> ProjectedMindState:
    return ProjectedMindState(
        projection_id=projection_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        projected_states=(make_state(state_id=f"state-{projection_id}", dimension="user.hunger"),),
        committed=False,
        sync=make_sync(make_scope(), projection_id),
    )


def make_turn_projection(projection_id: str = "turn-projection-1") -> TurnProjection:
    scope = make_scope()
    return TurnProjection(
        projection_id=projection_id,
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        effective_state_before=make_state(state_id="state-before", dimension="user.hunger"),
        observations=(),
        situation=None,
        assessment_trace_ref=None,
        intent_refs=(),
        policy_result_ref=None,
        transition_intents=(make_intent(),),
        projected_mind_state=make_projection(),
        created_at=NOW,
        sync=make_sync(scope, projection_id),
    )


def make_checkpoint(checkpoint_id: str = "checkpoint-1") -> TurnCheckpoint:
    scope = make_scope()
    return TurnCheckpoint(
        checkpoint_id=checkpoint_id,
        interaction_id="interaction-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        stage=TurnStage.PROCESSING,
        base_state_version=1,
        projection_ref="turn-projection-1",
        action_id=None,
        delivery_status=DeliveryStatus.UNSENT,
        checkpointed_at=NOW,
        sync=make_sync(scope, checkpoint_id),
    )


# --- ProjectedMindState ---


def test_projection_defaults_to_uncommitted() -> None:
    projection = make_projection()
    assert projection.committed is False
    assert "committed" in {field.name for field in fields(ProjectedMindState)}


def test_projection_can_record_committed_flag() -> None:
    projection = make_projection()
    committed = ProjectedMindState(
        projection_id="projection-2",
        scope=projection.scope,
        origin_runtime_id="runtime-1",
        projected_states=projection.projected_states,
        committed=True,
        sync=make_sync(make_scope(), "projection-2"),
    )
    assert committed.committed is True


def test_projection_is_syncable_and_immutable() -> None:
    projection = make_projection()
    assert isinstance(projection, Syncable)
    assert projection.sync_fields() is projection.sync
    with pytest.raises(FrozenInstanceError):
        projection.committed = True  # type: ignore[misc]


# --- TurnProjection ---


def test_turn_projection_preserves_baseline_field_names() -> None:
    field_names = {field.name for field in fields(TurnProjection)}
    baseline = {
        "interaction_id",
        "effective_state_before",
        "observations",
        "situation",
        "assessment_trace_ref",
        "intent_refs",
        "policy_result_ref",
        "transition_intents",
        "projected_mind_state",
        "created_at",
    }
    assert baseline <= field_names


def test_turn_projection_carries_sync_and_d1_3_additions() -> None:
    projection = make_turn_projection()
    assert projection.sync_fields() is projection.sync
    assert projection.projection_id == "turn-projection-1"
    assert projection.origin_runtime_id == "runtime-1"
    assert projection.scope.domain is ScopeDomain.USER
    assert projection.projected_mind_state.committed is False
    assert projection.effective_state_before.dimension == "user.hunger"
    assert projection.transition_intents[0].intent_id == "intent-1"
    assert projection.created_at == NOW


def test_turn_projection_d1_4_d1_5_fields_are_reference_ids() -> None:
    projection = make_turn_projection()
    assert projection.situation is None
    assert projection.assessment_trace_ref is None
    assert projection.intent_refs == ()
    assert projection.policy_result_ref is None


def test_turn_projection_is_immutable() -> None:
    projection = make_turn_projection()
    with pytest.raises(FrozenInstanceError):
        projection.interaction_id = "other"  # type: ignore[misc]


def test_turn_projection_created_at_must_be_aware_utc() -> None:
    scope = make_scope()
    naive = datetime(2026, 8, 20, 10, 0)
    with pytest.raises(ValueError, match="aware UTC"):
        TurnProjection(
            projection_id="tp-1",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=make_state(),
            observations=(),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(),
            projected_mind_state=make_projection(),
            created_at=naive,
            sync=make_sync(scope, "tp-1"),
        )


def test_projection_rejects_non_bool_committed() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="bool"):
        ProjectedMindState(
            projection_id="p-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            projected_states=(make_state(),),
            sync=make_sync(scope, "p-bad"),
            committed="yes",  # type: ignore[arg-type]
        )


def test_projection_rejects_mismatched_state_scope() -> None:
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    other_state = RuntimeState(
        state_id="other-state",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        dimension="user.hunger",
        value={"status": "hungry"},
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(other_scope, "other-state"),
    )
    with pytest.raises(ValueError, match="scope"):
        ProjectedMindState(
            projection_id="p-bad",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            projected_states=(other_state,),
            sync=make_sync(make_scope(), "p-bad"),
        )


def test_turn_projection_rejects_mismatched_effective_state_scope() -> None:
    scope = make_scope()
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    other_state = RuntimeState(
        state_id="other-state",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        dimension="user.hunger",
        value={"status": "hungry"},
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(other_scope, "other-state"),
    )
    with pytest.raises(ValueError, match="effective_state_before.scope"):
        TurnProjection(
            projection_id="tp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=other_state,
            observations=(),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(),
            projected_mind_state=make_projection(),
            created_at=NOW,
            sync=make_sync(scope, "tp-bad"),
        )


def test_turn_projection_rejects_mismatched_projected_scope() -> None:
    scope = make_scope()
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    other_state = RuntimeState(
        state_id="other-state",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        dimension="user.hunger",
        value={"status": "hungry"},
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(other_scope, "other-state"),
    )
    with pytest.raises(ValueError, match="projected_mind_state.scope"):
        TurnProjection(
            projection_id="tp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=make_state(),
            observations=(),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(),
            projected_mind_state=ProjectedMindState(
                projection_id="p-other",
                scope=other_scope,
                origin_runtime_id="runtime-1",
                projected_states=(other_state,),
                sync=make_sync(other_scope, "p-other"),
            ),
            created_at=NOW,
            sync=make_sync(scope, "tp-bad"),
        )


def test_turn_projection_accepts_agent_scoped_projected_mind_state() -> None:
    """ADR-0002 (D7.7): the projected mind state may carry the persona's
    agent scope while the turn envelope stays in the user scope."""
    scope = make_scope()
    agent_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0")
    agent_state = RuntimeState(
        state_id="agent.affect.longing:projected",
        scope=agent_scope,
        origin_runtime_id="runtime-1",
        dimension="agent.affect.longing",
        value=0.6,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(agent_scope, "agent.affect.longing:projected"),
    )
    projection = TurnProjection(
        projection_id="tp-agent",
        interaction_id="i-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        effective_state_before=make_state(),
        observations=(),
        situation=None,
        assessment_trace_ref=None,
        intent_refs=(),
        policy_result_ref=None,
        transition_intents=(),
        projected_mind_state=ProjectedMindState(
            projection_id="p-agent",
            scope=agent_scope,
            origin_runtime_id="runtime-1",
            projected_states=(agent_state,),
            sync=make_sync(agent_scope, "p-agent"),
        ),
        created_at=NOW,
        sync=make_sync(scope, "tp-agent"),
    )
    assert projection.scope == scope
    assert projection.projected_mind_state.scope == agent_scope


def test_turn_projection_accepts_matching_observation_scopes() -> None:
    from mind_runtime.contracts import Observation

    scope = make_scope()
    observation = Observation(
        id="obs-1",
        interaction_id="i-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.hunger",
        value="hungry",
        confidence=0.8,
        observed_at=NOW,
        evidence_refs=(),
        sync=make_sync(scope, "obs-1"),
    )
    projection = TurnProjection(
        projection_id="tp-ok",
        interaction_id="i-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        effective_state_before=make_state(),
        observations=(observation,),
        situation="situation-1",
        assessment_trace_ref="assessment-1",
        intent_refs=("intent-1",),
        policy_result_ref="policy-1",
        transition_intents=(),
        projected_mind_state=make_projection(),
        created_at=NOW,
        sync=make_sync(scope, "tp-ok"),
    )
    assert projection.observations == (observation,)
    assert projection.situation == "situation-1"
    assert projection.intent_refs == ("intent-1",)


def test_turn_projection_rejects_mismatched_observation_scope() -> None:
    from mind_runtime.contracts import Observation

    scope = make_scope()
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    observation = Observation(
        id="obs-other",
        interaction_id="i-1",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.hunger",
        value="hungry",
        confidence=0.8,
        observed_at=NOW,
        evidence_refs=(),
        sync=make_sync(other_scope, "obs-other"),
    )
    with pytest.raises(ValueError, match="scope"):
        TurnProjection(
            projection_id="tp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=make_state(),
            observations=(observation,),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(),
            projected_mind_state=make_projection(),
            created_at=NOW,
            sync=make_sync(scope, "tp-bad"),
        )


def test_turn_projection_rejects_mismatched_intent_scope() -> None:
    scope = make_scope()
    other_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    other_state = RuntimeState(
        state_id="other-state",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        dimension="user.hunger",
        value={"status": "hungry"},
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=NOW,
        version=1,
        sync=make_sync(other_scope, "other-state"),
    )
    intent = TransitionIntent(
        intent_id="intent-other",
        interaction_id="i-1",
        scope=other_scope,
        origin_runtime_id="runtime-1",
        target_dimension="user.hunger",
        before=other_state,
        proposed_after=other_state,
        cause_refs=(),
        policy="test",
        confidence=0.5,
        commit_phase="turn_commit",
    )
    with pytest.raises(ValueError, match="scope"):
        TurnProjection(
            projection_id="tp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=make_state(),
            observations=(),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(intent,),
            projected_mind_state=make_projection(),
            created_at=NOW,
            sync=make_sync(scope, "tp-bad"),
        )


# --- TurnStage / DeliveryStatus ---


def test_turn_stage_values() -> None:
    assert {stage.value for stage in TurnStage} == {
        "processing",
        "dispatching",
        "awaiting_commit",
    }


def test_delivery_status_distinguishes_unsent_sent_unknown() -> None:
    assert {status.value for status in DeliveryStatus} == {"unsent", "sent", "unknown"}


# --- TurnCheckpoint ---


def test_checkpoint_preserves_d5_fields() -> None:
    field_names = {field.name for field in fields(TurnCheckpoint)}
    d5_fields = {
        "interaction_id",
        "stage",
        "base_state_version",
        "projection_ref",
        "action_id",
        "delivery_status",
    }
    assert d5_fields <= field_names


def test_checkpoint_carries_sync_and_is_immutable() -> None:
    checkpoint = make_checkpoint()
    assert isinstance(checkpoint, Syncable)
    assert checkpoint.sync_fields() is checkpoint.sync
    assert checkpoint.stage is TurnStage.PROCESSING
    assert checkpoint.base_state_version == 1
    assert checkpoint.delivery_status is DeliveryStatus.UNSENT
    with pytest.raises(FrozenInstanceError):
        checkpoint.stage = TurnStage.AWAITING_COMMIT  # type: ignore[misc]


def test_checkpoint_rejects_unknown_stage() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="stage"):
        TurnCheckpoint(
            checkpoint_id="cp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            stage="nonsense",  # type: ignore[arg-type]
            base_state_version=1,
            projection_ref="tp-1",
            action_id=None,
            delivery_status=DeliveryStatus.UNSENT,
            checkpointed_at=NOW,
            sync=make_sync(scope, "cp-bad"),
        )


def test_checkpoint_rejects_invalid_base_state_version() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="at least 1"):
        TurnCheckpoint(
            checkpoint_id="cp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            stage=TurnStage.PROCESSING,
            base_state_version=0,
            projection_ref="tp-1",
            action_id=None,
            delivery_status=DeliveryStatus.UNSENT,
            checkpointed_at=NOW,
            sync=make_sync(scope, "cp-bad"),
        )


def test_checkpoint_rejects_unknown_delivery_status() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="delivery_status"):
        TurnCheckpoint(
            checkpoint_id="cp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            stage=TurnStage.PROCESSING,
            base_state_version=1,
            projection_ref="tp-1",
            action_id=None,
            delivery_status="nonsense",  # type: ignore[arg-type]
            checkpointed_at=NOW,
            sync=make_sync(scope, "cp-bad"),
        )


def test_checkpoint_checkpointed_at_must_be_aware_utc() -> None:
    scope = make_scope()
    naive = datetime(2026, 8, 20, 10, 0)
    with pytest.raises(ValueError, match="aware UTC"):
        TurnCheckpoint(
            checkpoint_id="cp-bad",
            interaction_id="i-1",
            scope=scope,
            origin_runtime_id="runtime-1",
            stage=TurnStage.PROCESSING,
            base_state_version=1,
            projection_ref="tp-1",
            action_id=None,
            delivery_status=DeliveryStatus.UNSENT,
            checkpointed_at=naive,
            sync=make_sync(scope, "cp-bad"),
        )


# --- ActionReceipt / DeliveryReceipt ---


def test_action_receipt_received_at_must_be_aware_utc() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="aware UTC"):
        ActionReceipt(
            receipt_id="r-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_intent_id="intent-1",
            delivery_status=DeliveryStatus.UNSENT,
            outcome=None,
            received_at=datetime(2026, 8, 20, 10, 0),
            sync=make_sync(scope, "r-bad"),
        )


def test_turn_projection_rejects_empty_interaction_id() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        TurnProjection(
            projection_id="tp-bad",
            interaction_id=" ",
            scope=scope,
            origin_runtime_id="runtime-1",
            effective_state_before=make_state(),
            observations=(),
            situation=None,
            assessment_trace_ref=None,
            intent_refs=(),
            policy_result_ref=None,
            transition_intents=(),
            projected_mind_state=make_projection(),
            created_at=NOW,
            sync=make_sync(scope, "tp-bad"),
        )


def test_action_receipt_carries_sync_and_delivery_status() -> None:
    scope = make_scope()
    receipt = ActionReceipt(
        receipt_id="receipt-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        action_intent_id="intent-1",
        delivery_status=DeliveryStatus.SENT,
        outcome="delivered",
        received_at=NOW,
        sync=make_sync(scope, "receipt-1"),
    )
    assert isinstance(receipt, Syncable)
    assert receipt.delivery_status is DeliveryStatus.SENT
    assert receipt.outcome == "delivered"
    with pytest.raises(FrozenInstanceError):
        receipt.delivery_status = DeliveryStatus.UNKNOWN  # type: ignore[misc]


def test_delivery_receipt_distinguishes_send_states() -> None:
    scope = make_scope()
    unknown = DeliveryReceipt(
        receipt_id="dr-unknown",
        scope=scope,
        origin_runtime_id="runtime-1",
        message_id="message-1",
        delivery_status=DeliveryStatus.UNKNOWN,
        delivered_at=None,
        sync=make_sync(scope, "dr-unknown"),
    )
    sent = DeliveryReceipt(
        receipt_id="dr-sent",
        scope=scope,
        origin_runtime_id="runtime-1",
        message_id="message-2",
        delivery_status=DeliveryStatus.SENT,
        delivered_at=NOW,
        sync=make_sync(scope, "dr-sent"),
    )
    assert unknown.delivered_at is None
    assert sent.delivered_at == NOW
    assert unknown.delivery_status is DeliveryStatus.UNKNOWN
    assert sent.delivery_status is DeliveryStatus.SENT


def test_action_receipt_rejects_unknown_delivery_status() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="delivery_status"):
        ActionReceipt(
            receipt_id="r-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_intent_id="intent-1",
            delivery_status="nonsense",  # type: ignore[arg-type]
            outcome=None,
            received_at=NOW,
            sync=make_sync(scope, "r-bad"),
        )


def test_action_receipt_rejects_empty_outcome() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        ActionReceipt(
            receipt_id="r-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_intent_id="intent-1",
            delivery_status=DeliveryStatus.SENT,
            outcome="   ",
            received_at=NOW,
            sync=make_sync(scope, "r-bad"),
        )


def test_action_receipt_sync_fields_exposed() -> None:
    scope = make_scope()
    receipt = ActionReceipt(
        receipt_id="receipt-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        action_intent_id="intent-1",
        delivery_status=DeliveryStatus.UNKNOWN,
        outcome=None,
        received_at=NOW,
        sync=make_sync(scope, "receipt-1"),
    )
    assert receipt.sync_fields() is receipt.sync


def test_delivery_receipt_rejects_unknown_delivery_status() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="delivery_status"):
        DeliveryReceipt(
            receipt_id="dr-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            message_id="message-1",
            delivery_status="nonsense",  # type: ignore[arg-type]
            delivered_at=None,
            sync=make_sync(scope, "dr-bad"),
        )


def test_delivery_receipt_sync_fields_exposed() -> None:
    scope = make_scope()
    receipt = DeliveryReceipt(
        receipt_id="dr-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        message_id="message-1",
        delivery_status=DeliveryStatus.UNSENT,
        delivered_at=None,
        sync=make_sync(scope, "dr-1"),
    )
    assert receipt.sync_fields() is receipt.sync


def test_delivery_receipt_delivered_at_must_be_aware_utc_when_present() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="aware UTC"):
        DeliveryReceipt(
            receipt_id="dr-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            message_id="message-1",
            delivery_status=DeliveryStatus.SENT,
            delivered_at=datetime(2026, 8, 20, 10, 0),
            sync=make_sync(scope, "dr-bad"),
        )


def test_delivery_receipt_is_immutable() -> None:
    scope = make_scope()
    receipt = DeliveryReceipt(
        receipt_id="dr-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        message_id="message-1",
        delivery_status=DeliveryStatus.UNSENT,
        delivered_at=None,
        sync=make_sync(scope, "dr-1"),
    )
    with pytest.raises(FrozenInstanceError):
        receipt.delivery_status = DeliveryStatus.SENT  # type: ignore[misc]


def test_opaque_ids_must_be_non_empty() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        ActionReceipt(
            receipt_id="",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_intent_id="intent-1",
            delivery_status=DeliveryStatus.UNSENT,
            outcome=None,
            received_at=NOW,
            sync=make_sync(scope, "receipt-x"),
        )
