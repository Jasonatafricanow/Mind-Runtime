"""Tests for MR Affect Slice 02: Longitudinal Temporal Structure (Baseline, Recent Deviation, Repair).

Covers:
- Core Experiment A: Long stable history + recent deviation (no entity verdicts).
- Core Experiment B: Same recent history, different deep history (counterfactual verification).
- Core Experiment C: Verbal repair vs behavioral repair (distinction and no forgiven/trust restored verdicts).
- Core Experiment D: Reappraisal of same occurrence (trajectory preservation, distinct_root_count = 1).
- Core Experiment E: Numeric ablation (identical Slow/Fast/Persona, different temporal condition).
- Occurrence identity authority & unresolved record handling.
- Controls: Grammar omission & 0-history silence.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from mind_runtime.contracts import (
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.appraisal import AcceptedAppraisalRecord
from mind_runtime.contracts.expression import TurnConditionProjection
from mind_runtime.contracts.historical import (
    AppraisalRevisionTrajectory,
    EarlierPatternSummary,
    LongitudinalQuery,
    LongitudinalView,
    RecentSegmentSummary,
    RepairEvidenceSummary,
)
from mind_runtime.emotional_transition.history import (
    derive_longitudinal_view,
    resolve_occurrence_identity,
)
from mind_runtime.expression.context import compile_condition


def _make_appraisal_record(
    *,
    interaction_id: str,
    source_occurrence_id: str,
    source_refs: tuple[str, ...] = (),
    user_id: str = "alice",
    salience: float = 0.1,
    valence: str = "positive",
    meanings: tuple[str, ...] = ("ordinary_exchange",),
    occurred_at: datetime,
    assessed_at: datetime | None = None,
    acceptance_id: str | None = None,
) -> AcceptedAppraisalRecord:
    scope = Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id=user_id, persona_id="kayla_v0")
    refs = source_refs or (f"ev-{source_occurrence_id}",)
    return AcceptedAppraisalRecord(
        acceptance_id=acceptance_id or f"acc-{interaction_id}",
        interaction_id=interaction_id,
        source_occurrence_id=source_occurrence_id,
        candidate_id=f"cand-{interaction_id}",
        candidate_kind="ordinary_interaction",
        candidate_confidence=0.9,
        appraisal_id=f"app-{interaction_id}",
        meanings=meanings,
        valence=valence,
        relationship_relevance="relational_security",
        appraisal_confidence=0.85,
        salience=salience,
        source_scope=scope,
        owner_scope=Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0"),
        resolved_relationship_scope=scope,
        source_refs=refs,
        supporting_refs=refs,
        context_dependency_refs=(),
        source_occurred_at=occurred_at,
        source_received_at=occurred_at,
        assessed_at=assessed_at or occurred_at,
        persona_id="kayla_v0",
        persona_version="1",
        route_status="ACCEPTED",
        acceptance_status="COMMITTED",
        acceptance_reason="low_salience_relationship_appraisal",
        contract_version="1",
        binding_version="1",
        payload_digest="digest",
    )


# ============================================================================
# Core Experiment A: Long Stable History + Recent Deviation
# ============================================================================


def test_core_experiment_a_long_stable_plus_recent_deviation():
    """Core Experiment A: 40 earlier positive (8 weeks) + 3 recent negative.

    Condition notes deviation from earlier distribution without entity verdicts.
    """
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
        max_records=256,
        recent_window_days=7,
        min_earlier_occurrences=3,
        min_recent_occurrences=1,
    )

    # 40 earlier positive records across 8 weeks (older than 7 days)
    earlier = [
        _make_appraisal_record(
            interaction_id=f"inter-early-{i}",
            source_occurrence_id=f"occ-early-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=56 - i),
        )
        for i in range(40)
    ]

    # 3 recent negative records (within last 7 days)
    recent = [
        _make_appraisal_record(
            interaction_id=f"inter-recent-{i}",
            source_occurrence_id=f"occ-recent-{i}",
            user_id="alice",
            valence="negative",
            occurred_at=now - timedelta(days=3 - i),
        )
        for i in range(3)
    ]

    view = derive_longitudinal_view(tuple(earlier + recent), query=query, now=now)

    assert view.distinct_root_count == 43
    assert view.earlier_pattern is not None
    assert view.earlier_pattern.occurrence_count == 40
    assert view.earlier_pattern.predominant_valence == "positive"
    assert view.recent_segment is not None
    assert view.recent_segment.occurrence_count == 3
    assert view.recent_segment.has_recent_deviation is True

    cond = compile_condition(
        user_message="Good morning.",
        participant_id="alice",
        longitudinal_view=view,
    )

    assert not cond.is_omitted
    assert "Earlier covered appraisal history for alice: 40 independent occurrences" in cond.condition_text
    assert "Recent covered segment: 3 consecutive negative appraisal occurrences, differing from the earlier distribution." in cond.condition_text

    # Strictly no entity verdicts
    forbidden = ["reliable", "unreliable", "stable relationship", "deteriorating", "trust collapsed", "attachment"]
    for word in forbidden:
        assert word not in cond.condition_text.lower()


# ============================================================================
# Core Experiment B: Same Recent, Different Deep History (Counterfactual)
# ============================================================================


def test_core_experiment_b_counterfactual_same_recent_different_deep_history():
    """Core Experiment B: Same recent 3 negative, but World A has 40 earlier positive vs World B 40 earlier negative.

    Proves counterfactual: compiled condition strictly differs based on deep temporal history structure.
    """
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
        max_records=256,
        recent_window_days=7,
    )

    recent_3_neg = [
        _make_appraisal_record(
            interaction_id=f"inter-rec-{i}",
            source_occurrence_id=f"occ-rec-{i}",
            user_id="alice",
            valence="negative",
            occurred_at=now - timedelta(days=3 - i),
        )
        for i in range(3)
    ]

    # World A: 40 earlier positive
    world_a_earlier = [
        _make_appraisal_record(
            interaction_id=f"inter-a-early-{i}",
            source_occurrence_id=f"occ-a-early-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=56 - i),
        )
        for i in range(40)
    ]
    view_a = derive_longitudinal_view(tuple(world_a_earlier + recent_3_neg), query=query, now=now)

    # World B: 40 earlier negative
    world_b_earlier = [
        _make_appraisal_record(
            interaction_id=f"inter-b-early-{i}",
            source_occurrence_id=f"occ-b-early-{i}",
            user_id="alice",
            valence="negative",
            occurred_at=now - timedelta(days=56 - i),
        )
        for i in range(40)
    ]
    view_b = derive_longitudinal_view(tuple(world_b_earlier + recent_3_neg), query=query, now=now)

    cond_a = compile_condition(user_message="Good morning.", participant_id="alice", longitudinal_view=view_a)
    cond_b = compile_condition(user_message="Good morning.", participant_id="alice", longitudinal_view=view_b)

    assert cond_a.condition_text != cond_b.condition_text

    # World A notes deviation
    assert "differing from the earlier distribution" in cond_a.condition_text
    # World B notes consistency
    assert "consistent with earlier pattern" in cond_b.condition_text


# ============================================================================
# Core Experiment C: Verbal Repair vs Behavioral Repair
# ============================================================================


def test_core_experiment_c_verbal_vs_behavioral_repair():
    """Core Experiment C: Distinguishes verbal apology signal from behavioral fulfillment.

    Neither results in 'forgiven' or 'trust restored' verdicts.
    """
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )

    base_history = [
        _make_appraisal_record(
            interaction_id=f"inter-base-{i}",
            source_occurrence_id=f"occ-base-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=20 - i),
        )
        for i in range(10)
    ]
    # Breach event
    breach = _make_appraisal_record(
        interaction_id="inter-breach",
        source_occurrence_id="occ-breach",
        user_id="alice",
        valence="negative",
        occurred_at=now - timedelta(days=5),
    )
    # Verbal apology
    verbal_apology = _make_appraisal_record(
        interaction_id="inter-apology",
        source_occurrence_id="occ-apology",
        user_id="alice",
        valence="neutral",
        meanings=("verbal_apology",),
        occurred_at=now - timedelta(days=4),
    )

    # World A: Apology only
    view_a = derive_longitudinal_view(tuple(base_history + [breach, verbal_apology]), query=query, now=now)
    assert view_a.repair_evidence is not None
    assert view_a.repair_evidence.has_verbal_repair is True
    assert view_a.repair_evidence.has_behavioral_repair is False
    assert view_a.repair_evidence.repair_assessment == "verbal_only"

    cond_a = compile_condition(user_message="Hello.", participant_id="alice", longitudinal_view=view_a)
    assert "Verbal repair signal recorded; no subsequent behavioral fulfillment observed." in cond_a.condition_text

    # World B: Apology + subsequent fulfilled commitment
    commitment_fulfilled = _make_appraisal_record(
        interaction_id="inter-fulfillment",
        source_occurrence_id="occ-fulfillment",
        user_id="alice",
        valence="positive",
        meanings=("promise_kept", "commitment_fulfilled"),
        occurred_at=now - timedelta(days=2),
    )
    view_b = derive_longitudinal_view(
        tuple(base_history + [breach, verbal_apology, commitment_fulfilled]),
        query=query,
        now=now,
    )
    assert view_b.repair_evidence is not None
    assert view_b.repair_evidence.has_verbal_repair is True
    assert view_b.repair_evidence.has_behavioral_repair is True
    assert view_b.repair_evidence.repair_assessment == "behavioral_supported"

    cond_b = compile_condition(user_message="Hello.", participant_id="alice", longitudinal_view=view_b)
    assert "Subsequent behavior consistent with repair observed (1 occurrences)." in cond_b.condition_text

    # Forbidden verdicts in both
    for cond in (cond_a, cond_b):
        for forbidden_word in ["forgiven", "trust restored", "relationship repaired", "repaired relationship"]:
            assert forbidden_word not in cond.condition_text.lower()


# ============================================================================
# Core Experiment D: Reappraisal of Same Occurrence
# ============================================================================


def test_core_experiment_d_reappraisal_trajectory():
    """Core Experiment D: Multiple appraisal revisions for one occurrence.

    Occurrence is counted once; revision trajectory is preserved; effective appraisal is latest.
    """
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )

    t_occurred = now - timedelta(days=10)
    t_rev1 = now - timedelta(days=10)
    t_rev2 = now - timedelta(days=2)

    # Revision 1: initial negative appraisal
    rev1 = _make_appraisal_record(
        interaction_id="inter-occ1-r1",
        source_occurrence_id="occ-1",
        user_id="alice",
        valence="negative",
        occurred_at=t_occurred,
        assessed_at=t_rev1,
        acceptance_id="acc-r1",
    )
    # Revision 2: reappraisal after context -> neutral
    rev2 = _make_appraisal_record(
        interaction_id="inter-occ1-r2",
        source_occurrence_id="occ-1",
        user_id="alice",
        valence="neutral",
        occurred_at=t_occurred,
        assessed_at=t_rev2,
        acceptance_id="acc-r2",
    )

    view = derive_longitudinal_view((rev1, rev2), query=query, now=now)

    # Invariants
    assert view.distinct_root_count == 1
    assert view.total_record_count == 1
    assert view.raw_record_count == 2
    assert len(view.revision_trajectories) == 1

    traj = view.revision_trajectories[0]
    assert traj.occurrence_id == "occ-1"
    assert traj.has_reappraisal is True
    assert traj.initial_valence == "negative"
    assert traj.effective_valence == "neutral"
    assert len(traj.revisions) == 2
    assert traj.effective_appraisal == rev2

    cond = compile_condition(user_message="Hello.", participant_id="alice", longitudinal_view=view)
    assert "One earlier event was later reappraised after additional context." in cond.condition_text


# ============================================================================
# Core Experiment E: Numeric Ablation
# ============================================================================


def test_core_experiment_e_numeric_ablation():
    """Core Experiment E: Identical numeric Slow state, Fast state, and Persona, but different temporal structure -> different TurnConditionProjection."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=now)

    # History A: 20 positive occurrences
    hist_a = [
        _make_appraisal_record(
            interaction_id=f"inter-a-{i}",
            source_occurrence_id=f"occ-a-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=30 - i),
        )
        for i in range(20)
    ]
    # History B: 5 positive occurrences
    hist_b = [
        _make_appraisal_record(
            interaction_id=f"inter-b-{i}",
            source_occurrence_id=f"occ-b-{i}",
            user_id="alice",
            valence="positive",
            occurred_at=now - timedelta(days=10 - i),
        )
        for i in range(5)
    ]

    view_a = derive_longitudinal_view(tuple(hist_a), query=query, now=now)
    view_b = derive_longitudinal_view(tuple(hist_b), query=query, now=now)

    # Identical external states
    mock_fast = None
    mock_slow = None
    persona = "kayla_v0"

    cond_a = compile_condition(
        user_message="Hello.",
        participant_id="alice",
        longitudinal_view=view_a,
        fast_state=mock_fast,
        slow_state=mock_slow,
        persona_ref=persona,
    )
    cond_b = compile_condition(
        user_message="Hello.",
        participant_id="alice",
        longitudinal_view=view_b,
        fast_state=mock_fast,
        slow_state=mock_slow,
        persona_ref=persona,
    )

    assert cond_a.condition_text != cond_b.condition_text
    assert "20 independent occurrences" in cond_a.condition_text
    assert "4 independent occurrences" in cond_b.condition_text
    assert "Recent covered segment: 1 occurrences" in cond_b.condition_text


