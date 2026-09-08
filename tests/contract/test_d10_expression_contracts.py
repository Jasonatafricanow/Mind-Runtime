"""Frozen contracts for the bounded D10 expression boundary."""

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    DecisionContext,
    DecisionContextCompileTrace,
    DeliveryStatus,
    DiagnosticExpressionContext,
    ExpressionAttemptTrace,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardInput,
    ExpressionGuardResult,
    ExpressionOutcome,
    PreviousExpression,
    ProviderExpressionContext,
    Scope,
)
from tests.golden.fixtures.common import make_scope

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def make_decision_context(
    *,
    scope: Scope | None = None,
    origin_runtime_id: str = "runtime-1",
    attempt: int = 0,
    expression_context: tuple[ExpressionContextItem, ...] = (),
) -> DecisionContext:
    return DecisionContext(
        context_id="context-1",
        scope=scope or make_scope(),
        origin_runtime_id=origin_runtime_id,
        interaction_ref="interaction-1",
        situation_ref="situation-1",
        effective_user_state_ref="state-1",
        projected_agent_state_ref="projection-1",
        relationship_state_refs=("relationship-1",),
        historical_context_ref="history-1",
        assessment_trace_ref="assessment-1",
        intent_ref="intent-1",
        policy_result_ref="policy-1",
        relevant_persona_ref="persona-1",
        goals_refs=("goal-1",),
        selected_intent_kind="respond",
        selected_action_type="text_message",
        attempt=attempt,
        expression_context=expression_context,
    )


def test_expression_context_item_is_typed_and_source_referenced() -> None:
    item = ExpressionContextItem(
        item_id="item-action",
        kind=ExpressionContextKind.ACTION,
        key="selected_action",
        value="text_message",
        source_refs=("policy-1",),
        priority=0,
    )
    assert item.source_refs == ("policy-1",)


@pytest.mark.parametrize("field", ["item_id", "key", "value"])
def test_expression_context_item_rejects_blank_identity_parts(field: str) -> None:
    with pytest.raises(ValueError):
        ExpressionContextItem(
            item_id=" " if field == "item_id" else "item-action",
            kind=ExpressionContextKind.ACTION,
            key=" " if field == "key" else "selected_action",
            value=" " if field == "value" else "text_message",
            source_refs=("policy-1",),
            priority=0,
        )


def test_expression_context_item_rejects_blank_source_ref_and_negative_priority() -> None:
    with pytest.raises(ValueError, match="source_refs"):
        ExpressionContextItem(
            "item-action",
            ExpressionContextKind.ACTION,
            "selected_action",
            "text_message",
            (),
            0,
        )
    with pytest.raises(ValueError):
        ExpressionContextItem(
            "item-action",
            ExpressionContextKind.ACTION,
            "selected_action",
            "text_message",
            (" ",),
            0,
        )
    with pytest.raises(ValueError):
        ExpressionContextItem(
            "item-action",
            ExpressionContextKind.ACTION,
            "selected_action",
            "text_message",
            ("policy-1",),
            -1,
        )


def test_decision_context_rejects_duplicate_item_identity() -> None:
    item = ExpressionContextItem(
        "item-1",
        ExpressionContextKind.FACT,
        "time.daypart",
        "evening",
        ("situation-1",),
        10,
    )
    with pytest.raises(ValueError, match="unique"):
        make_decision_context(expression_context=(item, item))


