"""D3.C1 canonical ingest integration: TurnOrchestrator admits facts through the port.

The orchestrator must never construct an Observation from raw Evidence
itself; every ingest goes through the FactIngestPort so authority,
ownership, idempotency, and provenance always run on the canonical path.

Replay semantics are bound by ADR-0009: a replayed Evidence retains the
audit Interaction but adds no Observation to the current turn. The old
per-turn-view replay expectation (`test_ingest_replay_same_evidence_no_duplicate_observation`
asserting the replay stays in the current-turn view) is superseded by
ADR-0009; the contract tests that replace it land in W-B.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from mind_runtime.contracts import (
    Evidence,
    Interaction,
    InteractionStatus,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.facts.ports import FactAdmissionDisposition, FactAdmissionResult, FactIngestPort
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError, OwnershipError
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


class RecordingPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        self.calls.append((interaction_id, writing_runtime, writing_persona_id))
        scope = evidence.scope
        observation = Observation(
            id=f"observation-{evidence.id}",
            interaction_id=interaction_id,
            scope=scope,
            origin_runtime_id=writing_runtime,
            type="factual",
            key="fake.observed",
            value="fake",
            confidence=1.0,
            observed_at=NOW,
            evidence_refs=(evidence.id,),
            sync=SyncFields(scope, writing_runtime, f"observation-{evidence.id}", 1, "idem"),
        )
        return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)


def make_interaction(
    *, scope: Scope | None = None, interaction_id: str = "interaction-1"
) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=scope or make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id="turn-1",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_orchestrator(**kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), **kwargs)


def service_of(orchestrator: TurnOrchestrator) -> FactIngestService:
    """Narrow the port to the concrete service for store assertions."""
    assert isinstance(orchestrator.fact_ingest, FactIngestService)
    return orchestrator.fact_ingest


def test_orchestrator_default_ingest_is_fact_ingest_service() -> None:
    orchestrator = make_orchestrator()
    assert isinstance(orchestrator.fact_ingest, FactIngestService)
    assert isinstance(orchestrator.fact_ingest, FactIngestPort)


def test_ingest_delegates_observation_into_service_store() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    observation = orchestrator.ingest(make_evidence(text="我刚睡醒"))
    assert isinstance(observation, Observation)
    service = service_of(orchestrator)
    assert service.observations.count() == 1
    assert service.evidence.count() == 1
    # The observation and its provenance are bound to the turn interaction.
    assert observation.interaction_id == "interaction-1"
    entry = service.provenance.all()[0]
    assert entry.interaction_id == "interaction-1"


def test_ingest_rejects_assistant_evidence_no_observation() -> None:
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction())
    evidence = make_evidence(
        text="感觉你有点累。",
        source_id="assistant-1",
        source_type="assistant_message",
    )
    with pytest.raises(AuthorityError, match="assistant"):
        orchestrator.ingest(evidence)
    assert orchestrator.observations == ()
    assert service_of(orchestrator).observations.count() == 0
    # Evidence is still retained for independent auditability.
    assert service_of(orchestrator).evidence.count() == 1


def test_ingest_cross_persona_write_fails_closed() -> None:
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    orchestrator = make_orchestrator(runtime_id="lara")
    orchestrator.begin_turn(make_interaction(scope=kayla_scope))
    evidence = make_evidence(text="kayla affect write", scope=kayla_scope)
    with pytest.raises(OwnershipError, match="cannot write"):
        orchestrator.ingest(evidence)
    assert orchestrator.observations == ()
    assert service_of(orchestrator).observations.count() == 0


def test_ingest_owner_runtime_admitted() -> None:
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    orchestrator = make_orchestrator(
        runtime_id="kayla",
        persona=PersonaProfile(persona_id="persona-kayla", dimensions=()),
    )
    orchestrator.begin_turn(make_interaction(scope=kayla_scope))
    observation = orchestrator.ingest(
        make_evidence(text="kayla affect write", scope=kayla_scope, runtime_id="kayla")
    )
    assert isinstance(observation, Observation)
    assert service_of(orchestrator).observations.count() == 1


def test_ingest_replay_same_evidence_no_duplicate_observation() -> None:
    orchestrator = make_orchestrator()
    evidence = make_evidence(text="我刚睡醒")
    orchestrator.begin_turn(make_interaction(interaction_id="interaction-1"))
    orchestrator.ingest(evidence)
    orchestrator.begin_turn(make_interaction(interaction_id="interaction-2"))
    orchestrator.ingest(evidence)
    # The admission store never grows on replay (ADR-0009).
    service = service_of(orchestrator)
    assert service.observations.count() == 1
    assert service.evidence.count() == 1
    # ADR-0009: replay adds no Observation to the current turn; the audit
    # Interaction is retained and the turn continues without a new factual
    # event. (Supersedes the old per-turn-view expectation.)
    assert orchestrator.observations == ()


def test_fact_ingest_port_injectable_with_fake() -> None:
    port = RecordingPort()
    orchestrator = make_orchestrator(runtime_id="lara", fact_ingest=port)
    assert isinstance(orchestrator.fact_ingest, FactIngestPort)
    orchestrator.begin_turn(make_interaction())
    orchestrator.ingest(make_evidence(text="hello"))
    assert port.calls == [("interaction-1", "lara", None)]
    assert orchestrator.observations[0].id == "observation-evidence-1"


@pytest.mark.parametrize(
    "scope",
    (
        Scope(domain=ScopeDomain.AGENT, agent_id="runtime-1", persona_id="persona-kayla"),
        Scope(
            domain=ScopeDomain.RELATIONSHIP,
            relationship_id="relationship-user-kayla",
            persona_id="persona-kayla",
        ),
    ),
)
def test_orchestrator_forwards_persona_only_for_persona_owned_scope(scope: Scope) -> None:
    port = RecordingPort()
    orchestrator = make_orchestrator(
        fact_ingest=port,
        persona=PersonaProfile(persona_id="persona-kayla", dimensions=()),
    )
    orchestrator.begin_turn(make_interaction(scope=scope))
    orchestrator.ingest(make_evidence(text="owned write", scope=scope))
    assert port.calls == [("interaction-1", "runtime-1", "persona-kayla")]


def test_relationship_ingest_without_active_persona_fails_closed() -> None:
    scope = Scope(
        domain=ScopeDomain.RELATIONSHIP,
        relationship_id="relationship-user-kayla",
        persona_id="persona-kayla",
    )
    orchestrator = make_orchestrator()
    orchestrator.begin_turn(make_interaction(scope=scope))
    with pytest.raises(OwnershipError, match="persona"):
        orchestrator.ingest(make_evidence(text="owned write", scope=scope))
    assert orchestrator.observations == ()
    assert service_of(orchestrator).observations.count() == 0
