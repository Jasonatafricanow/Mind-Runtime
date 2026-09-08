"""Default typed stubs for the compressed walking skeleton."""

from datetime import UTC, datetime
from typing import cast

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyInput,
    ActionPolicyResult,
    AppraisalPath,
    AppraisalRouteDecision,
    AssessmentTrace,
    DecisionContext,
    DecisionContextCompileTrace,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    ExpressionAttemptTrace,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    ExpressionOutcome,
    Intent,
    IntentEngineInput,
    IntentEngineResult,
    IntentScoreContribution,
    IntentScoreTrace,
    IntentStatus,
    Interaction,
    ProjectedMindState,
    ProviderExpressionContext,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    Situation,
    SyncFields,
)
from mind_runtime.expression.context import DecisionContextCompilerInput
from mind_runtime.pipeline.ports import (
    AgentPort,
    ContextRendererPort,
    ExpressionGuardPort,
)
from mind_runtime.providers.clock import Clock
from mind_runtime.state.resolver import EffectiveStateView


def _now(clock: datetime) -> datetime:
    return clock if clock.tzinfo is not None else clock.replace(tzinfo=UTC)


class StubEffectiveState:
    """Return a passthrough RuntimeState without semantic interpretation."""

    overlay_supported = True

    def effective(
        self,
        *,
        interaction_id: str,
        evidence_refs: tuple[str, ...],
        canonical_snapshot: tuple[RuntimeState, ...],
        scope: Scope,
        clock: datetime,
    ) -> RuntimeState:
        now = _now(clock)
        if canonical_snapshot:
            return canonical_snapshot[0]
        dimension = f"{scope.domain.value}.effective"
        return RuntimeState(
            state_id=f"effective-{interaction_id}",
            scope=scope,
            origin_runtime_id="runtime-1",
            dimension=dimension,
            value={"evidence_refs": list(evidence_refs)},
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=evidence_refs,
            transition_refs=(),
            updated_at=now,
            version=1,
            sync=SyncFields(scope, "runtime-1", f"effective-{interaction_id}", 1, "idem-eff"),
        )


class StubSituation:
    """Return a factual Context frame carrying only the effective-state ref."""

    def build(
        self,
        *,
        interaction: Interaction,
        effective_view: EffectiveStateView,
        scope: Scope,
        clock: datetime,
    ) -> Situation:
        ref = effective_view.states[0].state_id if effective_view.states else "none"
        return Situation(
            situation_id=f"situation-{interaction.interaction_id}",
            scope=scope,
            origin_runtime_id="runtime-1",
            derived_facts=(("stub", "pass"),),
            effective_state_ref=ref,
            observed_at=_now(clock),
            historical_context=None,
            persona_id=None,
            relationship_ids=(),
            evidence_refs=(),
        )


