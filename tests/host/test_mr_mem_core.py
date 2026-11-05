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
