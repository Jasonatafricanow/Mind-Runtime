"""Focused tests for the optional Surface.initiative admission gate."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
import json

import pytest

from mind_runtime.contracts import (
    IntentEngineInput,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.surface import SurfaceProductionAdapter
from tests.surface.spec_support import sample_candidate

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
RUNTIME = "fixture-runtime"
SCOPE = Scope(
    domain=ScopeDomain.AGENT,
    agent_id="fixture-persona",
    persona_id="persona-fixture-a",
)


def _sync(object_id: str, version: int = 1) -> SyncFields:
    return SyncFields(SCOPE, RUNTIME, object_id, version, f"idem-{object_id}-v{version}")


def _fixture(
    *,
    sharing_urge: float = 0.6,
    curiosity: float = 0.5,
    sadness: float = 0.2,
):
    raw = sample_candidate()
    overrides = {
        "agent.affect.sharing_urge": sharing_urge,
        "agent.affect.curiosity": curiosity,
        "agent.affect.sadness": sadness,
    }
    for item in raw["projected_dynamics"]["states"]:
        if item["dimension"] in overrides:
            item["value"] = overrides[item["dimension"]]
    surface = SurfaceProductionAdapter().project(raw)
    states = tuple(
        RuntimeState(
            state_id=item["state_id"],
            scope=SCOPE,
            origin_runtime_id=RUNTIME,
            dimension=item["dimension"],
            value=item["value"],
            status="active",
            valid_from=NOW,
            valid_until=None,
            relevant_until=None,
            last_observed_at=NOW,
            evidence_refs=("evidence-1",),
            transition_refs=(),
            updated_at=NOW,
            version=item["version"],
            sync=_sync(item["state_id"], item["version"]),
        )
        for item in raw["projected_dynamics"]["states"]
    )
    projected = ProjectedMindState(
        projection_id="projection:fixture-1",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        projected_states=states,
        sync=_sync("projection:fixture-1"),
    )
    situation = Situation(
        situation_id="situation-1",
        scope=SCOPE,
        origin_runtime_id=RUNTIME,
        derived_facts=(),
        effective_state_ref="effective-1",
        observed_at=NOW,
        historical_context=None,
        persona_id=SCOPE.persona_id,
        relationship_ids=(),
        evidence_refs=("evidence-1",),
    )
    return raw, surface, projected, situation


def _rule(
    *,
    kind: str = "spontaneous_share",
    root: str = "agent.affect.sharing_urge",
    minimum_initiative: float | None = 0.5,
) -> IntentRule:
    return IntentRule(
        rule_id=f"rule-{kind}",
        kind=kind,
        base_strength=0.0,
        dimension_weights=((root, 1.0),),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.3,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        minimum_initiative=minimum_initiative,
    )


def _evaluate(rule: IntentRule, *, surface=True, **values):
    raw, projected_surface, projected, situation = _fixture(**values)
    result = DeterministicIntentEngine((rule,), RUNTIME).evaluate(
        IntentEngineInput(
            interaction_id="fixture-1",
            scope=SCOPE,
            origin_runtime_id=RUNTIME,
            context=situation,
            projected=projected,
            accepted_events=(),
            clock=NOW,
            surface=projected_surface if surface else None,
            persona_version=raw["persona"]["persona_version"],
            persona_content_digest=raw["persona"]["persona_content_digest"],
        )
    )
    return result


@pytest.mark.parametrize(
    ("kind", "root"),
    [
        ("spontaneous_share", "agent.affect.sharing_urge"),
        ("proactive_inquiry", "agent.affect.curiosity"),
    ],
)
def test_gate_allows_supported_spontaneous_motives(kind: str, root: str) -> None:
    result = _evaluate(_rule(kind=kind, root=root))
    assert len(result.candidates) == 1
    assert result.traces[0].reason_codes == ("threshold_met",)
    assert result.traces[0].surface_controls_ref is not None
    assert all(c.source_kind != "surface" for c in result.traces[0].contributions)


def test_low_initiative_suppresses_candidate_without_changing_domain_strength() -> None:
    result = _evaluate(
        _rule(minimum_initiative=0.7),
        sharing_urge=0.6,
        curiosity=0.1,
        sadness=0.8,
    )
    assert result.candidates == ()
    trace = result.traces[0]
    assert trace.final_strength == 0.6
    assert trace.unclamped_score == 0.6
    assert trace.reason_codes == ("initiative_below_minimum",)


def test_gate_fails_closed_when_surface_is_missing() -> None:
    result = _evaluate(_rule(), surface=False)
    assert result.candidates == ()
    assert result.traces[0].final_strength == 0.6
    assert result.traces[0].reason_codes == ("surface_unavailable",)


def test_gate_rejects_stale_surface_lineage() -> None:
    raw, surface, projected, situation = _fixture()
    stale = replace(projected, projection_id="projection:stale")
    result = DeterministicIntentEngine((_rule(),), RUNTIME).evaluate(
        IntentEngineInput(
            interaction_id="fixture-1",
            scope=SCOPE,
            origin_runtime_id=RUNTIME,
            context=situation,
            projected=stale,
            accepted_events=(),
            clock=NOW,
            surface=surface,
            persona_version=raw["persona"]["persona_version"],
            persona_content_digest=raw["persona"]["persona_content_digest"],
        )
    )
    assert result.candidates == ()
    assert result.traces[0].reason_codes == ("surface_stale_or_mismatch",)


def test_high_sadness_does_not_gate_reach_out() -> None:
    rule = IntentRule(
        rule_id="reach-out",
        kind="reach_out",
        base_strength=0.8,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.5,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
    )
    result = _evaluate(
        rule,
        sharing_urge=0.0,
        curiosity=0.0,
        sadness=1.0,
    )
    assert [candidate.kind for candidate in result.candidates] == ["reach_out"]


@pytest.mark.parametrize(
    ("kind", "root", "surface_weights", "event_kind", "direct_weight"),
    [
        ("reach_out", "agent.affect.sharing_urge", (), None, 1.0),
        (
            "spontaneous_share",
            "agent.affect.sharing_urge",
            (("initiative", 0.1),),
            None,
            1.0,
        ),
        ("spontaneous_share", "agent.affect.sharing_urge", (), "event", 1.0),
        ("spontaneous_share", "agent.affect.sharing_urge", (), None, 0.5),
    ],
)
def test_gate_rejects_shapes_that_mix_authorities(
    kind: str,
    root: str,
    surface_weights: tuple[tuple[str, float], ...],
    event_kind: str | None,
    direct_weight: float,
) -> None:
    with pytest.raises(ValueError):
        IntentRule(
            rule_id="invalid-gate",
            kind=kind,
            base_strength=0.0,
            dimension_weights=((root, direct_weight),),
            event_kind=event_kind,
            event_bonus=0.0,
            minimum_strength=0.3,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
            surface_control_weights=surface_weights,
            minimum_initiative=0.5,
        )


def test_legacy_ruleset_hash_shape_omits_absent_gate() -> None:
    legacy = _rule(minimum_initiative=None)
    engine = DeterministicIntentEngine((legacy,), RUNTIME)
    wire = asdict(legacy)
    wire.pop("minimum_initiative")
    expected = "ruleset:" + sha256(
        json.dumps(
            [wire],
            sort_keys=True,
            default=str,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    assert engine._ruleset_ref == expected
