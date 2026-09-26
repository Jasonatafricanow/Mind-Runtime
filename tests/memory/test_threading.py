from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from mind_runtime.contracts import SemanticEventCandidate
from mind_runtime.memory.product import MemoryProductStore, ThreadStatus
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.threading import (
    ThreadAutoUpdateService,
    ThreadSignal,
    ThreadSignalAction,
)
from tests.memory.test_contracts import memory

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def remembered(memory_id: str, content: str, evidence_id: str, observation_id: str):
    item = memory()
    return replace(
        item,
        memory_id=memory_id,
        content=content,
        provenance=replace(
            item.provenance,
            evidence_refs=(evidence_id,),
            observation_id=observation_id,
        ),
        sync=replace(
            item.sync,
            object_id=memory_id,
            idempotency_key=memory_id,
        ),
    )


def event(
    *,
    candidate_id: str,
    refs: tuple[str, ...],
    action: str,
    question: str,
    summary: str,
) -> SemanticEventCandidate:
    return SemanticEventCandidate(
        candidate_id=candidate_id,
        scope=memory().scope,
        origin_runtime_id="runtime-1",
        kind="user_open_line",
        attributes=(
            ("thread_action", action),
            ("thread_question", question),
            ("thread_summary", summary),
        ),
        confidence=0.95,
        evidence_refs=refs,
    )


class RecordingCompiler:
    def __init__(self, baseline_id: str | None = "baseline-1") -> None:
        self.baseline_id = baseline_id
        self.calls = []

    def compile(self, thread):
        self.calls.append(thread)
        return self.baseline_id


def setup_service(tmp_path):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    canonical._commit(
        (
            remembered(
                "m1",
                "I am thinking about replacing my laptop.",
                "e1",
                "o1",
            ),
            remembered(
                "m2",
                "The current laptop is getting slow.",
                "e2",
                "o2",
            ),
            remembered(
                "m3",
                "I decided to buy the replacement.",
                "e3",
                "o3",
            ),
        )
    )
    product = MemoryProductStore(path, canonical)
    return canonical, product, ThreadAutoUpdateService(canonical=canonical, product=product)


def test_track_creates_then_updates_same_thread_and_matures(tmp_path):
    canonical, product, service = setup_service(tmp_path)
    first = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c1",
                refs=("e1",),
                action="track",
                question="Will I replace my laptop?",
                summary="Laptop replacement is under consideration.",
            ),
        ),
        at=NOW,
    )
    assert len(first) == 1
    thread = first[0]
    assert thread.status is ThreadStatus.OPEN
    assert thread.current_support_ids == ("m1",)
    assert thread.working_summary == "Laptop replacement is under consideration."
    assert not thread.mature

    second = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c2",
                refs=("o2",),
                action="track",
                question="Will I replace my laptop?",
                summary="Performance pressure keeps laptop replacement active.",
            ),
        ),
        at=NOW,
    )
    assert len(second) == 1
    updated = second[0]
    assert updated.thread_id == thread.thread_id
    assert updated.current_support_ids == ("m1", "m2")
    assert updated.mature
    assert len(product.list_threads(memory().scope)) == 1
    service.close()


def test_mature_thread_is_compiled_and_removed_from_active_set(tmp_path):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    canonical._commit(
        (
            remembered("m1", "I want a new laptop.", "e1", "o1"),
            remembered("m2", "The current laptop is slow.", "e2", "o2"),
        )
    )
    product = MemoryProductStore(path, canonical)
    compiler = RecordingCompiler()
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        projection_compiler=compiler,
    )
    first = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c1",
                refs=("e1",),
                action="track",
                question="Will I replace my laptop?",
                summary="Laptop replacement is under consideration.",
            ),
        ),
        at=NOW,
    )[0]
    assert first.status is ThreadStatus.OPEN

    service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c2",
                refs=("e2",),
                action="track",
                question="Will I replace my laptop?",
                summary="Performance pressure makes the replacement logic explicit.",
            ),
        ),
        at=NOW,
    )
    assert len(compiler.calls) == 1
    assert compiler.calls[0].mature
    assert product.get_thread(first.thread_id) is None
    assert product.list_threads(memory().scope, status=ThreadStatus.OPEN) == ()
    service.close()


def test_failed_or_disabled_projection_keeps_mature_thread_active(tmp_path):
    path = tmp_path / "memory.sqlite"
    canonical = CanonicalMemoryStore(path)
    canonical._commit(
        (
            remembered("m1", "I want a new laptop.", "e1", "o1"),
            remembered("m2", "The current laptop is slow.", "e2", "o2"),
        )
    )
    product = MemoryProductStore(path, canonical)
    compiler = RecordingCompiler(None)
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        projection_compiler=compiler,
    )
    service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c1",
                refs=("e1",),
                action="track",
                question="Will I replace my laptop?",
                summary="Laptop replacement is under consideration.",
            ),
            event(
                candidate_id="c2",
                refs=("e2",),
                action="track",
                question="Will I replace my laptop?",
                summary="Performance pressure makes the replacement logic explicit.",
            ),
        ),
        at=NOW,
    )
    active = product.list_threads(memory().scope, status=ThreadStatus.OPEN)
    assert len(active) == 1
    assert active[0].mature
    service.close()


def test_replay_is_idempotent_and_does_not_increment_touch_count(tmp_path):
    canonical, product, service = setup_service(tmp_path)
    signal = event(
        candidate_id="c1",
        refs=("e1",),
        action="track",
        question="Will I replace my laptop?",
        summary="Laptop replacement is under consideration.",
    )
    first = service.apply(
        scope=memory().scope,
        accepted_events=(signal,),
        at=NOW,
    )[0]
    replay = service.apply(
        scope=memory().scope,
        accepted_events=(signal,),
        at=NOW,
    )[0]
    assert replay == first
    assert replay.touch_count == 0
    service.close()


