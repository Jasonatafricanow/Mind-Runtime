"""Native durable row -> one Body invocation -> sibling routing."""

import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mr_mem import MemoryCore, Scope, ScopeDomain
from xiyue.semantic_delta_composition import run_one_pass
from xiyue.semantic_delta_protocol import parse_body_turn_result
from xiyue.semantic_delta_source import HermesDeltaSources

from mind_runtime.host.xiyue_adapter import _interaction_id

SCOPE = Scope(ScopeDomain.USER, user_id="logical-user")


class DB:
    def __init__(self, path):
        self.db_path, self.conn = path, sqlite3.connect(path)
        self.conn.executescript("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT);
        INSERT INTO sessions VALUES('s1','native-user');
        CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,
        timestamp REAL,tool_calls TEXT,platform_message_id TEXT,active INTEGER,compacted INTEGER);
        """)

    def append_message(self, *, session_id, role, content, platform_message_id=None):
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO messages VALUES(NULL,?,?,?,?,NULL,?,1,0)",
                (session_id, role, content, 100.0, platform_message_id),
            )
        return cursor.lastrowid


class Agent:
    def __init__(self, db, output):
        self._session_db, self.output = db, output
        self.ephemeral_system_prompt, self.stream_delta_callback = "Normal MR context.", None
        self.calls = 0

    def _persist_session(self, messages, *args, **kwargs):
        for message in messages:
            if not message.get("_db_persisted"):
                self._session_db.append_message(
                    session_id="s1", role=message["role"], content=message["content"]
                )
                message["_db_persisted"] = True

    def run_conversation(self, user_message, **kwargs):
        assert kwargs["conversation_history"] == [{"role": "assistant", "content": "History."}]
        assert kwargs["stream_callback"] is None
        self.request = user_message, self.ephemeral_system_prompt
        messages = [{"role": "user", "content": user_message}]
        self._persist_session(messages)
        self.calls += 1
        messages.append({"role": "assistant", "content": self.output})
        self._persist_session(messages)
        self._persist_session(messages)
        return dict(final_response=self.output, messages=messages, api_calls=1)


def payload():
    return dict(
        schema_version="semantic_delta_v1",
        points=[
            dict(
                point_id="p1",
                meaning="用户要求日报只展示异常与结论。",
                status="resolved",
                speech_act="directive",
                polarity="positive",
                epistemic_status="asserted",
                temporal_scope="future",
            )
        ],
        dependencies=[],
    )


@pytest.mark.parametrize("mode", ["valid", "bad_json", "bad_delta", "defer", "guard_reject"])
def test_sibling_failure_independence_with_native_row_receipt(tmp_path, mode):
    sidecar = payload()
    if mode == "bad_delta":
        sidecar["points"][0]["status"] = "invented"
    elif mode == "defer":
        sidecar["points"][0].update(status="defer", unresolved_refs=["指代"])
    output = json.dumps(
        dict(assistant_response="明白。", semantic_delta=sidecar), ensure_ascii=False
    )
    if mode == "bad_json":
        output = '{"assistant_response":"明白。","semantic_delta":{malformed}'
    db, events = DB(tmp_path / "native.sqlite"), []
    agent = Agent(db, output)
    iid = _interaction_id("telegram", "s1", "m1")
    sources = HermesDeltaSources(
        db.db_path,
        scope=SCOPE,
        namespace="hermes-test",
        session_id="s1",
        message_id="m1",
        user_id="native-user",
        interaction_id=iid,
        channel="telegram",
    )
    try:
        with MemoryCore(tmp_path / "memory.sqlite") as core:
            admission = core.semantic_admission(
                sources=sources,
                clock=SimpleNamespace(now=lambda: datetime(2026, 10, 2, tzinfo=UTC)),
                origin_runtime_id="host",
            )
            result = run_one_pass(
                agent,
                "我以后日报只看异常和结论。",
                admission=admission,
                sources=sources,
                scope=SCOPE,
                interaction_id=iid,
                message_id="m1",
                guard=lambda prose: mode != "guard_reject",
                telemetry=events.append,
                conversation_history=[{"role": "assistant", "content": "History."}],
            )
            assert agent.calls == result["api_calls"] == 1
            assert result["final_response"] == ("" if mode == "guard_reject" else "明白。")
            assert len(core.load_all()) == (1 if mode in ("valid", "guard_reject") else 0)
            assert agent.ephemeral_system_prompt == "Normal MR context."
            assert "semantic_delta" not in result["messages"][-1]["content"]
            assert sources.current_user_source(SCOPE, iid).record_id == "1"
            assert "latest raw USER turn" in agent.request[1] and len(events) == 1
            assert events[0]["semantic_delta.validation_failed"] == (
                mode in ("bad_json", "bad_delta")
            )
            with db.conn:
                db.conn.execute("UPDATE messages SET content='modified' WHERE id=1")
            if core.load_all():
                assert (
                    sources.current_ref(SCOPE, core.load_all()[0].provenance.source_refs[0])
                    != (core.load_all()[0].provenance.source_refs[0])
                )
            assert sources.current_user_source(SCOPE, "forged") is None
    finally:
        sources.close()
        db.conn.close()


def test_parser_preserves_response_and_source_association_rejects_forgery(tmp_path):
    assert parse_body_turn_result("普通回复").assistant_response == "普通回复"
    result = parse_body_turn_result(dict(assistant_response="正常回复", semantic_delta="{bad"))
    assert result.assistant_response == "正常回复" and result.semantic_delta == "{bad"
    db = DB(tmp_path / "native.sqlite")
    try:
        with pytest.raises(ValueError, match="association"):
            HermesDeltaSources(
                db.db_path,
                scope=SCOPE,
                namespace="native",
                session_id="s1",
                message_id="m1",
                user_id="native-user",
                interaction_id="forged",
                channel="telegram",
            )
    finally:
        db.conn.close()


def test_envelope_duplicate_keys_do_not_bypass_strict_validator():
    response = parse_body_turn_result(
        '{"assistant_response":"正常回复","semantic_delta":'
        '{"schema_version":"forged","schema_version":"semantic_delta_v1",'
        '"points":[],"dependencies":[]}}'
    )
    assert response.assistant_response == "正常回复" and response.semantic_delta is None


def test_external_patch_is_bounded_idempotent_and_refuses_drift(tmp_path):
    from xiyue.apply_semantic_delta_patch import ANCHOR, MARKER, render

    source = (
        "def body():\n    if True:\n        if True:\n"
        "            if True:\n                if True:\n"
    )
    source += "                    # --- end Xiyue MR begin seam ---\n" + ANCHOR + "\n"
    patched = render(source, tmp_path)
    assert patched.count(MARKER) == 1 and "_delta_run_gateway_turn(" in patched
    assert render(patched, tmp_path) == patched
    with pytest.raises(ValueError, match="drift"):
        render(source.replace(ANCHOR, "                    result = drift()"), tmp_path)
