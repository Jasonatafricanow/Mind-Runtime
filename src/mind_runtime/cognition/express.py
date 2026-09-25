"""Proactive would-send expression preparation (C5C).

ALLOWED proactive intent -> DecisionContext -> generation request ->
ExpressionGuard -> would-send artifact. This module owns no expression
rules: it reuses the frozen D10 authorities (DecisionContextCompiler,
DeterministicContextRenderer, DeterministicExpressionGuardChain) through
the one DeterministicExpressionCoordinator, exactly as the C2.10 turn
path does, and stops at the artifact. There is no outbound, no receipt,
and no delivery surface here.

Counter facts are READ-ONLY inputs during preparation: this module never
admits Evidence and never writes facts — authoritative counter updates
belong to later settled action/delivery outcomes (C7). Entry-angle
repetition stays a seam: the injected read-only PreviousExpressionPort is
the future backing point for durable would-send/sent history (C7/C8),
not a new rule.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from mind_runtime.contracts import (
    ActionDecision,
    ActionPolicyResult,
    ExpressionDisposition,
    Intent,
    ProjectedMindState,
    RuntimeState,
    Situation,
)
from mind_runtime.contracts.common import require_non_empty
from mind_runtime.contracts.late_projection import AcceptedAppraisal
from mind_runtime.expression import (
    DecisionContextCompiler,
    DeterministicExpressionCoordinator,
)
from mind_runtime.expression.context import DecisionContextCompilerInput
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.ports import PreviousExpressionPort


@dataclass(frozen=True, slots=True)
class ProactiveExpressionConfig:
    """Host-owned action types that may prepare would-send prose."""

    proactive_action_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.proactive_action_types:
            raise ValueError("proactive_action_types must not be empty")
        seen: set[str] = set()
        for action_type in self.proactive_action_types:
            require_non_empty(action_type, "proactive_action_types entries")
            if action_type in seen:
                raise ValueError("proactive_action_types entries must be unique")
            seen.add(action_type)


@dataclass(frozen=True, slots=True)
class ProactiveExpressionArtifact:
    """One would-send preparation result: ids and disposition, never delivery."""

    interaction_id: str
    intent_id: str
    action_type: str
    context_id: str | None = None
    outcome_id: str | None = None
    disposition: ExpressionDisposition | None = None
    would_send: str | None = None
    attempt_count: int = 0
    skip_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Operability payload only — never carries the would-send text."""
        return {
            "intent_id": self.intent_id,
            "action_type": self.action_type,
            "context_id": self.context_id,
            "outcome_id": self.outcome_id,
            "disposition": self.disposition.value if self.disposition is not None else None,
            "attempt_count": self.attempt_count,
            "skip_reason": self.skip_reason,
        }


class ProactiveExpressionPreparer:
    """Drive the frozen D10 expression chain for one proactive ALLOW.

    Fail-closed by construction: the compiler, the coordinator (which owns
    renderer, agent, and guard chain), the read-only previous-expression
    port, and the proactive action-type set are all explicitly injected.
    """

    def __init__(
        self,
        *,
        orchestrator: TurnOrchestrator,
        compiler: DecisionContextCompiler,
        coordinator: DeterministicExpressionCoordinator,
        previous_expression: PreviousExpressionPort,
        config: ProactiveExpressionConfig,
        runtime_id: str,
    ) -> None:
        if not isinstance(compiler, DecisionContextCompiler):
            raise ValueError("compiler must be a DecisionContextCompiler")
        if not isinstance(coordinator, DeterministicExpressionCoordinator):
            raise ValueError("coordinator must be a DeterministicExpressionCoordinator")
        require_non_empty(runtime_id, "runtime_id")
        self._orchestrator = orchestrator
        self._compiler = compiler
        self._coordinator = coordinator
        self._previous_expression = previous_expression
        self._config = config
        self._runtime_id = runtime_id

    def handles(self, *, policy_result: ActionPolicyResult) -> bool:
        """Whether this ALLOW's action type is a proactive preparation target."""

        permission = policy_result.permission
        return (
            policy_result.decision is ActionDecision.ALLOW
            and permission is not None
            and permission.action_type in self._config.proactive_action_types
        )

    def prepare(
        self,
        *,
        interaction_id: str,
        intent: Intent,
        policy_result: ActionPolicyResult,
        situation: Situation,
        projected: ProjectedMindState,
        assessment_trace_ref: str,
        state_rows: tuple[RuntimeState, ...],
        persona_ref: str | None,
        now: datetime,
        accepted_appraisals: tuple[AcceptedAppraisal, ...] = (),
    ) -> ProactiveExpressionArtifact:
        """Prepare one would-send artifact; never writes facts or lifecycle."""

        base = ProactiveExpressionArtifact(
            interaction_id=interaction_id,
            intent_id=intent.intent_id,
            action_type=policy_result.permission.action_type
            if policy_result.permission is not None
            else "",
        )
        permission = policy_result.permission
        if policy_result.decision is not ActionDecision.ALLOW or permission is None:
            return replace(base, skip_reason="not_allowed")
        if permission.action_type not in self._config.proactive_action_types:
            return replace(base, skip_reason="not_proactive")
        # Effective State is resolved through the orchestrator's frozen
        # authority over the tick's loaded durable rows — never raw state.
        effective = self._orchestrator.effective_state.effective(
            interaction_id=interaction_id,
            evidence_refs=(),
            canonical_snapshot=state_rows,
            scope=intent.scope,
            clock=now,
        )
        previous = self._previous_expression.previous(
            scope=intent.scope, action_type=permission.action_type
        )
        context, _compile_trace = self._compiler.compile(
            DecisionContextCompilerInput(
                interaction_id=interaction_id,
                scope=intent.scope,
                origin_runtime_id=self._runtime_id,
                situation=situation,
                effective_user_state=effective,
                projected_agent_state=projected,
                assessment_trace_ref=assessment_trace_ref,
                intent=intent,
                policy_result=policy_result,
                persona_ref=persona_ref,
                prior_expression=previous,
                attempt=0,
                rewrite_reason_codes=(),
                accepted_appraisals=accepted_appraisals,
            )
        )
        self._orchestrator.trace.record(
            interaction_id,
            "proactive_expression_context",
            ref=context.context_id,
            at=now,
        )
        outcome = self._coordinator.express(context)
        self._orchestrator.trace.record(
            interaction_id,
            "proactive_expression",
            ref=outcome.outcome_id,
            outcome=outcome.final_disposition.value,
            at=now,
        )
        return replace(
            base,
            context_id=context.context_id,
            outcome_id=outcome.outcome_id,
            disposition=outcome.final_disposition,
            would_send=outcome.accepted_expression,
            attempt_count=len(outcome.attempts),
        )
