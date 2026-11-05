"""User-bound client for the current MR-Mem core's HTTP contract.

Search results are derived context. Their result locators are not raw evidence.
No optional MR-Mem implementation package is imported by MR.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class MrMemUnavailable(RuntimeError):
    """An explicitly configured core failed; never reinterpret this as empty memory."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any,
                         headers: Any, newurl: Any) -> None:
        return None


@dataclass(frozen=True)
class MrMemClient:
    base_url: str
    user_id: str
    token_env: str | None = None
    timeout: float = 120.0
    exclusive_instance: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("MR-Mem URL must be an HTTP(S) service origin")
        if not self.user_id.strip() or self.user_id != self.user_id.strip():
            raise ValueError("MR-Mem needs a nonempty, normalized user_id")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("MR-Mem timeout must be positive and finite")
        if self.token_env and not os.environ.get(self.token_env, "").strip():
            raise ValueError("MR-Mem authentication environment variable is missing")

    def _request(self, route: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token_env:
            token = os.environ.get(self.token_env, "").strip()
            if not token:
                raise MrMemUnavailable("MR-Mem authentication environment variable is missing")
            headers["Authorization"] = "Bearer " + token
        body = None if payload is None else json.dumps(
            payload, ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        request = Request(self.base_url.rstrip("/") + route, data=body, headers=headers)
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise MrMemUnavailable("MR-Mem response exceeds limit")
            result = json.loads(raw)
        except HTTPError as exc:
            # Do not expose server body, URLs, credentials or private message text.
            raise MrMemUnavailable(f"MR-Mem HTTP {exc.code}") from None
        except (URLError, OSError, ValueError) as exc:
            raise MrMemUnavailable("MR-Mem transport or JSON failure") from exc
        if not isinstance(result, dict):
            raise MrMemUnavailable("MR-Mem response must be an object")
        return result

    def add(self, *, request_id: str, session_id: str,
            messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not request_id.strip() or not session_id.strip() or not messages:
            raise ValueError("stable request/session IDs and durable messages required")
        result = self._request("/add", {"request_id": request_id, "user_id": self.user_id,
                                      "session_id": session_id, "messages": messages})
        if (result.get("success") is not True or any(result.get(k) != v for k, v in
                {"request_id": request_id, "user_id": self.user_id,
                 "session_id": session_id}.items())):
            raise MrMemUnavailable("MR-Mem Add receipt does not match the request")
        return result

    def search(self, query: str, *, top_k: int = 20) -> dict[str, Any]:
        if not query.strip() or len(query) > 4096 or type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError("MR-Mem query needs 1..4096 characters and top_k in 1..100")
        result = self._request("/search", {"user_id": self.user_id, "query": query,
                                         "top_k": top_k})
        data = result.get("data")
        if not isinstance(data, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or not row["id"].strip() or not isinstance(row.get("content"), str)
            for row in data
        ):
            raise MrMemUnavailable("MR-Mem Search returned malformed items")
        return result

    def health(self) -> dict[str, Any]:
        return self._request("/health", None)

    def flush(self) -> dict[str, Any]:
        # The current core HTTP flush is instance-wide, even if user_id is supplied.
        if not self.exclusive_instance:
            raise ValueError("MR-Mem HTTP Flush requires an explicitly exclusive instance")
        return self._request("/admin/flush", {})
