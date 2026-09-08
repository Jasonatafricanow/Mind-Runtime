"""Phase 3 Final: live UrllibChatTransport smoke (opt-in integration).

This test is an EXPLICIT INTEGRATION check, not part of the deterministic
project gate. It is skipped under two conditions:

  1. ``DEEPSEEK_API_KEY`` is not set in the environment, OR
  2. ``MIND_RUNTIME_RUN_LIVE_SMOKE`` is not explicitly set to "1"

The dual gate ensures a normal pytest run never makes a network call,
even by accident, and the live wire only runs when an operator
explicitly asks for it. The certification evidence is the manual
one-off wire that has already been recorded; this test exists so the
same wire can be re-run on demand for re-certification.

Production path:
    GuardedSemanticProvider -> OpenAICompatibleProvider ->
    UrllibChatTransport -> real DeepSeek chat-completions endpoint.

ONE real input suffices to prove:
  * real Authorization header is sent
  * bounded grounding handles (o0, o1, ...) cross the provider boundary
  * response returns and bounded handles resolve to canonical ids
  * validate_candidate accepts the resolved candidate

No test-side schema normalisation. No ON/OFF/ON loop.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Observation,
    Scope,
    ScopeDomain,
    Situation,
    SyncFields,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.provider import (
    EgressMode,
    GuardedSemanticProvider,
    ModelEgressPolicy,
    OpenAICompatibleProvider,
    UrllibChatTransport,
)
from tests.support.fake_clock import FakeClock

LIVE_KEY = "DEEPSEEK_API_KEY"
LIVE_FLAG = "MIND_RUNTIME_RUN_LIVE_SMOKE"  # explicit operator opt-in
ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
ALLOWED_HOSTS = ("api.deepseek.com",)
USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="u-smoke")
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _persona() -> PersonaProfile:
    return PersonaProfile(
        persona_id="smoke",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )


def _observation(obs_id: str, text: str) -> Observation:
    return Observation(
        id=obs_id,
        interaction_id="i-smoke",
        scope=USER_SCOPE,
        origin_runtime_id="smoke",
        type="factual",
        key="user_message.observed",
        value={"text": text},
        confidence=1.0,
        observed_at=NOW,
        evidence_refs=(obs_id,),
        sync=SyncFields(USER_SCOPE, "smoke", obs_id, 1, f"idem-{obs_id}"),
    )


def _build_stack() -> tuple[
    OpenAICompatibleProvider, tuple[Observation, ...], Situation
]:
    """Wire the production provider against a real DeepSeek endpoint."""
    persona = _persona()
    guarded = GuardedSemanticProvider(
        egress=ModelEgressPolicy(
            mode=EgressMode.SANITIZED, provider_name="smoke", known_names=()
        ),
        clock=FakeClock(NOW),
    )
    transport = UrllibChatTransport(allowed_hosts=ALLOWED_HOSTS)
    provider = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url=ENDPOINT,
        model=MODEL,
        api_key_env=LIVE_KEY,
        transport=transport,
        timeout_s=30.0,
        allowed_hosts=ALLOWED_HOSTS,
    )
    obs = (_observation("obs-smoke-1", "今天下午想和你分享一首诗"),)
    situation = Situation(
        situation_id="sit-smoke",
        scope=USER_SCOPE,
        origin_runtime_id="smoke",
        derived_facts=(("time.daypart", "afternoon"),),
        effective_state_ref="none",
        observed_at=NOW,
        historical_context=None,
        persona_id=persona.persona_id,
        relationship_ids=(),
        evidence_refs=(),
    )
    return provider, obs, situation


@pytest.mark.skipif(
    not (os.environ.get(LIVE_KEY) and os.environ.get(LIVE_FLAG) == "1"),
    reason=(
        f"live smoke is opt-in integration: set both {LIVE_KEY} and "
        f"{LIVE_FLAG}=1 to enable a real network round-trip"
    ),
)
def test_live_deepseek_smoke(tmp_path: Path) -> None:  # noqa: ARG001
    """One real wire to live DeepSeek: proves Authorization, bounded
    handles, and validate_candidate all survive the production path."""
    provider, obs, situation = _build_stack()

    # The single canonical call: the same one Mind Runtime would issue.
    candidates = provider.propose(
        observations=obs,
        context=situation,
        scope=USER_SCOPE,
    )
    # The handle protocol guarantees a single non-empty tuple (or
    # SchemaInvalidError). A failed resolution would have raised at the
    # inner resolver, never reaching this line.
    assert 0 < len(candidates) <= len(obs)
    for candidate in candidates:
        assert candidate.evidence_refs
        for ref in candidate.evidence_refs:
            assert ref in ("obs-smoke-1",)
        # No affect numeric authority: confidence is the only numeric
        # and the validator accepts a bounded [0, 1] value.
        assert 0.0 <= candidate.confidence <= 1.0
