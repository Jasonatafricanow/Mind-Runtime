"""Semantic routing keeps language providers bounded and optional."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    AppraisalPath,
    Observation,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.emotional_transition.semantic import SemanticRouter

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
OTHER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-2")


def sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, 1, f"idem-{object_id}")


def context() -> Situation:
    return Situation(
        situation_id="context-1",
        scope=SCOPE,
        origin_runtime_id="runtime-1",
        derived_facts=(("conversation.active", "true"),),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )


def observation(
    *,
    key: str,
    value: object,
    observation_id: str = "observation-1",
) -> Observation:
    return Observation(
        id=observation_id,
        interaction_id="interaction-1",
        scope=SCOPE,
        type="factual",
        key=key,
        value=value,
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=("evidence-1",),
        origin_runtime_id="runtime-1",
        sync=sync(SCOPE, observation_id),
    )


def candidate(
    candidate_id: str,
    kind: str,
    confidence: float,
    *,
    scope: Scope = SCOPE,
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=scope,
        origin_runtime_id="runtime-1",
        kind=kind,
        attributes=(),
        confidence=confidence,
        evidence_refs=("evidence-1",),
    )


class ScriptedProvider:
    def __init__(self, result: tuple[SemanticEventCandidate, ...]) -> None:
        self.result = result
        self.calls = 0

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        assert observations
        assert context.scope == scope
        self.calls += 1
        return self.result


def test_trusted_typed_event_routes_without_provider() -> None:
    provider = ScriptedProvider((candidate("provider-1", "other", 0.99),))
    router = SemanticRouter(provider=provider)

    result = router.route(
        observations=(
            observation(
                key="typed_event.observed",
                value={
                    "kind": "plan_cancelled",
                    "attributes": {"recurrence": "2"},
                },
            ),
        ),
        context=context(),
        supplied_candidates=(),
    )

    assert result.route.path is AppraisalPath.TYPED_MAPPING
    assert result.route.reason_codes == ("trusted_typed_event",)
    assert result.provider_call_count == 0
    assert provider.calls == 0
    assert result.candidates[0].kind == "plan_cancelled"
    assert result.candidates[0].attributes == (("recurrence", "2"),)


def test_no_observation_is_deterministic_no_event() -> None:
    provider = ScriptedProvider((candidate("provider-1", "other", 0.99),))
    result = SemanticRouter(provider=provider).route(
        observations=(),
        context=context(),
        supplied_candidates=(),
    )

    assert result.route.path is AppraisalPath.DETERMINISTIC
    assert result.route.reason_codes == ("no_semantic_event",)
    assert result.candidates == ()
    assert result.provider_call_count == 0
    assert provider.calls == 0


def test_unmapped_language_without_provider_abstains() -> None:
    result = SemanticRouter().route(
        observations=(observation(key="user_message.observed", value={"text": "要不下周再约？"}),),
        context=context(),
        supplied_candidates=(),
    )

    assert result.route.path is AppraisalPath.LLM
    assert result.candidates == ()
    assert result.provider_call_count == 0
    assert result.abstention_reasons == ("semantic_provider_unavailable",)


def test_unmapped_language_calls_optional_provider_once() -> None:
    provider = ScriptedProvider((candidate("provider-1", "plan_deferred", 0.9),))
    result = SemanticRouter(provider=provider).route(
        observations=(observation(key="user_message.observed", value={"text": "要不下周再约？"}),),
        context=context(),
        supplied_candidates=(),
    )

    assert result.route.path is AppraisalPath.LLM
    assert result.route.reason_codes == ("unmapped_language", "provider_candidate")
    assert result.provider_call_count == 1
    assert provider.calls == 1
    assert result.candidates == (candidate("provider-1", "plan_deferred", 0.9),)


def test_low_confidence_candidate_is_retained_for_audit_but_abstains() -> None:
    low = candidate("provider-low", "plan_deferred", 0.74)
    result = SemanticRouter(provider=ScriptedProvider((low,))).route(
        observations=(observation(key="user_message.observed", value={"text": "maybe"}),),
        context=context(),
        supplied_candidates=(),
    )

    assert result.candidates == (low,)
    assert result.abstention_reasons == ("low_confidence",)


def test_near_equal_different_candidates_abstain_as_conflicting() -> None:
    first = candidate("candidate-a", "plan_cancelled", 0.90)
    second = candidate("candidate-b", "plan_deferred", 0.85)
    result = SemanticRouter(provider=ScriptedProvider((second, first))).route(
        observations=(observation(key="user_message.observed", value={"text": "ambiguous"}),),
        context=context(),
        supplied_candidates=(),
    )

    assert result.candidates == (first, second)
    assert result.abstention_reasons == ("conflicting_candidates",)


def test_wrong_scope_and_duplicate_provider_candidates_fail_closed() -> None:
    wrong_scope = replace(candidate("candidate-a", "plan_cancelled", 0.9), scope=OTHER_SCOPE)
    with pytest.raises(ValueError, match="scope"):
        SemanticRouter(provider=ScriptedProvider((wrong_scope,))).route(
            observations=(observation(key="user_message.observed", value={"text": "x"}),),
            context=context(),
            supplied_candidates=(),
        )

    duplicate = candidate("candidate-a", "plan_cancelled", 0.9)
    with pytest.raises(ValueError, match="unique"):
        SemanticRouter(provider=ScriptedProvider((duplicate, duplicate))).route(
            observations=(observation(key="user_message.observed", value={"text": "x"}),),
            context=context(),
            supplied_candidates=(),
        )


def test_router_rejects_invalid_thresholds_and_observation_scope() -> None:
    with pytest.raises(ValueError, match="minimum_confidence"):
        SemanticRouter(minimum_confidence=True)
    with pytest.raises(ValueError, match="conflict_margin"):
        SemanticRouter(conflict_margin=1.1)
    with pytest.raises(ValueError, match="observation scope"):
        SemanticRouter().route(
            observations=(
                replace(
                    observation(key="user_message.observed", value={"text": "x"}),
                    scope=OTHER_SCOPE,
                    sync=sync(OTHER_SCOPE, "observation-1"),
                ),
            ),
            context=context(),
            supplied_candidates=(),
        )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("not-a-mapping", "value must be a mapping"),
        ({"kind": ""}, "kind must be non-empty"),
        ({"kind": "event", "attributes": []}, "attributes must be a mapping"),
        (
            {"kind": "event", "attributes": {"count": 2}},
            "attributes must contain strings",
        ),
    ],
)
def test_typed_event_payload_fails_closed(value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SemanticRouter().route(
            observations=(observation(key="typed_event.observed", value=value),),
            context=context(),
            supplied_candidates=(),
        )
