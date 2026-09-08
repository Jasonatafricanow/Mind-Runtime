"""AA.2: relationship history provenance survives the real D8 path."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    EmotionalTransitionInput,
    EmotionalTransitionResult,
    Evidence,
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    Interaction,
    InteractionStatus,
    PatternMatchSummary,
    Scope,
    ScopeDomain,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.dynamics.ports import EngineEmotionalTransitionPort
from mind_runtime.emotional_transition.effects import EventEffectRule
from mind_runtime.emotional_transition.history import BoundedHistoricalContextAdapter
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.facts.service import FactIngestService
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from tests.golden.fixtures.common import make_evidence
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
RELATIONSHIP_SCOPE = Scope(
    domain=ScopeDomain.RELATIONSHIP,
    relationship_id="relationship-user-kayla",
    persona_id="persona-kayla",
)
LARA_SCOPE = Scope(
    domain=ScopeDomain.RELATIONSHIP,
    relationship_id="relationship-user-lara",
    persona_id="persona-lara",
)


def persona() -> PersonaProfile:
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


def relationship_item(
    *,
    scope: Scope = RELATIONSHIP_SCOPE,
    source_refs: tuple[str, ...] = ("relationship-evidence-1",),
) -> HistoricalContextItem:
    return HistoricalContextItem(
        item_id="relationship-item-1",
        scope=scope,
        external_id="provider-external-1",
        kind="relationship_event",
        proposition="A prior private agreement was cancelled.",
        source_refs=source_refs,
        confidence=0.9,
        relevance_hint=0.8,
    )


def pattern_summary(
    *,
    scope: Scope = RELATIONSHIP_SCOPE,
    matched_refs: tuple[str, ...] = ("relationship-item-1",),
) -> PatternMatchSummary:
    return PatternMatchSummary(
        summary_id="relationship-summary-1",
        scope=scope,
        origin_runtime_id="provider-runtime",
        match_count=1,
        first_seen_at=NOW,
        last_seen_at=NOW,
        matched_refs=matched_refs,
        confidence=0.8,
    )


def relationship_bundle(
    *,
    scope: Scope = RELATIONSHIP_SCOPE,
    events: tuple[HistoricalContextItem, ...] | None = None,
    summaries: tuple[PatternMatchSummary, ...] | None = None,
) -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id="relationship-bundle-1",
        scope=scope,
        origin_runtime_id="provider-runtime",
        episodes=(),
        stable_facts=(),
        relationship_events=(relationship_item(scope=scope),) if events is None else events,
        pattern_summaries=(pattern_summary(scope=scope),) if summaries is None else summaries,
        source_refs=("provider-source-1", "provider-source-2"),
        provider_trace="provider-trace-exact",
    )


def user_category_bundle() -> HistoricalContextBundle:
    user_item = relationship_item(scope=USER_SCOPE)
    user_summary = pattern_summary(scope=USER_SCOPE)
    return HistoricalContextBundle(
        bundle_id="user-bundle-with-private-category",
        scope=USER_SCOPE,
        origin_runtime_id="provider-runtime",
        episodes=(),
        stable_facts=(),
        relationship_events=(user_item,),
        pattern_summaries=(user_summary,),
        source_refs=(user_item.item_id,),
        provider_trace="provider-user-invalid-category",
    )


class RecordingProvider:
    def __init__(self, bundle: HistoricalContextBundle) -> None:
        self.bundle = bundle
        self.queries: list[HistoricalContextQuery] = []

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        self.queries.append(query)
        return self.bundle


class CountingSemanticProvider:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, **_kwargs: object) -> tuple[()]:
        self.calls += 1
        return ()


class RecordingTransition:
    def __init__(self, delegate: EngineEmotionalTransitionPort) -> None:
        self.delegate = delegate
        self.inputs: list[EmotionalTransitionInput] = []

    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        self.inputs.append(transition_input)
        return self.delegate.transition(transition_input)


def interaction(scope: Scope) -> Interaction:
    return Interaction(
        interaction_id=f"interaction-{scope.domain.value}",
        scope=scope,
        channel="chat",
        session_id="session-1",
        turn_id=f"turn-{scope.domain.value}",
        started_at=NOW,
        committed_at=None,
        status=InteractionStatus.OPEN,
    )


def typed_evidence(scope: Scope) -> Evidence:
    return replace(
        make_evidence(
            text="cancelled",
            scope=scope,
            occurred_at=NOW,
            received_at=NOW,
            evidence_id=f"evidence-{scope.domain.value}",
            source_id=f"event-{scope.domain.value}",
        ),
        source_type="typed_event",
        payload={"kind": "plan_cancelled", "attributes": {"recurrence": "1"}},
    )


def make_runtime(
    provider_bundle: HistoricalContextBundle,
) -> tuple[
    TurnOrchestrator,
    FactIngestService,
    RecordingProvider,
    CountingSemanticProvider,
    RecordingTransition,
]:
    clock = FakeClock(NOW)
    profile = persona()
    service = FactIngestService(clock=clock)
    provider = RecordingProvider(provider_bundle)
    semantic = CountingSemanticProvider()
    transition = RecordingTransition(
        EngineEmotionalTransitionPort(
            engine=DynamicsEngine(persona=profile),
            runtime_id="runtime-1",
            effect_rules=(
                EventEffectRule(
                    event_kind="plan_cancelled",
                    dimension="agent.affect.anxiety",
                    base_amount=0.2,
                    history_amount_per_match=0.03,
                    history_amount_cap=0.05,
                    minimum_history_confidence=0.5,
                ),
            ),
            semantic_router=SemanticRouter(provider=semantic),
        )
    )
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=service,
        persona=profile,
        historical_context=BoundedHistoricalContextAdapter(provider=provider, budget=2),
        emotional_transition=transition,
    )
    return orchestrator, service, provider, semantic, transition


def begin_with_evidence(orchestrator: TurnOrchestrator, scope: Scope) -> None:
    orchestrator.begin_turn(interaction(scope))
    orchestrator.ingest(typed_evidence(scope))


def test_same_relationship_provenance_reaches_applied_history_effect() -> None:
    provider_bundle = relationship_bundle()
    before = sha256_bytes(canonical_json_bytes(provider_bundle))
    orchestrator, _service, provider, semantic, transition = make_runtime(provider_bundle)
    begin_with_evidence(orchestrator, RELATIONSHIP_SCOPE)
    orchestrator.run()
    after = sha256_bytes(canonical_json_bytes(provider_bundle))

    expected_history = replace(
        provider.bundle,
        source_refs=tuple(sorted(set(provider.bundle.source_refs))),
    )
    assert provider.queries[0].scope == RELATIONSHIP_SCOPE
    assert provider.queries[0].origin_runtime_id == "runtime-1"
    assert transition.inputs[0].history_context == expected_history
    assert orchestrator.situation is not None
    assert orchestrator.situation.historical_context == expected_history
    assert orchestrator.turn_projection is not None
    assert orchestrator.intent is not None
    assert orchestrator.policy_result is not None
    assert orchestrator.expression_outcome is not None
    assert orchestrator.transition_result is not None
    history_contributions = tuple(
        item
        for item in orchestrator.transition_result.assessment_trace.contributions
        if item.source_kind == "history" and item.applied
    )
    assert tuple(item.source_ref for item in history_contributions) == ("relationship-summary-1",)
    assert semantic.calls == 0
    assert before == after


@pytest.mark.parametrize("invalid_kind", ("foreign", "empty_refs", "missing_summary_ref"))
def test_invalid_relationship_history_stops_before_published_situation(
    invalid_kind: str,
) -> None:
    if invalid_kind == "foreign":
        provider_bundle = relationship_bundle(scope=LARA_SCOPE)
    elif invalid_kind == "empty_refs":
        provider_bundle = relationship_bundle(
            events=(relationship_item(source_refs=()),),
        )
    else:
        provider_bundle = relationship_bundle(
            summaries=(pattern_summary(matched_refs=("missing-item",)),),
        )
    orchestrator, service, _provider, semantic, transition = make_runtime(provider_bundle)
    begin_with_evidence(orchestrator, RELATIONSHIP_SCOPE)
    canonical_before = orchestrator.canonical

    with pytest.raises(ValueError):
        orchestrator.run()

    assert transition.inputs == []
    assert semantic.calls == 0
    assert orchestrator.situation is None
    assert orchestrator.transition_result is None
    assert orchestrator.turn_projection is None
    assert orchestrator.intent is None
    assert orchestrator.policy_result is None
    assert orchestrator.expression_outcome is None
    assert orchestrator.canonical == canonical_before
    assert service.observations.count() == 1
    assert service.evidence.count() == 1


def test_user_turn_rejects_private_relationship_category_before_dynamics() -> None:
    orchestrator, service, _provider, semantic, transition = make_runtime(user_category_bundle())
    begin_with_evidence(orchestrator, USER_SCOPE)
    canonical_before = orchestrator.canonical

    with pytest.raises(ValueError, match="relationship_events require relationship scope"):
        orchestrator.run()

    assert transition.inputs == []
    assert semantic.calls == 0
    assert orchestrator.situation is None
    assert orchestrator.transition_result is None
    assert orchestrator.turn_projection is None
    assert orchestrator.intent is None
    assert orchestrator.policy_result is None
    assert orchestrator.expression_outcome is None
    assert orchestrator.canonical == canonical_before
    assert service.observations.count() == 1
    assert service.evidence.count() == 1
