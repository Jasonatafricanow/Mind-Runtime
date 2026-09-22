"""Step 0 / Step 3 & 4 RED tests: Bounded Longitudinal View & Dynamic Harness Compiler.

Covers:
- 1 occurrence vs 40 occurrences in LongitudinalView.
- Earlier positive pattern + 2 recent negative exceptions.
- No writeback / no self-reinforcement.
- No-Intent condition compilation via compile_condition.
- Counterfactual: World A (40) vs World B (1) with identical Slow -> different condition text.
- R6: Semantic relevance omission ("Check grammar: ..." omits relationship affect projection).
- R5: Wrong-target control: Bob's 40 items never appear in Alice's greeting condition.
"""

from datetime import UTC, datetime, timedelta
import pytest

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.contracts.appraisal import AcceptedAppraisalRecord
from mind_runtime.contracts.expression import TurnConditionProjection
from mind_runtime.contracts.historical import LongitudinalQuery, LongitudinalView
from mind_runtime.emotional_transition.history import derive_longitudinal_view
from mind_runtime.expression.context import (
    AffectBand,
    AffectExpressionRule,
    DecisionContextCompiler,
    DecisionContextConfig,
    compile_condition,
)


def _make_record(
    *,
    interaction_id: str,
    source_occurrence_id: str,
    user_id: str = "alice",
    salience: float = 0.1,
    valence: str = "positive",
    occurred_at: datetime,
) -> AcceptedAppraisalRecord:
    scope = Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id=user_id, persona_id="kayla_v0")
    return AcceptedAppraisalRecord(
        acceptance_id=f"acc-{interaction_id}",
        interaction_id=interaction_id,
        source_occurrence_id=source_occurrence_id,
        candidate_id=f"cand-{interaction_id}",
        candidate_kind="ordinary_interaction",
        candidate_confidence=0.9,
        appraisal_id=f"app-{interaction_id}",
        meanings=("ordinary_exchange",),
        valence=valence,
        relationship_relevance="relational_security",
        appraisal_confidence=0.85,
        salience=salience,
        source_scope=scope,
        owner_scope=Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0"),
        resolved_relationship_scope=scope,
        source_refs=(f"ev-{source_occurrence_id}",),
        supporting_refs=(f"ev-{source_occurrence_id}",),
        context_dependency_refs=(),
        source_occurred_at=occurred_at,
        source_received_at=occurred_at,
        assessed_at=occurred_at,
        persona_id="kayla_v0",
        persona_version="1",
        route_status="ACCEPTED",
        acceptance_status="COMMITTED",
        acceptance_reason="low_salience_relationship_appraisal",
        contract_version="1",
        binding_version="1",
        payload_digest="digest",
    )


def test_longitudinal_view_1_vs_40_distinction():
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
        max_records=256,
    )

    # 1 occurrence
    rec_1 = _make_record(
        interaction_id="inter-1",
        source_occurrence_id="occ-1",
        user_id="alice",
        occurred_at=now - timedelta(days=1),
    )
    view_1 = derive_longitudinal_view((rec_1,), query=query, now=now)
    assert view_1.total_record_count == 1
    assert view_1.positive_count == 1

    # 40 occurrences over 8 weeks
    records_40 = tuple(
        _make_record(
            interaction_id=f"inter-{i}",
            source_occurrence_id=f"occ-{i}",
            user_id="alice",
            occurred_at=now - timedelta(days=56 - i),
        )
        for i in range(40)
    )
    view_40 = derive_longitudinal_view(records_40, query=query, now=now)
    assert view_40.total_record_count == 40
    assert view_40.positive_count == 40
    assert view_40.covered_time_span_days >= 35


