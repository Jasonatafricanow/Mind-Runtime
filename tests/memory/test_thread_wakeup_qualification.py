from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mind_runtime.decision import (
    DecisionAnswer,
    DecisionCapability,
    DecisionKind,
    DecisionModelUnavailable,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.memory.product import MemoryProductStore
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.memory.threading import ThreadAutoUpdateService
from tests.memory.test_contracts import memory
from tests.memory.test_threading import event, remembered

NOW = datetime(2026, 9, 29, tzinfo=UTC)


class _ChoiceBackend:
    def __init__(self, selected: str) -> None:
        self.selected = selected
        self.calls: list[DecisionRequest] = []

    @property
    def backend_name(self) -> str:
        return "thread-choice-fixture"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        self.calls.append(request)
        question = request.questions[0]
        probabilities = {
            option: (
                0.90 if option == self.selected else
                0.10 / max(1, len(question.options) - 1)
            )
            for option in question.options
        }
        return DecisionResult(
            backend=self.backend_name,
            model_version="fixture-v1",
            answers=(
                DecisionAnswer(
                    question_id=question.question_id,
                    kind=DecisionKind.CHOICE,
                    probabilities=probabilities,
                    selected=self.selected,
                ),
            ),
        )


class _OfflineBackend:
    @property
    def backend_name(self) -> str:
        return "offline"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        del request
        raise DecisionModelUnavailable("offline")


def _plane(
    tmp_path: Path,
) -> tuple[CanonicalMemoryStore, MemoryProductStore]:
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
                "The battery is becoming unbearable.",
                "e2",
                "o2",
            ),
            remembered(
                "m3",
                "I am comparing M4 benchmark results.",
                "e3",
                "o3",
            ),
            remembered(
                "m4",
                "I am deciding whether to move apartments.",
                "e4",
                "o4",
            ),
        )
    )
    product = MemoryProductStore(path, canonical)
    return canonical, product


def test_low_lexical_continuation_can_reuse_existing_thread(
    tmp_path: Path,
) -> None:
    canonical, product = _plane(tmp_path)
    product.open_thread(
        thread_id="laptop-purchase",
        scope=memory().scope,
        open_question="Will I replace my laptop?",
        supporting_memory_ids=("m1",),
        at=NOW,
        working_summary="A replacement purchase remains undecided.",
    )
    backend = _ChoiceBackend("thread_0")
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        decision=DecisionCapability(backend),
    )

    changed = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="low-lexical",
                refs=("e2",),
                action="track",
                question="Should I finally get the M4?",
                summary="Battery pain is making the purchase urgent.",
            ),
        ),
        at=NOW,
    )

    assert changed[0].thread_id == "laptop-purchase"
    assert len(product.list_threads(memory().scope)) == 1
    assert len(backend.calls) == 1
    service.close()


def test_same_entity_distinct_intent_may_choose_none_and_open_new_thread(
    tmp_path: Path,
) -> None:
    canonical, product = _plane(tmp_path)
    product.open_thread(
        thread_id="laptop-purchase",
        scope=memory().scope,
        open_question="Will I buy the M4 laptop?",
        supporting_memory_ids=("m1",),
        at=NOW,
        working_summary="The M4 purchase remains undecided.",
    )
    backend = _ChoiceBackend("none")
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        decision=DecisionCapability(backend),
    )

    changed = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="benchmarks",
                refs=("e3",),
                action="track",
                question="Does the M4 benchmark affect purchase?",
                summary="Technical benchmark comparison is a separate task.",
            ),
        ),
        at=NOW,
    )

    assert changed[0].thread_id != "laptop-purchase"
    assert len(product.list_threads(memory().scope)) == 2
    assert len(backend.calls) == 1
    service.close()


def test_decision_plane_disambiguates_two_competing_threads(
    tmp_path: Path,
) -> None:
    canonical, product = _plane(tmp_path)
    product.open_thread(
        thread_id="laptop-purchase",
        scope=memory().scope,
        open_question="Will I replace my laptop?",
        supporting_memory_ids=("m1",),
        at=NOW,
        working_summary="Purchase decision remains open.",
    )
    product.open_thread(
        thread_id="move-home",
        scope=memory().scope,
        open_question="Will I move apartments?",
        supporting_memory_ids=("m4",),
        at=NOW,
        working_summary="Housing move decision remains open.",
    )
    backend = _ChoiceBackend("thread_1")
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        decision=DecisionCapability(backend),
    )

    changed = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="ambiguous",
                refs=("e2",),
                action="track",
                question="Should I finally make the change?",
                summary="The unresolved decision is becoming urgent.",
            ),
        ),
        at=NOW,
    )

    assert changed[0].thread_id == "move-home"
    assert len(product.list_threads(memory().scope)) == 2
    service.close()


def test_unavailable_decision_preserves_baseline_new_thread_behavior(
    tmp_path: Path,
) -> None:
    canonical, product = _plane(tmp_path)
    product.open_thread(
        thread_id="laptop-purchase",
        scope=memory().scope,
        open_question="Will I replace my laptop?",
        supporting_memory_ids=("m1",),
        at=NOW,
        working_summary="A replacement purchase remains undecided.",
    )
    service = ThreadAutoUpdateService(
        canonical=canonical,
        product=product,
        decision=DecisionCapability(_OfflineBackend()),
    )

    changed = service.apply(
        scope=memory().scope,
        accepted_events=(
            event(
                candidate_id="weak",
                refs=("e2",),
                action="track",
                question="Should I finally get the M4?",
                summary="Battery pain is making the purchase urgent.",
            ),
        ),
        at=NOW,
    )

    assert changed[0].thread_id != "laptop-purchase"
    assert len(product.list_threads(memory().scope)) == 2
    service.close()
