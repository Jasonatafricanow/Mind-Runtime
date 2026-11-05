"""Exercise the pinned current MR-Mem core over real HTTP with a fixture compiler."""

import threading

import pytest

from mind_runtime.integrations.mr_mem_core import MrMemClient, MrMemUnavailable

mrmem = pytest.importorskip("mr_mem_aml", reason="paired MR-Mem core is an optional dependency")


def test_current_core_add_line_raw_read_flush_replay_and_restart(tmp_path):
    from mr_mem_aml.compiler import CompiledBlock, LineOut
    from mr_mem_aml.config import RuntimeConfig
    from mr_mem_aml.runtime import MemoryRuntime
    from mr_mem_aml.server import RuntimeHost, build_server

    class FixtureCompiler:
        version = "mr-host-fixture"
        calls = 0

        def compile(self, messages, *args, **kwargs):
            self.calls += 1
            return tuple(CompiledBlock(
                m.content, (m.record_id,), None, None,
                (LineOut(None, None if i == 0 else f"b{i}", False, None),),
            ) for i, m in enumerate(messages))

    compiler = FixtureCompiler()
    config = RuntimeConfig(
        data_dir=tmp_path / "core", compiler={"type": "command", "argv": ["unused"]},
        path_a_engine="tree", placement="points", raw_base=True,
        compile_window={"soft": 10, "hard": 20}, line_read={"raw_full": 3},
        port=0,
    )
    def start():
        host = RuntimeHost(lambda: MemoryRuntime(config, compiler=compiler))
        server = build_server(config, host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = MrMemClient(f"http://127.0.0.1:{server.server_port}", "u1",
                             exclusive_instance=True)
        return host, server, thread, client

    def stop(host, server, thread):
        server.shutdown()
        server.server_close()
        thread.join()
        host.close()

    payload = {"request_id": "durable-one", "session_id": "s1", "messages": [
        {"role": "user", "content": "Daily reports include everything", "timestamp": 1000000},
        {"role": "user", "content": "Change reports to exceptions only", "timestamp": 2000000},
    ]}
    host, server, thread, client = start()
    try:
        assert client.add(**payload)["success"]
        assert compiler.calls == 0
        assert client.flush()["windows"] == 1
        found = client.search("reports")["data"]
        assert any(i["id"].startswith("line:") for i in found)
        assert any(i["id"].startswith("raw:") for i in found)
        assert "exceptions only" in str(found)
        assert client.add(**payload)["replayed"] is True
        other = MrMemClient(client.base_url, "other")
        assert other.search("reports")["data"] == []
        changed = {**payload, "messages": [{"role": "user", "content": "changed"}]}
        with pytest.raises(MrMemUnavailable, match="HTTP 422"):
            client.add(**changed)
    finally:
        stop(host, server, thread)
    count = compiler.calls
    host, server, thread, client = start()
    try:
        assert "exceptions only" in str(client.search("reports"))
        assert client.add(**payload)["replayed"] is True
        assert client.flush()["windows"] == 0
        assert compiler.calls == count
        assert client.health()["status"] == "ok"
    finally:
        stop(host, server, thread)
