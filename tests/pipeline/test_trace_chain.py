"""D5.6 trace causal chain tests: Evidence -> Observation -> State -> Projection."""

from datetime import UTC, datetime

from mind_runtime.contracts import Evidence, Interaction, InteractionStatus, Observation, SyncFields
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)


class TypedFactPort:
    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        scope = evidence.scope
        observation = Observation(
            id=f"observation-{evidence.id}",
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key="user.sleep.phase.observed",
            value="awake",
            confidence=1.0,
            observed_at=evidence.occurred_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, f"observation-{evidence.id}", 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


def run_full_turn(commit: bool = True) -> TurnOrchestrator:
    orchestrator = TurnOrchestrator(
        clock=FakeClock(NOW),
        trace=TraceRecorder(),
        fact_ingest=TypedFactPort(),
    )
    orchestrator.begin_turn(
        Interaction(
            interaction_id="interaction-1",
            scope=make_scope(),
            channel="chat",
            session_id="session-1",
            turn_id="turn-1",
            started_at=NOW,
            committed_at=None,
            status=InteractionStatus.OPEN,
        )
    )
    orchestrator.ingest(make_evidence(text="我刚睡醒", occurred_at=NOW))
    orchestrator.run()
    if commit:
        orchestrator.commit_turn()
    return orchestrator


def test_trace_chain_covers_full_causality() -> None:
    orchestrator = run_full_turn()
    entries = orchestrator.trace.trace("interaction-1")
    stages = [entry.stage for entry in entries]
    # begin -> ingest -> state (facts) -> process -> projection -> dispatch -> commit
    assert stages[0] == "begin"
    assert stages[1] == "ingest"
    assert "state" in stages
    assert stages.index("state") < stages.index("process")
    assert "projection" in stages
    assert stages.index("projection") < stages.index("dispatch")
    assert stages[-1] == "commit"
    # The chain references resolve across stages.
    refs = {entry.ref for entry in entries}
    assert "evidence-1" in refs
    assert "observation-evidence-1" not in refs  # observations carry evidence ids
    assert any(ref is not None and ref.startswith("user.sleep.phase:") for ref in refs)
    assert "projection-interaction-1" in refs
    assert "receipt-interaction-1" in refs


def test_trace_chain_replays_identically() -> None:
    first = run_full_turn()
    second = run_full_turn()
    assert [entry.stage for entry in first.trace.trace("interaction-1")] == [
        entry.stage for entry in second.trace.trace("interaction-1")
    ]


def test_abort_chain_ends_with_abort() -> None:
    orchestrator = run_full_turn(commit=False)
    orchestrator.abort_turn()
    entries = orchestrator.trace.trace("interaction-1")
    assert entries[-1].stage == "abort"
    assert entries[-1].outcome == "manual"
