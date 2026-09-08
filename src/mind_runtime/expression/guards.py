"""Deterministic expression guard chain with registered rules only."""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.contracts import (
    DecisionContext,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
)
from mind_runtime.contracts.common import require_non_empty

STRUCTURAL_ORDER = (
    "invalid_expression",
    "scope_mismatch",
    "origin_mismatch",
    "attempt_mismatch",
    "missing_temporal_fact",
    "malformed_temporal_fact",
)

CONTENT_ORDER = (
    "forbidden_opening",
    "prefix_duplicate",
    "temporal_conflict",
)

_GUARD_ID = "deterministic_expression_guard_chain"

_PRIOR_EXPRESSION_KEY = "previous_expression"


def normalize_for_prefix(text: str, markers: tuple[str, ...]) -> str:
    """Strip one configured leading transport marker and Unicode whitespace."""
    value = text.strip()
    for marker in markers:
        if value.startswith(marker):
            value = value[len(marker) :]
            break
    return value.strip()


@dataclass(frozen=True, slots=True)
class TemporalConflictRule:
    rule_id: str
    incompatible_dayparts: tuple[str, ...]
    phrases: tuple[str, ...]
    temporal_fact_key: str

    def __post_init__(self) -> None:
        require_non_empty(self.rule_id, "rule_id")
        if not self.incompatible_dayparts:
            raise ValueError("incompatible_dayparts must not be empty")
        for daypart in self.incompatible_dayparts:
            require_non_empty(daypart, "incompatible_dayparts entries")
        if not self.phrases:
            raise ValueError("phrases must not be empty")
        for phrase in self.phrases:
            require_non_empty(phrase, "phrases entries")
        require_non_empty(self.temporal_fact_key, "temporal_fact_key")


@dataclass(frozen=True, slots=True)
class ExpressionGuardConfig:
    prefix_length: int
    transport_markers: tuple[str, ...]
    banned_openings: tuple[str, ...]
    temporal_rules: tuple[TemporalConflictRule, ...]

    def __post_init__(self) -> None:
        _require_unique_strings(self.transport_markers, "transport_markers")
        _require_unique_strings(self.banned_openings, "banned_openings")
        if (
            isinstance(self.prefix_length, bool)
            or not isinstance(self.prefix_length, int)
            or self.prefix_length < 1
        ):
            raise ValueError("prefix_length must be a positive integer")
        rule_ids: set[str] = set()
        first_fact_key: str | None = None
        for rule in self.temporal_rules:
            if not isinstance(rule, TemporalConflictRule):
                raise ValueError("temporal_rules entries must be TemporalConflictRule")
            if rule.rule_id in rule_ids:
                raise ValueError("temporal rule ids must be unique")
            if first_fact_key is None:
                first_fact_key = rule.temporal_fact_key
            elif rule.temporal_fact_key != first_fact_key:
                raise ValueError("temporal rules must share one temporal fact key")
            rule_ids.add(rule.rule_id)


def _require_unique_strings(values: tuple[str, ...], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        require_non_empty(value, f"{field_name} entries")
        if value in seen:
            raise ValueError(f"{field_name} entries must be unique")
        seen.add(value)


class DeterministicExpressionGuardChain:
    """Evaluate registered guards in fixed order; never calls a model."""

    def __init__(self, config: ExpressionGuardConfig) -> None:
        if not isinstance(config, ExpressionGuardConfig):
            raise ValueError("config must be an ExpressionGuardConfig")
        self._config = config
        self._temporal_fact_key = (
            config.temporal_rules[0].temporal_fact_key if config.temporal_rules else None
        )

    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        if not isinstance(guard_input, ExpressionGuardInput):
            raise ValueError("guard_input must be an ExpressionGuardInput")
        context = guard_input.decision_context
        expression = guard_input.expression
        structural = self._structural_violations(context, expression)
        if structural:
            return self._result(context, expression, ExpressionDisposition.REJECT, structural)
        content = self._content_violations(context, expression)
        if content:
            return self._result(context, expression, ExpressionDisposition.REWRITE, content)
        return self._result(context, expression, ExpressionDisposition.ACCEPT, ())

    def _structural_violations(self, context: DecisionContext, expression: str) -> tuple[str, ...]:
        violations: list[str] = []
        if not expression.strip():
            violations.append("invalid_expression")
        if self._temporal_fact_key is not None:
            facts = self._typed_items(context, ExpressionContextKind.FACT, self._temporal_fact_key)
            if not facts:
                violations.append("missing_temporal_fact")
            elif len(facts) > 1:
                violations.append("malformed_temporal_fact")
        return tuple(code for code in STRUCTURAL_ORDER if code in violations)

    def _content_violations(self, context: DecisionContext, expression: str) -> tuple[str, ...]:
        violations: list[str] = []
        prior_items = self._typed_items(
            context, ExpressionContextKind.PRIOR_EXPRESSION, _PRIOR_EXPRESSION_KEY
        )
        prior = prior_items[0].value if prior_items else None
        normalized = normalize_for_prefix(expression, self._config.transport_markers)
        if prior is not None:
            for opening in self._config.banned_openings:
                if normalized.startswith(opening):
                    violations.append("forbidden_opening")
                    break
            normalized_prior = normalize_for_prefix(prior, self._config.transport_markers)
            prefix = self._config.prefix_length
            if normalized_prior and normalized[:prefix] == normalized_prior[:prefix]:
                violations.append("prefix_duplicate")
        if self._temporal_fact_key is not None:
            facts = self._typed_items(context, ExpressionContextKind.FACT, self._temporal_fact_key)
            # Structural evaluation already guarantees exactly one typed
            # temporal fact (missing/malformed reject before content checks).
            daypart = facts[0].value
            for rule in self._config.temporal_rules:
                if daypart in rule.incompatible_dayparts and any(
                    phrase in expression for phrase in rule.phrases
                ):
                    violations.append("temporal_conflict")
                    break
        return tuple(code for code in CONTENT_ORDER if code in violations)

    def _result(
        self,
        context: DecisionContext,
        expression: str,
        disposition: ExpressionDisposition,
        violations: tuple[str, ...],
    ) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id=_GUARD_ID,
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            expression=expression,
            disposition=disposition,
            violations=violations,
        )

    @staticmethod
    def _typed_items(
        context: DecisionContext, kind: ExpressionContextKind, key: str
    ) -> list[ExpressionContextItem]:
        return [
            item for item in context.expression_context if item.kind is kind and item.key == key
        ]
