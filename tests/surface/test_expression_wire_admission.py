"""Surface Expression refuses incomplete or internally revealing provider inputs."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mind_runtime.contracts import ExpressionContextKind, Scope, ScopeDomain
from mind_runtime.expression.context import DecisionContextCompiler
from mind_runtime.expression.expression_map import (
    candidate_expression_map,
    map_surface_to_qualitative_guidance,
    validate_expression_map,
)
from tests.surface.test_expression_provider_boundary import _build_test_harness


@pytest.mark.parametrize("change", ["guidance", "action", "internal_state"])
def test_renderer_rejects_incomplete_or_raw_surface_bundle(change):
    compiler, inp, renderer, _surface = _build_test_harness()
    context, _trace = compiler.compile(inp)
    items = context.expression_context
    if change == "guidance":
        items = tuple(
            item
            for item in items
            if not (item.kind is ExpressionContextKind.SURFACE_GUIDANCE and item.key == "warmth")
        )
    elif change == "action":
        items = tuple(item for item in items if item.kind is not ExpressionContextKind.ACTION)
    else:
        legacy_compiler, legacy_inp, _renderer, _surface = _build_test_harness(mode="LEGACY")
        legacy_context, _trace = legacy_compiler.compile(legacy_inp)
        internal = next(
            item
            for item in legacy_context.expression_context
            if item.kind is ExpressionContextKind.INTERNAL_STATE
        )
        items = (*items, internal)
    reason = (
        "SURFACE_PROVIDER_ISOLATION_VIOLATION"
        if change == "internal_state"
        else "SURFACE_ESSENTIAL_BUNDLE_INCOMPLETE"
    )
    with pytest.raises(ValueError, match=reason):
        renderer.render(replace(context, expression_context=items))


def test_compiler_requires_surface_and_can_bind_strict_mode():
    compiler, inp, _renderer, _surface = _build_test_harness()
    with pytest.raises(ValueError, match="requires surface"):
        compiler.compile(replace(inp, surface=None))
    context, _trace = compiler.compile_surface_v1(replace(inp, mode=None))
    assert any(
        item.kind is ExpressionContextKind.SURFACE_GUIDANCE for item in context.expression_context
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(map_id="other"),
        lambda m: m["consumed_controls"].append("contact_seeking"),
    ],
)
def test_expression_map_rejects_unpublished_identity_or_content(mutation):
    mapping = candidate_expression_map()
    mutation(mapping)
    with pytest.raises(ValueError, match="SURFACE_EXPRESSION_MAP_CONFLICT"):
        validate_expression_map(mapping)


@pytest.mark.parametrize(
    "surface,reason",
    [({"status": "UNAVAILABLE"}, "not AVAILABLE"), (None, "SurfaceProjectionResult or dict")],
)
def test_expression_map_requires_available_typed_surface(surface, reason):
    with pytest.raises((ValueError, TypeError), match=reason):
        map_surface_to_qualitative_guidance(surface)


def test_essential_surface_bundle_budget_checks_each_limit():
    compiler, inp, _renderer, surface = _build_test_harness()
    items = compiler.admit_surface_controls(surface, inp)
    config = compiler._config
    assert DecisionContextCompiler.withhold_on_budget_overflow(None, config)
    assert DecisionContextCompiler.withhold_on_budget_overflow(object(), config)
    assert not DecisionContextCompiler.withhold_on_budget_overflow(items, None)
    assert DecisionContextCompiler.withhold_on_budget_overflow(
        items, replace(config, max_item_chars=1)
    )
    assert DecisionContextCompiler.withhold_on_budget_overflow(items, replace(config, max_items=1))
    assert DecisionContextCompiler.withhold_on_budget_overflow(
        items, replace(config, max_render_chars=10)
    )
    assert not DecisionContextCompiler.withhold_on_budget_overflow(items, config)


def test_surface_compiler_rejects_invalid_mode_configuration():
    compiler, inp, _renderer, _surface = _build_test_harness()
    with pytest.raises(ValueError, match="mode must be LEGACY or SURFACE_V1"):
        replace(compiler._config, mode="unknown")
    with pytest.raises(ValueError, match="mode must be LEGACY or SURFACE_V1"):
        replace(inp, mode="unknown")


def test_renderer_rejects_diagnostic_reference_in_provider_text():
    _compiler, _inp, renderer, _surface = _build_test_harness()
    with pytest.raises(AssertionError, match="diagnostic reference"):
        renderer.verify_provider_information_isolation("[ACTION]\n- controls_id: leaked")
    assert renderer.render_surface_bundle(object()) == {}


@pytest.mark.parametrize(
    "part,reason",
    [
        ("situation_scope", "Situation scope"),
        ("effective_scope", "effective user state scope"),
        ("intent_scope", "Intent and Policy scope"),
        ("projected_scope", "projected agent state scope"),
        ("situation_origin", "Situation origin"),
        ("slow_origin", "slow_state origin_runtime_id mismatch"),
    ],
)
def test_expression_authority_rejects_cross_scope_or_origin_inputs(part, reason):
    compiler, inp, _renderer, _surface = _build_test_harness()
    other_scope = Scope(domain=ScopeDomain.AGENT, agent_id="other-agent", persona_id="other")
    if part == "situation_scope":
        inp = replace(inp, situation=replace(inp.situation, scope=other_scope))
    elif part == "effective_scope":
        state = inp.effective_user_state
        inp = replace(
            inp,
            effective_user_state=replace(
                state, scope=other_scope, sync=replace(state.sync, scope=other_scope)
            ),
        )
    elif part == "intent_scope":
        inp = replace(
            inp,
            intent=replace(
                inp.intent,
                scope=other_scope,
                sync=replace(inp.intent.sync, scope=other_scope),
            ),
        )
    elif part == "projected_scope":
        user_scope = Scope(domain=ScopeDomain.USER, user_id="other-user")
        state = inp.projected_agent_state.projected_states[0]
        user_state = replace(
            state,
            scope=user_scope,
            dimension="user.affect.anger",
            sync=replace(state.sync, scope=user_scope),
        )
        inp = replace(
            inp,
            projected_agent_state=replace(
                inp.projected_agent_state,
                scope=user_scope,
                projected_states=(user_state,),
                sync=replace(inp.projected_agent_state.sync, scope=user_scope),
            ),
        )
    elif part == "situation_origin":
        inp = replace(inp, situation=replace(inp.situation, origin_runtime_id="other-runtime"))
    else:
        state = inp.slow_state_records[0]
        slow = replace(
            state,
            origin_runtime_id="other-runtime",
            sync=replace(state.sync, origin_runtime_id="other-runtime"),
        )
        inp = replace(inp, slow_state_records=(slow,))
    with pytest.raises(ValueError, match=reason):
        compiler.compile(inp)
