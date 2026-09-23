"""ADR-0027: vendor event examples are not an exhaustive ontology."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Observation, Scope, ScopeDomain, Situation, SyncFields
from mind_runtime.emotional_transition import glm_provider, zen_provider

SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")
NOW = datetime(2026, 9, 9, tzinfo=UTC)
OBS = Observation(
    id="obs-1",
    interaction_id="turn-1",
    scope=SCOPE,
    type="factual",
    key="text",
    value="You remembered why this matters to me.",
    confidence=1.0,
    observed_at=NOW,
    evidence_refs=("evidence-1",),
    origin_runtime_id="runtime-1",
    sync=SyncFields(SCOPE, "runtime-1", "obs-1", 1, "idem-1"),
)
CONTEXT = Situation(
    situation_id="situation-1",
    scope=SCOPE,
    origin_runtime_id="runtime-1",
    derived_facts=(),
    effective_state_ref="effective-1",
    observed_at=NOW,
    historical_context=None,
    persona_id="kayla",
    relationship_ids=(),
    evidence_refs=("evidence-1",),
)
VALID = {
    "kind": "being_understood_in_a_new_way",
    "confidence": 0.91,
    "attributes": {"meaning": "recognition"},
}


@pytest.fixture(params=["glm", "zen"])
def run_provider(request, monkeypatch):
    provider = (
        glm_provider.GLMSemanticProvider(api_key="offline-test")
        if request.param == "glm"
        else zen_provider.ZenHy3Provider()
    )

    def run(payload):
        if request.param == "glm":
            monkeypatch.setattr(
                provider, "_classify_with_usage", lambda messages: (payload, None, "offline")
            )
        else:
            monkeypatch.setattr(provider, "_classify", lambda messages: payload)
        return provider.propose_with_telemetry(observations=(OBS,), context=CONTEXT, scope=SCOPE)

    return run


@pytest.mark.parametrize(
    "kind",
    [
        VALID["kind"],
        "plan_confirmed",
        "plan_cancelled",
        "warm_reunion",
        "harsh_message",
        "被理解后的释然",
    ],
)
def test_open_event_vocabulary_retains_observation_lineage(run_provider, kind):
    result = run_provider(dict(VALID, kind=kind))
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == kind
    assert candidate.evidence_refs == OBS.evidence_refs
    assert candidate.scope == SCOPE
    assert candidate.origin_runtime_id == OBS.origin_runtime_id
    assert candidate.confidence == 0.91
    assert candidate.attributes == (("meaning", "recognition"),)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "event",
        {},
        dict(VALID, unexpected="state write"),
        dict(VALID, kind=""),
        dict(VALID, kind=" "),
        dict(VALID, kind=123),
        dict(VALID, kind="x" * 129),
        dict(VALID, kind="event\nwrite"),
        dict(VALID, confidence=True),
        dict(VALID, confidence="0.9"),
        dict(VALID, confidence=None),
        dict(VALID, confidence=-0.1),
        dict(VALID, confidence=1.1),
        dict(VALID, confidence=float("nan")),
        dict(VALID, confidence=float("inf")),
        dict(VALID, attributes=[]),
        dict(VALID, attributes=None),
        dict(VALID, attributes={"meaning": 123}),
        dict(VALID, attributes={"": "meaning"}),
        dict(VALID, attributes={"meaning": ""}),
        dict(VALID, attributes={"x" * 65: "meaning"}),
        dict(VALID, attributes={"meaning": "x" * 1025}),
        dict(VALID, attributes={str(i): "meaning" for i in range(33)}),
        dict(VALID, attributes={str(i): "x" * 1024 for i in range(9)}),
        {"kind": "abstain", "confidence": True, "attributes": {}},
    ],
)
def test_malformed_or_oversized_response_fails_closed(run_provider, payload):
    result = run_provider(payload)
    assert result.candidates == ()
    assert result.error == "invalid_candidate_schema"
    assert not result.explicit_abstain


@pytest.mark.parametrize("kind", ["abstain", "none"])
def test_explicit_abstention_is_validated(run_provider, kind):
    result = run_provider({"kind": kind, "confidence": 0.0, "attributes": {}})
    assert result.candidates == ()
    assert result.explicit_abstain
    assert result.error is None


@pytest.mark.parametrize("module", [glm_provider, zen_provider])
def test_prompt_examples_are_explicitly_nonexhaustive(module):
    prompt = module.SYSTEM_PROMPT.lower()
    assert "non-exhaustive" in prompt
    assert "novel" in prompt
    assert "only legal values" not in prompt
    assert "never output any other kind" not in prompt
    for kind in ("plan_confirmed", "plan_cancelled", "warm_reunion", "harsh_message"):
        assert kind in prompt


@pytest.mark.parametrize(
    "payload",
    [
        dict(VALID, kind="x" * 128),
        dict(VALID, attributes={"x" * 64: "v" * 1024}),
        dict(VALID, attributes={str(i): "meaning" for i in range(32)}),
        dict(VALID, confidence=0),
        dict(VALID, confidence=1),
    ],
)
def test_valid_boundary_values_remain_accepted(run_provider, payload):
    assert len(run_provider(payload).candidates) == 1
