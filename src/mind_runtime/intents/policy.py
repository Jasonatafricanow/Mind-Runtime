"""Pure fixed-fact ActionPolicy with no LLM or state mutation."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
)
from mind_runtime.contracts.common import require_aware_utc, require_non_empty


@dataclass(frozen=True, slots=True)
class IntentPolicyRule:
    """One configured Intent-kind to currently available action mapping."""

    intent_kind: str
    action_type: str
    proactive: bool
    interrupts_active_conversation: bool
    media_counter_fact: str | None
    media_limit: int | None
    required_resource: str | None

    def __post_init__(self) -> None:
        require_non_empty(self.intent_kind, "intent_kind")
        require_non_empty(self.action_type, "action_type")
        if not isinstance(self.proactive, bool):
            raise ValueError("proactive must be a bool")
        if not isinstance(self.interrupts_active_conversation, bool):
            raise ValueError("interrupts_active_conversation must be a bool")
        if (self.media_counter_fact is None) != (self.media_limit is None):
            raise ValueError("media counter fact and media limit must be configured together")
        if self.media_counter_fact is not None:
            require_non_empty(self.media_counter_fact, "media_counter_fact")
        if self.media_limit is not None and (
            isinstance(self.media_limit, bool) or self.media_limit < 1
        ):
            raise ValueError("media_limit must be at least one")
        if self.required_resource is not None:
            require_non_empty(self.required_resource, "required_resource")


@dataclass(frozen=True, slots=True)
class ActionPolicyConfig:
    """Product-owned fixed rules and global resettable-action cooldown."""

    rules: tuple[IntentPolicyRule, ...]
    proactive_cooldown: timedelta

    def __post_init__(self) -> None:
        if self.proactive_cooldown < timedelta(0):
            raise ValueError("proactive_cooldown cannot be negative")
        seen: set[str] = set()
        for rule in self.rules:
            if rule.intent_kind in seen:
                raise ValueError("Intent policy intent_kind values must be unique")
            seen.add(rule.intent_kind)


class DeterministicActionPolicy:
    """Evaluate only named factual inputs in a stable fail-closed gate order."""

    def __init__(self, config: ActionPolicyConfig, runtime_id: str) -> None:
        require_non_empty(runtime_id, "runtime_id")
        self._config = config
        self._runtime_id = runtime_id
        self._rules = {rule.intent_kind: rule for rule in config.rules}

    def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
        intent = policy_input.intent
        if (
            intent.origin_runtime_id != self._runtime_id
            or policy_input.context.origin_runtime_id != self._runtime_id
        ):
            return self._result(
                policy_input,
                ActionDecision.DENY,
                intent.kind,
                "origin_mismatch",
            )
        if intent.earliest_at is not None and policy_input.clock < intent.earliest_at:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                intent.kind,
                "not_yet_earliest",
            )
        if intent.expires_at is not None and policy_input.clock >= intent.expires_at:
            return self._result(
                policy_input,
                ActionDecision.DENY,
                intent.kind,
                "intent_expired",
            )

        rule = self._rules.get(intent.kind)
        if rule is None:
            return self._result(
                policy_input,
                ActionDecision.DENY,
                intent.kind,
                "unsupported_intent_kind",
            )
        available = policy_input.resources.available_actions
        if rule.action_type not in available:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                "action_unavailable",
            )
        if rule.required_resource is not None and rule.required_resource not in available:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                "required_resource_unavailable",
            )

        facts, duplicate = _facts(policy_input.context.derived_facts)
        if duplicate is not None:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                "duplicate_context_fact",
            )
        interruption = self._interruption_reason(rule, facts)
        if interruption is not None:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                interruption,
            )
        cooldown = self._cooldown_reason(rule, facts, policy_input.clock)
        if cooldown is not None:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                cooldown,
            )
        media = self._media_reason(rule, facts)
        if media is not None:
            return self._result(
                policy_input,
                ActionDecision.DEFER,
                rule.action_type,
                media,
            )
        return self._result(
            policy_input,
            ActionDecision.ALLOW,
            rule.action_type,
            "allowed",
        )

    @staticmethod
    def _interruption_reason(rule: IntentPolicyRule, facts: dict[str, str]) -> str | None:
        if rule.interrupts_active_conversation and "conversation.active" in facts:
            active = _boolean_fact(facts["conversation.active"])
            if active is None:
                return "malformed_conversation_active"
            if active:
                return "active_conversation"
        if rule.proactive and "conversation.pending_reply" in facts:
            pending = _boolean_fact(facts["conversation.pending_reply"])
            if pending is None:
                return "malformed_pending_reply"
            if pending:
                return "pending_reply"
        return None

    def _cooldown_reason(
        self, rule: IntentPolicyRule, facts: dict[str, str], clock: datetime
    ) -> str | None:
        if not rule.proactive or "counter.last_proactive_at" not in facts:
            return None
        last = _timestamp_fact(facts["counter.last_proactive_at"])
        if last is None:
            return "malformed_last_proactive_at"
        if clock < last + self._config.proactive_cooldown:
            return "proactive_cooldown"
        return None

    @staticmethod
    def _media_reason(rule: IntentPolicyRule, facts: dict[str, str]) -> str | None:
        if rule.media_counter_fact is None or rule.media_limit is None:
            return None
        raw_count = facts.get(rule.media_counter_fact)
        if raw_count is None:
            return "missing_media_counter"
        if not raw_count.isdigit():
            return "malformed_media_counter"
        count = int(raw_count)
        if count >= rule.media_limit:
            return "media_budget_exhausted"
        return None

    def _result(
        self,
        policy_input: ActionPolicyInput,
        decision: ActionDecision,
        action_type: str,
        reason: str,
    ) -> ActionPolicyResult:
        intent = policy_input.intent
        suffix = f"{intent.intent_id}-v{intent.sync.version}"
        allowed = decision is ActionDecision.ALLOW
        permission = ActionPermission(
            permission_id=f"permission-{suffix}",
            scope=policy_input.scope,
            origin_runtime_id=self._runtime_id,
            action_type=action_type,
            allowed=allowed,
            reasons=(reason,),
            constraints=() if allowed else (reason,),
        )
        return ActionPolicyResult(
            policy_id=f"policy-{suffix}",
            scope=policy_input.scope,
            origin_runtime_id=self._runtime_id,
            intent_id=intent.intent_id,
            decision=decision,
            permission=permission,
            reason_codes=(reason,),
        )


def _facts(entries: tuple[tuple[str, str], ...]) -> tuple[dict[str, str], str | None]:
    result: dict[str, str] = {}
    for key, value in entries:
        if key in result:
            return result, key
        result[key] = value
    return result, None


def _boolean_fact(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _timestamp_fact(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        require_aware_utc(parsed, "timestamp fact")
    except (TypeError, ValueError):
        return None
    return parsed