class StubEmotionalTransition:
    """Return one uncommitted projection, candidate Intent, and empty trace."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        now = self._clock.now()
        scope = transition_input.scope
        interaction_id = transition_input.interaction_id
        state_id = f"projected-{interaction_id}"
        state = RuntimeState(
            state_id=state_id,
            scope=scope,
            origin_runtime_id=transition_input.origin_runtime_id,
            dimension=f"{scope.domain.value}.affect.stub",
            value="stub",
            status="active",
            valid_from=now,
            valid_until=None,
            relevant_until=None,
            last_observed_at=now,
            evidence_refs=transition_input.context.evidence_refs,
            transition_refs=(),
            updated_at=now,
            version=1,
            sync=SyncFields(
                scope,
                transition_input.origin_runtime_id,
                state_id,
                1,
                f"idem-{state_id}",
            ),
        )
        projection_id = f"projection-{interaction_id}"
        projected = ProjectedMindState(
            projection_id=projection_id,
            scope=scope,
            origin_runtime_id=transition_input.origin_runtime_id,
            projected_states=(state,),
            sync=SyncFields(
                scope,
                transition_input.origin_runtime_id,
                projection_id,
                1,
                f"idem-{projection_id}",
            ),
            committed=False,
        )
        trace_id = f"assessment-{interaction_id}"
        trace = AssessmentTrace(
            trace_id=trace_id,
            scope=scope,
            origin_runtime_id=transition_input.origin_runtime_id,
            context_ref=transition_input.context.situation_id,
            persona_id=transition_input.persona_id,
            persona_version=transition_input.persona_version,
            state_before=tuple(
                (state.dimension, float(cast(float, state.value)))
                for state in transition_input.current_affect
            ),
            contributions=(),
            state_after=tuple(
                (state.dimension, float(cast(float, state.value)))
                for state in transition_input.current_affect
            ),
            evidence_refs=transition_input.context.evidence_refs,
            history_refs=(
                transition_input.history_context.source_refs
                if transition_input.history_context is not None
                else ()
            ),
            abstention_reasons=(),
            route_decision=AppraisalRouteDecision(
                route_id=f"route-{interaction_id}",
                scope=scope,
                path=(
                    AppraisalPath.TYPED_MAPPING
                    if transition_input.semantic_candidates
                    else AppraisalPath.DETERMINISTIC
                ),
                ambiguity_score=0.0,
                confidence=1.0,
                reason_codes=(
                    "candidate_supplied"
                    if transition_input.semantic_candidates
                    else "no_semantic_event",
                ),
            ),
            created_at=now,
        )
        return EmotionalTransitionResult(
            projected=projected,
            accepted_events=(),
            assessment_trace=trace,
        )


class StubIntentEngine:
    """Preserve one immediate walking-skeleton response candidate."""

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        intent_id = f"intent-{engine_input.interaction_id}"
        candidate = Intent(
            intent_id=intent_id,
            scope=engine_input.scope,
            origin_runtime_id=engine_input.origin_runtime_id,
            kind="respond",
            strength=0.5,
            earliest_at=engine_input.clock,
            due_at=None,
            expires_at=None,
            reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
            cause_refs=(engine_input.context.situation_id,),
            state_refs=(engine_input.projected.projection_id,),
            status=IntentStatus.CANDIDATE,
            sync=SyncFields(
                engine_input.scope,
                engine_input.origin_runtime_id,
                intent_id,
                1,
                f"idem-{intent_id}-v1",
            ),
        )
        trace = IntentScoreTrace(
            trace_id=f"intent-score-{engine_input.interaction_id}-respond",
            scope=engine_input.scope,
            rule_id="stub-respond",
            intent_id=intent_id,
            contributions=(
                IntentScoreContribution(
                    source_kind="stub",
                    source_ref="walking_skeleton",
                    amount=0.5,
                ),
            ),
            unclamped_score=0.5,
            final_strength=0.5,
            admitted=True,
            reason_codes=("stub",),
            created_at=engine_input.clock,
        )
        return IntentEngineResult(candidates=(candidate,), traces=(trace,))


class StubActionPolicy:
    """Allow the candidate for walking-skeleton plumbing only."""

    def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
        intent = policy_input.intent
        scope = policy_input.scope
        return ActionPolicyResult(
            policy_id=f"policy-{intent.intent_id}",
            scope=scope,
            origin_runtime_id=intent.origin_runtime_id,
            intent_id=intent.intent_id,
            decision=ActionDecision.ALLOW,
            permission=ActionPermission(
                permission_id=f"permission-{intent.intent_id}",
                scope=scope,
                origin_runtime_id=intent.origin_runtime_id,
                action_type=intent.kind,
                allowed=True,
                reasons=("stub",),
                constraints=(),
            ),
            reason_codes=("stub",),
        )


class StubContextRenderer:
    """Render the walking-skeleton action item without exposing raw objects."""

    def render(self, context: DecisionContext) -> ProviderExpressionContext:
        action = next(item for item in context.expression_context if item.kind.value == "action")
        return ProviderExpressionContext(
            render_id=f"render-{context.context_id}",
            context_id=context.context_id,
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            text=f"selected_action={action.value}",
            included_item_ids=(action.item_id,),
            omitted_item_ids=(),
        )


class StubExpressionGuard:
    """Return an accepted guard result."""

    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        return ExpressionGuardResult(
            guard_id="guard-stub",
            scope=guard_input.decision_context.scope,
            origin_runtime_id=guard_input.decision_context.origin_runtime_id,
            expression=guard_input.expression,
            disposition=ExpressionDisposition.ACCEPT,
            violations=(),
        )


class StubDecisionContextCompiler:
    """Walking-skeleton compiler: one ACTION item plus the final D9 refs."""

    def compile(
        self, compiler_input: DecisionContextCompilerInput
    ) -> tuple[DecisionContext, DecisionContextCompileTrace]:
        policy = compiler_input.policy_result
        permission = policy.permission
        assert permission is not None
        item = ExpressionContextItem(
            item_id=f"context-action-{compiler_input.interaction_id}",
            kind=ExpressionContextKind.ACTION,
            key="selected_action",
            value=permission.action_type,
            source_refs=(policy.policy_id,),
            priority=0,
        )
        context = DecisionContext(
            context_id=f"context-{compiler_input.interaction_id}",
            scope=compiler_input.scope,
            origin_runtime_id=compiler_input.origin_runtime_id,
            interaction_ref=compiler_input.interaction_id,
            situation_ref=compiler_input.situation.situation_id,
            effective_user_state_ref=compiler_input.effective_user_state.state_id,
            projected_agent_state_ref=compiler_input.projected_agent_state.projection_id,
            relationship_state_refs=(),
            historical_context_ref=(
                compiler_input.situation.historical_context.bundle_id
                if compiler_input.situation.historical_context is not None
                else None
            ),
            assessment_trace_ref=compiler_input.assessment_trace_ref,
            intent_ref=compiler_input.intent.intent_id,
            policy_result_ref=policy.policy_id,
            relevant_persona_ref=compiler_input.persona_ref,
            goals_refs=(),
            selected_intent_kind=compiler_input.intent.kind,
            selected_action_type=permission.action_type,
            attempt=compiler_input.attempt,
            expression_context=(item,),
        )
        trace = DecisionContextCompileTrace(
            trace_id=f"compile-{context.context_id}",
            context_id=context.context_id,
            included_item_refs=(item.item_id,),
            omitted_item_refs=(),
            reason_codes=(),
        )
        return context, trace

    def retry(
        self, context: DecisionContext, reason_codes: tuple[str, ...]
    ) -> tuple[DecisionContext, DecisionContextCompileTrace]:
        raise NotImplementedError("the D2S stub compiler never retries")


class StubExpressionCoordinator:
    """D2S single-attempt compatibility; never a second production pipeline."""

    def __init__(
        self,
        *,
        renderer: ContextRendererPort,
        agent: AgentPort,
        guard: ExpressionGuardPort,
    ) -> None:
        self._renderer = renderer
        self._agent = agent
        self._guard = guard

    def express(self, context: DecisionContext) -> ExpressionOutcome:
        rendered = self._renderer.render(context)
        expression = self._agent.respond(rendered)
        guard_input = ExpressionGuardInput(
            draft_id=f"draft-{context.context_id}",
            decision_context=context,
            expression=expression,
            attempt=context.attempt,
        )
        try:
            result = self._guard.guard(guard_input)
        except Exception:
            return self._outcome(
                context, rendered, None, ExpressionDisposition.REJECT, ("guard_failure",)
            )
        if result.scope != context.scope:
            return self._outcome(
                context, rendered, guard_input, ExpressionDisposition.REJECT, ("scope_mismatch",)
            )
        if result.origin_runtime_id != context.origin_runtime_id:
            return self._outcome(
                context, rendered, guard_input, ExpressionDisposition.REJECT, ("origin_mismatch",)
            )
        if result.expression != expression:
            return self._outcome(
                context,
                rendered,
                guard_input,
                ExpressionDisposition.REJECT,
                ("invalid_expression",),
            )
        if result.disposition is ExpressionDisposition.ACCEPT:
            return self._outcome(
                context, rendered, guard_input, ExpressionDisposition.ACCEPT, (), result.expression
            )
        return self._outcome(
            context, rendered, guard_input, ExpressionDisposition.REJECT, result.violations
        )

    @staticmethod
    def _outcome(
        context: DecisionContext,
        rendered: ProviderExpressionContext,
        guard_input: ExpressionGuardInput | None,
        disposition: ExpressionDisposition,
        reason_codes: tuple[str, ...],
        accepted_expression: str | None = None,
    ) -> ExpressionOutcome:
        attempt = ExpressionAttemptTrace(
            attempt_id=f"attempt-{context.context_id}",
            context_id=context.context_id,
            render_id=rendered.render_id,
            draft_id=guard_input.draft_id if guard_input is not None else None,
            attempt=context.attempt,
            disposition=disposition,
            reason_codes=reason_codes,
        )
        return ExpressionOutcome(
            outcome_id=f"outcome-{context.context_id}",
            scope=context.scope,
            origin_runtime_id=context.origin_runtime_id,
            accepted_expression=accepted_expression,
            final_disposition=disposition,
            attempts=(attempt,),
        )
