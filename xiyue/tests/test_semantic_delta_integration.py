"""Frozen A-J and MT-LT-04 regressions over durable native and canonical databases."""

import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mr_mem import MemoryCore, MemoryLifecycle, SemanticMemoryCandidate
from mr_mem.memory.projection import ProjectionWorker
from mr_mem.memory.semantic_store import SemanticSourceBinding
from xiyue.semantic_delta_composition import run_one_pass
from xiyue.semantic_delta_gateway import enabled, run_gateway_turn
from xiyue.semantic_delta_source import HermesDeltaSources
from xiyue.tests.test_semantic_delta_composition import DB, SCOPE, Agent, payload

from mind_runtime.contracts import Scope as MRScope
from mind_runtime.contracts import ScopeDomain as MRScopeDomain
from mind_runtime.host.xiyue_adapter import _interaction_id


def point(pid, text, **fields):
    result = payload()["points"][0] | dict(point_id=pid, meaning=text)
    result.update(fields)
    return result


def edge(target, *, current="p1", kind="memory", boundary="context", lifecycle="supersede"):
    return dict(
        from_point_id=current,
        target_kind=kind,
        target_id=target,
        relation="当前变化依赖此含义",
        boundary_policy=boundary,
        lifecycle_effect=lifecycle,
    )


def reader(db, mid="m1"):
    return HermesDeltaSources(
        db.db_path,
        scope=SCOPE,
        namespace="hermes-test",
        session_id="s1",
        message_id=mid,
        user_id="native-user",
        interaction_id=_interaction_id("telegram", "s1", mid),
        channel="telegram",
    )


def service(core, sources):
    return core.semantic_admission(
        sources=sources,
        origin_runtime_id="host",
        clock=SimpleNamespace(now=lambda: datetime(2026, 10, 2, tzinfo=UTC)),
    )


def seed(core, db, texts):
    memories = []
    for index, text in enumerate(texts):
        mid = "seed-" + str(index)
        db.append_message(session_id="s1", role="user", content=text, platform_message_id=mid)
        sources = reader(db, mid)
        try:
            ref = sources.current_user_source(SCOPE, sources.interaction_id)
            memories.append(
                service(core, sources).admit(
                    SemanticMemoryCandidate(
                        semantic_id=mid,
                        scope=SCOPE,
                        content=text,
                        source_refs=(ref,),
                        compiler_version="seed-canonical-v1",
                    )
                )
            )
        finally:
            sources.close()
    return tuple(memories)


CASES = [
    ("A", "我以后日报只看异常和结论。", 1),
    ("B", "测试通过了。以后别为了coverage写重复测试。", 2),
    ("C", "我不认为这个结果证明算法正确，只能说明夹具能跑。", 1),
    ("D", "如果服务器恢复，就别重启数据库。", 1),
    ("E", "不对，改20/30/50/70。", 1),
    ("F", "地点改上海，其他不变。", 1),
    ("G", "还是那个吧。", 0),
    ("H", "正常请求。", 0),
]


