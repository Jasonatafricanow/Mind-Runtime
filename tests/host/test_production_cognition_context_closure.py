"""P0 production composition closure: canonical slow state reaches Hermes context."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.contracts import RuntimeState, Scope, ScopeDomain, SyncFields
from mind_runtime.expression.context import DecisionContextCompiler
from mind_runtime.host.xiyue_adapter import default_adapter
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "certification/d11s/inputs/runtime-config.json"


def test_production_composition_consumes_persisted_slow_state_in_host_context(
    tmp_path: Path, monkeypatch
) -> None:
    """The Hermes production composition must use the real compiler and renderer."""
    from mind_runtime.emotional_transition import appraisal as appraisal_module
    from mind_runtime.emotional_transition import factory as factory_module

    class OfflineSemanticProvider:
        def propose(self, *, observations, context, scope):
            return ()

    monkeypatch.setattr(factory_module, "create_semantic_provider", OfflineSemanticProvider)
    monkeypatch.setattr(
        appraisal_module,
        "ModelBackedSemanticAppraisalModel",
        lambda **kwargs: appraisal_module.ConfiguredSemanticAppraisalModel(),
    )

    from xiyue import mr_seam

    monkeypatch.setenv("MR_RUNTIME_CONFIG", str(MANIFEST))
    monkeypatch.setenv("MR_FACTS_DB", str(tmp_path / "facts.sqlite"))
    monkeypatch.setenv("MR_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("MR_ENABLED", "true")

    composition = mr_seam._load_production_composition()
    binding = RuntimeBinding(
        persona_id="kayla_v0",
        agent_id="hermes-test",
        runtime_id="runtime-1",
        storage_namespace="production/xiyue",
        environment=RuntimeEnvironment.PRODUCTION,
    )
    adapter = default_adapter(binding=binding, **composition)
    orchestrator = adapter._port.orchestrator

    assert isinstance(orchestrator.decision_context_compiler, DecisionContextCompiler)
    assert orchestrator.decision_context_compiler.__class__.__name__ != (
        "StubDecisionContextCompiler"
    )

    slow_scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="kayla_v0",
        persona_id="kayla_v0",
    )
    slow_state = RuntimeState(
        state_id="slow-relationship-security-v3",
        scope=slow_scope,
        origin_runtime_id="runtime-1",
        dimension="agent.longitudinal.relationship_security",
        value=0.8,
        status="active",
        valid_from=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
        valid_until=None,
        relevant_until=None,
        last_observed_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
        evidence_refs=("evidence-previous-turn",),
        transition_refs=("transition-previous-turn",),
        updated_at=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
        version=3,
        sync=SyncFields(
            slow_scope,
            "runtime-1",
            "slow-relationship-security-v3",
            3,
            "idem-slow-relationship-security-v3",
        ),
    )
    assert orchestrator._state_backend is not None
    assert orchestrator._state_backend.save_state(slow_state)

    handle = adapter.begin_turn(
        message="你好，今天见到你很开心。",
        channel="telegram",
        session_id="session-prod-closure",
        message_id="message-next-turn",
        occurred_at=datetime(2026, 9, 9, 8, 1, tzinfo=UTC),
    )
    assert handle is not None

    context = orchestrator.decision_context
    assert context is not None
    slow_items = [
        item
        for item in context.expression_context
        if item.kind.value == "internal_state" and item.key.startswith("slow_")
    ]
    assert len(slow_items) == 1
    assert slow_items[0].key == "slow_agent.longitudinal.relationship_security"
    assert slow_items[0].value == "0.8"
    assert slow_items[0].source_refs == (
        "slow",
        "slow-relationship-security-v3",
        "v3",
    )

    rendered = orchestrator.context_renderer.render(context)
    assert "slow_agent.longitudinal.relationship_security: 0.8" in rendered.text
    assert handle.bounded_context is not None
    assert "slow_agent.longitudinal.relationship_security" in (
        handle.bounded_context.emotional_state
    )
    assert adapter.abort_turn(handle)

    restarted_adapter = default_adapter(binding=binding, **composition)
    restarted_orchestrator = restarted_adapter._port.orchestrator
    assert isinstance(restarted_orchestrator.decision_context_compiler, DecisionContextCompiler)
    restarted_handle = restarted_adapter.begin_turn(
        message="重启后继续聊。",
        channel="telegram",
        session_id="session-prod-closure",
        message_id="message-after-restart",
        occurred_at=datetime(2026, 9, 9, 8, 2, tzinfo=UTC),
    )
    assert restarted_handle is not None
    restarted_context = restarted_orchestrator.decision_context
    assert restarted_context is not None
    assert any(
        item.key == "slow_agent.longitudinal.relationship_security"
        and item.kind.value == "internal_state"
        for item in restarted_context.expression_context
    )
