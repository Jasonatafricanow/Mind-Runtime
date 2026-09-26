from __future__ import annotations

from pathlib import Path

import pytest

from mind_runtime.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchRequest,
)
from mind_runtime.aml.providers import ThreadSemanticDecision
from mind_runtime.aml.runtime import AmlMemoryRuntime, AmlRequestConflict


class _ThreadSemantics:
    def analyze(
        self,
        *,
        message: AmlMessage,
        context: tuple[AmlMessage, ...],
    ) -> ThreadSemanticDecision:
        del context
        return ThreadSemanticDecision(
            action="track",
            question="Where should the user travel?",
            summary=f"Travel planning remains active: {message.content}",
            mature=True,
            confidence=0.9,
        )


def _request(
    *,
    request_id: str = "req-1",
    user_id: str = "user-1",
    content: str = "I prefer quiet coastal towns.",
    timestamp: int | None = 1704067200000,
) -> AmlAddRequest:
    return AmlAddRequest(
        request_id=request_id,
        user_id=user_id,
        session_id="session-1",
        messages=(AmlMessage("user", content, timestamp),),
    )


def test_add_is_immediately_searchable_bounded_and_idempotent(tmp_path: Path) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            result_cap=1,
            candidate_limit=10,
            thread_enabled=False,
            lce_enabled=False,
        ),
    )
    request = _request()
    runtime.add(request)
    runtime.add(request)

    results = runtime.search(
        AmlSearchRequest(
            user_id="user-1",
            query="quiet coastal towns",
            top_k=100,
        )
    )
    assert len(results) == 1
    assert results[0].layer == "memory"
    assert "I prefer quiet coastal towns." in results[0].content
    assert results[0].created_at.startswith("2024-01-01")

    assert runtime.search(
        AmlSearchRequest(
            user_id="different-user",
            query="quiet coastal towns",
            top_k=100,
        )
    ) == ()


def test_replayed_request_id_with_different_bytes_fails_closed(tmp_path: Path) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            thread_enabled=False,
            lce_enabled=False,
        ),
    )
    runtime.add(_request())
    with pytest.raises(AmlRequestConflict):
        runtime.add(_request(content="Different immutable transcript."))


def test_thread_lane_is_a_projection_over_canonical_memory(tmp_path: Path) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            result_cap=5,
            candidate_limit=10,
            thread_enabled=True,
            lce_enabled=False,
        ),
        thread_semantics=_ThreadSemantics(),
    )
    runtime.add(
        AmlAddRequest(
            request_id="req-a",
            user_id="user-1",
            session_id="session-1",
            messages=(
                AmlMessage(
                    "user",
                    "I am considering a quiet beach trip.",
                    1704067200000,
                ),
            ),
        )
    )
    runtime.add(
        AmlAddRequest(
            request_id="req-b",
            user_id="user-1",
            session_id="session-1",
            messages=(
                AmlMessage(
                    "user",
                    "The travel plan is still active.",
                    1704153600000,
                ),
            ),
        )
    )

    results = runtime.search(
        AmlSearchRequest(
            user_id="user-1",
            query="travel plan",
            top_k=100,
        )
    )
    assert results
    assert results[0].layer == "thread"
    assert "[Thread working context]" in results[0].content
    assert "Support:" in results[0].content
    assert any(item.layer == "memory" for item in results)


def test_options_are_search_context_not_stored_gold(tmp_path: Path) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            thread_enabled=False,
            lce_enabled=False,
        ),
    )
    runtime.add(
        _request(content="The user chose the blue notebook.")
    )
    results = runtime.search(
        AmlSearchRequest(
            user_id="user-1",
            query="Which notebook?",
            options=("A. red notebook", "B. blue notebook"),
            top_k=100,
        )
    )
    assert results
    assert "blue notebook" in results[0].content