@pytest.mark.parametrize("case,current,count", CASES, ids=[c[0] for c in CASES])
def test_frozen_business_cases(tmp_path, case, current, count):
    db, events = DB(tmp_path / "native.sqlite"), []
    sources = reader(db)
    try:
        with MemoryCore(tmp_path / "memory.sqlite") as core:
            old = seed(
                core,
                db,
                ["top-k=100"]
                if case == "E"
                else ["预算80万", "地点北京", "车型SUV"]
                if case == "F"
                else [],
            )
            sidecar = payload()
            if case == "B":
                sidecar["points"] = [
                    point("p1", "本轮测试通过了。", speech_act="assertion", temporal_scope="past"),
                    point("p2", "用户要求以后不为coverage编写重复测试。"),
                ]
            elif case == "C":
                sidecar["points"] = [
                    point(
                        "p1",
                        "用户不认为本轮结果证明算法正确。",
                        polarity="negative",
                        speech_act="assertion",
                    ),
                    point("p2", "本轮结果只能说明夹具能跑。", speech_act="assertion"),
                ]
                sidecar["dependencies"] = [
                    edge("p1", current="p2", kind="point", boundary="cohabit", lifecycle="none")
                ]
            elif case == "D":
                sidecar["points"] = [
                    point("p1", "如果服务器恢复。", epistemic_status="hypothetical"),
                    point(
                        "p2",
                        "在该条件下，用户要求不重启数据库。",
                        polarity="negative",
                        epistemic_status="hypothetical",
                    ),
                ]
                sidecar["dependencies"] = [
                    edge("p1", current="p2", kind="point", boundary="cohabit", lifecycle="none")
                ]
            elif case in ("E", "F"):
                sidecar["points"] = [
                    point(
                        "p1",
                        "用户将top-k改为20/30/50/70。" if case == "E" else "用户将地点改为上海。",
                    )
                ]
                sidecar["dependencies"] = [edge(old[0 if case == "E" else 1].memory_id)]
            elif case == "G":
                sidecar["points"] = [
                    point(
                        "p1",
                        "仍选那个，指代无法唯一确定。",
                        status="defer",
                        unresolved_refs=["那个"],
                    )
                ]
            output = json.dumps(
                dict(assistant_response="明白。", semantic_delta=sidecar), ensure_ascii=False
            )
            if case == "H":
                output = '{"assistant_response":"明白。","semantic_delta":{malformed}'
            agent = Agent(db, output)
            admission = service(core, sources)
            result = run_one_pass(
                agent,
                current,
                admission=admission,
                sources=sources,
                scope=SCOPE,
                interaction_id=sources.interaction_id,
                message_id="m1",
                activated_memories=old,
                guard=lambda prose: True,
                telemetry=events.append,
                sidecar_token_counter=lambda text: len(text) // 4,
                conversation_history=[dict(role="assistant", content="History.")],
            )
            assert agent.calls == 1 and result["final_response"] == "明白。"
            ref = sources.current_user_source(SCOPE, sources.interaction_id)
            created = tuple(m for m in core.load_all() if m.provenance.source_refs == (ref,))
            assert len(created) == count
            for memory in created:
                assert memory.provenance.observation_id is None
                assert memory.provenance.evidence_refs == ()
                assert (
                    core.get_semantic_metadata(memory.memory_id).source_interaction_id
                    == sources.interaction_id
                )
            if case in ("C", "D"):
                assert created[0].content == "\n".join(p["meaning"] for p in sidecar["points"])
                assert core.get_semantic_metadata(created[0].memory_id).member_point_ids == (
                    "p1",
                    "p2",
                )
            if old:
                changed = old[0 if case == "E" else 1]
                assert core.get(changed.memory_id).lifecycle is MemoryLifecycle.SUPERSEDED
                assert core.get_semantic_metadata(created[0].memory_id).context_memory_ids == (
                    changed.memory_id,
                )
                assert changed.content not in created[0].content
                for untouched in old:
                    if untouched != changed:
                        assert core.get(untouched.memory_id) == untouched
            embedded = []

            class Writer:
                def upsert(self, memory, *, intent):
                    embedded.append(memory)
                    return memory.memory_id

            ProjectionWorker(
                core.canonical.projection_queue(), Writer(), target="unassigned"
            ).run_once()
            assert {m.memory_id for m in embedded if m.provenance.source_refs == (ref,)} == {
                m.memory_id for m in created
            }
            assert events[0]["semantic_delta.validation_failed"] == (case == "H")
    finally:
        sources.close()
        db.conn.close()


