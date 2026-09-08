"""D1.5 Affect / Dynamics / Intent / Policy contract tests."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionIntent,
    ActionPermission,
    ActionPolicyResult,
    AffectiveDimensionProfile,
    DynamicsPolicy,
    Scope,
    ScopeDomain,
    SyncFields,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def make_profile(dimension: str = "agent.affect.longing") -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=0.6,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(("growth", 0.05),),
        coupling_profile=(("agent.affect.anxiety", 0.4),),
    )


def make_intent(intent_id: str = "intent-1") -> ActionIntent:
    scope = make_scope()
    return ActionIntent(
        intent_id=intent_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        cognitive_intent_id="cognitive-intent-1",
        action="send_message",
        target="user-1",
        sync=make_sync(scope, intent_id),
    )


def make_permission() -> ActionPermission:
    return ActionPermission(
        permission_id="permission-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        action_type="send_message",
        allowed=False,
        reasons=("proactive_cooldown",),
        constraints=("next_allowed_at=2026-08-20T12:30:00Z",),
    )


def make_policy_result() -> ActionPolicyResult:
    return ActionPolicyResult(
        policy_id="policy-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        decision=ActionDecision.DENY,
        permission=make_permission(),
        reason_codes=("proactive_cooldown",),
    )


# --- AffectiveDimensionProfile (4.6) ---


def test_profile_preserves_baseline_46_fields() -> None:
    field_names = {field.name for field in fields(AffectiveDimensionProfile)}
    assert {
        "dimension",
        "baseline",
        "initial_value",
        "sensitivity",
        "recovery_rate",
        "ceiling",
        "floor",
        "growth_profile",
        "coupling_profile",
    } <= field_names


def test_profile_has_no_current_field() -> None:
    field_names = {field.name for field in fields(AffectiveDimensionProfile)}
    assert "current" not in field_names
    assert "current_value" not in field_names


def test_profile_is_immutable() -> None:
    profile = make_profile()
    with pytest.raises(FrozenInstanceError):
        profile.baseline = 0.5  # type: ignore[misc]


def test_profile_requires_non_empty_dimension() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        make_profile(dimension=" ")


# --- DynamicsPolicy ---


def test_dynamics_policy_is_runtime_checkable_protocol() -> None:
    assert DynamicsPolicy is not None


def test_dynamics_policy_accepts_conforming_implementation() -> None:
    class LinearPolicy:
        def apply(
            self,
            dimension: str,
            profile: AffectiveDimensionProfile,
            current_value: float,
            delta: timedelta,
        ) -> float:
            return current_value + profile.sensitivity * delta.total_seconds() / 3600

    assert isinstance(LinearPolicy(), DynamicsPolicy)


# --- ActionIntent ---


def test_action_intent_accepts_none_target() -> None:
    scope = make_scope()
    intent = ActionIntent(
        intent_id="intent-2",
        scope=scope,
        origin_runtime_id="runtime-1",
        cognitive_intent_id="cognitive-intent-1",
        action="send_message",
        target=None,
        sync=make_sync(scope, "intent-2"),
    )
    assert intent.target is None


def test_action_intent_carries_sync_and_flow_position() -> None:
    intent = make_intent()
    assert intent.sync_fields() is intent.sync
    assert intent.cognitive_intent_id == "cognitive-intent-1"
    assert intent.action == "send_message"
    with pytest.raises(FrozenInstanceError):
        intent.action = "other"  # type: ignore[misc]


# --- ActionPermission (15.1) ---


def test_permission_preserves_baseline_151_fields() -> None:
    field_names = {field.name for field in fields(ActionPermission)}
    assert {"action_type", "allowed", "reasons", "constraints"} <= field_names


def test_permission_rejects_non_bool_allowed() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="allowed"):
        ActionPermission(
            permission_id="p-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_type="send_message",
            allowed="yes",  # type: ignore[arg-type]
            reasons=(),
            constraints=(),
        )


def test_permission_rejects_blank_action_type() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        ActionPermission(
            permission_id="p-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            action_type="",
            allowed=True,
            reasons=(),
            constraints=(),
        )


# --- ActionPolicyResult ---


def test_policy_result_has_machine_readable_reason_codes() -> None:
    result = make_policy_result()
    assert result.reason_codes == ("proactive_cooldown",)
    assert result.decision is ActionDecision.DENY
    assert result.permission is not None
    assert result.permission.allowed is False


def test_action_decision_values() -> None:
    assert {decision.value for decision in ActionDecision} == {"allow", "deny", "defer"}


def test_policy_result_rejects_unknown_decision() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="decision"):
        ActionPolicyResult(
            policy_id="p-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            intent_id="intent-1",
            decision="nonsense",  # type: ignore[arg-type]
            permission=None,
            reason_codes=(),
        )


def test_policy_result_is_immutable() -> None:
    result = make_policy_result()
    with pytest.raises(FrozenInstanceError):
        result.decision = ActionDecision.ALLOW  # type: ignore[misc]


def test_policy_result_carries_no_expression_fields() -> None:
    # ActionPolicy != ExpressionGuard: the policy result schema must not
    # absorb expression-level fields (rewrite, violations, expression text).
    field_names = {field.name for field in fields(ActionPolicyResult)}
    assert "expression" not in field_names
    assert "rewritten_expression" not in field_names
    assert "violations" not in field_names
