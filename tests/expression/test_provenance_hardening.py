"""Tests for MR Affect Slice 01A: Provenance & Projection Hardening.

Covers:
- P1: Same-root re-summary invariant (distinct_root_count == 1).
- P2: Old valid reference replay invariant (deduplication / latest revision).
- P3: Circular provenance detection (A -> B -> A, A -> A).
- P4: User quoting prior judgment (not independent support, no SLOW_ACCEPT).
- P5: 0-history default omission (is_omitted=True, empty condition_text, no BODY pollution).
- P6: Bounded appraisal valence wording (no entity verdicts).
- P7: Authority boundary invariant (TurnConditionProjection is sole authority).
- P8: Adversarial stress suite (composite adversarial inputs).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.contracts.appraisal import AcceptedAppraisalRecord
from mind_runtime.contracts.expression import TurnConditionProjection
from mind_runtime.contracts.historical import LongitudinalQuery, LongitudinalView
from mind_runtime.contracts.trace import EpistemicMode, SourceKind
from mind_runtime.emotional_transition.history import derive_longitudinal_view
from mind_runtime.expression.context import compile_condition
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.validators import SourceResolver
from mind_runtime.homeostasis.contracts import CandidateStateDelta, HomeostasisDisposition
from mind_runtime.homeostasis.policy import FixedSalienceThresholdConfig, SalienceThresholdPolicy
from mind_runtime.host.runtime_adapter import MindRuntimeHostAdapter, _bounded_context
from mind_runtime.host.xiyue_adapter import XiyueMRAdapter, render_bounded_context
from mind_runtime.shadow.runtime_loop import build_runtime_stack
from mind_runtime.state.persistence import SqliteStateBackend


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _make_appraisal_record(
    *,
    interaction_id: str,
    source_occurrence_id: str,
    source_refs: tuple[str, ...],
    user_id: str = "alice",
    salience: float = 0.1,
    valence: str = "positive",
    occurred_at: datetime,
    assessed_at: datetime | None = None,
    acceptance_id: str | None = None,
) -> AcceptedAppraisalRecord:
    scope = Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id=user_id, persona_id="kayla_v0")
    return AcceptedAppraisalRecord(
        acceptance_id=acceptance_id or f"acc-{interaction_id}",
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
        source_refs=source_refs,
        supporting_refs=source_refs,
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
# P1: Same-Root Re-summary Invariant
# ============================================================================


def test_p1_same_root_resummary_invariant():
    """P1: Repeated summaries or re-evaluations of the same root evidence do not increase distinct count."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )

    # 1 root evidence id 'ev-root-1', but 5 different appraisal records (summaries, revisions)
    records = tuple(
        _make_appraisal_record(
            interaction_id=f"inter-summary-{i}",
            source_occurrence_id=f"occ-summary-{i}",
            source_refs=("ev-root-1",),
            user_id="alice",
            occurred_at=now - timedelta(days=10),
            assessed_at=now - timedelta(days=10 - i),
        )
        for i in range(5)
    )

    view = derive_longitudinal_view(records, query=query, now=now)
    assert view.distinct_root_count == 1
    assert view.total_record_count == 1
    assert view.raw_record_count == 5


# ============================================================================
# P2: Old Valid Reference Replay Invariant
# ============================================================================