def test_I_J_replay_and_restart_after_accepted_freeze_without_body(tmp_path, monkeypatch):
    db = DB(tmp_path / "native.sqlite")
    sources = reader(db)
    path = tmp_path / "memory.sqlite"
    agent = Agent(db, json.dumps(dict(assistant_response="明白。", semantic_delta=payload())))
    try:
        with MemoryCore(path) as core:
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TRIGGER crash BEFORE INSERT ON semantic_block_metadata "
                    "BEGIN SELECT RAISE(ABORT,'interrupt after freeze'); END"
                )
            result = run_one_pass(
                agent,
                "当前变化",
                admission=service(core, sources),
                sources=sources,
                scope=SCOPE,
                interaction_id=sources.interaction_id,
                message_id="m1",
                conversation_history=[dict(role="assistant", content="History.")],
            )
            assert result["final_response"] == "明白。" and core.load_all() == ()
        with sqlite3.connect(path) as conn:
            frozen = conn.execute("SELECT accepted FROM semantic_compilations").fetchone()[0]
            conn.execute("DROP TRIGGER crash")
        binding = SemanticSourceBinding(
            SCOPE,
            sources.interaction_id,
            sources.current_user_source(SCOPE, sources.interaction_id),
        )

        def forbidden(*args, **kwargs):
            raise AssertionError("no model/semantic compilation on recovery")

        monkeypatch.setattr(agent, "run_conversation", forbidden)
        monkeypatch.setattr("mr_mem.memory.semantic_admission.compile_semantic_delta", forbidden)
        with MemoryCore(path) as core:
            admission = service(core, sources)
            receipt = admission.resume_semantic_delta(binding)
            assert receipt == admission.resume_semantic_delta(binding)
            assert receipt == admission.admit_semantic_delta(
                payload(), binding=binding, activated_memory_ids=()
            )
            assert len(core.load_all()) == 1 and agent.calls == 1
        with sqlite3.connect(path) as conn:
            assert (
                conn.execute("SELECT accepted FROM semantic_compilations").fetchone()[0] == frozen
            )
    finally:
        sources.close()
        db.conn.close()


def test_MT_LT_04_current_change_only_with_necessary_activated_block(tmp_path):
    db = DB(tmp_path / "native.sqlite")
    sources = reader(db)
    try:
        with MemoryCore(tmp_path / "memory.sqlite") as core:
            baseline = seed(
                core, db, ["预算80万", "车型SUV", "贷款50万", "交期本月", "购车意向确定"]
            )
            sidecar = payload()
            sidecar["points"] = [point("p1", "用户将交期改为下月。", temporal_expression="下月")]
            sidecar["dependencies"] = [edge(baseline[3].memory_id)]
            agent = Agent(db, json.dumps(dict(assistant_response="明白。", semantic_delta=sidecar)))
            result = run_one_pass(
                agent,
                "交期改下月，其他不变。",
                admission=service(core, sources),
                sources=sources,
                scope=SCOPE,
                interaction_id=sources.interaction_id,
                message_id="m1",
                activated_memories=(baseline[3],),
                conversation_history=[dict(role="assistant", content="History.")],
            )
            assert agent.calls == 1 and result["final_response"] == "明白。"
            for memory in baseline:
                if memory != baseline[3]:
                    assert memory.content not in agent.request[1]
                    assert core.get(memory.memory_id) == memory
            assert len(core.load_all()) == 6 and len(sidecar["dependencies"]) == 1
            latest = service(core, sources).semantic_delta_receipt(
                SemanticSourceBinding(
                    SCOPE,
                    sources.interaction_id,
                    sources.current_user_source(SCOPE, sources.interaction_id),
                )
            )
            assert core.get(latest.memory_ids[0]).content == "用户将交期改为下月。"
    finally:
        sources.close()
        db.conn.close()


