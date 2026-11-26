"""Core HTTP receipts, scope binding and failure boundaries, without model calls."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mind_runtime.integrations.mr_mem_core import MrMemClient, MrMemUnavailable


@pytest.fixture
def service():
    calls = []
    state = {"failure": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body))
            result = ({"success": True, **{k: body[k] for k in
                       ("request_id", "session_id", "user_id")}} if self.path == "/add"
                      else {"data": [{"id": "line:one", "content": "A remembered change"}]})
            raw = json.dumps(result).encode()
            self.send_response(503 if state["failure"] else 200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield MrMemClient(f"http://127.0.0.1:{server.server_port}", "u1"), calls, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bound_core_add_search_and_failure(service):
    client, calls, state = service
    client.add(request_id="durable-1", session_id="s1",
               messages=[{"role": "user", "content": "A remembered change", "timestamp": 1000}])
    assert client.search("remembered")["data"][0]["id"] == "line:one"
    assert all(body["user_id"] == "u1" for _, body in calls)
    state["failure"] = True
    with pytest.raises(MrMemUnavailable, match="HTTP 503"):
        client.search("remembered")
    with pytest.raises(ValueError, match="exclusive"):
        client.flush()
    assert [path for path, _ in calls] == ["/add", "/search", "/search"]


@pytest.mark.parametrize("url", ["file:///secret", "http://user:secret@localhost", "http://x/path"])
def test_service_origin_rejects_embedded_secrets_and_routes(url):
    with pytest.raises(ValueError):
        MrMemClient(url, "u1")


@pytest.fixture
def raw_service():
    """A core stub whose reply is set per test, so failure shapes are explicit."""
    seen = []
    reply = {"status": 200, "body": b"{}", "headers": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            seen.append((self.path, dict(self.headers), self.rfile.read(length)))
            self.send_response(reply["status"])
            for key, value in reply["headers"].items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(reply["body"])))
            self.end_headers()
            self.wfile.write(reply["body"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen, reply
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_token_stays_on_configured_origin_and_vanishing_token_fails_closed(
    raw_service, monkeypatch,
):
    origin, seen, reply = raw_service
    monkeypatch.setenv("MR_MEM_TEST_TOKEN", "secret-token")
    client = MrMemClient(origin, "u1", token_env="MR_MEM_TEST_TOKEN")
    reply.update(status=307, headers={"Location": "http://elsewhere.invalid/search"})
    with pytest.raises(MrMemUnavailable, match="HTTP 307"):
        client.search("anything")
    assert len(seen) == 1 and seen[0][1]["Authorization"] == "Bearer secret-token"
    monkeypatch.delenv("MR_MEM_TEST_TOKEN")
    with pytest.raises(MrMemUnavailable, match="authentication"):
        client.search("anything")
    assert len(seen) == 1
    with pytest.raises(ValueError, match="authentication"):
        MrMemClient(origin, "u1", token_env="MR_MEM_TEST_TOKEN")


@pytest.mark.parametrize("body", [
    b"not json",
    b"[]",
    b'{"data": {"id": "x"}}',
    b'{"data": [{"id": " ", "content": "blank id"}]}',
    b'{"data": [{"id": "line:x"}]}',
])
def test_malformed_search_reply_is_unavailable_not_empty_memory(raw_service, body):
    origin, _, reply = raw_service
    reply["body"] = body
    with pytest.raises(MrMemUnavailable):
        MrMemClient(origin, "u1").search("anything")


def test_add_receipt_for_another_scope_is_rejected(raw_service):
    origin, _, reply = raw_service
    reply["body"] = json.dumps({"success": True, "request_id": "r1",
                                "session_id": "s1", "user_id": "u2"}).encode()
    with pytest.raises(MrMemUnavailable, match="receipt"):
        MrMemClient(origin, "u1").add(request_id="r1", session_id="s1",
                                      messages=[{"role": "user", "content": "x"}])


def test_unreachable_core_is_unavailable():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    with pytest.raises(MrMemUnavailable, match="transport"):
        MrMemClient(f"http://127.0.0.1:{port}", "u1", timeout=2).search("anything")