def test_expression_contracts_construct_every_new_type() -> None:
    item = ExpressionContextItem(
        "item-action",
        ExpressionContextKind.ACTION,
        "selected_action",
        "text_message",
        ("policy-1",),
        0,
    )
    context = make_decision_context(expression_context=(item,))
    previous = PreviousExpression(
        "expression-previous",
        context.scope,
        "runtime-1",
        "text_message",
        "hello",
        "receipt-1",
        DeliveryStatus.SENT,
        NOW,
    )
    compile_trace = DecisionContextCompileTrace(
        "compile-1", context.context_id, (item.item_id,), (), ()
    )
    provider = ProviderExpressionContext(
        "render-1", context.context_id, context.scope, "runtime-1", "prompt", (item.item_id,), ()
    )
    diagnostic = DiagnosticExpressionContext("render-1", context.context_id, "diagnostic")
    guard_input = ExpressionGuardInput("draft-1", context, "hello", 0)
    guard_result = ExpressionGuardResult(
        "guard-1", context.scope, "runtime-1", "hello", ExpressionDisposition.ACCEPT, ()
    )
    attempt = ExpressionAttemptTrace(
        "attempt-1",
        context.context_id,
        provider.render_id,
        guard_input.draft_id,
        0,
        guard_result.disposition,
        (),
    )
    outcome = ExpressionOutcome(
        "outcome-1", context.scope, "runtime-1", "hello", ExpressionDisposition.ACCEPT, (attempt,)
    )

    assert previous.receipt_ref == "receipt-1"
    assert compile_trace.included_item_refs == ("item-action",)
    assert provider.included_item_ids == ("item-action",)
    assert diagnostic.context_id == context.context_id
    assert outcome.attempts == (attempt,)


def test_guard_input_rejects_mismatched_scope_origin_and_attempt() -> None:
    context = make_decision_context(attempt=1)
    with pytest.raises(ValueError, match="attempt"):
        ExpressionGuardInput("draft-1", context, "hello", 0)


def test_guard_accept_requires_no_violations() -> None:
    with pytest.raises(ValueError, match="ACCEPT"):
        ExpressionGuardResult(
            guard_id="guard-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            expression="你好",
            disposition=ExpressionDisposition.ACCEPT,
            violations=("prefix_duplicate",),
        )


