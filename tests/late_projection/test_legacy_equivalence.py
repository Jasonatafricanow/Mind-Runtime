"""Frozen pre-W1 EffectMapper outputs; never regenerate as part of tests.

Captured against accepted ADR-0027 base 7e9119f before mapper delegation.
The fixture records mapper output, real Dynamics output, and real gate decisions.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    AppraisalRouteDecision,
    HistoricalContextBundle,
    PatternMatchSummary,
    Scope,
    ScopeDomain,
    SemanticAppraisal,
    SemanticEventCandidate,
    SemanticRoutingResult,
)
from mind_runtime.dynamics.engine import DynamicsEngine
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.homeostasis.contracts import CandidateStateDelta
from mind_runtime.homeostasis.policy import FixedSalienceThresholdConfig, SalienceThresholdPolicy

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "legacy-effects.json"
NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
SCOPE = Scope(domain=ScopeDomain.USER, user_id="fixture-user")


def _config():
    manifest = json.loads(
        (ROOT / "certification/d11s/inputs/runtime-config.json").read_text(encoding="utf-8")
    )
    return {item["component_id"]: item["payload"] for item in manifest["components"]}


def _observe(case):
    config = _config()
    candidate = SemanticEventCandidate(
        candidate_id="fixture-candidate",
        scope=SCOPE,
        origin_runtime_id="fixture-runtime",
        kind=case["kind"],
        attributes=(),
        confidence=case["confidence"],
        evidence_refs=("current-evidence",),
    )
    appraisals = {}
    if case["appraisal_present"]:
        appraisals[candidate.candidate_id] = SemanticAppraisal(
            appraisal_id="fixture-appraisal",
            scope=SCOPE,
            origin_runtime_id="fixture-runtime",
            situation_ref="fixture-situation",
            meanings=("fixture-meaning",),
            valence="neutral",
            relationship_relevance="primary",
            confidence=case["confidence"],
            evidence_refs=candidate.evidence_refs,
            salience=case["salience"],
        )
    routing = SemanticRoutingResult(
        route=AppraisalRouteDecision(
            route_id="fixture-route",
            scope=SCOPE,
            path=AppraisalPath.DETERMINISTIC,
            ambiguity_score=None,
            confidence=case["confidence"],
            reason_codes=(),
        ),
        candidates=(candidate,),
        abstention_reasons=(),
        provider_call_count=0,
        appraisals_by_candidate_id=appraisals,
    )
    summaries = tuple(
        PatternMatchSummary(
            summary_id=f"pattern-{index}",
            scope=SCOPE,
            origin_runtime_id="fixture-runtime",
            match_count=item["matches"],
            first_seen_at=NOW - timedelta(days=10),
            last_seen_at=NOW - timedelta(days=1),
            matched_refs=(f"past-{index}",),
            confidence=item["confidence"],
        )
        for index, item in enumerate(case["history"])
    )
    history = (
        HistoricalContextBundle(
            bundle_id="fixture-history",
            scope=SCOPE,
            origin_runtime_id="fixture-runtime",
            episodes=(),
            stable_facts=(),
            relationship_events=(),
            pattern_summaries=summaries,
            source_refs=tuple(ref for item in summaries for ref in item.matched_refs),
            provider_trace="offline-fixture",
        )
        if summaries
        else None
    )
    mapped = EffectMapper(
        rules=tuple(EventEffectRule(**rule) for rule in config["emotional_effects"]["rules"])
    ).map(routing=routing, history=history)
    persona_config = config["persona_profile"]
    profiles = tuple(
        AffectiveDimensionProfile(
            **{
                **profile,
                "growth_profile": tuple(profile["growth_profile"]),
                "coupling_profile": tuple(profile["coupling_profile"]),
            }
        )
        for profile in persona_config["dimensions"]
    )
    engine = DynamicsEngine(
        persona=PersonaProfile(
            persona_id=persona_config["persona_id"],
            version=persona_config["version"],
            dimensions=profiles,
        )
    )
    dynamics = engine.step(
        current={p.dimension: p.initial_value for p in profiles},
        elapsed=timedelta(0),
        impulses=mapped.impulses,
    )
    policy = SalienceThresholdPolicy(config=FixedSalienceThresholdConfig(**config["homeostasis"]))
    confidences = dict(mapped.source_confidences)
    decisions = []
    # Gate input amounts come from Dynamics contributions for immediate affect,
    # and verbatim mapper proposals for longitudinal targets, matching Seam B.
    gate_inputs = [
        (c.dimension, c.source.removeprefix("impulse:"), c.amount)
        for c in dynamics.contributions
        if c.source.startswith("impulse:")
    ]
    gate_inputs += [
        (i.dimension, i.source_ref, i.amount)
        for i in mapped.impulses
        if i.source_ref.startswith("longitudinal:")
    ]
    for dimension, source, amount in gate_inputs:
        delta = CandidateStateDelta(
            target_dimension=dimension,
            proposed_value=amount,
            scope=SCOPE,
            evidence_refs=mapped.evidence_refs_by_source[source],
            salience=mapped.salience_by_source[source],
            confidence=confidences[source],
            source_event_ref=source,
            observed_at=NOW,
        )
        verdict = policy.decide(delta, None)
        decisions.append(
            {
                "dimension": dimension,
                "source": source,
                "amount": amount,
                "decision": verdict.decision.value,
                "reason_code": verdict.reason_code,
            }
        )
    return json.loads(
        json.dumps({"mapped": asdict(mapped), "dynamics": asdict(dynamics), "gate": decisions})
    )


def _cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("sample", _cases(), ids=lambda sample: sample["id"])
def test_production_rule_matches_frozen_pre_w1_output(sample):
    assert _observe(sample["input"]) == sample["expected"]


def test_fixture_covers_all_production_rules_and_authority_edges():
    cases = _cases()
    assert {sample["input"]["kind"] for sample in cases} == {
        rule["event_kind"] for rule in _config()["emotional_effects"]["rules"]
    }
    for kind in {sample["input"]["kind"] for sample in cases}:
        selected = [s for s in cases if s["input"]["kind"] == kind]
        assert {s["input"]["salience"] for s in selected} >= {None, 0.0, 0.2, 0.95}
        assert {s["input"]["confidence"] for s in selected} >= {0.0, 0.2, 0.95}
        assert any(not s["input"]["appraisal_present"] for s in selected)
        assert any(s["expected"]["gate"][-1]["decision"] == "reject" for s in selected)


@pytest.mark.parametrize(
    "kind", ("plan_cancelled", "plan_confirmed", "harsh_message", "warm_reunion")
)
def test_missing_confidence_cannot_enter_legacy_mapper(kind):
    # The existing typed candidate boundary rejects absent confidence before
    # mapping. It must never silently substitute a confidence authority.
    with pytest.raises((TypeError, ValueError)):
        SemanticEventCandidate(
            candidate_id="missing-confidence",
            scope=SCOPE,
            origin_runtime_id="fixture-runtime",
            kind=kind,
            attributes=(),
            confidence=None,
            evidence_refs=("current-evidence",),
        )