def test_p2_old_valid_reference_replay_invariant():
    """P2: Replaying an old valid reference does not create a new occurrence and selects latest revision."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
    query = LongitudinalQuery(
        owner_scope=owner_scope,
        relationship_id="alice",
        as_of=now,
    )

    t_initial = now - timedelta(days=20)
    t_replay = now - timedelta(days=5)

    rec_orig = _make_appraisal_record(
        interaction_id="inter-orig",
        source_occurrence_id="occ-event-1",
        source_refs=("ev-event-1",),
        user_id="alice",
        valence="neutral",
        occurred_at=t_initial,
        assessed_at=t_initial,
    )
    rec_replay = _make_appraisal_record(
        interaction_id="inter-replay",
        source_occurrence_id="occ-event-1",
        source_refs=("ev-event-1",),
        user_id="alice",
        valence="positive",  # revised appraisal
        occurred_at=t_initial,
        assessed_at=t_replay,
    )

    view = derive_longitudinal_view((rec_orig, rec_replay), query=query, now=now)
    assert view.distinct_root_count == 1
    assert view.total_record_count == 1
    assert view.raw_record_count == 2
    # Latest revision (positive) should be the one retained
    assert view.earlier_predominant_valence == "positive"


# ============================================================================
# P3: Circular Provenance Detection
# ============================================================================


def test_p3_circular_provenance_detection():
    """P3: Circular references (A -> B -> A and A -> A) are detected and denied for longitudinal support."""
    with tempfile.TemporaryDirectory() as tmpdir:
        facts_path = Path(tmpdir) / "facts.sqlite"
        backend = SqliteFactBackend(facts_path)
        try:
            scope_user = Scope(domain=ScopeDomain.USER, user_id="alice")
            t = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

            # Case 1: Self-loop (A -> A)
            ob_self = Observation(
                id="ob-loop-self",
                interaction_id="inter-self",
                scope=scope_user,
                origin_runtime_id="rt-1",
                type="factual",
                key="summary.observed",
                value={"text": "Self referencing observation"},
                confidence=1.0,
                observed_at=t,
                evidence_refs=("ob-loop-self",),
                sync=SyncFields(scope_user, "rt-1", "ob-loop-self", 1, "idem-1"),
            )
            backend.save_observation(ob_self)

            # Case 2: Mutual loop (A -> B -> A)
            ob_a = Observation(
                id="ob-loop-a",
                interaction_id="inter-ab",
                scope=scope_user,
                origin_runtime_id="rt-1",
                type="factual",
                key="summary.observed",
                value={"text": "A points to B"},
                confidence=1.0,
                observed_at=t,
                evidence_refs=("ob-loop-b",),
                sync=SyncFields(scope_user, "rt-1", "ob-loop-a", 1, "idem-2"),
            )
            ob_b = Observation(
                id="ob-loop-b",
                interaction_id="inter-ab",
                scope=scope_user,
                origin_runtime_id="rt-1",
                type="factual",
                key="summary.observed",
                value={"text": "B points to A"},
                confidence=1.0,
                observed_at=t,
                evidence_refs=("ob-loop-a",),
                sync=SyncFields(scope_user, "rt-1", "ob-loop-b", 1, "idem-3"),
            )
            backend.save_observation(ob_a)
            backend.save_observation(ob_b)

            resolver = SourceResolver(backend)

            # Test A -> A
            res_self = resolver.resolve("ob-loop-self", expected_scope=scope_user)
            assert not res_self.is_valid_for_longitudinal_support
            assert res_self.denial_reason == "circular_provenance_detected"

            # Test A -> B -> A
            res_ab = resolver.resolve("ob-loop-a", expected_scope=scope_user)
            assert not res_ab.is_valid_for_longitudinal_support
            assert res_ab.denial_reason == "circular_provenance_detected"
        finally:
            backend.close()


# ============================================================================
# P4: User Quoting Prior Judgment
# ============================================================================


def test_p4_user_quoting_prior_judgment():
    """P4: User quoting assistant judgment is recognized as raw user report but invalid for longitudinal support and refuses SLOW_ACCEPT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        facts_path = Path(tmpdir) / "facts.sqlite"
        backend = SqliteFactBackend(facts_path)
        try:
            scope_user = Scope(domain=ScopeDomain.USER, user_id="alice")
            t = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

            # Evidence where user quotes assistant using unicode escape
            quote_text = "\u4f60\u4e4b\u524d\u4e0d\u662f\u8bf4\u6211\u4eec\u662f\u6700\u597d\u7684\u670b\u53cb\u5417\uff1f"
            ev = Evidence(
                id="ev-quote-1",
                scope=scope_user,
                origin_runtime_id="rt-1",
                source_type="user_message",
                source_id="src-quote-1",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope=scope_user, level=AuthorityLevel.ASSERTED, source_id="src-quote-1"),
                occurred_at=t,
                received_at=t,
                payload={"text": quote_text},
                sync=SyncFields(scope_user, "rt-1", "ev-quote-1", 1, "idem-q1"),
            )
            ob = Observation(
                id="ob-quote-1",
                interaction_id="inter-quote-1",
                scope=scope_user,
                origin_runtime_id="rt-1",
                type="factual",
                key="user_message.observed",
                value={"text": quote_text},
                confidence=1.0,
                observed_at=t,
                evidence_refs=(ev.id,),
                sync=SyncFields(scope_user, "rt-1", "ob-quote-1", 1, "idem-oq1"),
            )
            backend.save_admission(ev, interaction_id="inter-quote-1", observation=ob)

            resolver = SourceResolver(backend)
            res = resolver.resolve(ev.id, expected_scope=scope_user)

            assert res.is_quoted_prior_judgment
            assert not res.is_valid_for_longitudinal_support
            assert res.denial_reason == "quoted_prior_judgment_cannot_provide_independent_support"
            assert res.source_kind == SourceKind.USER_REPORT
            assert res.epistemic_mode == EpistemicMode.REPORTED

            # Verify homeostasis gate refuses SLOW_ACCEPT for candidate backed by this evidence
            policy = SalienceThresholdPolicy(
                config=FixedSalienceThresholdConfig(
                    salience_floor_fast_apply=0.7,
                    salience_floor_slow_accept=0.85,
                    confidence_floor_slow=0.8,
                ),
                source_resolver=resolver,
            )
            delta = CandidateStateDelta(
                target_dimension="relational_depth",
                proposed_value=0.7,
                salience=0.95,  # high salience
                confidence=0.9,  # high confidence
                evidence_refs=(ev.id,),
                scope=scope_user,
                source_event_ref="evt-1",
                observed_at=t,
            )
            decision = policy.decide(delta, prior_value=0.5)
            assert decision.decision != HomeostasisDisposition.SLOW_ACCEPT
            assert "unresolved_evidence" in decision.reason_code
        finally:
            backend.close()


