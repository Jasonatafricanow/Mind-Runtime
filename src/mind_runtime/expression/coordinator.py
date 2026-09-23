"""Bounded rewrite coordination for the deterministic expression path."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from mind_runtime.contracts import (
    DecisionContext,
    ExpressionAttemptTrace,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    ExpressionOutcome,
    ProviderExpressionContext,
)
from mind_runtime.expression.context import DecisionContextCompiler


@dataclass(frozen=True, slots=True)
class ExpressionCoordinatorConfig:
    max_rewrites: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_rewrites, bool)
            or not isinstance(self.max_rewrites, int)
            or self.max_rewrites < 0
        ):
            raise ValueError("max_rewrites must be a non-negative integer")


class _RendererPort(Protocol):
    def render(self, context: DecisionContext) -> ProviderExpressionContext: ...


class _AgentPort(Protocol):
    def respond(self, provider_context: ProviderExpressionContext) -> str: ...


class _GuardPort(Protocol):
    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult: ...


class DeterministicExpressionCoordinator:
    """The only owner of retry counting; returns one final expression outcome."""

    def __init__(
        self,
        *,
        compiler: DecisionContextCompiler,
        renderer: _RendererPort,
        agent: _AgentPort,
        guard: _GuardPort,
        config: ExpressionCoordinatorConfig,
    ) -> None:
        if not isinstance(compiler, DecisionContextCompiler):
            raise ValueError("compiler must be a DecisionContextCompiler")
        if not isinstance(config, ExpressionCoordinatorConfig):
            raise ValueError("config must be an ExpressionCoordinatorConfig")
        self._compiler = compiler
        self._renderer = renderer
        self._agent = agent
        self._guard = guard
        self._config = config

    def express(self, context: DecisionContext) -> ExpressionOutcome:
        if not isinstance(context, DecisionContext):
            raise ValueError("context must be a DecisionContext")
        attempts: list[ExpressionAttemptTrace] = []
        current = context
        while True:
            rendered = self._renderer.render(current)
            expression = self._agent.respond(rendered)
            if not isinstance(expression, str):
                attempts.append(
                    self._attempt(
                        current,
                        rendered,
                        None,
                        ExpressionDisposition.REJECT,
                        ("invalid_expression",),
                    )
                )
                return self._outcome(current, attempts, ExpressionDisposition.REJECT, None)
            guard_input = ExpressionGuardInput(
                draft_id=f"draft-{current.context_id}",
                decision_context=current,
                expression=expression,
                attempt=current.attempt,
            )
            try:
                result = self._guard.guard(guard_input)
            except Exception:
                attempts.append(self._attempt(current, rendered, None, None, ("guard_failure",)))
                return self._outcome(current, attempts, ExpressionDisposition.REJECT, None)
            mismatch = self._mismatch_code(current, guard_input, result)
            if mismatch is not None:
                attempts.append(self._attempt(current, rendered, guard_input, None, (mismatch,)))
                return self._outcome(current, attempts, ExpressionDisposition.REJECT, None)
            if result.disposition is ExpressionDisposition.ACCEPT:
                attempts.append(
                    self._attempt(current, rendered, guard_input, ExpressionDisposition.ACCEPT, ())
                )
                return self._outcome(
                    current, attempts, ExpressionDisposition.ACCEPT, result.expression
                )
            if result.disposition is ExpressionDisposition.REJECT:
                attempts.append(
                    self._attempt(
                        current,
                        rendered,
                        guard_input,
                        ExpressionDisposition.REJECT,
                        result.violations,
                    )
                )
                return self._outcome(current, attempts, ExpressionDisposition.REJECT, None)
            attempts.append(
                self._attempt(
                    current, rendered, guard_input, ExpressionDisposition.REWRITE, result.violations
                )
            )
            if current.attempt >= self._config.max_rewrites:
                attempts[-1] = replace(
                    attempts[-1],
                    disposition=ExpressionDisposition.REJECT,
                    reason_codes=result.violations + ("retry_exhausted",),
                )
                return self._outcome(current, attempts, ExpressionDisposition.REJECT, None)
            current, _ = self._compiler.retry(current, result.violations)

    @staticmethod
    def _mismatch_code(
        context: DecisionContext,
        guard_input: ExpressionGuardInput,
        result: ExpressionGuardResult,
    ) -> str | None:
        if result.scope != context.scope:
            return "scope_mismatch"
        if result.origin_runtime_id != context.origin_runtime_id:
            return "origin_mismatch"
        if result.expression != guard_input.expression:
            return "invalid_expression"
        return None

    @staticmethod
    def _attempt(
        current: DecisionContext,
        rendered: ProviderExpressionContext,
        guard_input: ExpressionGuardInput | None,
        disposition: ExpressionDisposition | None,
        reason_codes: tuple[str, ...],
    ) -> ExpressionAttemptTrace:
        controls_ref: str | None = None
        expression_map_ref: str | None = None
        guidance: list[tuple[str, str]] = []
        for item in current.expression_context:
            if item.kind is ExpressionContextKind.SURFACE_GUIDANCE:
                guidance.append((item.key, item.value))
                if controls_ref is None and item.source_refs:
                    controls_ref = item.source_refs[0]
        if guidance:
            from mind_runtime.expression.expression_map import (
                CANDIDATE_MAP_ID,
                CANDIDATE_MAP_VERSION,
            )

            expression_map_ref = f"{CANDIDATE_MAP_ID}:{CANDIDATE_MAP_VERSION}"

        return ExpressionAttemptTrace(
            attempt_id=f"attempt-{current.context_id}",
            context_id=current.context_id,
            render_id=rendered.render_id,
            draft_id=guard_input.draft_id if guard_input is not None else None,
            attempt=current.attempt,
            disposition=disposition,
            reason_codes=reason_codes,
            surface_controls_ref=controls_ref,
            expression_map_ref=expression_map_ref,
            qualitative_guidance=tuple(guidance),
        )

    @staticmethod
    def _outcome(
        current: DecisionContext,
        attempts: list[ExpressionAttemptTrace],
        final_disposition: ExpressionDisposition,
        accepted_expression: str | None,
    ) -> ExpressionOutcome:
        return ExpressionOutcome(
            outcome_id=f"outcome-{current.context_id}",
            scope=current.scope,
            origin_runtime_id=current.origin_runtime_id,
            accepted_expression=accepted_expression,
            final_disposition=final_disposition,
            attempts=tuple(attempts),
        )
