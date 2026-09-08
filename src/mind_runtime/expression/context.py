"""Compile authorized runtime objects into bounded provider-visible context."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyResult,
    DecisionContext,
    DecisionContextCompileTrace,
    ExpressionContextItem,
    ExpressionContextKind,
    Intent,
    PreviousExpression,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SlowStateProjection,
    StateDefinition,
    StateDomain,
)
from mind_runtime.contracts.common import require_non_empty
from typing import Protocol, runtime_checkable


@runtime_checkable
class StateDefinitionRegistry(Protocol):
    """Protocol for state definition lookup in expression compiler."""

    def get(self, key: str) -> StateDefinition | None:
        ...

REWRITE_GUIDANCE: dict[str, str] = {
    "forbidden_opening": "Use a different opening.",
    "prefix_duplicate": "Start with a distinct first phrase.",
    "temporal_conflict": "Use wording consistent with the supplied time context.",
}

_SECTION_ORDER = {
    ExpressionContextKind.ACTION: 0,
    ExpressionContextKind.FACT: 1,
    ExpressionContextKind.INTERNAL_STATE: 2,
    ExpressionContextKind.POLICY_CONSTRAINT: 3,
    ExpressionContextKind.PERSONA_STYLE: 4,
    ExpressionContextKind.HISTORY: 5,
    ExpressionContextKind.PRIOR_EXPRESSION: 6,
    ExpressionContextKind.REWRITE_GUIDANCE: 7,
}
_ESSENTIAL_KINDS = {
    ExpressionContextKind.ACTION,
    ExpressionContextKind.POLICY_CONSTRAINT,
}


def _require_positive_integer(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_non_negative_integer(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AffectBand:
    upper_bound: float
    label: str

    def __post_init__(self) -> None:
        if isinstance(self.upper_bound, bool) or not isinstance(self.upper_bound, (int, float)):
            raise ValueError("upper_bound must be a finite number")
        if not isfinite(float(self.upper_bound)):
            raise ValueError("upper_bound must be a finite number")
        require_non_empty(self.label, "label")


@dataclass(frozen=True, slots=True)
class AffectExpressionRule:
    dimension: str
    output_key: str
    bands: tuple[AffectBand, ...]
    priority: int

    def __post_init__(self) -> None:
        require_non_empty(self.dimension, "dimension")
        require_non_empty(self.output_key, "output_key")
        if not self.bands:
            raise ValueError("bands must not be empty")
        previous_bound: float | None = None
        for band in self.bands:
            if not isinstance(band, AffectBand):
                raise ValueError("bands entries must be AffectBand")
            if previous_bound is not None and band.upper_bound <= previous_bound:
                raise ValueError("bands must be strictly increasing")
            previous_bound = float(band.upper_bound)
        if self.bands[-1].upper_bound < 1.0:
            raise ValueError("final band must cover the dimension range")
        _require_non_negative_integer(self.priority, "priority")


@dataclass(frozen=True, slots=True)
class DecisionContextConfig:
    allowed_situation_facts: tuple[str, ...]
    affect_rules: tuple[AffectExpressionRule, ...]
    persona_style_constraints: tuple[tuple[str, str], ...]
    allowed_history_kinds: tuple[str, ...]
    max_history_items: int
    max_prior_expression_chars: int
    max_item_chars: int
    max_items: int
    max_render_chars: int

    def __post_init__(self) -> None:
        _require_unique_strings(self.allowed_situation_facts, "allowed_situation_facts")
        _require_unique_strings(self.allowed_history_kinds, "allowed_history_kinds")
        dimensions: set[str] = set()
        output_keys: set[str] = set()
        for rule in self.affect_rules:
            if not isinstance(rule, AffectExpressionRule):
                raise ValueError("affect_rules entries must be AffectExpressionRule")
            if rule.dimension in dimensions or rule.output_key in output_keys:
                raise ValueError("affect rules dimensions and output keys must be unique")
            dimensions.add(rule.dimension)
            output_keys.add(rule.output_key)
        style_keys: set[str] = set()
        for constraint in self.persona_style_constraints:
            if not isinstance(constraint, tuple) or len(constraint) != 2:
                raise ValueError("persona_style_constraints entries must be key/value pairs")
            key, value = constraint
            require_non_empty(key, "persona_style_constraints keys")
            require_non_empty(value, "persona_style_constraints values")
            if key in style_keys:
                raise ValueError("persona_style_constraints keys must be unique")
            style_keys.add(key)
        for field_name in (
            "max_history_items",
            "max_prior_expression_chars",
            "max_item_chars",
            "max_items",
            "max_render_chars",
        ):
            _require_positive_integer(getattr(self, field_name), field_name)


def _require_unique_strings(values: tuple[str, ...], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        require_non_empty(value, f"{field_name} entries")
        if value in seen:
            raise ValueError(f"{field_name} entries must be unique")
        seen.add(value)


@dataclass(frozen=True, slots=True)
class DecisionContextCompilerInput:
    interaction_id: str
    scope: Scope
    origin_runtime_id: str
    situation: Situation
    effective_user_state: RuntimeState
    projected_agent_state: ProjectedMindState
    assessment_trace_ref: str
    intent: Intent
    policy_result: ActionPolicyResult
    persona_ref: str | None
    prior_expression: PreviousExpression | None
    attempt: int
    rewrite_reason_codes: tuple[str, ...]
    # C10-C1: authoritative agent.slow.* RuntimeState records read from
    # SQLite at turn-runtime.  Carried verbatim — no band mapping, no
    # threshold, no coefficient applied here.  Empty tuple when no
    # registered slow dimensions are present.
    slow_state_records: SlowStateProjection = ()
    state_definitions: StateDefinitionRegistry | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.interaction_id, "interaction_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        require_non_empty(self.assessment_trace_ref, "assessment_trace_ref")
        if self.persona_ref is not None:
            require_non_empty(self.persona_ref, "persona_ref")
        _require_non_negative_integer(self.attempt, "attempt")
        for reason_code in self.rewrite_reason_codes:
            require_non_empty(reason_code, "rewrite_reason_codes entries")
        if self.state_definitions is not None and not isinstance(
            self.state_definitions, StateDefinitionRegistry
        ):
            raise ValueError("state_definitions must be a StateDefinitionRegistry")
        # C10-C1: validate each slow record has non-empty state_id and
        # dimension; origin_runtime_id and scope are validated against
        # the compiler input authority in _validate_authority().
        for slow_state in self.slow_state_records:
            if not isinstance(slow_state, RuntimeState):
                raise ValueError("slow_state_records entries must be RuntimeState")
            require_non_empty(slow_state.state_id, "slow_state.state_id")
            require_non_empty(slow_state.dimension, "slow_state.dimension")


class DecisionContextCompiler:
    """A deterministic, non-persistent projection into expression context."""

    def __init__(
        self,
        config: DecisionContextConfig,
        *,
        definitions: StateDefinitionRegistry | None = None,
    ) -> None:
        if not isinstance(config, DecisionContextConfig):
            raise ValueError("config must be a DecisionContextConfig")
        if definitions is not None and not isinstance(definitions, StateDefinitionRegistry):
            raise ValueError("definitions must be a StateDefinitionRegistry")
        self._config = config
        self._definitions = definitions

    def compile(
        self, compiler_input: DecisionContextCompilerInput
    ) -> tuple[DecisionContext, DecisionContextCompileTrace]:
        self._validate_authority(compiler_input)
        candidates = self._action_items(compiler_input)
        candidates += self._fact_items(compiler_input.situation)
        candidates += self._affect_items(compiler_input.projected_agent_state)
        # C10-C1: emit slow-state items from the authoritative projection.
        candidates += self._slow_state_items(compiler_input.slow_state_records)
        candidates += self._style_items(compiler_input.persona_ref)
        candidates += self._history_items(
            compiler_input.situation.historical_context, compiler_input
        )
        candidates += self._prior_expression_items(compiler_input.prior_expression, compiler_input)
        candidates += self._rewrite_items(compiler_input.rewrite_reason_codes)
        included, omitted = self._fit_item_budget(candidates)
        context = self._context(compiler_input, included)
        return context, self._trace(context, included, omitted, compiler_input.rewrite_reason_codes)

    def retry(
        self, context: DecisionContext, reason_codes: tuple[str, ...]
    ) -> tuple[DecisionContext, DecisionContextCompileTrace]:
        if not isinstance(context, DecisionContext):
            raise ValueError("context must be a DecisionContext")
        guidance = self._rewrite_items(reason_codes)
        retained = tuple(
            item
            for item in context.expression_context
            if item.kind is not ExpressionContextKind.REWRITE_GUIDANCE
        )
        retry_items = retained + tuple(guidance)
        if len(retry_items) > self._config.max_items:
            raise ValueError("retry context exceeds max_items")
        if sum(len(item.value) for item in retry_items) > self._config.max_render_chars:
            raise ValueError("retry context exceeds max_render_chars")
        attempt = context.attempt + 1
        retry_context = DecisionContext(
            context_id=f"context-{context.interaction_ref}-a{attempt}",
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            interaction_ref=context.interaction_ref,
            situation_ref=context.situation_ref,
            effective_user_state_ref=context.effective_user_state_ref,
            projected_agent_state_ref=context.projected_agent_state_ref,
            relationship_state_refs=context.relationship_state_refs,
            historical_context_ref=context.historical_context_ref,
            assessment_trace_ref=context.assessment_trace_ref,
            intent_ref=context.intent_ref,
            policy_result_ref=context.policy_result_ref,
            relevant_persona_ref=context.relevant_persona_ref,
            goals_refs=context.goals_refs,
            selected_intent_kind=context.selected_intent_kind,
            selected_action_type=context.selected_action_type,
            attempt=attempt,
            expression_context=retry_items,
            slow_state_projection_refs=context.slow_state_projection_refs,
        )
        return retry_context, self._trace(retry_context, retry_items, (), reason_codes)

    def _validate_authority(self, compiler_input: DecisionContextCompilerInput) -> None:
        if not isinstance(compiler_input, DecisionContextCompilerInput):
            raise ValueError("compiler_input must be a DecisionContextCompilerInput")
        scope = compiler_input.scope
        origin = compiler_input.origin_runtime_id
        situation = compiler_input.situation
        effective_state = compiler_input.effective_user_state
        projected = compiler_input.projected_agent_state
        intent = compiler_input.intent
        policy = compiler_input.policy_result
        if situation.scope != scope:
            raise ValueError("Situation scope must match compiler input scope")
        if effective_state.scope != scope:
            raise ValueError("effective user state scope must match compiler input scope")
        if intent.scope != scope or policy.scope != scope:
            raise ValueError("Intent and Policy scope must match compiler input scope")
        if projected.scope != scope and projected.scope.domain is not ScopeDomain.AGENT:
            raise ValueError("projected agent state scope must match or be an agent scope")
        for value, name in (
            (situation.origin_runtime_id, "Situation"),
            (effective_state.origin_runtime_id, "effective user state"),
            (projected.origin_runtime_id, "projected agent state"),
            (intent.origin_runtime_id, "Intent"),
            (policy.origin_runtime_id, "Policy"),
        ):
            if value != origin:
                raise ValueError(f"{name} origin must match compiler input origin")
        if policy.intent_id != intent.intent_id:
            raise ValueError("Policy intent must match selected Intent")
        if policy.decision is not ActionDecision.ALLOW or policy.permission is None:
            raise ValueError("Policy must ALLOW the selected Intent")
        # The ActionPolicyResult contract (contracts/action.py) already
        # guarantees ALLOW carries an allowed permission, so no second
        # permission.allowed check is needed here.
        self._validate_prior(compiler_input.prior_expression, compiler_input)
        self._validate_reason_codes(compiler_input.rewrite_reason_codes)
        # C10-C1 / C10-C2: validate that every slow-state record originates from the
        # same runtime and that cross-scope AGENT slow-states are authorized
        # by registered accumulator StateDefinitions matching the composed agent.
        definitions = compiler_input.state_definitions or self._definitions
        for slow_state in compiler_input.slow_state_records:
            if slow_state.origin_runtime_id != origin:
                raise ValueError(
                    f"slow_state origin_runtime_id mismatch: "
                    f"expected {origin!r}, got {slow_state.origin_runtime_id!r}"
                )
            if slow_state.scope == scope:
                if definitions is not None:
                    defn = definitions.get(slow_state.dimension)
                    if defn is not None and defn.dynamics_policy != "accumulator":
                        raise ValueError(
                            f"slow_state dimension {slow_state.dimension!r} is not an accumulator "
                            f"(dynamics_policy={defn.dynamics_policy!r})"
                        )
                continue

            # Cross-scope projection: only authorized longitudinal AGENT slow state
            # is permitted into current (e.g. USER) DecisionContext.
            if slow_state.scope.domain is not ScopeDomain.AGENT:
                raise ValueError(
                    f"slow_state scope mismatch: expected {scope!r}, got {slow_state.scope!r}"
                )

            # Security / Identity check: ensure AGENT slow state belongs to the same
            # agent being composed.
            agent_id = slow_state.scope.agent_id
            persona_id = slow_state.scope.persona_id
            has_agent_context = False

            if compiler_input.persona_ref is not None:
                has_agent_context = True
                if persona_id != compiler_input.persona_ref and agent_id != compiler_input.persona_ref:
                    raise ValueError(
                        f"slow_state agent identity mismatch: "
                        f"expected {compiler_input.persona_ref!r}, got {slow_state.scope!r}"
                    )

            if projected.scope.domain is ScopeDomain.AGENT:
                has_agent_context = True
                agent_match = (
                    projected.scope.agent_id is not None
                    and agent_id == projected.scope.agent_id
                )
                persona_match = (
                    projected.scope.persona_id is not None
                    and persona_id == projected.scope.persona_id
                )
                if not (agent_match or persona_match):
                    raise ValueError(
                        f"slow_state agent identity mismatch with projected agent state: "
                        f"expected {projected.scope!r}, got {slow_state.scope!r}"
                    )

            if not has_agent_context:
                raise ValueError(
                    f"cross-scope slow_state requires agent context in compiler input: "
                    f"got {slow_state.scope!r}"
                )

            # Longitudinal StateDefinition authorization:
            # Must have registered StateDefinition with dynamics_policy == 'accumulator'
            # and matching domain.
            if definitions is None:
                raise ValueError(
                    f"cross-scope slow_state {slow_state.dimension!r} requires StateDefinitionRegistry"
                )

            defn = definitions.get(slow_state.dimension)
            if defn is None:
                raise ValueError(
                    f"slow_state dimension {slow_state.dimension!r} has no registered StateDefinition"
                )
            if defn.dynamics_policy != "accumulator":
                raise ValueError(
                    f"slow_state dimension {slow_state.dimension!r} is not an accumulator "
                    f"(dynamics_policy={defn.dynamics_policy!r})"
                )
            if defn.domain.value != slow_state.scope.domain.value:
                raise ValueError(
                    f"slow_state scope domain {slow_state.scope.domain!r} does not match "
                    f"StateDefinition domain {defn.domain!r}"
                )

    def _action_items(
        self, compiler_input: DecisionContextCompilerInput
    ) -> list[ExpressionContextItem]:
        policy = compiler_input.policy_result
        assert policy.permission is not None
        items = [
            ExpressionContextItem(
                "action-selected_action",
                ExpressionContextKind.ACTION,
                "selected_action",
                policy.permission.action_type,
                (policy.policy_id, policy.permission.permission_id),
                0,
            )
        ]
        constraints = policy.permission.constraints
        if len(set(constraints)) != len(constraints):
            raise ValueError("Policy constraints must be unique")
        for constraint in constraints:
            items.append(
                ExpressionContextItem(
                    f"policy_constraint-{constraint}",
                    ExpressionContextKind.POLICY_CONSTRAINT,
                    constraint,
                    constraint,
                    (policy.policy_id, policy.permission.permission_id),
                    10,
                )
            )
        return items

    def _fact_items(self, situation: Situation) -> list[ExpressionContextItem]:
        by_key: dict[str, str] = {}
        for key, value in situation.derived_facts:
            if key in self._config.allowed_situation_facts:
                if key in by_key:
                    raise ValueError("allowed Situation facts must not be duplicate")
                by_key[key] = value
        return [
            ExpressionContextItem(
                f"fact-{key}",
                ExpressionContextKind.FACT,
                key,
                value,
                (situation.situation_id,),
                10,
            )
            for key, value in by_key.items()
        ]

    def _affect_items(self, projected: ProjectedMindState) -> list[ExpressionContextItem]:
        states = {state.dimension: state for state in projected.projected_states}
        items: list[ExpressionContextItem] = []
        for rule in self._config.affect_rules:
            state = states.get(rule.dimension)
            if state is None:
                continue
            label = self._affect_label(state, rule)
            items.append(
                ExpressionContextItem(
                    f"internal_state-{rule.output_key}",
                    ExpressionContextKind.INTERNAL_STATE,
                    rule.output_key,
                    label,
                    (projected.projection_id, state.state_id),
                    rule.priority,
                )
            )
        return items

    def _affect_label(self, state: RuntimeState, rule: AffectExpressionRule) -> str:
        value = state.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError(f"affect value for {rule.dimension} must be a finite number")
        for band in rule.bands:
            if value <= band.upper_bound:
                return band.label
        raise ValueError(f"affect value for {rule.dimension} is outside configured bands")

    # C10-C1: emit INTERNAL_STATE items from the authoritative slow-state
    # projection.  Each item carries the raw float value as a string (no
    # band mapping, no coefficient).  Key prefix "slow_" distinguishes slow
    # from affect; source_refs carry (label, state_id, version) for
    # traceability.  Priority 40 places slow items in the same sort band
    # as affect items (INTERNAL_STATE section).
    def _slow_state_items(
        self, slow_records: SlowStateProjection
    ) -> list[ExpressionContextItem]:
        if not slow_records:
            return []
        items: list[ExpressionContextItem] = []
        for state in slow_records:
            value = state.value
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(
                    f"slow_state value for {state.dimension} must be a finite number"
                )
            items.append(
                ExpressionContextItem(
                    f"internal_state-slow_{state.dimension}",
                    ExpressionContextKind.INTERNAL_STATE,
                    f"slow_{state.dimension}",
                    str(value),
                    ("slow", state.state_id, f"v{state.version}"),
                    40,
                )
            )
        return items

    def _style_items(self, persona_ref: str | None) -> list[ExpressionContextItem]:
        if persona_ref is None:
            return []
        return [
            ExpressionContextItem(
                f"persona_style-{key}",
                ExpressionContextKind.PERSONA_STYLE,
                key,
                value,
                (persona_ref,),
                20,
            )
            for key, value in self._config.persona_style_constraints
        ]

    def _history_items(
        self, history: object, compiler_input: DecisionContextCompilerInput
    ) -> list[ExpressionContextItem]:
        if history is None:
            return []
        from mind_runtime.contracts import HistoricalContextBundle, HistoricalContextItem

        if not isinstance(history, HistoricalContextBundle):
            raise ValueError("historical_context must be a HistoricalContextBundle")
        if (
            history.scope != compiler_input.scope
            or history.origin_runtime_id != compiler_input.origin_runtime_id
        ):
            raise ValueError("historical context scope and origin must match compiler input")
        entries: list[HistoricalContextItem] = []
        for collection in (history.episodes, history.stable_facts, history.relationship_events):
            entries.extend(collection)
        selected: list[HistoricalContextItem] = []
        for item in entries:
            if item.scope != compiler_input.scope:
                raise ValueError("historical item scope must match compiler input")
            if item.kind in self._config.allowed_history_kinds:
                if not item.source_refs:
                    raise ValueError("included historical items require source refs")
                selected.append(item)
        selected.sort(key=lambda item: (-(item.relevance_hint or 0.0), item.item_id))
        return [
            ExpressionContextItem(
                f"history-{item.item_id}",
                ExpressionContextKind.HISTORY,
                item.item_id,
                item.proposition,
                item.source_refs,
                30,
            )
            for item in selected[: self._config.max_history_items]
        ]

    def _prior_expression_items(
        self, prior: PreviousExpression | None, compiler_input: DecisionContextCompilerInput
    ) -> list[ExpressionContextItem]:
        if prior is None:
            return []
        return [
            ExpressionContextItem(
                "prior_expression-previous_expression",
                ExpressionContextKind.PRIOR_EXPRESSION,
                "previous_expression",
                prior.text[: self._config.max_prior_expression_chars],
                (prior.expression_id, prior.receipt_ref),
                30,
            )
        ]

    def _rewrite_items(self, reason_codes: tuple[str, ...]) -> list[ExpressionContextItem]:
        self._validate_reason_codes(reason_codes)
        return [
            ExpressionContextItem(
                f"rewrite_guidance-{reason_code}",
                ExpressionContextKind.REWRITE_GUIDANCE,
                reason_code,
                REWRITE_GUIDANCE[reason_code],
                ("product:rewrite_guidance",),
                40,
            )
            for reason_code in sorted(reason_codes)
        ]

    def _validate_prior(
        self, prior: PreviousExpression | None, compiler_input: DecisionContextCompilerInput
    ) -> None:
        if prior is None:
            return
        if not isinstance(prior, PreviousExpression):
            raise ValueError("prior expression must be a PreviousExpression")
        if prior.scope != compiler_input.scope:
            raise ValueError("prior expression scope must match compiler input scope")
        if prior.origin_runtime_id != compiler_input.origin_runtime_id:
            raise ValueError("prior expression origin must match compiler input origin")
        permission = compiler_input.policy_result.permission
        assert permission is not None
        if prior.action_type != permission.action_type:
            raise ValueError("prior expression action type must match Policy action type")

    def _validate_reason_codes(self, reason_codes: tuple[str, ...]) -> None:
        unknown = sorted(set(reason_codes) - REWRITE_GUIDANCE.keys())
        if unknown:
            raise ValueError(f"unknown rewrite reason codes: {unknown}")
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("rewrite reason codes must be unique")

    def _fit_item_budget(
        self, candidates: list[ExpressionContextItem]
    ) -> tuple[tuple[ExpressionContextItem, ...], tuple[ExpressionContextItem, ...]]:
        ordered = tuple(sorted(candidates, key=_item_sort_key))
        included: list[ExpressionContextItem] = []
        omitted: list[ExpressionContextItem] = []
        total_chars = 0
        for item in ordered:
            item_chars = len(item.value)
            essential = item.kind in _ESSENTIAL_KINDS
            if item_chars > self._config.max_item_chars:
                if essential:
                    raise ValueError("essential context item exceeds max_item_chars")
                omitted.append(item)
                continue
            exceeds_budget = (
                len(included) + 1 > self._config.max_items
                or total_chars + item_chars > self._config.max_render_chars
            )
            if exceeds_budget:
                if essential:
                    raise ValueError("essential context items exceed configured budget")
                omitted.append(item)
                continue
            included.append(item)
            total_chars += item_chars
        return tuple(included), tuple(omitted)

    def _context(
        self, compiler_input: DecisionContextCompilerInput, items: tuple[ExpressionContextItem, ...]
    ) -> DecisionContext:
        situation = compiler_input.situation
        policy = compiler_input.policy_result
        assert policy.permission is not None
        # C10-C1: carry authoritative slow-state state_ids into the
        # DecisionContext so downstream consumers can resolve them back
        # to the B-W state rows.
        slow_refs = tuple(state.state_id for state in compiler_input.slow_state_records)
        return DecisionContext(
            context_id=f"context-{compiler_input.interaction_id}-a{compiler_input.attempt}",
            scope=compiler_input.scope,
            origin_runtime_id=compiler_input.origin_runtime_id,
            interaction_ref=compiler_input.interaction_id,
            situation_ref=situation.situation_id,
            effective_user_state_ref=compiler_input.effective_user_state.state_id,
            projected_agent_state_ref=compiler_input.projected_agent_state.projection_id,
            relationship_state_refs=situation.relationship_ids,
            historical_context_ref=(
                situation.historical_context.bundle_id
                if situation.historical_context is not None
                else None
            ),
            assessment_trace_ref=compiler_input.assessment_trace_ref,
            intent_ref=compiler_input.intent.intent_id,
            policy_result_ref=policy.policy_id,
            relevant_persona_ref=compiler_input.persona_ref,
            goals_refs=(),
            selected_intent_kind=compiler_input.intent.kind,
            selected_action_type=policy.permission.action_type,
            attempt=compiler_input.attempt,
            expression_context=items,
            slow_state_projection_refs=slow_refs,
        )

    def _trace(
        self,
        context: DecisionContext,
        included: tuple[ExpressionContextItem, ...],
        omitted: tuple[ExpressionContextItem, ...],
        reason_codes: tuple[str, ...],
    ) -> DecisionContextCompileTrace:
        return DecisionContextCompileTrace(
            trace_id=f"compile-{context.context_id}",
            context_id=context.context_id,
            included_item_refs=tuple(item.item_id for item in included),
            omitted_item_refs=tuple(item.item_id for item in omitted),
            reason_codes=tuple(sorted(reason_codes)),
        )


def _item_sort_key(item: ExpressionContextItem) -> tuple[int, int, str, tuple[str, ...], str]:
    return (_SECTION_ORDER[item.kind], item.priority, item.key, item.source_refs, item.item_id)
