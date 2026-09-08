"""Deterministic ActionPolicy is the only D9 action-permission authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyInput,
    ActionPolicyResult,
    Intent,
    IntentStatus,
    PolicyResources,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")


def intent(
    kind: str = "respond",
    *,
    earliest_at: datetime | None = NOW,
    expires_at: datetime | None = NOW + timedelta(hours=1),
) -> Intent:
    intent_id = f"intent-{kind}"
    return Intent(
        intent_id=intent_id,
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        kind=kind,
        strength=0.7,
        earliest_at=earliest_at,
        due_at=None,
        expires_at=expires_at,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("situation-1",),
        state_refs=("projection-1",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(USER_SCOPE, "runtime-1", intent_id, 1, f"admit-{intent_id}"),
    )


def situation(facts: tuple[tuple[str, str], ...] = ()) -> Situation:
    return Situation(
        situation_id="situation-1",
        scope=USER_SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=facts,
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="persona-1",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def rule(
    kind: str,
    action_type: str,
    *,
    proactive: bool = False,
    interrupts: bool = False,
    media_counter_fact: str | None = None,
    media_limit: int | None = None,
    required_resource: str | None = None,
) -> IntentPolicyRule:
    return IntentPolicyRule(
        intent_kind=kind,
        action_type=action_type,
        proactive=proactive,
        interrupts_active_conversation=interrupts,
        media_counter_fact=media_counter_fact,
        media_limit=media_limit,
        required_resource=required_resource,
    )


def policy() -> DeterministicActionPolicy:
    return DeterministicActionPolicy(
        ActionPolicyConfig(
            rules=(
                rule("respond", "text_message"),
                rule(
                    "contact_user",
                    "text_message",
                    proactive=True,
                    interrupts=True,
                ),
                rule(
                    "share_photo",
                    "photo_message",
                    proactive=True,
                    interrupts=True,
                    media_counter_fact="counter.photo_count_today",
                    media_limit=2,
                    required_resource="camera",
                ),
            ),
            proactive_cooldown=timedelta(minutes=30),
        ),
        runtime_id="runtime-1",
    )


def policy_input(
    cognitive_intent: Intent,
    *,
    facts: tuple[tuple[str, str], ...] = (),
    clock: datetime = NOW,
    resources: tuple[str, ...] = ("text_message", "photo_message", "camera"),
) -> ActionPolicyInput:
    return ActionPolicyInput(
        intent=cognitive_intent,
        context=situation(facts),
        scope=USER_SCOPE,
        clock=clock,
        resources=PolicyResources(resources),
    )


def assert_result(
    result: ActionPolicyResult,
    decision: ActionDecision,
    allowed: bool,
    reason: str,
) -> None:
    assert result.decision is decision
    assert result.permission is not None
    assert result.permission.allowed is allowed
    assert result.permission.reasons == (reason,)
    assert result.reason_codes == (reason,)


def test_allows_supported_ordinary_response() -> None:
    result = policy().policy(policy_input(intent()))

    assert_result(result, ActionDecision.ALLOW, True, "allowed")
    assert result.permission is not None
    assert result.permission.action_type == "text_message"


def test_defers_before_earliest_and_denies_at_expiry_boundary() -> None:
    not_yet = intent(earliest_at=NOW + timedelta(seconds=1))
    expired = intent(expires_at=NOW)

    assert_result(
        policy().policy(policy_input(not_yet)),
        ActionDecision.DEFER,
        False,
        "not_yet_earliest",
    )
    assert_result(
        policy().policy(policy_input(expired)),
        ActionDecision.DENY,
        False,
        "intent_expired",
    )


def test_defers_proactive_intent_during_active_conversation_or_pending_reply() -> None:
    proactive = intent("contact_user")

    active = policy().policy(policy_input(proactive, facts=(("conversation.active", "true"),)))
    pending = policy().policy(
        policy_input(proactive, facts=(("conversation.pending_reply", "true"),))
    )

    assert_result(active, ActionDecision.DEFER, False, "active_conversation")
    assert_result(pending, ActionDecision.DEFER, False, "pending_reply")


def test_proactive_cooldown_defers_immediately_before_and_allows_at_boundary() -> None:
    proactive = intent("contact_user", earliest_at=NOW - timedelta(hours=1))
    facts = (("counter.last_proactive_at", "2026-08-22T11:30:00+00:00"),)

    before = policy().policy(
        policy_input(proactive, facts=facts, clock=NOW - timedelta(microseconds=1))
    )
    at_boundary = policy().policy(policy_input(proactive, facts=facts, clock=NOW))

    assert_result(before, ActionDecision.DEFER, False, "proactive_cooldown")
    assert_result(at_boundary, ActionDecision.ALLOW, True, "allowed")


def test_media_budget_allows_below_limit_and_defers_at_limit() -> None:
    photo = intent("share_photo")
    below_facts = (("counter.photo_count_today", "1"),)
    at_limit_facts = (("counter.photo_count_today", "2"),)

    below = policy().policy(policy_input(photo, facts=below_facts))
    at_limit = policy().policy(policy_input(photo, facts=at_limit_facts))

    assert_result(below, ActionDecision.ALLOW, True, "allowed")
    assert_result(at_limit, ActionDecision.DEFER, False, "media_budget_exhausted")


def test_missing_current_action_or_required_resource_defers() -> None:
    photo = intent("share_photo")
    facts = (("counter.photo_count_today", "0"),)

    missing_action = policy().policy(policy_input(photo, facts=facts, resources=("camera",)))
    missing_camera = policy().policy(policy_input(photo, facts=facts, resources=("photo_message",)))

    assert_result(missing_action, ActionDecision.DEFER, False, "action_unavailable")
    assert_result(
        missing_camera,
        ActionDecision.DEFER,
        False,
        "required_resource_unavailable",
    )


def test_unknown_intent_kind_is_denied_as_permanently_unsupported() -> None:
    result = policy().policy(policy_input(intent("unknown")))

    assert_result(result, ActionDecision.DENY, False, "unsupported_intent_kind")


def test_action_policy_input_rejects_wrong_scope_before_policy() -> None:
    valid = policy_input(intent())

    with pytest.raises(ValueError, match="intent scope"):
        replace(valid, scope=OTHER_SCOPE)


@pytest.mark.parametrize(
    ("kind", "facts", "reason"),
    [
        ("contact_user", (("conversation.active", "yes"),), "malformed_conversation_active"),
        (
            "contact_user",
            (("conversation.pending_reply", "unknown"),),
            "malformed_pending_reply",
        ),
        (
            "contact_user",
            (("counter.last_proactive_at", "recently"),),
            "malformed_last_proactive_at",
        ),
        (
            "share_photo",
            (("counter.photo_count_today", "two"),),
            "malformed_media_counter",
        ),
    ],
)
def test_malformed_named_facts_fail_closed_as_defer(
    kind: str, facts: tuple[tuple[str, str], ...], reason: str
) -> None:
    result = policy().policy(policy_input(intent(kind), facts=facts))

    assert_result(result, ActionDecision.DEFER, False, reason)


def test_policy_does_not_mutate_intent_context_or_resources() -> None:
    original_intent = intent("share_photo")
    original_input = policy_input(
        original_intent,
        facts=(("counter.photo_count_today", "1"),),
    )
    snapshot = repr(original_input)

    policy().policy(original_input)

    assert repr(original_input) == snapshot
    assert original_input.intent is original_intent


def test_policy_denies_origin_mismatch_and_defers_duplicate_facts() -> None:
    original = intent()
    wrong_origin = replace(
        original,
        origin_runtime_id="other-runtime",
        sync=replace(original.sync, origin_runtime_id="other-runtime"),
    )
    origin_result = policy().policy(policy_input(wrong_origin))
    duplicate_result = policy().policy(
        policy_input(
            intent("contact_user"),
            facts=(
                ("conversation.active", "false"),
                ("conversation.active", "true"),
            ),
        )
    )

    assert_result(origin_result, ActionDecision.DENY, False, "origin_mismatch")
    assert_result(
        duplicate_result,
        ActionDecision.DEFER,
        False,
        "duplicate_context_fact",
    )


def test_explicit_false_interruption_facts_and_missing_media_counter() -> None:
    allowed = policy().policy(
        policy_input(
            intent("contact_user"),
            facts=(
                ("conversation.active", "false"),
                ("conversation.pending_reply", "false"),
            ),
        )
    )
    missing_counter = policy().policy(policy_input(intent("share_photo")))

    assert_result(allowed, ActionDecision.ALLOW, True, "allowed")
    assert_result(
        missing_counter,
        ActionDecision.DEFER,
        False,
        "missing_media_counter",
    )


def test_policy_configuration_rejects_ambiguous_rules() -> None:
    duplicate = rule("respond", "text_message")
    with pytest.raises(ValueError, match="intent_kind"):
        ActionPolicyConfig((duplicate, duplicate), timedelta(minutes=1))
    with pytest.raises(ValueError, match="media"):
        replace(duplicate, media_counter_fact="counter.photo_count_today")
    with pytest.raises(ValueError, match="cooldown"):
        ActionPolicyConfig((duplicate,), timedelta(seconds=-1))
    with pytest.raises(ValueError, match="proactive"):
        replace(duplicate, proactive=cast(bool, "true"))
    with pytest.raises(ValueError, match="interrupts"):
        replace(duplicate, interrupts_active_conversation=cast(bool, 1))
    media = rule(
        "share_photo",
        "photo_message",
        media_counter_fact="counter.photo_count_today",
        media_limit=2,
    )
    with pytest.raises(ValueError, match="media_limit"):
        replace(media, media_limit=0)
