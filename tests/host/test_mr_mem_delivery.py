"""Native incremental delivery, retry/restart, edit blocking and patch lifecycle."""

import sqlite3
from types import SimpleNamespace

import pytest

from mind_runtime.integrations.mr_mem_delivery import NativeMemoryDelivery, NativeSourceChanged


@pytest.fixture
def native(tmp_path):
    path = tmp_path / "native.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT);"
            "INSERT INTO sessions VALUES('s1','native-user');"
            "CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,"
            "content TEXT,timestamp REAL,tool_calls TEXT,active INTEGER,compacted INTEGER);"
            "INSERT INTO messages VALUES(1,'s1','user','already compiled',1000,NULL,1,0);"
            "INSERT INTO messages VALUES(2,'s1','user','incremental report',2000,NULL,1,0);"
        )
    return path


def test_incremental_native_retry_replays_frozen_batch_after_restart(native, tmp_path):
    attempts = []
    def add(**payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise TimeoutError("receipt lost after remote persistence")
        return {"success": True}
    client = SimpleNamespace(base_url="http://localhost:8765", user_id="u1", add=add)
    def open_delivery():
        return NativeMemoryDelivery(native, tmp_path / "journal.sqlite", client,
                                    native_user="native-user", runtime_id="mr", baseline=1)
    delivery = open_delivery()
    assert delivery.synchronize("s1")["status"] == "validated"
    assert not attempts
    with pytest.raises(TimeoutError):
        delivery.synchronize("s1", after_commit=True)
    delivery.close()
    delivery = open_delivery()
    assert delivery.synchronize("s1", after_commit=True)["sent_batches"] == 1
    assert attempts[0] == attempts[1]
    assert [m["content"] for m in attempts[1]["messages"]] == ["incremental report"]
    assert attempts[1]["messages"][0]["timestamp"] == 2000000
    assert delivery.synchronize("s1", after_commit=True)["sent_batches"] == 0
    assert not any("incremental report" in str(row) for row in
                   delivery.db.execute("SELECT * FROM batches"))
    delivery.close()


@pytest.mark.parametrize("change", ["edit", "delete", "hidden", "foreign"])
def test_source_change_in_old_session_blocks_next_read(native, tmp_path, change):
    client = SimpleNamespace(base_url="http://localhost:8765", user_id="u1", add=lambda **kw: {})
    delivery = NativeMemoryDelivery(native, tmp_path / "journal.sqlite", client,
                                    native_user="native-user", runtime_id="mr", baseline=1)
    delivery.synchronize("s1", after_commit=True)
    with sqlite3.connect(native) as db:
        if change == "edit":
            db.execute("UPDATE messages SET content='changed' WHERE id=2")
        elif change == "delete":
            db.execute("DELETE FROM messages WHERE id=2")
        elif change == "hidden":
            db.execute("UPDATE messages SET active=0 WHERE id=2")
        else:
            db.execute("UPDATE sessions SET user_id='foreign' WHERE id='s1'")
        db.execute("INSERT INTO sessions VALUES('s2','native-user')")
    with pytest.raises(ValueError if change == "foreign" else NativeSourceChanged):
        delivery.synchronize("s2")
    delivery.close()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_patch_only_delivers_after_successful_commit(tmp_path, newline):
    from xiyue.apply_core_memory_patch import BEGIN, COMMIT, MARKER, render
    source = "def gateway():\n"
    for indent in range(4, 24, 4):
        source += " " * indent + "if True:\n"
    source += BEGIN + "\n                            message='hello')\n"
    source += "                        if True:\n" + COMMIT + "\n"
    source = source.replace("\n", newline)
    patched = render(source, tmp_path)
    assert MARKER in patched and render(patched, tmp_path) == patched
    assert ("\r\n" in patched) == (newline == "\r\n")
    events = []
    for committed in (False, True):
        events.clear()
        def sync(*args, **kwargs):
            events.append("after" if kwargs.get("after_commit") else "before")
        adapter = SimpleNamespace(commit_turn=lambda handle, ok=committed: ok)
        seam = SimpleNamespace(get_mr_adapter=lambda bound=adapter: bound,
                               begin_turn_clean=lambda **kw: ("handle", "ok"))
        import xiyue.core_memory as module
        original = module.sync_core_memory
        module.sync_core_memory = sync
        try:
            namespace = {"_mr_sys": SimpleNamespace(path=SimpleNamespace(insert=lambda *a: None)),
                         "_mr_seam": seam, "_active_adapter": adapter,
                         "agent": None, "source": None, "session_id": "s"}
            exec(patched, namespace)
            namespace["gateway"]()
            assert events == (["before", "after"] if committed else ["before"])
        finally:
            module.sync_core_memory = original


def test_failed_memory_delivery_cannot_reverse_successful_host_commit(
    native, tmp_path, monkeypatch,
):
    from xiyue.core_memory import sync_core_memory

    monkeypatch.setenv("MR_MEM_NATIVE_HTTP_ENABLED", "true")
    monkeypatch.setenv("MR_MEM_NATIVE_JOURNAL", str(tmp_path / "journal.sqlite"))
    monkeypatch.setenv("MR_MEM_NATIVE_BASELINE", "1")
    calls = []
    def add(**payload):
        calls.append(payload)
        if len(calls) == 1:
            raise TimeoutError("lost core receipt")
        return {"success": True}
    client = SimpleNamespace(base_url="http://localhost:8765", user_id="u1", add=add)
    agent = SimpleNamespace(_session_db=SimpleNamespace(db_path=native))
    adapter = SimpleNamespace(memory=client, _runtime_id="r")
    source = SimpleNamespace(user_id="native-user")
    result = sync_core_memory(agent, source, "s1", adapter, after_commit=True)
    assert result == {"status": "pending", "error_type": "TimeoutError"}
    assert agent._mr_native_memory_status == result
    assert sync_core_memory(agent, source, "s1", adapter)["status"] == "validated"
    assert sync_core_memory(agent, source, "s1", adapter, after_commit=True)["status"] == "accepted"
    assert calls[0] == calls[1]
