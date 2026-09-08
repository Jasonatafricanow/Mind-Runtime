"""Historical context is optional, bounded, deduplicated, and read-only."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    HistoricalContextBundle,
    HistoricalContextItem,
    HistoricalContextQuery,
    Observation,
    PatternMatchSummary,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.emotional_transition.history import (
    BoundedHistoricalContextAdapter,
    HistoryProviderUnavailable,
    NullHistoricalContext,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")
RELATIONSHIP_SCOPE = Scope(
    domain=ScopeDomain.RELATIONSHIP,
    relationship_id="relationship-user-kayla",
    persona_id="persona-kayla",
)


def sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def context() -> Situation:
    return Situation(
        situation_id="context-1",
        scope=SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=("evidence-current",),
    )


def typed_observation() -> Observation:
    return Observation(
        id="observation-current",
        interaction_id="interaction-1",
        scope=SCOPE,
        type="factual",
        key="typed_event.observed",
        value={"kind": "plan_cancelled", "attributes": {}},
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("evidence-current",),
        origin_runtime_id="runtime-1",
        sync=sync(SCOPE, "observation-current"),
    )


def item(item_id: str, *, scope: Scope = SCOPE) -> HistoricalContextItem:
    return HistoricalContextItem(
        item_id=item_id,
        scope=scope,
        external_id=f"external-{item_id}",
        kind="episode",
        proposition=f"historical fact {item_id}",
        source_refs=(f"evidence-{item_id}",),
        confidence=0.8,
        relevance_hint=0.7,
    )


def summary(summary_id: str, *, scope: Scope = SCOPE) -> PatternMatchSummary:
    return PatternMatchSummary(
        summary_id=summary_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        match_count=3,
        first_seen_at=NOW,
        last_seen_at=NOW,
        matched_refs=("evidence-old-1", "evidence-old-1", "evidence-old-2"),
        confidence=0.7,
    )


def bundle(*, scope: Scope = SCOPE) -> HistoricalContextBundle:
    repeated = item("item-a", scope=scope)
    return HistoricalContextBundle(
        bundle_id="bundle-1",
        scope=scope,
        origin_runtime_id="runtime-1",
        episodes=(item("item-b", scope=scope), repeated, item("item-c", scope=scope)),
        stable_facts=(repeated,),
        relationship_events=(),
        pattern_summaries=(summary("summary-a", scope=scope),),
        source_refs=("source-2", "source-1", "source-2"),
        provider_trace="fixture-provider",
    )


def relationship_context(*, scope: Scope = RELATIONSHIP_SCOPE) -> Situation:
    return replace(context(), scope=scope, persona_id=scope.persona_id)


def relationship_item(
    item_id: str = "relationship-item-1",
    *,
    scope: Scope = RELATIONSHIP_SCOPE,
    source_refs: tuple[str, ...] = ("evidence-relationship-1",),
) -> HistoricalContextItem:
    return HistoricalContextItem(
        item_id=item_id,
        scope=scope,
        external_id=f"external-{item_id}",
        kind="relationship_event",
        proposition=f"private relationship fact {item_id}",
        source_refs=source_refs,
        confidence=0.91,
        relevance_hint=0.83,
    )


def relationship_summary(
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
        confidence=0.77,
    )


def relationship_bundle(
    *,
    scope: Scope = RELATIONSHIP_SCOPE,
    episodes: tuple[HistoricalContextItem, ...] = (),
    events: tuple[HistoricalContextItem, ...] = (relationship_item(),),
    summaries: tuple[PatternMatchSummary, ...] = (relationship_summary(),),
) -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id="relationship-bundle-1",
        scope=scope,
        origin_runtime_id="provider-runtime",
        episodes=episodes,
        stable_facts=(),
        relationship_events=events,
        pattern_summaries=summaries,
        source_refs=("provider-source-2", "provider-source-1"),
        provider_trace="provider-trace-exact",
    )


class RecordingProvider:
    def __init__(
        self,
        result: HistoricalContextBundle | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self.result = result or bundle()
        self.unavailable = unavailable
        self.queries: list[HistoricalContextQuery] = []
        self.touch_calls = 0

    def query(self, query: HistoricalContextQuery) -> HistoricalContextBundle:
        self.queries.append(query)
        if self.unavailable:
            raise HistoryProviderUnavailable("offline")
        return self.result

    def touch(self, _item_id: str) -> None:
        self.touch_calls += 1


def test_null_history_keeps_current_turn_operational() -> None:
    assert (
        NullHistoricalContext().read(
            interaction_id="interaction-1",
            context=context(),
            observations=(typed_observation(),),
            scope=SCOPE,
            clock=NOW,
        )
        is None
    )


def test_adapter_builds_typed_query_and_returns_bounded_deduplicated_copy() -> None:
    provider = RecordingProvider()
    adapter = BoundedHistoricalContextAdapter(provider=provider, budget=2)

    result = adapter.read(
        interaction_id="interaction-1",
        context=context(),
        observations=(typed_observation(),),
        scope=SCOPE,
        clock=NOW,
    )

    assert result is not None
    assert result is not provider.result
    surfaced_ids = tuple(
        entry.item_id
        for entries in (result.episodes, result.stable_facts, result.relationship_events)
        for entry in entries
    )
    assert surfaced_ids == ("item-a", "item-b")
    assert result.pattern_summaries == ()
    assert result.source_refs == ("source-1", "source-2")
    assert provider.queries[0].budget == 2
    assert provider.queries[0].pattern_queries[0].signature == "plan_cancelled"
    assert provider.touch_calls == 0


def test_summary_refs_are_deduplicated_when_budget_reaches_summary() -> None:
    provider_bundle = replace(
        bundle(),
        episodes=(item("item-a"),),
        stable_facts=(),
        relationship_events=(),
    )
    result = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(provider_bundle), budget=2
    ).read(
        interaction_id="interaction-1",
        context=context(),
        observations=(typed_observation(),),
        scope=SCOPE,
        clock=NOW,
    )

    assert result is not None
    assert result.pattern_summaries[0].matched_refs == (
        "evidence-old-1",
        "evidence-old-2",
    )


def test_wrong_scope_bundle_and_item_fail_closed() -> None:
    adapter = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(bundle(scope=OTHER_SCOPE)), budget=2
    )
    with pytest.raises(ValueError, match="bundle scope"):
        adapter.read(
            interaction_id="interaction-1",
            context=context(),
            observations=(typed_observation(),),
            scope=SCOPE,
            clock=NOW,
        )

    mixed = replace(bundle(), episodes=(item("wrong", scope=OTHER_SCOPE),))
    with pytest.raises(ValueError, match="item scope"):
        BoundedHistoricalContextAdapter(provider=RecordingProvider(mixed), budget=2).read(
            interaction_id="interaction-1",
            context=context(),
            observations=(typed_observation(),),
            scope=SCOPE,
            clock=NOW,
        )


def test_declared_provider_unavailability_returns_none_without_touching() -> None:
    provider = RecordingProvider(unavailable=True)
    result = BoundedHistoricalContextAdapter(provider=provider, budget=2).read(
        interaction_id="interaction-1",
        context=context(),
        observations=(typed_observation(),),
        scope=SCOPE,
        clock=NOW,
    )

    assert result is None
    assert len(provider.queries) == 1
    assert provider.touch_calls == 0


def test_adapter_rejects_invalid_budget_and_input_scopes() -> None:
    provider = RecordingProvider()
    with pytest.raises(ValueError, match="budget"):
        BoundedHistoricalContextAdapter(provider=provider, budget=-1)

    adapter = BoundedHistoricalContextAdapter(provider=provider, budget=2)
    with pytest.raises(ValueError, match="context scope"):
        adapter.read(
            interaction_id="interaction-1",
            context=replace(context(), scope=OTHER_SCOPE),
            observations=(),
            scope=SCOPE,
            clock=NOW,
        )
    with pytest.raises(ValueError, match="observation scope"):
        adapter.read(
            interaction_id="interaction-1",
            context=context(),
            observations=(
                replace(
                    typed_observation(),
                    scope=OTHER_SCOPE,
                    sync=sync(OTHER_SCOPE, "observation-current"),
                ),
            ),
            scope=SCOPE,
            clock=NOW,
        )


def test_query_ignores_untyped_or_malformed_signatures() -> None:
    provider = RecordingProvider()
    observations = (
        replace(typed_observation(), key="user_message.observed", value="hello"),
        replace(
            typed_observation(),
            id="observation-2",
            value={"kind": 42},
            sync=sync(SCOPE, "observation-2"),
        ),
    )
    BoundedHistoricalContextAdapter(provider=provider, budget=2).read(
        interaction_id="interaction-1",
        context=context(),
        observations=observations,
        scope=SCOPE,
        clock=NOW,
    )
    assert provider.queries[0].pattern_queries == ()


def test_wrong_scope_and_duplicate_summaries_fail_or_deduplicate() -> None:
    wrong_summary = replace(bundle(), pattern_summaries=(summary("wrong", scope=OTHER_SCOPE),))
    with pytest.raises(ValueError, match="summary scope"):
        BoundedHistoricalContextAdapter(provider=RecordingProvider(wrong_summary), budget=2).read(
            interaction_id="interaction-1",
            context=context(),
            observations=(),
            scope=SCOPE,
            clock=NOW,
        )

    repeated = summary("summary-repeat")
    duplicate_bundle = replace(
        bundle(),
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(repeated, repeated),
    )
    result = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(duplicate_bundle), budget=2
    ).read(
        interaction_id="interaction-1",
        context=context(),
        observations=(),
        scope=SCOPE,
        clock=NOW,
    )
    assert result is not None
    assert tuple(summary.summary_id for summary in result.pattern_summaries) == ("summary-repeat",)
    assert result.pattern_summaries[0].matched_refs == (
        "evidence-old-1",
        "evidence-old-2",
    )


def test_user_scope_cannot_categorize_relationship_events() -> None:
    invalid = replace(bundle(), relationship_events=(item("private-user-item"),))
    adapter = BoundedHistoricalContextAdapter(provider=RecordingProvider(invalid), budget=0)
    with pytest.raises(ValueError, match="relationship_events require relationship scope"):
        adapter.read(
            interaction_id="interaction-1",
            context=context(),
            observations=(),
            scope=SCOPE,
            clock=NOW,
        )


@pytest.mark.parametrize(
    ("events", "summaries", "message"),
    (
        ((relationship_item(source_refs=()),), (relationship_summary(),), "source refs"),
        ((relationship_item(),), (relationship_summary(matched_refs=()),), "matched refs"),
        (
            (relationship_item(),),
            (relationship_summary(matched_refs=("missing-item",)),),
            "selected relationship item",
        ),
    ),
)
def test_relationship_provenance_fails_closed(
    events: tuple[HistoricalContextItem, ...],
    summaries: tuple[PatternMatchSummary, ...],
    message: str,
) -> None:
    provider = RecordingProvider(relationship_bundle(events=events, summaries=summaries))
    with pytest.raises(ValueError, match=message):
        BoundedHistoricalContextAdapter(provider=provider, budget=0).read(
            interaction_id="interaction-relationship",
            context=relationship_context(),
            observations=(),
            scope=RELATIONSHIP_SCOPE,
            clock=NOW,
        )


@pytest.mark.parametrize("foreign_field", ("relationship_id", "persona_id"))
@pytest.mark.parametrize("record_kind", ("bundle", "item", "summary"))
def test_foreign_relationship_identity_fails_closed(
    foreign_field: str,
    record_kind: str,
) -> None:
    foreign_scope = (
        replace(RELATIONSHIP_SCOPE, relationship_id="relationship-user-lara")
        if foreign_field == "relationship_id"
        else replace(RELATIONSHIP_SCOPE, persona_id="persona-lara")
    )
    provider_bundle = relationship_bundle()
    if record_kind == "bundle":
        provider_bundle = relationship_bundle(scope=foreign_scope)
        message = "bundle scope"
    elif record_kind == "item":
        provider_bundle = relationship_bundle(events=(relationship_item(scope=foreign_scope),))
        message = "item scope"
    else:
        provider_bundle = relationship_bundle(
            summaries=(relationship_summary(scope=foreign_scope),)
        )
        message = "summary scope"

    with pytest.raises(ValueError, match=message):
        BoundedHistoricalContextAdapter(provider=RecordingProvider(provider_bundle), budget=2).read(
            interaction_id="interaction-relationship",
            context=relationship_context(),
            observations=(),
            scope=RELATIONSHIP_SCOPE,
            clock=NOW,
        )


def test_relationship_provenance_survives_selection_without_mutating_input() -> None:
    provider_bundle = relationship_bundle()
    before = sha256_bytes(canonical_json_bytes(provider_bundle))
    result = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(provider_bundle), budget=2
    ).read(
        interaction_id="interaction-relationship",
        context=relationship_context(),
        observations=(),
        scope=RELATIONSHIP_SCOPE,
        clock=NOW,
    )
    after = sha256_bytes(canonical_json_bytes(provider_bundle))

    assert result is not None
    assert result.bundle_id == provider_bundle.bundle_id
    assert result.scope == RELATIONSHIP_SCOPE
    assert result.origin_runtime_id == "provider-runtime"
    assert result.relationship_events == provider_bundle.relationship_events
    assert result.pattern_summaries == provider_bundle.pattern_summaries
    assert result.source_refs == ("provider-source-1", "provider-source-2")
    assert result.provider_trace == "provider-trace-exact"
    assert before == after


def test_clipped_relationship_summary_is_omitted_whole() -> None:
    events = tuple(relationship_item(f"relationship-item-{index}") for index in range(1, 4))
    matched_refs = (events[0].item_id, events[2].item_id)
    provider_bundle = relationship_bundle(
        events=events,
        summaries=(relationship_summary(matched_refs=matched_refs),),
    )

    clipped = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(provider_bundle), budget=2
    ).read(
        interaction_id="interaction-relationship",
        context=relationship_context(),
        observations=(),
        scope=RELATIONSHIP_SCOPE,
        clock=NOW,
    )
    complete = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(provider_bundle), budget=4
    ).read(
        interaction_id="interaction-relationship",
        context=relationship_context(),
        observations=(),
        scope=RELATIONSHIP_SCOPE,
        clock=NOW,
    )

    assert clipped is not None
    assert clipped.pattern_summaries == ()
    assert complete is not None
    assert complete.pattern_summaries[0].matched_refs == matched_refs


def test_cross_category_dedup_cannot_leave_relationship_summary_unresolved() -> None:
    duplicate_id = "relationship-item-1"
    provider_bundle = relationship_bundle(
        episodes=(item(duplicate_id, scope=RELATIONSHIP_SCOPE),),
        events=(relationship_item(duplicate_id),),
        summaries=(relationship_summary(matched_refs=(duplicate_id,)),),
    )

    result = BoundedHistoricalContextAdapter(
        provider=RecordingProvider(provider_bundle), budget=2
    ).read(
        interaction_id="interaction-relationship",
        context=relationship_context(),
        observations=(),
        scope=RELATIONSHIP_SCOPE,
        clock=NOW,
    )

    assert result is not None
    assert tuple(entry.item_id for entry in result.episodes) == (duplicate_id,)
    assert result.relationship_events == ()
    assert result.pattern_summaries == ()
