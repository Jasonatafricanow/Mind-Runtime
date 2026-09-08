"""Pure configuration-owned Intent scoring with inspectable contributions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite

from mind_runtime.contracts import (
    Intent,
    IntentEngineInput,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    ReconsiderationPolicy,
    SemanticEventCandidate,
    SyncFields,
)
from mind_runtime.contracts.common import require_aware_utc, require_non_empty


def _require_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{field_name} must be a finite numeric value")
    return float(value)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class IntentRule:
    """One product/persona-owned deterministic mapping into an Intent kind."""

    rule_id: str
    kind: str
    base_strength: float
    dimension_weights: tuple[tuple[str, float], ...]
    event_kind: str | None
    event_bonus: float
    minimum_strength: float
    due_at_attribute: str | None
    expires_after: timedelta | None
    reconsideration_policy: ReconsiderationPolicy

    def __post_init__(self) -> None:
        require_non_empty(self.rule_id, "rule_id")
        require_non_empty(self.kind, "kind")
        _require_number(self.base_strength, "base_strength")
        _require_number(self.event_bonus, "event_bonus")
        minimum = _require_number(self.minimum_strength, "minimum_strength")
        if not 0 <= minimum <= 1:
            raise ValueError("minimum_strength must be in [0, 1]")
        seen_dimensions: set[str] = set()
        for dimension, weight in self.dimension_weights:
            require_non_empty(dimension, "dimension_weights dimensions")
            _require_number(weight, "dimension weight")
            if dimension in seen_dimensions:
                raise ValueError("dimension_weights dimensions must be unique")
            seen_dimensions.add(dimension)
        if self.event_kind is not None:
            require_non_empty(self.event_kind, "event_kind")
        elif self.event_bonus != 0:
            raise ValueError("event_bonus requires event_kind")
        if self.due_at_attribute is not None:
            require_non_empty(self.due_at_attribute, "due_at_attribute")
            if self.event_kind is None:
                raise ValueError("due_at_attribute requires event_kind")
        if self.expires_after is not None and self.expires_after <= timedelta(0):
            raise ValueError("expires_after must be positive")
        if not isinstance(self.reconsideration_policy, ReconsiderationPolicy):
            raise ValueError("reconsideration_policy must be a ReconsiderationPolicy")


class DeterministicIntentEngine:
    """Apply fixed numeric rules without LLM or permission authority."""

    def __init__(self, rules: tuple[IntentRule, ...], runtime_id: str) -> None:
        require_non_empty(runtime_id, "runtime_id")
        rule_ids: set[str] = set()
        kinds: set[str] = set()
        for rule in rules:
            if rule.rule_id in rule_ids:
                raise ValueError("Intent rule_id values must be unique")
            if rule.kind in kinds:
                raise ValueError("Intent rule kind values must be unique")
            rule_ids.add(rule.rule_id)
            kinds.add(rule.kind)
        self._rules = rules
        self._runtime_id = runtime_id

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        if engine_input.origin_runtime_id != self._runtime_id:
            raise ValueError("intent engine input origin must match runtime_id")
        projected_values = {
            state.dimension: state.value for state in engine_input.projected.projected_states
        }
        candidates: list[Intent] = []
        traces: list[IntentScoreTrace] = []
        for rule in self._rules:
            candidate, trace = self._evaluate_rule(rule, engine_input, projected_values)
            traces.append(trace)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(key=lambda item: (-item.strength, item.kind, item.intent_id))
        return IntentEngineResult(candidates=tuple(candidates), traces=tuple(traces))

    def _evaluate_rule(
        self,
        rule: IntentRule,
        engine_input: IntentEngineInput,
        projected_values: dict[str, object],
    ) -> tuple[Intent | None, IntentScoreTrace]:
        intent_id = f"intent-{engine_input.interaction_id}-{rule.rule_id}"
        contributions = [IntentScoreContribution("base", rule.rule_id, float(rule.base_strength))]
        score = _decimal(float(rule.base_strength))
        for dimension, weight in rule.dimension_weights:
            raw_value = projected_values.get(dimension)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                amount = 0.0
            elif not isfinite(raw_value):
                amount = 0.0
            else:
                amount = float(_decimal(float(raw_value)) * _decimal(float(weight)))
            contributions.append(IntentScoreContribution("dimension", dimension, amount))
            score += _decimal(amount)

        matched_event = self._first_event(rule, engine_input.accepted_events)
        if matched_event is not None:
            contributions.append(
                IntentScoreContribution(
                    "event", matched_event.candidate_id, float(rule.event_bonus)
                )
            )
            score += _decimal(float(rule.event_bonus))

        unclamped = float(score)
        final_strength = min(1.0, max(0.0, unclamped))
        earliest_at = engine_input.clock
        due_at: datetime | None = None
        schedule_valid = True
        if rule.due_at_attribute is not None:
            due_at = self._due_at(matched_event, rule.due_at_attribute)
            if due_at is None:
                schedule_valid = False
            else:
                earliest_at = due_at
        expiry_base = due_at if due_at is not None else engine_input.clock
        expires_at = expiry_base + rule.expires_after if rule.expires_after is not None else None
        if expires_at is not None and expires_at <= engine_input.clock:
            schedule_valid = False

        admitted = schedule_valid and final_strength >= rule.minimum_strength
        if not schedule_valid:
            reason_codes = ("invalid_due_at",)
        elif not admitted:
            reason_codes = ("below_minimum_strength",)
        else:
            reason_codes = ("threshold_met",)
        trace = IntentScoreTrace(
            trace_id=f"intent-score-{engine_input.interaction_id}-{rule.rule_id}",
            scope=engine_input.scope,
            rule_id=rule.rule_id,
            intent_id=intent_id,
            contributions=tuple(contributions),
            unclamped_score=unclamped,
            final_strength=final_strength,
            admitted=admitted,
            reason_codes=reason_codes,
            created_at=engine_input.clock,
        )
        if not admitted:
            return None, trace

        cause_refs = [engine_input.context.situation_id]
        if matched_event is not None:
            cause_refs.append(matched_event.candidate_id)
        candidate = Intent(
            intent_id=intent_id,
            scope=engine_input.scope,
            origin_runtime_id=self._runtime_id,
            kind=rule.kind,
            strength=final_strength,
            earliest_at=earliest_at,
            due_at=due_at,
            expires_at=expires_at,
            reconsideration_policy=rule.reconsideration_policy,
            cause_refs=tuple(cause_refs),
            state_refs=(engine_input.projected.projection_id,),
            status=IntentStatus.CANDIDATE,
            sync=SyncFields(
                scope=engine_input.scope,
                origin_runtime_id=self._runtime_id,
                object_id=intent_id,
                version=1,
                idempotency_key=f"idem-{intent_id}-v1",
            ),
        )
        return candidate, trace

    @staticmethod
    def _first_event(
        rule: IntentRule, accepted_events: tuple[SemanticEventCandidate, ...]
    ) -> SemanticEventCandidate | None:
        if rule.event_kind is None:
            return None
        return next((event for event in accepted_events if event.kind == rule.event_kind), None)

    @staticmethod
    def _due_at(event: SemanticEventCandidate | None, attribute: str) -> datetime | None:
        if event is None:
            return None
        values = tuple(value for key, value in event.attributes if key == attribute)
        if len(values) != 1:
            return None
        try:
            parsed = datetime.fromisoformat(values[0])
            require_aware_utc(parsed, attribute)
        except (TypeError, ValueError):
            return None
        return parsed.astimezone(UTC)
