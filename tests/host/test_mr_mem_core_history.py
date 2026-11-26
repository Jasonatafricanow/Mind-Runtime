"""Current core -> MR context, with bounded scope and commit/restart behavior."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Observation, Scope, ScopeDomain, Situation, SyncFields
from mind_runtime.integrations.mr_mem_core import MrMemClient
from mind_runtime.integrations.mr_mem_core_history import MrMemCoreHistory
from mind_runtime.memory.retrieval import MemorySurfaceBudget

NOW = datetime(2026, 11, 5, tzinfo=UTC)
SCOPE = Scope(ScopeDomain.USER, user_id="u1")


def read(port, scope=SCOPE):
    situation = Situation("s", scope, "runtime", (), "state", NOW, None, None, (), ())
    observation = Observation(
        "o", "turn", scope, "factual", "user_message.observed", {"text": "reports"},
        1.0, NOW, ("e",), "runtime", SyncFields(scope, "runtime", "o", 1, "o"),
    )
    return port.read(interaction_id="turn", context=situation,
                     observations=(observation,), scope=scope, clock=NOW)


def test_core_order_budget_and_projection_authority(monkeypatch):
    calls = []
    def search(self, text, *, top_k):
        calls.append((text, top_k))
        return {"data": [{"id": "line:a", "content": "first"},
                         {"id": "thread:b", "content": "second"},
                         {"id": "raw:c", "content": "oversized"}]}
    monkeypatch.setattr(MrMemClient, "search", search)
    client = MrMemClient("http://localhost:8765", "u1")
    port = MrMemCoreHistory(client, budget=MemorySurfaceBudget(3, 11))
    bundle = read(port)
    assert [i.external_id for i in bundle.episodes] == ["line:a", "thread:b"]
    assert all(i.kind == "memory.mr_mem_projection" for i in bundle.episodes)
    assert all(":result:" in ref for ref in bundle.source_refs)
    assert bundle.stable_facts == ()
    assert read(port, Scope(ScopeDomain.USER, user_id="foreign")) is None
    assert len(calls) == 1


def test_default_composition_consumes_core_across_restart_and_replay(tmp_path, monkeypatch):
    from mind_runtime import runtime_binding
    from mind_runtime.host.xiyue_adapter import default_adapter
    from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment

    calls = []
    def search(self, query, **kwargs):
        calls.append(query)
        return {"data": [{"id": "line:fixture", "content": "Use weekly reports now"}]}
    monkeypatch.setattr(MrMemClient, "search", search)
    monkeypatch.setenv("MR_ENABLED", "true")
    monkeypatch.setattr(runtime_binding, "DEFAULT_PRODUCTION_ROOT", tmp_path)
    binding = RuntimeBinding(persona_id="p", agent_id="a", runtime_id="r",
                             storage_namespace="production/r",
                             environment=RuntimeEnvironment.PRODUCTION)
    client = MrMemClient("http://localhost:8765", "u1")
    for message_id in ("one", "two"):
        adapter = default_adapter(binding=binding, user_id="u1", mr_mem=client)
        handle = adapter.begin_turn(message="reports", channel="test", session_id="s",
                                    message_id=message_id, occurred_at=NOW)
        assert handle is not None
        history = adapter._port.orchestrator._turn.situation.historical_context
        assert history.episodes[0].proposition == "Use weekly reports now"
        assert adapter.memory is client
        assert adapter.commit_turn(handle)
    before = len(calls)
    replay = adapter.begin_turn(message="reports", channel="test", session_id="s",
                                message_id="two", occurred_at=NOW)
    assert replay is not None and len(calls) == before
    with pytest.raises(ValueError, match="legacy"):
        default_adapter(binding=binding, user_id="u1", mr_mem=client, memory_enabled=True)


def test_core_history_reaches_existing_body_context_compiler_without_reordering(monkeypatch):
    from dataclasses import replace

    from tests.expression.test_context import make_compiler, make_compiler_input

    from mind_runtime.expression.renderer import DeterministicContextRenderer

    # Deliberately opposite lexical IDs: the core's returned order is authoritative
    # for this derived projection, even through the existing context budget/sort.
    monkeypatch.setattr(MrMemClient, "search", lambda *a, **k: {"data": [
        {"id": "line:z", "content": "FIRST core line"},
        {"id": "raw:a", "content": "SECOND original snippet"},
    ]})
    bundle = read(MrMemCoreHistory(MrMemClient("http://localhost:8765", "u1")))
    from mind_runtime.host.xiyue_adapter import default_adapter

    with pytest.raises(ValueError, match="must allow"):
        default_adapter(user_id="u1", mr_mem=MrMemClient("http://localhost:8765", "u1"),
                        decision_context_config=make_compiler()._config)
    compiler = make_compiler(allowed_history_kinds=("memory.mr_mem_projection",))
    prepared = make_compiler_input(scope=SCOPE)
    situation = replace(prepared.situation, historical_context=replace(
        bundle, origin_runtime_id=prepared.origin_runtime_id,
    ))
    context, _ = compiler.compile(replace(prepared, situation=situation))
    rendered = DeterministicContextRenderer(compiler._config).render(context)
    text = str(rendered)
    assert "FIRST core line" in text and "SECOND original snippet" in text
    assert text.index("FIRST core line") < text.index("SECOND original snippet")


def test_core_client_for_another_user_cannot_be_composed():
    from mind_runtime.host.xiyue_adapter import XiyueMRAdapter, default_adapter

    foreign = MrMemClient("http://localhost:8765", "u2")
    with pytest.raises(ValueError, match="share user_id"):
        default_adapter(user_id="u1", mr_mem=foreign)
    with pytest.raises(ValueError, match="share user_id"):
        XiyueMRAdapter(object(), user_id="u1", memory=foreign)