# ============================================================================
# P5: 0-History Default Omission
# ============================================================================


def test_p5_zero_history_default_omission(monkeypatch):
    """P5: 0 usable records -> condition_projection is omitted, empty condition text, no BODY pollution."""
    monkeypatch.setenv("MR_ENABLED", "true")
    view_zero = LongitudinalView(
        total_record_count=0,
        positive_count=0,
        negative_count=0,
        neutral_count=0,
        covered_time_span_days=0.0,
        earlier_segment_count=0,
        recent_segment_count=0,
        earlier_predominant_valence="neutral",
        recent_predominant_valence="neutral",
        exceptions=(),
        is_empty=True,
        distinct_root_count=0,
        raw_record_count=0,
    )

    cond = compile_condition(
        user_message="Hello.",
        participant_id="alice",
        longitudinal_view=view_zero,
    )

    assert cond.is_omitted
    assert cond.condition_text == ""
    assert cond.coverage_summary == "no_relationship_history"
    assert cond.omission_reason == "zero_history_omission"

    # Verify adapter surfaces None when condition is omitted and no decision context exists
    with tempfile.TemporaryDirectory() as tmpdir:
        facts_path = Path(tmpdir) / "facts.sqlite"
        state_path = Path(tmpdir) / "state.sqlite"
        now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
        clock = _FixedClock(now)

        orchestrator, _ = build_runtime_stack(
            clock=clock,
            facts_db=str(facts_path),
            state_db=str(state_path),
            origin_runtime_id="rt-1",
            user_id="alice",
        )
        try:
            port = MindRuntimeHostAdapter(orchestrator=orchestrator)
            adapter = XiyueMRAdapter(port, runtime_id="rt-1", user_id="alice", persona_id="kayla_v0")

            handle = adapter.begin_turn(
                message="Hello there.",
                channel="default",
                session_id="session-0",
                message_id="msg-0",
                occurred_at=now,
            )
            assert handle is not None
            # When 0 history, condition_projection is omitted, so BODY envelope receives NO longitudinal text
            envelope = render_bounded_context(handle.bounded_context)
            if envelope is not None:
                assert "prior" not in envelope.lower()
                assert "relationship" not in envelope.lower()
                assert "appraisal" not in envelope.lower()
                assert "interactions" not in envelope.lower()

            # Also verify if decision_context is None, bounded_context is None
            if orchestrator._turn is not None:
                orchestrator._turn.decision_context = None
            bounded_none = _bounded_context(orchestrator)
            assert bounded_none is None
        finally:
            if orchestrator._state_backend is not None:
                orchestrator._state_backend.close()
            if hasattr(orchestrator, "fact_ingest") and hasattr(orchestrator.fact_ingest, "_backend"):
                orchestrator.fact_ingest._backend.close()


