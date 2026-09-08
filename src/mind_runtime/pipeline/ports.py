"""Typed stub port protocols for the D2S walking skeleton."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from mind_runtime.contracts import (
    ActionPolicyInput,
    ActionPolicyResult,
    DecisionContext,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    ExpressionGuardInput,
    ExpressionGuardResult,
    ExpressionOutcome,
    HistoricalContextBundle,
    IntentEngineInput,
    IntentEngineResult,
    Interaction,
    Observation,
    PreviousExpression,
    ProviderExpressionContext,
    RuntimeState,
    Scope,
    Situation,
)
from mind_runtime.state.resolver import EffectiveStateView


class AgentFailure(Exception):
    """Raised by an agent port when the agent call fails."""


@runtime_checkable
class EffectiveStatePort(Protocol):
    """Compute effective state from canonical snapshot plus turn overlay."""

    def effective(
        self,
        *,
        interaction_id: str,
        evidence_refs: tuple[str, ...],
        canonical_snapshot: tuple[RuntimeState, ...],
        scope: Scope,
        clock: datetime,
    ) -> RuntimeState:
        """Return the effective state for this turn."""
        ...


@runtime_checkable
class SituationPort(Protocol):
    """Build the Situation for this turn from Effective State + Interaction."""

    def build(
        self,
        *,
        interaction: Interaction,
        effective_view: EffectiveStateView,
        scope: Scope,
        clock: datetime,
    ) -> Situation:
        """Return the situation (derived facts only; no raw state dump)."""
        ...


@runtime_checkable
class EmotionalTransitionPort(Protocol):
    """Compute one projected internal-state step and candidate Intents."""

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        """Return one uncommitted projection with its causal trace."""
        ...


@runtime_checkable
class HistoricalContextPort(Protocol):
    """Read bounded historical facts without touching or reinforcing them."""

    def read(
        self,
        *,
        interaction_id: str,
        context: Situation,
        observations: tuple[Observation, ...],
        scope: Scope,
        clock: datetime,
    ) -> HistoricalContextBundle | None:
        """Return an immutable same-Scope bundle or no history."""
        ...


@runtime_checkable
class PreviousExpressionPort(Protocol):
    """Read at most one previously sent expression; never write history."""

    def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression | None:
        """Return an exact-Scope/action sent expression, or no history."""
        ...


@runtime_checkable
class ExpressionCoordinatorPort(Protocol):
    """The bounded retry owner; returns one final expression outcome."""

    def express(self, context: DecisionContext) -> ExpressionOutcome:
        """Run the capped provider/guard loop for one compiled context."""
        ...


@runtime_checkable
class IntentEnginePort(Protocol):
    """Score ordered candidate Intents without persistence or permission."""

    def evaluate(self, engine_input: IntentEngineInput) -> IntentEngineResult:
        """Return deterministic candidate Intents and their score traces."""
        ...


@runtime_checkable
class ActionPolicyPort(Protocol):
    """Decide whether a candidate Intent may become an action."""

    def policy(self, policy_input: ActionPolicyInput) -> ActionPolicyResult:
        """Return the policy result."""
        ...


@runtime_checkable
class ContextRendererPort(Protocol):
    """Render a compiled decision context into provider-safe text."""

    def render(self, context: DecisionContext) -> ProviderExpressionContext:
        """Return the bounded provider envelope for one expression attempt."""
        ...


@runtime_checkable
class AgentPort(Protocol):
    """The agent consuming the provider-safe expression context."""

    def respond(self, provider_context: ProviderExpressionContext) -> str:
        """Return the agent expression; may raise AgentFailure."""
        ...


@runtime_checkable
class ExpressionGuardPort(Protocol):
    """Guard the generated expression."""

    def guard(self, guard_input: ExpressionGuardInput) -> ExpressionGuardResult:
        """Return the guard result."""
        ...
