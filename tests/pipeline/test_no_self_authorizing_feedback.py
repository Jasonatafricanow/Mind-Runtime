"""ADR-0010: derived runtime artifacts never authorize their own feedback."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AuthorityLevel,
    Evidence,
    Interaction,
    InteractionStatus,
    Scope,
    ScopeDomain,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError, OwnershipError
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from tests.golden.fixtures.common import make_evidence, make_scope
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def make_persona() -> PersonaProfile:
    return PersonaProfile(
        persona_id="persona-kayla",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.anxiety",
                baseline=0.2,
                initial_value=0.2,
                sensitivity=0.7,
                recovery_rate=0.1,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )


def make_interaction(interaction_id: str, *, scope: Scope | None = None) -> Interaction:
    return Interaction(
        interaction_id=interaction_id,
        scope=scope or make_scope(),
        channel="chat",
        session_id="session-1",
        turn_id=f"turn-{interaction_id}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def make_runtime() -> tuple[TurnOrchestrator, FactIngestService]:
    clock = FakeClock(NOW)
    service = FactIngestService(clock=clock)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        fact_ingest=service,
        persona=make_persona(),
    )
    return orchestrator, service


def run_committed_user_turn(
    orchestrator: TurnOrchestrator,
    *,
    interaction_id: str,
    evidence: Evidence,
) -> None:
    orchestrator.begin_turn(make_interaction(interaction_id, scope=evidence.scope))
    orchestrator.ingest(evidence)
    orchestrator.run()
    orchestrator.commit_turn()


def test_later_user_turn_does_not_reconsume_expression_or_projection() -> None:
    orchestrator, service = make_runtime()
    run_committed_user_turn(
        orchestrator,
        interaction_id="interaction-1",
        evidence=make_evidence(text="第一条真实用户消息"),
    )
    before_ids = tuple(item.id for item in service.evidence.all())
    expression = orchestrator.expression_outcome
    projection = orchestrator.turn_projection
    projected = orchestrator.projected
    assert expression is not None
    assert expression.accepted_expression is not None
    assert projection is not None
    assert projected is not None

    run_committed_user_turn(
        orchestrator,
        interaction_id="interaction-2",
        evidence=make_evidence(
            text="第二条真实用户消息",
            evidence_id="evidence-user-2",
            source_id="message-user-2",
        ),
    )

    after = service.evidence.all()
    assert tuple(item.id for item in after) == before_ids + ("evidence-user-2",)
    assert all(item.source_id != expression.outcome_id for item in after)
    assert all(item.source_id != projection.projection_id for item in after)
    assert all(item.id != projection.projection_id for item in after)
    for item in after:
        assert isinstance(item.payload, Mapping)
        assert item.payload.get("text") != expression.accepted_expression
        assert item.payload.get("projection_id") != projection.projection_id


@pytest.mark.parametrize("source_type", ("assistant_output", "assistant_expression"))
@pytest.mark.parametrize("text", ("我是 Lara", "普通的助手输出"))
def test_assistant_expression_cannot_self_authorize(source_type: str, text: str) -> None:
    orchestrator, service = make_runtime()
    run_committed_user_turn(
        orchestrator,
        interaction_id="interaction-1",
        evidence=make_evidence(text="真实用户消息"),
    )
    expression = orchestrator.expression_outcome
    assert expression is not None
    canonical_before = orchestrator.canonical
    persona_before = orchestrator._persona
    observation_count_before = service.observations.count()
    internal_evidence = make_evidence(
        text=text,
        evidence_id=f"evidence-{source_type}-{text == '我是 Lara'}",
        source_id=expression.outcome_id,
        source_type=source_type,
        level=AuthorityLevel.SYSTEM,
    )

    orchestrator.begin_turn(make_interaction("interaction-feedback"))
    with pytest.raises(AuthorityError, match="internally derived"):
        orchestrator.ingest(internal_evidence)

    assert service.evidence.get(internal_evidence.scope, internal_evidence.id) == internal_evidence
    assert service.provenance.all()[-1].evidence_id == internal_evidence.id
    assert service.observations.count() == observation_count_before
    assert orchestrator.observations == ()
    assert orchestrator.canonical == canonical_before
    assert orchestrator._persona == persona_before


def test_real_projection_cannot_self_authorize() -> None:
    orchestrator, service = make_runtime()
    run_committed_user_turn(
        orchestrator,
        interaction_id="interaction-1",
        evidence=make_evidence(text="真实用户消息"),
    )
    projection = orchestrator.turn_projection
    projected = orchestrator.projected
    assert projection is not None
    assert projected is not None
    canonical_before = orchestrator.canonical
    persona_before = orchestrator._persona
    observation_count_before = service.observations.count()
    projection_evidence = make_evidence(
        text="projection echo",
        evidence_id="evidence-projection-echo",
        source_id=projection.projection_id,
        source_type="internal_projection",
        level=AuthorityLevel.SYSTEM,
    )
    projection_evidence = replace(
        projection_evidence,
        payload={
            "projection_id": projection.projection_id,
            "projected_state_ids": tuple(state.state_id for state in projected.projected_states),
        },
    )

    orchestrator.begin_turn(make_interaction("interaction-projection-feedback"))
    with pytest.raises(AuthorityError, match="internally derived"):
        orchestrator.ingest(projection_evidence)

    assert (
        service.evidence.get(projection_evidence.scope, projection_evidence.id)
        == projection_evidence
    )
    assert service.provenance.all()[-1].evidence_id == projection_evidence.id
    assert service.observations.count() == observation_count_before
    assert orchestrator.observations == ()
    assert orchestrator.canonical == canonical_before
    assert orchestrator._persona == persona_before


@pytest.mark.parametrize(
    "scope",
    (
        Scope(
            domain=ScopeDomain.AGENT,
            agent_id="runtime-1",
            persona_id="persona-lara",
        ),
        Scope(
            domain=ScopeDomain.RELATIONSHIP,
            relationship_id="relationship-user-lara",
            persona_id="persona-lara",
        ),
    ),
)
def test_registered_event_cannot_write_foreign_persona_scope(scope: Scope) -> None:
    orchestrator, service = make_runtime()
    canonical_before = orchestrator.canonical
    persona_before = orchestrator._persona
    evidence = make_evidence(
        text="typed foreign write",
        evidence_id=f"evidence-foreign-{scope.domain.value}",
        source_id=f"event-foreign-{scope.domain.value}",
        source_type="typed_event",
        scope=scope,
        level=AuthorityLevel.VERIFIED,
    )

    orchestrator.begin_turn(make_interaction("interaction-foreign", scope=scope))
    with pytest.raises(OwnershipError, match="persona"):
        orchestrator.ingest(evidence)

    assert service.evidence.get(scope, evidence.id) == evidence
    assert service.provenance.all()[-1].evidence_id == evidence.id
    assert service.observations.count() == 0
    assert orchestrator.observations == ()
    assert orchestrator.canonical == canonical_before
    assert orchestrator._persona == persona_before