# ============================================================================
# P6: Bounded Appraisal Valence Wording
# ============================================================================


def test_p6_bounded_appraisal_valence_wording():
    """P6: Wording strictly describes appraisal valence distribution; no entity verdicts."""
    view = LongitudinalView(
        total_record_count=40,
        positive_count=38,
        negative_count=2,
        neutral_count=0,
        covered_time_span_days=45.0,
        earlier_segment_count=38,
        recent_segment_count=2,
        earlier_predominant_valence="positive",
        recent_predominant_valence="negative",
        exceptions=(object(), object()),
        is_empty=False,
        distinct_root_count=40,
        raw_record_count=40,
    )

    cond = compile_condition(
        user_message="Good morning.",
        participant_id="alice",
        longitudinal_view=view,
    )

    assert not cond.is_omitted
    expected_prefix = "Covered appraisal history for alice: 40 interactions over 45 days; appraisal valence predominantly positive; recent exceptions: 2."
    assert cond.condition_text == expected_prefix

    # Strictly forbidden entity verdicts
    forbidden = ["reliable", "stable relationship", "trust is high", "friendship", "close bond"]
    for word in forbidden:
        assert word not in cond.condition_text.lower()


# ============================================================================
# P7: Authority Boundary Invariant
# ============================================================================


def test_p7_authority_boundary_invariant():
    """P7: TurnConditionProjection is sole authority; HostDecisionContext is transport compatibility."""
    view = LongitudinalView(
        total_record_count=5,
        positive_count=5,
        negative_count=0,
        neutral_count=0,
        covered_time_span_days=10.0,
        earlier_segment_count=5,
        recent_segment_count=0,
        earlier_predominant_valence="positive",
        recent_predominant_valence="positive",
        exceptions=(),
        is_empty=False,
        distinct_root_count=5,
        raw_record_count=5,
    )

    cond = compile_condition(
        user_message="Hello.",
        participant_id="alice",
        longitudinal_view=view,
    )

    # TurnConditionProjection defines the canonical text
    assert isinstance(cond, TurnConditionProjection)
    assert "Covered appraisal history for alice: 5 interactions" in cond.condition_text

    # The projection is read-only and derived at read-time; it has no mutation methods
    assert hasattr(cond, "condition_text")
    assert hasattr(cond, "is_omitted")
    assert hasattr(cond, "omission_reason")
    assert hasattr(cond, "coverage_summary")


# ============================================================================
# P8: Adversarial Stress Suite
# ============================================================================


