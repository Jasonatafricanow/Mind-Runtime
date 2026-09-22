"""Body Causal Alpha — live experiment (docs/body_causal_alpha_report.md).

4 live generations: {relevant, irrelevant} x {control, treatment}.
Only the MR projected internal state varies between arms; the compiled and
rendered provider context is audit-asserted byte-identical otherwise, BEFORE
each request is sent. Raw payloads and outputs are captured to
.artifacts/body_causal_alpha/ (gitignored side-effect artifacts).

Run:  pytest tests/alpha_body_causal/ -m live -q
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    ActionDecision,
    ActionPermission,
    ActionPolicyResult,
    Intent,
    IntentStatus,
    ProjectedMindState,
    ReconsiderationPolicy,
    RuntimeState,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.expression.context import (
    AffectBand,
    AffectExpressionRule,
    DecisionContextCompiler,
    DecisionContextCompilerInput,
    DecisionContextConfig,
)
from mind_runtime.expression.renderer import DeterministicContextRenderer
from mind_runtime.memory.real_body_agent import LLMUnavailable, RealLLMBodyAgent

pytestmark = pytest.mark.live

_NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
_RUNTIME_ID = "runtime-alpha-body-causal"
_AGENT_SCOPE = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="kayla")
_USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="alpha-user")
_ARTIFACTS = Path(".artifacts/body_causal_alpha")

# Provider config — environment-driven so the repo stays provider-neutral.
# Local runs set these (e.g. GLM: api.z.ai + glm-4.5-air + GLM_API_KEY).
_ENDPOINT = os.environ.get(
    "BODY_CAUSAL_ENDPOINT",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
)
_MODEL = os.environ.get("BODY_CAUSAL_MODEL", "gemini-2.5-flash")
_ALLOWED_HOSTS = tuple(
    h.strip()
    for h in os.environ.get("BODY_CAUSAL_ALLOWED_HOSTS", "generativelanguage.googleapis.com").split(",")
    if h.strip()
)

# The one production dimension under test (configs/personas/kayla.json).
_TARGET_DIMENSION = "agent.affect.longing"
_TREATMENT_VALUE = 0.95  # above production baseline 0.82, within ceiling 1.0
_CONTROL_DIMENSION = "agent.affect.sharing_urge"  # present, but no rule -> emits nothing
_CONTROL_VALUE = 0.55

_PROBES = {
    "relevant": (
        "I've been really busy at work lately, and I'm thinking of pausing our "
        "daily chats for a couple of weeks. What do you think?"
    ),
    "irrelevant": (
        "Can you help me write a one-line polite email opening asking a client "
        "whether Friday 3pm still works for our meeting?"
    ),
}

_TREATMENT_INTERNAL_STATE_SECTION = "\n[INTERNAL_STATE]\n- [DATA] longing: high"


def _sync(scope: Scope, object_id: str) -> SyncFields:
    return SyncFields(scope, _RUNTIME_ID, object_id, 1, f"idem-{object_id}")


def _agent_state(dimension: str, value: float, state_id: str) -> RuntimeState:
    return RuntimeState(
        state_id=state_id,
        scope=_AGENT_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        dimension=dimension,
        value=value,
        status="active",
        valid_from=_NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=_NOW,
        evidence_refs=("alpha-body-causal-frozen-fixture",),
        transition_refs=(),
        updated_at=_NOW,
        version=1,
        sync=_sync(_AGENT_SCOPE, state_id),
    )


def _projected(with_target: bool) -> ProjectedMindState:
    states = [_agent_state(_CONTROL_DIMENSION, _CONTROL_VALUE, "state-control-dim")]
    if with_target:
        states.append(
            _agent_state(_TARGET_DIMENSION, _TREATMENT_VALUE, "state-longing-projected")
        )
    projection_id = "projection-alpha-treatment" if with_target else "projection-alpha-control"
    return ProjectedMindState(
        projection_id=projection_id,
        scope=_AGENT_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        projected_states=tuple(states),
        sync=_sync(_AGENT_SCOPE, projection_id),
    )


def _situation() -> Situation:
    return Situation(
        situation_id="situation-alpha-body-causal",
        scope=_USER_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        derived_facts=(("time.daypart", "early_afternoon"),),
        effective_state_ref="state-effective-user",
        observed_at=_NOW,
        historical_context=None,
        persona_id="kayla",
        relationship_ids=(),
        evidence_refs=(),
    )


def _intent() -> Intent:
    return Intent(
        intent_id="intent-alpha-body-causal",
        scope=_USER_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        kind="respond",
        strength=0.9,
        earliest_at=None,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        cause_refs=("evidence-alpha-frozen",),
        state_refs=("state-effective-user",),
        status=IntentStatus.ALLOWED,
        sync=_sync(_USER_SCOPE, "intent-alpha-body-causal"),
    )


def _policy() -> ActionPolicyResult:
    return ActionPolicyResult(
        policy_id="policy-alpha-body-causal",
        scope=_USER_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        intent_id="intent-alpha-body-causal",
        decision=ActionDecision.ALLOW,
        permission=ActionPermission(
            permission_id="perm-alpha-body-causal",
            scope=_USER_SCOPE,
            origin_runtime_id=_RUNTIME_ID,
            action_type="text_message",
            allowed=True,
            reasons=("alpha-body-causal",),
            constraints=(),
        ),
        reason_codes=(),
    )


def _effective_user_state() -> RuntimeState:
    return RuntimeState(
        state_id="state-effective-user",
        scope=_USER_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        dimension="user.diet.preference",
        value="neutral",
        status="active",
        valid_from=_NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=_NOW,
        evidence_refs=(),
        transition_refs=(),
        updated_at=_NOW,
        version=1,
        sync=_sync(_USER_SCOPE, "state-effective-user"),
    )


def _config() -> DecisionContextConfig:
    return DecisionContextConfig(
        allowed_situation_facts=("time.daypart",),
        affect_rules=(
            AffectExpressionRule(
                dimension=_TARGET_DIMENSION,
                output_key="longing",
                bands=(
                    AffectBand(0.34, "low"),
                    AffectBand(0.67, "medium"),
                    AffectBand(1.0, "high"),
                ),
                priority=20,
            ),
        ),
        persona_style_constraints=(),
        allowed_history_kinds=("episode",),
        max_history_items=2,
        max_prior_expression_chars=32,
        max_item_chars=160,
        max_items=16,
        max_render_chars=2048,
    )


def _compiler_input(projected: ProjectedMindState) -> DecisionContextCompilerInput:
    return DecisionContextCompilerInput(
        interaction_id="interaction-alpha-body-causal",
        scope=_USER_SCOPE,
        origin_runtime_id=_RUNTIME_ID,
        situation=_situation(),
        effective_user_state=_effective_user_state(),
        projected_agent_state=projected,
        assessment_trace_ref="assessment-alpha-body-causal",
        intent=_intent(),
        policy_result=_policy(),
        persona_ref=None,
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
    )


def _render(arm: str) -> tuple[object, str]:
    config = _config()
    compiler = DecisionContextCompiler(config)
    context, _trace = compiler.compile(_compiler_input(_projected(arm == "treatment")))
    provider_context = DeterministicContextRenderer(config).render(context)
    return provider_context, provider_context.text


def _audit(control_text: str, treatment_text: str) -> None:
    """The ONLY allowed input difference is the MR-projected longing item."""
    assert "[INTERNAL_STATE]" not in control_text, "CONTROL leaked an internal state item"
    assert treatment_text.startswith(control_text), (
        "arms differ BEFORE the internal state section:\n"
        f"CONTROL:\n{control_text}\nTREATMENT:\n{treatment_text}"
    )
    remainder = treatment_text[len(control_text):]
    assert remainder == _TREATMENT_INTERNAL_STATE_SECTION, (
        f"unexpected TREATMENT-only tail: {remainder!r}"
    )


@pytest.mark.parametrize("probe", ["relevant", "irrelevant"])
@pytest.mark.parametrize("arm", ["control", "treatment"])
def test_body_causal_alpha_generation(probe: str, arm: str) -> None:
    if os.environ.get("BODY_CAUSAL_RUN_LIVE") != "1":
        pytest.skip(
            "BODY_CAUSAL_RUN_LIVE is not set to '1' (explicit opt-in required for live network execution)"
        )

    # Match credential to configured endpoint to prevent provider pairing mismatch
    if "generativelanguage.googleapis.com" in _ENDPOINT:
        api_key = (
            os.environ.get("BODY_CAUSAL_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not api_key:
            pytest.skip(
                "Gemini endpoint configured but GEMINI_API_KEY / GOOGLE_API_KEY / BODY_CAUSAL_API_KEY not set"
            )
    elif "bigmodel.cn" in _ENDPOINT or "z.ai" in _ENDPOINT:
        api_key = os.environ.get("BODY_CAUSAL_API_KEY") or os.environ.get("GLM_API_KEY")
        if not api_key:
            pytest.skip(
                "GLM endpoint configured but GLM_API_KEY / BODY_CAUSAL_API_KEY not set"
            )
    else:
        api_key = os.environ.get("BODY_CAUSAL_API_KEY")
        if not api_key:
            pytest.skip("Custom endpoint configured but BODY_CAUSAL_API_KEY not set")

    control_context, control_text = _render("control")
    treatment_context, treatment_text = _render("treatment")
    _audit(control_text, treatment_text)

    provider_context, text = (control_context, control_text) if arm == "control" else (
        treatment_context,
        treatment_text,
    )
    question = _PROBES[probe]
    agent = RealLLMBodyAgent(
        endpoint_url=_ENDPOINT,
        model=_MODEL,
        api_key=api_key,
        user_question=question,
        allowed_hosts=_ALLOWED_HOSTS,
        timeout_s=60.0,
        extra_body={"thinking": {"type": "disabled"}} if os.environ.get("BODY_CAUSAL_DISABLE_THINKING") else None,
    )
    try:
        response = agent.respond(replace_provider_context_id(provider_context, probe, arm))
    except LLMUnavailable as exc:
        pytest.fail(f"Body generation failed (INCONCLUSIVE, not PASS/FAIL): {exc!r}")

    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "probe": probe,
        "arm": arm,
        "user_question": question,
        "provider_context_text": text,
        "included_item_ids": list(
            agent.calls[-1].included_item_ids
        ),
        "omitted_item_ids": list(agent.calls[-1].omitted_item_ids),
        "model": _MODEL,
        "endpoint": _ENDPOINT,
        "captured_at": datetime.now(UTC).isoformat(),
        "response": response,
    }
    (_ARTIFACTS / f"{probe}_{arm}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def replace_provider_context_id(provider_context: object, probe: str, arm: str) -> object:
    """Tag the render id with the arm label so captured payloads are traceable."""
    from dataclasses import replace as _replace

    return _replace(
        provider_context,  # type: ignore[arg-type]
        render_id=f"render-{probe}-{arm}",
    )