def test_resolve_closes_matching_thread_without_creating_second_history(tmp_path):
    canonical, product, service = setup_service(tmp_path)
    opened = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c1",
                refs=("e1",),
                action="track",
                question="Will I replace my laptop?",
                summary="Laptop replacement is under consideration.",
            ),
        ),
        at=NOW,
    )[0]
    service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c2",
                refs=("e2",),
                action="track",
                question="Will I replace my laptop?",
                summary="Performance pressure keeps laptop replacement active.",
            ),
        ),
        at=NOW,
    )

    resolved = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c3",
                refs=("e3",),
                action="resolve",
                question="Will I replace my laptop?",
                summary="The replacement decision is settled.",
            ),
        ),
        at=NOW,
    )
    assert len(resolved) == 1
    assert resolved[0].thread_id == opened.thread_id
    assert resolved[0].status is ThreadStatus.RESOLVED
    assert resolved[0].current_support_ids == ("m1", "m2", "m3")
    assert product.list_threads(
        memory().scope,
        status=ThreadStatus.OPEN,
    ) == ()
    service.close()


def test_no_thread_signal_or_unresolved_support_is_ignored(tmp_path):
    canonical, product, service = setup_service(tmp_path)
    plain = SemanticEventCandidate(
        candidate_id="plain",
        scope=memory().scope,
        origin_runtime_id="runtime-1",
        kind="gratitude",
        attributes=(),
        confidence=0.9,
        evidence_refs=("e1",),
    )
    missing = event(
        candidate_id="missing",
        refs=("missing",),
        action="track",
        question="Will this exist?",
        summary="No canonical support exists.",
    )
    invalid_action = replace(
        missing,
        candidate_id="invalid-action",
        evidence_refs=("e1",),
        attributes=(("thread_action", "bogus"),),
    )
    none_action = replace(
        missing,
        candidate_id="none-action",
        evidence_refs=("e1",),
        attributes=(("thread_action", "none"),),
    )
    track_without_question = replace(
        missing,
        candidate_id="track-no-question",
        evidence_refs=("e1",),
        attributes=(("thread_action", "track"),),
    )
    resolve_without_context = replace(
        missing,
        candidate_id="resolve-no-context",
        evidence_refs=("e1",),
        attributes=(("thread_action", "resolve"),),
    )
    empty_refs = event(
        candidate_id="empty-refs",
        refs=(),
        action="track",
        question="Will empty support work?",
        summary="It must not.",
    )
    other_scope = replace(
        event(
            candidate_id="other-scope",
            refs=("e1",),
            action="track",
            question="Will cross-scope support work?",
            summary="It must not.",
        ),
        scope=replace(memory().scope, user_id="other"),
    )
    unmatched_resolve = event(
        candidate_id="unmatched-resolve",
        refs=("e1",),
        action="resolve",
        question="Does an absent line resolve?",
        summary="Nothing was opened.",
    )
    assert service.apply(
        scope=memory().scope,
        accepted_events=(
            plain,
            missing,
            invalid_action,
            none_action,
            track_without_question,
            resolve_without_context,
            empty_refs,
            other_scope,
            unmatched_resolve,
        ),
        at=NOW,
    ) == ()
    assert product.list_threads(memory().scope) == ()

    for bad in (True, -0.1, 1.1):
        with pytest.raises(ValueError, match="minimum_match"):
            ThreadAutoUpdateService(
                canonical=canonical,
                product=product,
                minimum_match=bad,
            )
    with pytest.raises(ValueError, match="action"):
        ThreadSignal(cast(ThreadSignalAction, "track"), "Question?", "Summary")
    with pytest.raises(ValueError, match="open_question"):
        ThreadSignal(ThreadSignalAction.TRACK, "", "Summary")
    with pytest.raises(ValueError, match="2048"):
        ThreadSignal(ThreadSignalAction.TRACK, "q" * 2049, "Summary")
    with pytest.raises(ValueError, match="summary"):
        ThreadSignal(ThreadSignalAction.TRACK, "Question?", "")
    with pytest.raises(ValueError, match="4096"):
        ThreadSignal(ThreadSignalAction.TRACK, "Question?", "s" * 4097)
    with pytest.raises(ValueError, match="mature"):
        ThreadSignal(
            ThreadSignalAction.TRACK,
            "Question?",
            "Summary",
            mature=cast(bool, 1),
        )
    service.close()


def test_semantically_similar_question_matches_existing_thread(tmp_path):
    canonical, product, service = setup_service(tmp_path)
    first = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c1",
                refs=("e1",),
                action="track",
                question="Will I replace my laptop?",
                summary="Laptop replacement is under consideration.",
            ),
        ),
        at=NOW,
    )[0]
    second = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c2",
                refs=("e2",),
                action="track",
                question="Is the laptop replacement still happening?",
                summary="The slow laptop keeps replacement relevant.",
            ),
        ),
        at=NOW,
    )[0]
    assert second.thread_id == first.thread_id
    assert len(product.list_threads(memory().scope)) == 1

    unrelated = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="c3",
                refs=("e3",),
                action="track",
                question="Weather?",
                summary="?",
            ),
        ),
        at=NOW,
    )[0]
    assert unrelated.thread_id != first.thread_id
    assert len(product.list_threads(memory().scope)) == 2
    service.close()
