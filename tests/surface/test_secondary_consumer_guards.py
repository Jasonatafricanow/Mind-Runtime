"""Intent and Expression retain independent Surface lineage checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import IntentEngineInput, ReconsiderationPolicy, Situation
from mind_runtime.expression.context import DecisionContextCompiler
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.surface import lineage
from tests.surface.test_consumer_lineage_rejection import _case, _forged
from tests.surface.test_expression_provider_boundary import _build_test_harness


def _intent_case(surface):
    source, projected_surface, projected = _case(surface)
    now = datetime(2026, 9, 23, tzinfo=UTC)
    situation = Situation(
        situation_id="sit-1",
        scope=projected.scope,
        origin_runtime_id="fixture-runtime",
        derived_facts=(),
        effective_state_ref="state-ref-1",
        observed_at=now,
        historical_context=None,
        persona_id=projected.scope.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )
    rule = IntentRule(
        rule_id="reach-out-rule",
        kind="reach_out",
        base_strength=0.1,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0.0,
        minimum_strength=0.2,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.4),),
    )
    engine = DeterministicIntentEngine(rules=(rule,), runtime_id="fixture-runtime")
    engine_input = IntentEngineInput(
        interaction_id="fixture-1",
        scope=projected.scope,
        origin_runtime_id="fixture-runtime",
        context=situation,
        projected=projected,
        accepted_events=(),
        clock=now,
        surface=projected_surface,
        persona_version=source["persona"]["persona_version"],
        persona_content_digest=source["persona"]["persona_content_digest"],
    )
    assert len(engine.evaluate(engine_input).candidates) == 1
    return engine, engine_input, projected_surface


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("runtime_id",), "other", "surface_stale_or_mismatch"),
        (("source_projection_id",), "projection:other", "surface_stale_or_mismatch"),
        (("source_phase",), "committed", "surface_stale_or_mismatch"),
        (("source_states", 0, "version"), 999, "surface_stale_or_mismatch"),
        (("values", "contact_seeking"), None, "surface_invalid"),
    ],
)
def test_intent_rejects_forgery_even_if_shared_validator_is_bypassed(
    surface, monkeypatch, path, value, reason
):
    engine, engine_input, projected_surface = _intent_case(surface)
    monkeypatch.setattr(lineage, "validate_projected_surface", lambda *_a, **_k: True)
    forged = _forged(projected_surface, path, value)
    result = engine.evaluate(replace(engine_input, surface=forged))
    assert result.candidates == ()
    assert result.traces[0].reason_codes == (reason,)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("runtime_id",), "other"),
        (("source_projection_id",), "projection:other"),
        (("source_phase",), "committed"),
        (("persona_id",), "other"),
        (("recipe_id",), "surface-reference-v1"),
        (("source_states", 0, "version"), 999),
    ],
)
def test_expression_rejects_forgery_even_if_shared_validator_is_bypassed(monkeypatch, path, value):
    compiler, compiler_input, _renderer, projected_surface = _build_test_harness()
    monkeypatch.setattr(lineage, "validate_projected_surface", lambda *_a, **_k: True)
    forged = _forged(projected_surface, path, value)
    with pytest.raises(ValueError, match="SURFACE_LINEAGE_MISMATCH"):
        compiler.admit_surface_controls(forged, compiler_input)


def test_expression_requires_typed_available_surface():
    with pytest.raises(ValueError, match="surface must not be None"):
        DecisionContextCompiler.admit_surface_controls(None)
    with pytest.raises(TypeError, match="SurfaceProjectionResult"):
        DecisionContextCompiler.admit_surface_controls({"status": "AVAILABLE"})