def test_longitudinal_view_earlier_pattern_plus_recent_exceptions():
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
        max_records=256,
        recent_days=7,
    )

    # 38 earlier positive records (older than 7 days)
    earlier = [
        _make_record(
            interaction_id=f"inter-early-{i}",
            source_occurrence_id=f"occ-early-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=50 - i),
        )
        for i in range(38)
    ]
    # 2 recent negative exceptions (within last 7 days)
    recent = [
        _make_record(
            interaction_id=f"inter-recent-{i}",
            source_occurrence_id=f"occ-recent-{i}",
            user_id="alice",
            valence="negative",
            occurred_at=now - timedelta(days=i + 1),
        )
        for i in range(2)
    ]

    view = derive_longitudinal_view(tuple(earlier + recent), query=query, now=now)
    assert view.total_record_count == 40
    assert view.earlier_segment_count == 38
    assert view.recent_segment_count == 2
    assert view.earlier_predominant_valence == "positive"
    assert view.recent_predominant_valence == "negative"
    assert len(view.exceptions) == 2


def test_r5_wrong_target_isolation():
    """R5: Bob's 40 history items must not appear in Alice's greeting condition."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")

    # Bob's 40 records
    bob_records = tuple(
        _make_record(
            interaction_id=f"inter-bob-{i}",
            source_occurrence_id=f"occ-bob-{i}",
            user_id="bob",
            occurred_at=now - timedelta(days=50 - i),
        )
        for i in range(40)
    )

    query_alice = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )
    view_alice = derive_longitudinal_view(bob_records, query=query_alice, now=now)
    assert view_alice.total_record_count == 0

    # Compile condition for Alice: must have 0 leakage of Bob
    cond = compile_condition(
        user_message="Good morning.",
        participant_id="alice",
        longitudinal_view=view_alice,
        fast_state=None,
        slow_state=None,
        persona_ref="kayla_v0",
    )
    assert "bob" not in cond.condition_text.lower()
    assert cond.coverage_summary == "no_relationship_history" or "0" in cond.condition_text


def test_r6_semantic_relevance_omission():
    """R6: Grammar / objective task omits relationship affect condition."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    alice_records = tuple(
        _make_record(
            interaction_id=f"inter-alice-{i}",
            source_occurrence_id=f"occ-alice-{i}",
            user_id="alice",
            occurred_at=now - timedelta(days=50 - i),
        )
        for i in range(40)
    )
    query_alice = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )
    view_alice = derive_longitudinal_view(alice_records, query=query_alice, now=now)

    # Objective task: "Check grammar: 'I look forward to our talk.'"
    cond = compile_condition(
        user_message='Check grammar: "I look forward to our talk."',
        participant_id="alice",
        longitudinal_view=view_alice,
        fast_state=None,
        slow_state=None,
        persona_ref="kayla_v0",
    )
    assert cond.is_omitted
    assert cond.omission_reason == "objective_task_omission"


def test_counterfactual_same_slow_different_history():
    """Counterfactual: World A (40) vs World B (1) with same Slow -> different condition text."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")

    # World A: 40 records
    rec_a = tuple(
        _make_record(
            interaction_id=f"inter-a-{i}",
            source_occurrence_id=f"occ-a-{i}",
            user_id="alice",
            occurred_at=now - timedelta(days=50 - i),
        )
        for i in range(40)
    )
    view_a = derive_longitudinal_view(
        rec_a,
        query=LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=now),
        now=now,
    )

    # World B: 1 record
    rec_b = (
        _make_record(
            interaction_id="inter-b-1",
            source_occurrence_id="occ-b-1",
            user_id="alice",
            occurred_at=now - timedelta(days=1),
        ),
    )
    view_b = derive_longitudinal_view(
        rec_b,
        query=LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=now),
        now=now,
    )

    cond_a = compile_condition(
        user_message="Good morning.",
        participant_id="alice",
        longitudinal_view=view_a,
        fast_state=None,
        slow_state=None,
        persona_ref="kayla_v0",
    )
    cond_b = compile_condition(
        user_message="Good morning.",
        participant_id="alice",
        longitudinal_view=view_b,
        fast_state=None,
        slow_state=None,
        persona_ref="kayla_v0",
    )

    assert not cond_a.is_omitted
    assert not cond_b.is_omitted
    assert cond_a.condition_text != cond_b.condition_text
    assert "40" in cond_a.condition_text
    assert "1" in cond_b.condition_text