@pytest.mark.parametrize("flag", [None, "false", "true"])
def test_flag_default_off_and_missing_setup_preserve_normal_body(tmp_path, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("SEMANTIC_DELTA_V1_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SEMANTIC_DELTA_V1_ENABLED", flag)
    assert enabled() is (flag == "true")
    agent = SimpleNamespace(
        run_conversation=lambda message, **kwargs: dict(final_response="正常回复", api_calls=1)
    )
    assert (
        run_gateway_turn(
            agent, "current", seam=None, handle=None, source=None, session_id="s1", message_id="m1"
        )["final_response"]
        == "正常回复"
    )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "delta_flag,legacy_flag,lce_flag,expected",
    [
        (False, False, False, False),
        (False, True, False, True),
        (False, False, True, True),
        (True, True, True, False),
    ],
)
def test_native_flag_disconnects_legacy_online_memory_composition(
    monkeypatch, delta_flag, legacy_flag, lce_flag, expected
):
    from xiyue import mr_seam

    composition = dict.fromkeys(
        [
            "persona",
            "situation",
            "decision_context_config",
            "effect_rules",
            "definitions",
            "appraisal_producer",
            "homeostasis_gate",
            "semantic_provider",
            "slow_plasticity_window_size",
        ]
    )
    recorded = []

    def adapter_factory(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setenv("MR_ENABLED", "true")
    for name, value in [
        ("SEMANTIC_DELTA_V1_ENABLED", delta_flag),
        ("MR_MEMORY_ENABLED", legacy_flag),
        ("MR_LCE_ENABLED", lce_flag),
    ]:
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv("MR_LCE_INSPIRATION_ENABLED", "false")
    monkeypatch.setattr(mr_seam, "_local", SimpleNamespace())
    monkeypatch.setattr(mr_seam, "_ensure_mr_importable", lambda: True)
    monkeypatch.setattr(mr_seam, "_load_production_composition", lambda: composition)
    monkeypatch.setattr(mr_seam, "get_trace_journal", lambda: None)
    monkeypatch.setattr(mr_seam, "load_readiness", lambda: {})
    monkeypatch.setattr("mind_runtime.host.xiyue_adapter.default_adapter", adapter_factory)
    assert mr_seam.get_mr_adapter() is not None
    assert recorded[0]["memory_enabled"] is expected


def test_gateway_factory_supplies_real_source_and_guard(tmp_path, monkeypatch):
    db = DB(tmp_path / "native.sqlite")
    agent = Agent(db, json.dumps(dict(assistant_response="明白。", semantic_delta=payload())))
    monkeypatch.setenv("SEMANTIC_DELTA_V1_ENABLED", "true")
    monkeypatch.setenv("MR_MEM_CANONICAL_DB", str(tmp_path / "memory.sqlite"))
    guarded = []
    adapter = SimpleNamespace(
        _runtime_id="host",
        _scope=MRScope(MRScopeDomain.USER, user_id=SCOPE.user_id),
        guard_turn_prose=lambda handle, prose: guarded.append(prose) or True,
    )
    handle = SimpleNamespace(
        interaction_id=_interaction_id("telegram", "s1", "m1"), channel="telegram"
    )
    try:
        result = run_gateway_turn(
            agent,
            "我以后日报只看异常和结论。",
            seam=SimpleNamespace(get_mr_adapter=lambda: adapter),
            handle=handle,
            source=SimpleNamespace(user_id="native-user"),
            session_id="s1",
            message_id="m1",
            conversation_history=[dict(role="assistant", content="History.")],
        )
        assert result["final_response"] == "明白。" and agent.calls == 1 and guarded == ["明白。"]
        with MemoryCore(tmp_path / "memory.sqlite", read_only=True) as core:
            assert len(core.load_all()) == 1
    finally:
        db.conn.close()


def test_source_revision_changed_during_body_cannot_relabel_proposal(tmp_path):
    db = DB(tmp_path / "native.sqlite")
    sources = reader(db)

    class EditingAgent(Agent):
        def run_conversation(self, user_message, **kwargs):
            messages = [dict(role="user", content=user_message)]
            self._persist_session(messages)
            self.calls += 1
            with db.conn:
                db.conn.execute(
                    "UPDATE messages SET content='edited during inference' WHERE role='user'"
                )
            messages.append(dict(role="assistant", content=self.output))
            self._persist_session(messages)
            return dict(final_response=self.output, messages=messages, api_calls=1)

    agent = EditingAgent(
        db, json.dumps(dict(assistant_response="明白。", semantic_delta=payload()))
    )
    events = []
    try:
        with MemoryCore(tmp_path / "memory.sqlite") as core:
            result = run_one_pass(
                agent,
                "original current USER",
                admission=service(core, sources),
                sources=sources,
                scope=SCOPE,
                interaction_id=sources.interaction_id,
                message_id="m1",
                telemetry=events.append,
            )
            assert result["final_response"] == "明白。" and agent.calls == 1
            assert core.load_all() == ()
            assert events[0]["semantic_delta.status"] == "SEMANTIC_DELTA_SCOPE_MISMATCH"
    finally:
        sources.close()
        db.conn.close()
