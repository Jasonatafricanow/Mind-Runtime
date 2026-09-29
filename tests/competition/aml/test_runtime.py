from __future__ import annotations

from pathlib import Path

import pytest

from mind_runtime.competition.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchRequest,
)
from mind_runtime.competition.aml.journal import AmlRequestConflict
from mind_runtime.competition.aml.runtime import AmlCompetitionRuntime
from mind_runtime.contracts import SemanticEventCandidate
from mind_runtime.memory.store import CanonicalMemoryStore


def _request(
    *,
    request_id: str = "req-1",
    user_id: str = "user-1",
    content: str = "I prefer quiet coastal towns.",
) -> AmlAddRequest:
    return AmlAddRequest(
        request_id=request_id,
        user_id=user_id,
        session_id="session-1",
        messages=(
            AmlMessage(
                "user",
                content,
                1704067200000,
            ),
        ),
    )


def _basic_runtime(tmp_path: Path) -> AmlCompetitionRuntime:
    return AmlCompetitionRuntime(
        tmp_path,
        run_id="qualification",
        config=AmlRuntimeConfig(
            result_cap=5,
            candidate_limit=20,
            thread_enabled=False,
            lce_enabled=False,
        ),
    )


def test_add_is_immediately_searchable_idempotent_and_user_scoped(
    tmp_path: Path,
) -> None:
    runtime = _basic_runtime(tmp_path)
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
    assert "quiet coastal towns" in results[0].content
    assert runtime.search(
        AmlSearchRequest(
            user_id="other-user",
            query="quiet coastal towns",
            top_k=100,
        )
    ) == ()


def test_request_id_payload_conflict_fails_closed(tmp_path: Path) -> None:
    runtime = _basic_runtime(tmp_path)
    runtime.add(_request())
    with pytest.raises(AmlRequestConflict):
        runtime.add(
            _request(content="Different immutable transcript.")
        )


def test_retry_after_canonical_stage_does_not_duplicate_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = AmlCompetitionRuntime(
        tmp_path,
        run_id="restart",
        config=AmlRuntimeConfig(
            thread_enabled=True,
            lce_enabled=False,
        ),
        semantic=_TrackSemantic(),
    )
    original = runtime._thread_stage
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic crash after canonical commit")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "_thread_stage", fail_once)
    with pytest.raises(RuntimeError):
        runtime.add(_request())
    user = runtime._user("user-1")
    store = CanonicalMemoryStore(
        user.paths.memory_db,
        read_only=True,
    )
    try:
        before = store.load_all()
    finally:
        store.close()
    assert len(before) == 1

    runtime.add(_request())
    store = CanonicalMemoryStore(
        user.paths.memory_db,
        read_only=True,
    )
    try:
        after = store.load_all()
    finally:
        store.close()
    assert tuple(item.memory_id for item in after) == tuple(
        item.memory_id for item in before
    )


class _TrackSemantic:
    def events(
        self,
        *,
        message: AmlMessage,
        visible_messages: tuple[AmlMessage, ...],
        active_threads,
        scope,
        origin_runtime_id: str,
        evidence_ref: str,
    ) -> tuple[SemanticEventCandidate, ...]:
        del visible_messages, active_threads
        return (
            SemanticEventCandidate(
                candidate_id=f"thread-{evidence_ref}",
                scope=scope,
                origin_runtime_id=origin_runtime_id,
                kind="aml.thread_signal",
                attributes=(
                    ("thread_action", "track"),
                    (
                        "thread_question",
                        "Where should the user travel?",
                    ),
                    (
                        "thread_summary",
                        f"Travel planning: {message.content}",
                    ),
                    ("thread_mature", "true"),
                ),
                confidence=0.9,
                evidence_refs=(evidence_ref,),
            ),
        )


def test_thread_stage_is_visible_before_add_returns(tmp_path: Path) -> None:
    runtime = AmlCompetitionRuntime(
        tmp_path,
        run_id="thread",
        config=AmlRuntimeConfig(
            result_cap=5,
            candidate_limit=20,
            thread_enabled=True,
            lce_enabled=False,
        ),
        semantic=_TrackSemantic(),
    )
    runtime.add(
        AmlAddRequest(
            request_id="req-thread",
            user_id="user-1",
            session_id="session-1",
            messages=(
                AmlMessage(
                    "user",
                    "I am considering a quiet beach trip.",
                    1704067200000,
                ),
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
    assert all(item.layer != "memory" for item in results)
