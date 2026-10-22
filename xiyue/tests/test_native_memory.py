"""Reuse the Hermes SQLite fixture for native ownership, edit and deletion wiring."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from xiyue.native_memory_source import HermesNativeSource
from xiyue.tests.test_semantic_delta_composition import DB, SCOPE


@pytest.mark.parametrize("change", ["edit", "delete", "hidden", "foreign"])
def test_native_reader_resolves_current_owned_version(tmp_path, change):
    db = DB(tmp_path / "native.sqlite")
    record = db.append_message(session_id="s1", role="user", content="Original")
    reader = HermesNativeSource(db.db_path, scope=SCOPE, user_id="native-user", namespace="n")
    try:
        original = reader.snapshot("s1")[0]
        assert reader.read(SCOPE, original.ref) == original
        with db.conn:
            if change == "edit":
                db.conn.execute("UPDATE messages SET content='Edited' WHERE id=?", (record,))
            elif change == "delete":
                db.conn.execute("DELETE FROM messages WHERE id=?", (record,))
            elif change == "hidden":
                db.conn.execute("UPDATE messages SET active=0,compacted=0 WHERE id=?", (record,))
            else:
                db.conn.execute("UPDATE sessions SET user_id='other'")
        if change == "foreign":
            with pytest.raises(ValueError, match="another owner"):
                reader.read(SCOPE, original.ref)
        elif change == "edit":
            assert reader.read(SCOPE, original.ref).ref != original.ref
        else:
            assert reader.read(SCOPE, original.ref) is None
    finally:
        reader.close()
        db.conn.close()


def test_host_hooks_queue_compile_read_and_invalidate_other_session(tmp_path, monkeypatch):
    from mr_mem_aml.compiler import CompiledBlock, LineOut
    from xiyue.native_memory import sync_native_memory
    from xiyue.tests import test_mr_mem_history as history

    from mind_runtime.contracts import Scope, ScopeDomain
    from mind_runtime.integrations.mr_mem_history import MrMemHistoricalContext

    class AcceptedCompiler:
        version = "host-fixture"

        def compile(self, messages, *args, **kwargs):
            return tuple(CompiledBlock(
                m.content, (m.record_id,), None, None,
                (LineOut(None, None if i == 0 else f"b{i}", False, None),),
            ) for i, m in enumerate(messages))

    db = DB(tmp_path / "native.sqlite")
    db.append_message(session_id="s1", role="user", content="Daily reports")
    db.append_message(session_id="s1", role="user", content="Weekly summaries instead")
    data = tmp_path / "memory"
    config = tmp_path / "native.json"
    config.write_text(json.dumps({"data_dir": str(data), "compiler": {"type": "disabled"},
                                  "path_a_engine": "tree", "placement": "points"}))
    for key, value in {"MR_MEM_NATIVE_ENABLED": "true", "MR_MEM_NATIVE_CONFIG": str(config),
                       "MR_MEM_CANONICAL_DB": str(data / "memory.sqlite"),
                       "MR_MEM_LINE_ROOT": str(data / "lce_tree"),
                       "SEMANTIC_DELTA_V1_ENABLED": "false"}.items():
        monkeypatch.setenv(key, value)
    agent = SimpleNamespace(_session_db=db)
    adapter = SimpleNamespace(_scope=SCOPE, _runtime_id="native-fixture")
    source = SimpleNamespace(user_id="native-user")
    try:
        pending = sync_native_memory(agent, source, "s1", adapter, compile_pending=True)
        assert pending["s1"]["status"] == "compiler_not_configured"
        ready = sync_native_memory(agent, source, "s1", adapter, compile_pending=True,
                                   compiler=AcceptedCompiler())
        assert ready["s1"]["applied_batches"] == 1
        monkeypatch.setattr(history, "NOW", datetime.now(UTC))
        port = MrMemHistoricalContext(data / "memory.sqlite", line_root=data / "lce_tree")
        context = history.read(port, scope=Scope(ScopeDomain.USER, user_id=SCOPE.user_id))
        assert context.episodes[0].kind == "memory.line"
        assert "Weekly summaries instead" in context.episodes[0].proposition
        # A later turn in another session must also discover deletion of old support.
        with db.conn:
            db.conn.execute("DELETE FROM messages WHERE session_id='s1'")
            db.conn.execute("INSERT INTO sessions VALUES('s2','native-user')")
        changed = sync_native_memory(agent, source, "s2", adapter)
        assert changed["s1"]["invalidated_memories"] == 2
        assert history.read(port, scope=Scope(ScopeDomain.USER, user_id=SCOPE.user_id)) is None
    finally:
        db.conn.close()


def test_native_gateway_patch_runs_before_read_and_after_commit(tmp_path):
    from xiyue.apply_native_memory_patch import BEGIN, COMMIT, MARKER, render

    source = "def gateway():\n"
    # Exact indentation of the external, already-patched Hermes gateway.
    for indent in range(4, 24, 4):
        source += " " * indent + "if True:\n"
    source += BEGIN + "\n                            message='hello')\n"
    source += "                        if True:\n" + COMMIT + "\n"
    patched = render(source, tmp_path)
    assert patched.count(MARKER) == 1
    assert patched.index("_native_sync(") < patched.index(BEGIN)
    assert patched.rindex("_native_sync(") > patched.index(COMMIT)
    assert render(patched, tmp_path) == patched
    with pytest.raises(ValueError, match="drift"):
        render(source.replace(COMMIT, "                            pass"), tmp_path)
