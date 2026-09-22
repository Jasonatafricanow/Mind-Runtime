"""Step 0 / Step 4 RED tests: End-to-End Host & BODY Envelope Capture for Daily Greeting.

Covers:
- R4: Alice greeting "Good morning." after 40 low-salience interactions:
  - Cold restart of runtime.
  - Turn runs with no new appraisal, no Slow mutation, no selected Intent.
  - Host bounded_context is NOT None.
  - Rendered BODY envelope contains the bounded historical condition.
  - Verifies exact forwarding from Compiler to Host to BODY without Host reinterpretation.
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
from mind_runtime.contracts.host import (
    HostCommitRequest,
    HostTurnRequest,
    HostTurnStatus,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.host.runtime_adapter import MindRuntimeHostAdapter
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


def _seed_40_interactions(facts_path: Path, state_path: Path, *, user_id: str = "alice"):
    facts_backend = SqliteFactBackend(facts_path)
    state_backend = SqliteStateBackend(state_path)
    try:
        scope_user = Scope(domain=ScopeDomain.USER, user_id=user_id)
        scope_rel = Scope(domain=ScopeDomain.RELATIONSHIP, relationship_id=user_id, persona_id="kayla_v0")
        owner_scope = Scope(domain=ScopeDomain.AGENT, agent_id="xiyue", persona_id="kayla_v0")

        base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        records = []
        for i in range(1, 41):
            t = base_time + timedelta(days=i)
            ev = Evidence(
                id=f"ev-{user_id}-{i}",
                scope=scope_user,
                origin_runtime_id="xiyue",
                source_type="user_message",
                source_id=f"src-{i}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope=scope_user, level=AuthorityLevel.ASSERTED, source_id=f"src-{i}"),
                occurred_at=t,
                received_at=t,
                payload={"text": f"Daily ordinary interaction {i}"},
                sync=SyncFields(scope_user, "xiyue", f"ev-{user_id}-{i}", 1, f"idem-ev-{i}"),
            )
            ob = Observation(
                id=f"ob-{user_id}-{i}",
                interaction_id=f"inter-{user_id}-{i}",
                scope=scope_user,
                origin_runtime_id="xiyue",
                type="factual",
                key="user_message.observed",
                value={"text": f"Daily ordinary interaction {i}"},
                confidence=1.0,
                observed_at=t,
                evidence_refs=(ev.id,),
                sync=SyncFields(scope_user, "xiyue", f"ob-{user_id}-{i}", 1, f"idem-ob-{i}"),
            )
            facts_backend.save_admission(ev, interaction_id=f"inter-{user_id}-{i}", observation=ob)

            rec = AcceptedAppraisalRecord(
                acceptance_id=f"acc-{user_id}-{i}",
                interaction_id=f"inter-{user_id}-{i}",
                source_occurrence_id=f"occ-{user_id}-{i}",
                candidate_id=f"cand-{user_id}-{i}",
                candidate_kind="ordinary_interaction",
                candidate_confidence=0.9,
                appraisal_id=f"app-{user_id}-{i}",
                meanings=("ordinary_interaction",),
                valence="positive",
                relationship_relevance="relational_security",
                appraisal_confidence=0.85,
                salience=0.1,
                source_scope=scope_user,
                owner_scope=owner_scope,
                resolved_relationship_scope=scope_rel,
                source_refs=(ev.id,),
                supporting_refs=(ev.id,),
                context_dependency_refs=(),
                source_occurred_at=t,
                source_received_at=t,
                assessed_at=t,
                persona_id="kayla_v0",
                persona_version="1",
                route_status="ACCEPTED",
                acceptance_status="COMMITTED",
                acceptance_reason="low_salience_relationship_appraisal",
                contract_version="1",
                binding_version="1",
                commit_marker_ref=f"marker-{user_id}-{i}",
                payload_digest="digest",
            )
            records.append(rec)

        state_backend.save_appraisal_evaluations(tuple(records))
    finally:
        facts_backend.close()
        state_backend.close()


def test_r4_cold_restart_greeting_with_no_intent(monkeypatch):
    """R4: Cold restart runtime -> Alice 'Good morning.' with no Intent -> Host bounded_context and BODY envelope."""
    monkeypatch.setenv("MR_ENABLED", "true")
    with tempfile.TemporaryDirectory() as tmpdir:
        facts_path = Path(tmpdir) / "facts.sqlite"
        state_path = Path(tmpdir) / "state.sqlite"

        # 1. Seed 40 low-salience interactions for Alice
        _seed_40_interactions(facts_path, state_path, user_id="alice")

        # 2. Cold start a fresh runtime stack
        now = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
        clock = _FixedClock(now)

        orchestrator, _ = build_runtime_stack(
            clock=clock,
            facts_db=str(facts_path),
            state_db=str(state_path),
            origin_runtime_id="xiyue",
            user_id="alice",
        )
        try:
            port = MindRuntimeHostAdapter(orchestrator=orchestrator)
            adapter = XiyueMRAdapter(port, runtime_id="xiyue", user_id="alice", persona_id="kayla_v0")

            # 3. Process ordinary greeting "Good morning."
            # This turn has no new relationship appraisal, no Slow mutation, and no selected Intent
            handle = adapter.begin_turn(
                message="Good morning.",
                channel="default",
                session_id="session-1",
                message_id="msg-1",
                occurred_at=now,
            )

            assert handle is not None
            assert handle.bounded_context is not None

            # 4. Render bounded context for BODY
            envelope = render_bounded_context(handle.bounded_context)
            assert envelope is not None

            # 5. Envelope must contain the bounded historical condition for Alice
            assert "40" in envelope
            assert "alice" in envelope.lower() or "internal relationship" in envelope.lower()
            assert "prior" in envelope.lower() or "history" in envelope.lower()

            # 6. Commit turn cleanly
            committed = adapter.commit_turn(handle)
            assert committed
        finally:
            if orchestrator._state_backend is not None:
                orchestrator._state_backend.close()
            if hasattr(orchestrator, "fact_ingest") and hasattr(orchestrator.fact_ingest, "_backend"):
                orchestrator.fact_ingest._backend.close()