@pytest.mark.parametrize(
    ("disposition", "expression", "violations"),
    [
        (ExpressionDisposition.REWRITE, "", ("prefix_duplicate",)),
        (ExpressionDisposition.REWRITE, "hello", ()),
        (ExpressionDisposition.REJECT, "hello", ()),
    ],
)
def test_guard_rejects_contradictory_dispositions(
    disposition: ExpressionDisposition, expression: str, violations: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        ExpressionGuardResult(
            "guard-1", make_scope(), "runtime-1", expression, disposition, violations
        )


def test_guard_contract_has_no_policy_or_guard_written_prose_fields() -> None:
    names = {field.name for field in fields(ExpressionGuardResult)}
    assert "rewritten_expression" not in names
    assert "accepted" not in names
    assert "decision" not in names
    assert "permission" not in names


def test_previous_expression_rejects_unsent_naive_or_blank_receipt() -> None:
    scope = make_scope()
    with pytest.raises(ValueError):
        PreviousExpression(
            "previous-1", scope, "runtime-1", "text_message", "hello", "", DeliveryStatus.SENT, NOW
        )
    with pytest.raises(ValueError):
        PreviousExpression(
            "previous-1",
            scope,
            "runtime-1",
            "text_message",
            "hello",
            "receipt-1",
            DeliveryStatus.UNSENT,
            NOW,
        )
    with pytest.raises(ValueError):
        PreviousExpression(
            "previous-1",
            scope,
            "runtime-1",
            "text_message",
            "hello",
            "receipt-1",
            DeliveryStatus.SENT,
            NOW.replace(tzinfo=None),
        )


def test_expression_outcome_rejects_rewrite_empty_attempts_and_wrong_accept_text() -> None:
    scope = make_scope()
    trace = ExpressionAttemptTrace(
        "attempt-1",
        "context-1",
        "render-1",
        "draft-1",
        0,
        ExpressionDisposition.REJECT,
        ("blocked",),
    )
    with pytest.raises(ValueError):
        ExpressionOutcome(
            "outcome-1", scope, "runtime-1", None, ExpressionDisposition.REWRITE, (trace,)
        )
    with pytest.raises(ValueError):
        ExpressionOutcome(
            "outcome-1", scope, "runtime-1", "hello", ExpressionDisposition.REJECT, (trace,)
        )
    with pytest.raises(ValueError):
        ExpressionOutcome(
            "outcome-1", scope, "runtime-1", "hello", ExpressionDisposition.ACCEPT, ()
        )


def test_decision_context_rejects_bad_attempt_and_non_item_entry() -> None:
    item = ExpressionContextItem(
        "item-1",
        ExpressionContextKind.FACT,
        "time.daypart",
        "evening",
        ("situation-1",),
        10,
    )
    with pytest.raises(ValueError, match="attempt"):
        make_decision_context(attempt=True, expression_context=(item,))
    with pytest.raises(ValueError, match="ExpressionContextItem"):
        make_decision_context(expression_context=(object(),))  # type: ignore[arg-type]


def test_expression_context_item_rejects_wrong_kind_type() -> None:
    with pytest.raises(ValueError, match="kind"):
        ExpressionContextItem(
            "item-1",
            "action",  # type: ignore[arg-type]
            "selected_action",
            "text_message",
            ("policy-1",),
            0,
        )


def test_previous_expression_rejects_wrong_delivery_status_type() -> None:
    with pytest.raises(ValueError, match="DeliveryStatus"):
        PreviousExpression(
            "expr-1",
            make_scope(),
            "runtime-1",
            "text_message",
            "hello",
            "receipt-1",
            "SENT",  # type: ignore[arg-type]
            NOW,
        )


def test_guard_input_rejects_blank_draft_bad_context_and_non_string_expression() -> None:
    context = make_decision_context(
        expression_context=(
            ExpressionContextItem(
                "item-1",
                ExpressionContextKind.ACTION,
                "selected_action",
                "text_message",
                ("policy-1",),
                0,
            ),
        )
    )
    with pytest.raises(ValueError, match="draft_id"):
        ExpressionGuardInput("", context, "hello", 0)
    with pytest.raises(ValueError, match="DecisionContext"):
        ExpressionGuardInput("draft-1", object(), "hello", 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="string"):
        ExpressionGuardInput("draft-1", context, 1, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attempt"):
        ExpressionGuardInput("draft-1", context, "hello", True)


def test_guard_result_rejects_non_string_expression() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="string"):
        ExpressionGuardResult(
            "guard-1",
            scope,
            "runtime-1",
            1,  # type: ignore[arg-type]
            ExpressionDisposition.ACCEPT,
            (),
        )


def test_attempt_trace_rejects_bad_attempt_and_disposition() -> None:
    with pytest.raises(ValueError, match="attempt"):
        ExpressionAttemptTrace("a", "c", "r", "d", True, ExpressionDisposition.REJECT, ("x",))
    with pytest.raises(ValueError, match="disposition"):
        ExpressionAttemptTrace("a", "c", "r", "d", 0, "reject", ("x",))  # type: ignore[arg-type]


def test_outcome_rejects_wrong_final_disposition_type_and_bad_attempt_entry() -> None:
    scope = make_scope()
    trace = ExpressionAttemptTrace(
        "attempt-1",
        "context-1",
        "render-1",
        "draft-1",
        0,
        ExpressionDisposition.REJECT,
        ("blocked",),
    )
    with pytest.raises(ValueError, match="final_disposition"):
        ExpressionOutcome(
            "outcome-1",
            scope,
            "runtime-1",
            None,
            "reject",  # type: ignore[arg-type]
            (trace,),
        )
    with pytest.raises(ValueError, match="ExpressionAttemptTrace"):
        ExpressionOutcome(
            "outcome-1",
            scope,
            "runtime-1",
            None,
            ExpressionDisposition.REJECT,
            (object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="accepted_expression"):
        ExpressionOutcome(
            "outcome-1", scope, "runtime-1", None, ExpressionDisposition.ACCEPT, (trace,)
        )
