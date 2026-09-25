"""Production-shaped W3 composition and C7 consumer-use restart evidence."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mind_runtime.binding_registry import BindingRegistry
from mind_runtime.contracts import ReconsiderationPolicy, Scope, ScopeDomain
from mind_runtime.contracts.host import (
    HostCommitRequest,
    HostProviderProseRequest,
    HostStatus,
    HostTurnRequest,
)
from mind_runtime.delivery.persistence import SqliteDeliveryBackend
from mind_runtime.expression.context import DecisionContextConfig
from mind_runtime.expression.guards import (
    DeterministicExpressionGuardChain,
    ExpressionGuardConfig,
)
from mind_runtime.host.runtime_adapter import MindRuntimeHostAdapter
from mind_runtime.host.xiyue_adapter import render_bounded_context
from mind_runtime.intents.engine import IntentRule
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import ActionPolicyConfig, IntentPolicyRule
from mind_runtime.persona_publication import PersonaConfigPublicationRepository
from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment
from mind_runtime.shadow.runtime_loop import build_runtime_stack
from tests.support.fake_clock import FakeClock
from tests.surface.spec_support import sample_candidate


def _stack(tmp_path, *, resources=("send_message",), max_render_chars=5000):
    tmp_path.mkdir(parents=True, exist_ok=True)
    profile = tmp_path / "fixture-persona.json"
    profile.write_text(json.dumps(sample_candidate()["persona"]["content"]), encoding="utf-8")
    publication = PersonaConfigPublicationRepository(tmp_path / "published")
    revision = publication.publish(profile)
    binding = RuntimeBinding(
        persona_id=revision.persona_id,
        agent_id="fixture-persona",
        runtime_id="fixture-runtime",
        storage_namespace="lab/fixture-runtime",
        environment=RuntimeEnvironment.LAB,
    )
    registry = BindingRegistry(tmp_path / "registry")
    registry.initialize()
    registry.register(binding, "fixture-binding")
    registry.pin_persona_revision("fixture-binding", revision)
    config = DecisionContextConfig(
        allowed_situation_facts=(),
        affect_rules=(),
        persona_style_constraints=(("format", "bullets"),),
        allowed_history_kinds=(),
        max_history_items=2,
        max_prior_expression_chars=100,
        max_item_chars=200,
        max_items=20,
        max_render_chars=max_render_chars,
        mode="SURFACE_V1",
    )
    rule = IntentRule(
        rule_id="contact",
        kind="reach_out",
        base_strength=0.5,
        dimension_weights=(),
        event_kind=None,
        event_bonus=0,
        minimum_strength=0.1,
        due_at_attribute=None,
        expires_after=None,
        reconsideration_policy=ReconsiderationPolicy.ON_CONTEXT_CHANGE,
        surface_control_weights=(("contact_seeking", 0.2),),
    )
    policy = ActionPolicyConfig(
        rules=(IntentPolicyRule("reach_out", "send_message", False, False, None, None, None),),
        proactive_cooldown=timedelta(0),
    )
    orchestrator, _ = build_runtime_stack(
        clock=FakeClock(datetime(2026, 9, 23, tzinfo=UTC)),
        facts_db=tmp_path / "facts.sqlite",
        state_db=tmp_path / "states.sqlite",
        origin_runtime_id="fixture-runtime",
        user_id="fixture-user",
        intent_rules=(rule,),
        intent_db=tmp_path / "intent.sqlite",
        action_policy_config=policy,
        policy_resources=resources,
        decision_context_config=config,
        persona_publication=publication,
        surface_binding_registry=registry,
        surface_binding_id="fixture-binding",
        surface_binding_environment=RuntimeEnvironment.LAB,
        delivery_db=tmp_path / "delivery.sqlite",
        expression_guard=DeterministicExpressionGuardChain(
            ExpressionGuardConfig(
                prefix_length=8,
                transport_markers=(),
                banned_openings=(),
                temporal_rules=(),
            )
        ),
    )
    return orchestrator


def test_real_turn_handoff_commits_before_host_provider_and_survives_restart(tmp_path):
    orchestrator = _stack(tmp_path)
    assert (
        orchestrator.surface_projection_port
        is orchestrator.cognitive_tick_components["ticker"].surface_projection_port
    )
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert result.bounded_context is not None, result.reason_codes
    request = orchestrator.surface_handoff_request()
    assert request is not None and request.surface_handoff is not None
    assert (request.channel, request.target) == ("body_provider_context", "body")
    assert request.surface_handoff.intent_surface_use_ref == "intent-score-turn-1-contact"
    assert render_bounded_context(result.bounded_context) == request.payload_bytes.decode("utf-8")
    assert "[SURFACE_GUIDANCE]" in request.payload_bytes.decode("utf-8")
    assert "attempt=" not in request.payload_bytes.decode("utf-8")
    assert request.surface_handoff.expression_map_ref == (
        "surface-v1-candidate-map:2:"
        "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"
    )
    reopened = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    assert reopened.get_durable_request(request.request_id).request == request
    from mind_runtime.delivery.state import DeliveryLifecycleState

    assert not reopened.record_request(request, lifecycle_state=DeliveryLifecycleState.PENDING)
    altered_guidance = tuple(
        (key, "high" if key == "warmth" else band)
        for key, band in request.surface_handoff.qualitative_guidance
    )
    conflicting = replace(
        request,
        surface_handoff=replace(
            request.surface_handoff,
            qualitative_guidance=altered_guidance,
        ),
    )
    with pytest.raises(ValueError, match="different immutable bytes"):
        reopened.record_request(conflicting, lifecycle_state=DeliveryLifecycleState.PENDING)
    reopened.close()
    persisted_intents = SqliteIntentBackend(tmp_path / "intent.sqlite")
    history = persisted_intents.history(request.scope, "intent-turn-1-contact")
    evidence = history[0].surface_use
    assert evidence is not None
    assert evidence.surface_controls_ref == request.surface_handoff.controls_id
    assert evidence.surface_weights == (("contact_seeking", 0.2),)
    assert evidence.contributions[-1].source_kind == "surface"
    persisted_intents.close()
    guard = host.guard_provider_prose(
        HostProviderProseRequest(
            turn_id=result.turn_id,
            interaction_id=result.interaction_id,
            prose="Hello from the provider.",
        )
    )
    assert guard.status is HostStatus.OK, guard.reason_codes
    committed = host.commit_turn(
        HostCommitRequest(
            turn_id=result.turn_id,
            interaction_id=result.interaction_id,
        )
    )
    assert committed.status is HostStatus.OK, committed.reason_codes
    operational = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    assert operational.get_durable_receipt(f"delivery-receipt-{request.request_id}") is not None
    from mind_runtime.delivery.surface_handoff import recover_admitted_surface_handoff

    replay = recover_admitted_surface_handoff(
        operational,
        request.request_id,
        origin_runtime_id="fixture-runtime",
        scope=request.scope,
    )
    assert replay.payload_bytes == request.payload_bytes
    assert replay.surface_handoff == request.surface_handoff
    with pytest.raises(ValueError, match="SURFACE_HANDOFF_BINDING_MISMATCH"):
        recover_admitted_surface_handoff(
            operational,
            request.request_id,
            origin_runtime_id="other-runtime",
            scope=request.scope,
        )
    operational.close()


def test_generic_c7_carrier_cannot_send_surface_provider_envelope(tmp_path):
    from mind_runtime.delivery.daemon import DaemonPass

    orchestrator = _stack(tmp_path)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    request = orchestrator.surface_handoff_request()
    assert request is not None

    class CarrierSpy:
        calls = 0

        def deliver(self, request):
            self.calls += 1
            raise AssertionError("provider context sent as carrier message")

    carrier = CarrierSpy()
    backend = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    outcomes = DaemonPass(backend=backend, port=carrier).run()
    assert carrier.calls == 0
    assert len(outcomes) == 1
    assert outcomes[0].reason_code == "surface_body_handoff_owned"
    backend.close()


def test_surface_handoff_budget_one_character_short_withholds_request(tmp_path):
    from mind_runtime.contracts import ExpressionContextKind
    from mind_runtime.expression.renderer import _item_sort_key, _render_text

    normal = _stack(tmp_path / "normal")
    normal_host = MindRuntimeHostAdapter(orchestrator=normal)
    normal_host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    essential = [
        item
        for item in normal.decision_context.expression_context
        if item.kind
        in (
            ExpressionContextKind.ACTION,
            ExpressionContextKind.POLICY_CONSTRAINT,
            ExpressionContextKind.SURFACE_GUIDANCE,
        )
    ]
    required = len(_render_text(sorted(essential, key=_item_sort_key)))
    assert required > 1

    short = _stack(tmp_path / "short", max_render_chars=required - 1)
    short_host = MindRuntimeHostAdapter(orchestrator=short)
    result = short_host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert result.bounded_context is None
    backend = SqliteDeliveryBackend(tmp_path / "short" / "delivery.sqlite")
    assert backend.get_durable_request("surface-handoff-turn-1") is None
    backend.close()


def test_c7_commit_failure_withholds_provider_handoff(tmp_path, monkeypatch):
    orchestrator = _stack(tmp_path)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    provider_calls = []
    monkeypatch.setattr(
        orchestrator.expression_coordinator,
        "express",
        lambda context: provider_calls.append(context),
    )

    def fail_commit(*args, **kwargs):
        raise OSError("durable C7 commit refused")

    monkeypatch.setattr(orchestrator._surface_delivery_backend, "record_request", fail_commit)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert result.outcome is HostStatus.FAILED
    assert result.bounded_context is None
    assert provider_calls == []
    backend = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    assert backend.get_durable_request("surface-handoff-turn-1") is None
    backend.close()


def test_surface_handoff_cannot_commit_without_guard(tmp_path):
    orchestrator = _stack(tmp_path)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert result.bounded_context is not None
    receipt = host.commit_turn(
        HostCommitRequest(
            turn_id=result.turn_id,
            interaction_id=result.interaction_id,
        )
    )
    assert receipt.status is HostStatus.FAILED
    backend = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    assert backend.get_durable_receipt("delivery-receipt-surface-handoff-turn-1") is None
    backend.close()


def test_failed_later_guard_clears_prior_acceptance(tmp_path, monkeypatch):
    orchestrator = _stack(tmp_path)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    request = HostProviderProseRequest(
        turn_id=result.turn_id,
        interaction_id=result.interaction_id,
        prose="First admitted prose.",
    )
    assert host.guard_provider_prose(request).status is HostStatus.OK

    def guard_failure(*args, **kwargs):
        raise ValueError("provider prose could not be validated")

    monkeypatch.setattr(orchestrator.expression_guard, "guard", guard_failure)
    assert host.guard_provider_prose(request).status is HostStatus.FAILED
    assert (
        host.commit_turn(
            HostCommitRequest(
                turn_id=result.turn_id,
                interaction_id=result.interaction_id,
            )
        ).status
        is HostStatus.FAILED
    )


def test_policy_withholds_c7_handoff_when_resource_unavailable(tmp_path):
    orchestrator = _stack(tmp_path, resources=())
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert orchestrator.surface_handoff_request() is None
    backend = SqliteDeliveryBackend(tmp_path / "delivery.sqlite")
    assert backend.get_durable_request("surface-handoff-turn-1") is None
    backend.close()
