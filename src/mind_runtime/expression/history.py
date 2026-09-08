"""Read-only previous-expression implementations for bounded D10 context."""

from dataclasses import dataclass

from mind_runtime.contracts import PreviousExpression, Scope


class NullPreviousExpressionPort:
    """Default history view: no prior sent expression is available."""

    def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression | None:
        return None


@dataclass(frozen=True, slots=True)
class FixedPreviousExpressionPort:
    """Immutable test-only read view over one validated sent expression."""

    expression: PreviousExpression

    def __post_init__(self) -> None:
        if not isinstance(self.expression, PreviousExpression):
            raise ValueError("expression must be a PreviousExpression")

    def previous(self, *, scope: Scope, action_type: str) -> PreviousExpression | None:
        if self.expression.scope != scope or self.expression.action_type != action_type:
            return None
        return self.expression
