"""D1.6 DecisionContext / Expression / Trace / Data Governance contract tests."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    DataSensitivity,
    DecisionContext,
    EvidenceRef,
    ExpressionContextItem,
    ExpressionContextKind,
    ExpressionDisposition,
    ExpressionGuardResult,
    RedactionPolicy,
    RetentionClass,
    Scope,
    ScopeDomain,
    TraceKind,
    TraceRef,
)

NOW = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_guard(guard_id: str = "guard-1") -> ExpressionGuardResult:
    return ExpressionGuardResult(
        guard_id=guard_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        expression="晚上好，今天感觉如何？",
        disposition=ExpressionDisposition.ACCEPT,
        violations=(),
    )


def make_context(context_id: str = "context-1") -> DecisionContext:
    return DecisionContext(
        context_id=context_id,
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        interaction_ref="interaction-1",
        situation_ref="situation-1",
        effective_user_state_ref="state-1",
        projected_agent_state_ref="projection-1",
        relationship_state_refs=(),
        historical_context_ref="bundle-1",
        assessment_trace_ref="assessment-1",
        intent_ref="intent-1",
        policy_result_ref="policy-1",
        relevant_persona_ref="persona-1",
        goals_refs=(),
        selected_intent_kind="respond",
        selected_action_type="text_message",
        attempt=0,
        expression_context=(
            ExpressionContextItem(
                "context-action-1",
                ExpressionContextKind.ACTION,
                "selected_action",
                "text_message",
                ("policy-1",),
                0,
            ),
        ),
    )


# --- ExpressionGuardResult (15.2) ---


def test_guard_preserves_expression_check_shape() -> None:
    field_names = {field.name for field in fields(ExpressionGuardResult)}
    assert {"disposition", "violations"} <= field_names


def test_guard_is_immutable() -> None:
    guard = make_guard()
    with pytest.raises(FrozenInstanceError):
        guard.disposition = ExpressionDisposition.REJECT  # type: ignore[misc]


def test_guard_rewrite_has_violations_without_written_prose() -> None:
    scope = make_scope()
    guard = ExpressionGuardResult(
        guard_id="guard-2",
        scope=scope,
        origin_runtime_id="runtime-1",
        expression="早上好",
        disposition=ExpressionDisposition.REWRITE,
        violations=("forbidden_opening",),
    )
    assert guard.disposition is ExpressionDisposition.REWRITE


def test_guard_rejects_blank_expression() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="ACCEPT"):
        ExpressionGuardResult(
            guard_id="guard-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            expression="",
            disposition=ExpressionDisposition.ACCEPT,
            violations=(),
        )


def test_guard_rejects_blank_violation() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        ExpressionGuardResult(
            guard_id="guard-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            expression="早上好",
            disposition=ExpressionDisposition.REJECT,
            violations=(" ",),
        )


def test_guard_carries_no_policy_fields() -> None:
    # ActionPolicy != ExpressionGuard: the guard result must not absorb
    # policy-level fields (decision, reason_codes, permission).
    field_names = {field.name for field in fields(ExpressionGuardResult)}
    assert "decision" not in field_names
    assert "reason_codes" not in field_names
    assert "permission" not in field_names


# --- DecisionContext (chapter 17) ---


def test_context_preserves_chapter_17_composition() -> None:
    field_names = {field.name for field in fields(DecisionContext)}
    assert {
        "interaction_ref",
        "situation_ref",
        "effective_user_state_ref",
        "projected_agent_state_ref",
        "relationship_state_refs",
        "historical_context_ref",
        "assessment_trace_ref",
        "intent_ref",
        "policy_result_ref",
        "relevant_persona_ref",
        "goals_refs",
        "expression_context",
    } <= field_names


def test_context_has_no_raw_dump_field() -> None:
    field_names = {field.name for field in fields(DecisionContext)}
    for raw_name in ("raw_state", "raw_dump", "statebar", "memory_dump", "payload"):
        assert raw_name not in field_names


def test_context_is_bounded_and_immutable() -> None:
    context = make_context()
    assert context.situation_ref == "situation-1"
    assert context.projected_agent_state_ref == "projection-1"
    assert context.assessment_trace_ref == "assessment-1"
    assert context.intent_ref == "intent-1"
    assert context.policy_result_ref == "policy-1"
    with pytest.raises(FrozenInstanceError):
        context.situation_ref = "other"  # type: ignore[misc]


def test_context_rejects_blank_refs() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="",
            situation_ref="situation-1",
            effective_user_state_ref="state-1",
            projected_agent_state_ref="projection-1",
            relationship_state_refs=(),
            historical_context_ref=None,
            assessment_trace_ref="assessment-1",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=None,
            goals_refs=(),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )


# --- TraceRef / EvidenceRef ---


def test_trace_kind_values() -> None:
    assert {kind.value for kind in TraceKind} == {
        "evidence",
        "observation",
        "transition",
        "appraisal",
        "action",
        "interaction",
    }


def test_trace_ref_is_immutable() -> None:
    ref = TraceRef(
        ref_id="trace-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        kind=TraceKind.APPRAISAL,
        target_id="appraisal-1",
    )
    assert ref.kind is TraceKind.APPRAISAL
    with pytest.raises(FrozenInstanceError):
        ref.target_id = "other"  # type: ignore[misc]


def test_trace_ref_rejects_unknown_kind() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="kind"):
        TraceRef(
            ref_id="trace-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            kind="nonsense",  # type: ignore[arg-type]
            target_id="x",
        )


def test_evidence_ref_binds_evidence_id() -> None:
    ref = EvidenceRef(
        ref_id="evref-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        evidence_id="evidence-1",
    )
    assert ref.evidence_id == "evidence-1"


# --- Data Governance (DECISION-032) ---


def test_data_sensitivity_values() -> None:
    assert {level.value for level in DataSensitivity} == {
        "public",
        "personal",
        "relationship_sensitive",
        "secret",
    }


def test_retention_class_is_immutable() -> None:
    retention = RetentionClass(
        retention_id="ret-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        sensitivity=DataSensitivity.SECRET,
        ttl_days=30,
        keep_after_close=False,
    )
    assert retention.sensitivity is DataSensitivity.SECRET
    assert retention.ttl_days == 30
    with pytest.raises(FrozenInstanceError):
        retention.ttl_days = 60  # type: ignore[misc]


def test_retention_class_rejects_negative_ttl() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="ttl"):
        RetentionClass(
            retention_id="ret-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity=DataSensitivity.PUBLIC,
            ttl_days=-1,
            keep_after_close=True,
        )


def test_redaction_policy_honors_sensitivity() -> None:
    policy = RedactionPolicy(
        policy_id="redact-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        sensitivity=DataSensitivity.SECRET,
        redact_fields=frozenset({"content", "sender_id"}),
    )
    assert policy.redact_fields == frozenset({"content", "sender_id"})
    with pytest.raises(FrozenInstanceError):
        policy.redact_fields = frozenset()  # type: ignore[misc]


def test_redaction_policy_accepts_empty_redact_fields() -> None:
    # An empty redact set means "redact nothing for this class" — legal.
    scope = make_scope()
    policy = RedactionPolicy(
        policy_id="redact-none",
        scope=scope,
        origin_runtime_id="runtime-1",
        sensitivity=DataSensitivity.PUBLIC,
        redact_fields=frozenset(),
    )
    assert policy.redact_fields == frozenset()


def test_context_rejects_blank_nested_refs() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="i-1",
            situation_ref="s-1",
            effective_user_state_ref="e-1",
            projected_agent_state_ref="p-1",
            relationship_state_refs=("",),
            historical_context_ref=None,
            assessment_trace_ref="assessment-1",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=None,
            goals_refs=(),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="i-1",
            situation_ref="s-1",
            effective_user_state_ref="e-1",
            projected_agent_state_ref="p-1",
            relationship_state_refs=(),
            historical_context_ref=" ",
            assessment_trace_ref="assessment-1",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=None,
            goals_refs=(),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="i-1",
            situation_ref="s-1",
            effective_user_state_ref="e-1",
            projected_agent_state_ref="p-1",
            relationship_state_refs=(),
            historical_context_ref=None,
            assessment_trace_ref="",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=None,
            goals_refs=(),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="i-1",
            situation_ref="s-1",
            effective_user_state_ref="e-1",
            projected_agent_state_ref="p-1",
            relationship_state_refs=(),
            historical_context_ref=None,
            assessment_trace_ref="assessment-1",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=" ",
            goals_refs=(),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )
    with pytest.raises(ValueError, match="non-empty"):
        DecisionContext(
            context_id="c-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            interaction_ref="i-1",
            situation_ref="s-1",
            effective_user_state_ref="e-1",
            projected_agent_state_ref="p-1",
            relationship_state_refs=(),
            historical_context_ref=None,
            assessment_trace_ref="assessment-1",
            intent_ref="intent-1",
            policy_result_ref="policy-1",
            relevant_persona_ref=None,
            goals_refs=("",),
            selected_intent_kind="respond",
            selected_action_type="text_message",
            attempt=0,
            expression_context=(),
        )


def test_guard_rejects_unknown_disposition() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="disposition"):
        ExpressionGuardResult(
            guard_id="guard-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            expression="早上好",
            disposition="yes",  # type: ignore[arg-type]
            violations=(),
        )


def test_guard_rejects_accept_with_violations() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="ACCEPT"):
        ExpressionGuardResult(
            guard_id="guard-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            expression="早上好",
            disposition=ExpressionDisposition.ACCEPT,
            violations=("blocked",),
        )


def test_guard_rejects_rewrite_without_violations() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="REWRITE"):
        ExpressionGuardResult(
            guard_id="guard-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            expression="早上好",
            disposition=ExpressionDisposition.REWRITE,
            violations=(),
        )


def test_retention_class_rejects_unknown_sensitivity() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="sensitivity"):
        RetentionClass(
            retention_id="ret-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity="nonsense",  # type: ignore[arg-type]
            ttl_days=None,
            keep_after_close=False,
        )


def test_retention_class_rejects_non_bool_keep_flag() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="keep_after_close"):
        RetentionClass(
            retention_id="ret-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity=DataSensitivity.PUBLIC,
            ttl_days=None,
            keep_after_close="yes",  # type: ignore[arg-type]
        )


def test_redaction_policy_rejects_unknown_sensitivity() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="sensitivity"):
        RedactionPolicy(
            policy_id="redact-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity="nonsense",  # type: ignore[arg-type]
            redact_fields=frozenset({"x"}),
        )


def test_redaction_policy_rejects_non_frozenset() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="frozenset"):
        RedactionPolicy(
            policy_id="redact-bad",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity=DataSensitivity.PUBLIC,
            redact_fields={"x"},  # type: ignore[arg-type]
        )


def test_governance_opaque_ids_must_be_non_empty() -> None:
    scope = make_scope()
    with pytest.raises(ValueError, match="non-empty"):
        RetentionClass(
            retention_id="",
            scope=scope,
            origin_runtime_id="runtime-1",
            sensitivity=DataSensitivity.PUBLIC,
            ttl_days=None,
            keep_after_close=False,
        )