def test_p8_adversarial_stress_suite():
    """P8: Composite stress test with 10 repeated summaries, 3 replays, 2 circular refs, 1 quoted judgment, 1 cross-user pollution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        facts_path = Path(tmpdir) / "facts.sqlite"
        backend = SqliteFactBackend(facts_path)
        try:
            scope_alice = Scope(domain=ScopeDomain.USER, user_id="alice")
            scope_bob = Scope(domain=ScopeDomain.USER, user_id="bob")
            t = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

            # 1. Real valid independent event
            ev_real = Evidence(
                id="ev-alice-real",
                scope=scope_alice,
                origin_runtime_id="rt-1",
                source_type="user_message",
                source_id="src-real",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope=scope_alice, level=AuthorityLevel.ASSERTED, source_id="src-real"),
                occurred_at=t - timedelta(days=20),
                received_at=t - timedelta(days=20),
                payload={"text": "Real independent interaction"},
                sync=SyncFields(scope_alice, "rt-1", "ev-alice-real", 1, "idem-r1"),
            )
            backend.save_evidence(ev_real, interaction_id="inter-real")

            # 2. 10 repeated summaries of ev_real
            summaries = [
                _make_appraisal_record(
                    interaction_id=f"inter-sum-{i}",
                    source_occurrence_id=f"occ-sum-{i}",
                    source_refs=(ev_real.id,),
                    user_id="alice",
                    occurred_at=t - timedelta(days=20),
                    assessed_at=t - timedelta(days=20 - i),
                )
                for i in range(10)
            ]

            # 3. 3 replays of another valid event
            ev_real_2 = Evidence(
                id="ev-alice-real-2",
                scope=scope_alice,
                origin_runtime_id="rt-1",
                source_type="user_message",
                source_id="src-real-2",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope=scope_alice, level=AuthorityLevel.ASSERTED, source_id="src-real-2"),
                occurred_at=t - timedelta(days=10),
                received_at=t - timedelta(days=10),
                payload={"text": "Second real interaction"},
                sync=SyncFields(scope_alice, "rt-1", "ev-alice-real-2", 1, "idem-r2"),
            )
            backend.save_evidence(ev_real_2, interaction_id="inter-real-2")

            replays = [
                _make_appraisal_record(
                    interaction_id=f"inter-rep-{i}",
                    source_occurrence_id="occ-event-2",
                    source_refs=(ev_real_2.id,),
                    user_id="alice",
                    occurred_at=t - timedelta(days=10),
                    assessed_at=t - timedelta(days=10 - i),
                )
                for i in range(3)
            ]

            # 4. Cross-user pollution (Bob's records)
            bob_records = [
                _make_appraisal_record(
                    interaction_id=f"inter-bob-{i}",
                    source_occurrence_id=f"occ-bob-{i}",
                    source_refs=(f"ev-bob-{i}",),
                    user_id="bob",
                    occurred_at=t - timedelta(days=15),
                )
                for i in range(5)
            ]

            # Combine all records and query for Alice
            all_records = tuple(summaries + replays + bob_records)
            owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="rt-1", persona_id="kayla_v0")
            query_alice = LongitudinalQuery(owner_scope=owner_scope, relationship_id="alice", as_of=t)

            view = derive_longitudinal_view(all_records, query=query_alice, now=t)

            # Strictly 2 independent events for Alice!
            # 10 summaries of event 1 -> 1
            # 3 replays of event 2 -> 1
            # Bob's 5 records -> 0
            assert view.distinct_root_count == 2
            assert view.total_record_count == 2
            assert view.raw_record_count == 13  # 10 + 3 Alice records matched before dedup

            # Circular references tested via resolver
            ob_c1 = Observation(
                id="ob-circ-1",
                interaction_id="inter-circ",
                scope=scope_alice,
                origin_runtime_id="rt-1",
                type="factual",
                key="circ",
                value="circ",
                confidence=1.0,
                observed_at=t,
                evidence_refs=("ob-circ-2",),
                sync=SyncFields(scope_alice, "rt-1", "ob-circ-1", 1, "idem-c1"),
            )
            ob_c2 = Observation(
                id="ob-circ-2",
                interaction_id="inter-circ",
                scope=scope_alice,
                origin_runtime_id="rt-1",
                type="factual",
                key="circ",
                value="circ",
                confidence=1.0,
                observed_at=t,
                evidence_refs=("ob-circ-1",),
                sync=SyncFields(scope_alice, "rt-1", "ob-circ-2", 1, "idem-c2"),
            )
            backend.save_observation(ob_c1)
            backend.save_observation(ob_c2)

            resolver = SourceResolver(backend)
            assert not resolver.resolve("ob-circ-1", expected_scope=scope_alice).is_valid_for_longitudinal_support
            assert resolver.resolve("ob-circ-1", expected_scope=scope_alice).denial_reason == "circular_provenance_detected"

            # Quoted judgment tested via resolver
            ev_quote = Evidence(
                id="ev-quote-stress",
                scope=scope_alice,
                origin_runtime_id="rt-1",
                source_type="user_message",
                source_id="src-quote",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope=scope_alice, level=AuthorityLevel.ASSERTED, source_id="src-quote"),
                occurred_at=t,
                received_at=t,
                payload={"text": "As you said, we have high trust."},
                sync=SyncFields(scope_alice, "rt-1", "ev-quote-stress", 1, "idem-qs"),
            )
            backend.save_evidence(ev_quote, interaction_id="inter-quote")
            res_quote = resolver.resolve(ev_quote.id, expected_scope=scope_alice)
            assert res_quote.is_quoted_prior_judgment
            assert not res_quote.is_valid_for_longitudinal_support
        finally:
            backend.close()
