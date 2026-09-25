"""Typed contracts at the bounded D10 expression boundary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mind_runtime.contracts import DecisionContext, DeliveryStatus
from mind_runtime.contracts.common import require_aware_utc, require_non_empty
from mind_runtime.contracts.scope import Scope


class ExpressionContextKind(StrEnum):
    ACTION = "action"
    FACT = "fact"
    COGNITIVE_MEANING = "cognitive_meaning"
    INTERNAL_STATE = "internal_state"
    POLICY_CONSTRAINT = "policy_constraint"
    PERSONA_STYLE = "persona_style"
    HISTORY = "history"
    PRIOR_EXPRESSION = "prior_expression"
    REWRITE_GUIDANCE = "rewrite_guidance"


@dataclass(frozen=True, slots=True)
class ExpressionContextItem:
    item_id: str
    kind: ExpressionContextKind
    key: str
    value: str
    source_refs: tuple[str, ...]
    priority: int

    def __post_init__(self) -> None:
        for field_name in ("item_id", "key", "value"):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.kind, ExpressionContextKind):
            raise ValueError("kind must be an ExpressionContextKind")
        if not self.source_refs:
            raise ValueError("source_refs must not be empty")
        for ref in self.source_refs:
            require_non_empty(ref, "source_refs entries")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority < 0
        ):
            raise ValueError("priority must be a non-negative integer")

    @property
    def identity(self) -> tuple[ExpressionContextKind, str, tuple[str, ...]]:
        return (self.kind, self.key, self.source_refs)


@dataclass(frozen=True, slots=True)
class PreviousExpression:
    expression_id: str
    scope: Scope
    origin_runtime_id: str
    action_type: str
    text: str
    receipt_ref: str
    delivery_status: DeliveryStatus
    sent_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "expression_id",
            "origin_runtime_id",
            "action_type",
            "text",
            "receipt_ref",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        if not isinstance(self.delivery_status, DeliveryStatus):
            raise ValueError("delivery_status must be a DeliveryStatus")
        if self.delivery_status is not DeliveryStatus.SENT:
            raise ValueError("delivery_status must be SENT")
        require_aware_utc(self.sent_at, "sent_at")


@dataclass(frozen=True, slots=True)
class DecisionContextCompileTrace:
    trace_id: str
    context_id: str
    included_item_refs: tuple[str, ...]
    omitted_item_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.trace_id, "trace_id")
        require_non_empty(self.context_id, "context_id")
        for field_name in ("included_item_refs", "omitted_item_refs", "reason_codes"):
            for value in getattr(self, field_name):
                require_non_empty(value, f"{field_name} entries")


@dataclass(frozen=True, slots=True)
class ProviderExpressionContext:
    render_id: str
    context_id: str
    scope: Scope
    origin_runtime_id: str
    text: str
    included_item_ids: tuple[str, ...]
    omitted_item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("render_id", "context_id", "origin_runtime_id", "text"):
            require_non_empty(getattr(self, field_name), field_name)
        for field_name in ("included_item_ids", "omitted_item_ids"):
            for value in getattr(self, field_name):
                require_non_empty(value, f"{field_name} entries")


@dataclass(frozen=True, slots=True)
class DiagnosticExpressionContext:
    render_id: str
    context_id: str
    text: str

    def __post_init__(self) -> None:
        for field_name in ("render_id", "context_id", "text"):
            require_non_empty(getattr(self, field_name), field_name)


class ExpressionDisposition(StrEnum):
    ACCEPT = "accept"
    REWRITE = "rewrite"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ExpressionGuardInput:
    draft_id: str
    decision_context: DecisionContext
    expression: str
    attempt: int

    def __post_init__(self) -> None:
        require_non_empty(self.draft_id, "draft_id")
        if not isinstance(self.decision_context, DecisionContext):
            raise ValueError("decision_context must be a DecisionContext")
        if not isinstance(self.expression, str):
            raise ValueError("expression must be a string")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if self.attempt != self.decision_context.attempt:
            raise ValueError("attempt must match decision_context.attempt")


@dataclass(frozen=True, slots=True)
class ExpressionGuardResult:
    guard_id: str
    scope: Scope
    origin_runtime_id: str
    expression: str
    disposition: ExpressionDisposition
    violations: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.guard_id, "guard_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.expression, str):
            raise ValueError("expression must be a string")
        if not isinstance(self.disposition, ExpressionDisposition):
            raise ValueError("disposition must be an ExpressionDisposition")
        for violation in self.violations:
            require_non_empty(violation, "violations entries")
        if self.disposition is ExpressionDisposition.ACCEPT and self.violations:
            raise ValueError("ACCEPT requires no violations")
        if (
            self.disposition
            in {
                ExpressionDisposition.ACCEPT,
                ExpressionDisposition.REWRITE,
            }
            and not self.expression.strip()
        ):
            raise ValueError("ACCEPT/REWRITE requires a non-blank expression")
        if self.disposition is not ExpressionDisposition.ACCEPT and not self.violations:
            raise ValueError("REWRITE/REJECT requires violations")


@dataclass(frozen=True, slots=True)
class ExpressionAttemptTrace:
    attempt_id: str
    context_id: str
    render_id: str
    draft_id: str | None
    attempt: int
    disposition: ExpressionDisposition | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("attempt_id", "context_id", "render_id"):
            require_non_empty(getattr(self, field_name), field_name)
        if self.draft_id is not None:
            require_non_empty(self.draft_id, "draft_id")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")
        if self.disposition is not None and not isinstance(self.disposition, ExpressionDisposition):
            raise ValueError("disposition must be an ExpressionDisposition or None")
        for reason_code in self.reason_codes:
            require_non_empty(reason_code, "reason_codes entries")


@dataclass(frozen=True, slots=True)
class ExpressionOutcome:
    outcome_id: str
    scope: Scope
    origin_runtime_id: str
    accepted_expression: str | None
    final_disposition: ExpressionDisposition
    attempts: tuple[ExpressionAttemptTrace, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.outcome_id, "outcome_id")
        require_non_empty(self.origin_runtime_id, "origin_runtime_id")
        if not isinstance(self.final_disposition, ExpressionDisposition):
            raise ValueError("final_disposition must be an ExpressionDisposition")
        if self.final_disposition not in {
            ExpressionDisposition.ACCEPT,
            ExpressionDisposition.REJECT,
        }:
            raise ValueError("final_disposition must be ACCEPT or REJECT")
        if not self.attempts:
            raise ValueError("attempts must not be empty")
        for attempt in self.attempts:
            if not isinstance(attempt, ExpressionAttemptTrace):
                raise ValueError("attempts entries must be ExpressionAttemptTrace")
        if self.final_disposition is ExpressionDisposition.ACCEPT:
            if self.accepted_expression is None or not self.accepted_expression.strip():
                raise ValueError("ACCEPT requires accepted_expression")
        elif self.accepted_expression is not None:
            raise ValueError("REJECT requires no accepted_expression")