# ============================================================================
# Occurrence Identity Authority & Unresolved Records
# ============================================================================


def test_occurrence_identity_authority_and_unresolved_handling():
    """Verify source_occurrence_id is canonical authority; unresolved records are excluded from independent occurrence counts."""
    from types import SimpleNamespace

    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=now)

    # Valid record with source_occurrence_id
    rec_valid = _make_appraisal_record(
        interaction_id="inter-valid",
        source_occurrence_id="occ-valid-1",
        user_id="alice",
        occurred_at=now - timedelta(days=5),
    )
    assert resolve_occurrence_identity(rec_valid) == "occ-valid-1"

    # Legacy record without source_occurrence_id but with source_refs
    scope = Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id="alice", persona_id="kayla_v0")
    rec_legacy = SimpleNamespace(
        source_occurrence_id="",  # empty
        source_refs=("ev-legacy-1",),
        resolved_relationship_scope=scope,
        valence="positive",
        source_occurred_at=now - timedelta(days=4),
        assessed_at=now - timedelta(days=4),
        acceptance_id="acc-legacy",
    )
    assert resolve_occurrence_identity(rec_legacy) == "ev-legacy-1"

    # Unresolved record: neither is present
    rec_unresolved = SimpleNamespace(
        source_occurrence_id="",
        source_refs=(),
        resolved_relationship_scope=scope,
        valence="positive",
        source_occurred_at=now - timedelta(days=3),
        assessed_at=now - timedelta(days=3),
        acceptance_id="acc-unresolved",
    )
    assert resolve_occurrence_identity(rec_unresolved) is None

    view = derive_longitudinal_view((rec_valid, rec_legacy, rec_unresolved), query=query, now=now)

    # Unresolved record does NOT increment distinct_root_count
    assert view.distinct_root_count == 2
    assert view.unresolved_record_count == 1
    assert view.raw_record_count == 3


# ============================================================================
# Controls: Grammar Omission & 0-History Silence
# ============================================================================


def test_controls_grammar_omission_and_zero_history_silence():
    """Verify objective tasks and zero-history continue to omit condition projection."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=now)

    rec = _make_appraisal_record(
        interaction_id="inter-1",
        source_occurrence_id="occ-1",
        user_id="alice",
        occurred_at=now - timedelta(days=5),
    )
    view = derive_longitudinal_view((rec,), query=query, now=now)

    # Objective task: grammar
    cond_grammar = compile_condition(
        user_message="Check grammar: 'I am here.'",
        participant_id="alice",
        longitudinal_view=view,
    )
    assert cond_grammar.is_omitted is True
    assert cond_grammar.omission_reason == "objective_task_omission"

    # 0 history
    view_zero = derive_longitudinal_view((), query=query, now=now)
    cond_zero = compile_condition(
        user_message="Hello.",
        participant_id="alice",
        longitudinal_view=view_zero,
    )
    assert cond_zero.is_omitted is True
    assert cond_zero.condition_text == ""
    assert cond_zero.omission_reason == "zero_history_omission"
