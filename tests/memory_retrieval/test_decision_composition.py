from __future__ import annotations

from dataclasses import replace

from mind_runtime.decision import (
    DecisionAnswer,
    DecisionCapability,
    DecisionKind,
    DecisionRequest,
    DecisionResult,
)
from mind_runtime.memory.retrieval_composition import build_memory_history
from mind_runtime.memory.store import CanonicalMemoryStore
from mind_runtime.runtime_binding import bind_storage
from tests.host.test_runtime_binding import lab_binding
from tests.memory.test_contracts import memory
from tests.memory_retrieval.test_history import inputs
from tests.memory_retrieval.test_retrieval import ScriptedProvider, candidate


class SharedHistoryDecisionBackend:
    @property
    def backend_name(self) -> str:
        return "history-fixture"

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        assert request.feature == "memory.retrieval.rerank"
        answers = []
        for question in request.questions:
            index = int(question.question_id.rsplit("_", 1)[1])
            content = request.state[f"candidate_{index}"]
            yes = 0.95 if "price" in content else 0.05
            answers.append(
                DecisionAnswer(
                    question.question_id,
                    DecisionKind.BOOLEAN,
                    {"false": 1.0 - yes, "true": yes},
                    selected="true" if yes >= 0.5 else "false",
                )
            )
        return DecisionResult(
            backend=self.backend_name,
            model_version="fixture-v1",
            answers=tuple(answers),
        )


def test_history_composition_injects_one_shared_decision_capability(tmp_path) -> None:
    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("decision-history")
    paths = bind_storage(binding, **roots)

    first = memory()
    second = replace(
        first,
        memory_id="memory-2",
        content="M4 price dropped enough to reconsider the purchase",
        sync=replace(
            first.sync,
            object_id="memory-2",
            idempotency_key="memory-2",
        ),
    )
    store = CanonicalMemoryStore(paths.memory_db)
    store._commit((first, second))
    store.close()

    provider = ScriptedProvider((candidate("memory-1"), candidate("memory-2")))
    decision = DecisionCapability(SharedHistoryDecisionBackend())
    port = build_memory_history(
        binding,
        provider=provider,
        decision=decision,
        **roots,
    )

    bundle = port.read(**inputs())
    assert bundle is not None
    assert [item.external_id for item in bundle.episodes] == [
        "memory-2",
        "memory-1",
    ]


def test_history_composition_without_decision_preserves_provider_order(tmp_path) -> None:
    roots = dict(production_root=tmp_path / "prod", lab_root=tmp_path / "lab")
    binding = lab_binding("baseline-history")
    paths = bind_storage(binding, **roots)

    first = memory()
    second = replace(
        first,
        memory_id="memory-2",
        content="M4 price dropped enough to reconsider the purchase",
        sync=replace(
            first.sync,
            object_id="memory-2",
            idempotency_key="memory-2",
        ),
    )
    store = CanonicalMemoryStore(paths.memory_db)
    store._commit((first, second))
    store.close()

    port = build_memory_history(
        binding,
        provider=ScriptedProvider((candidate("memory-1"), candidate("memory-2"))),
        **roots,
    )
    bundle = port.read(**inputs())
    assert bundle is not None
    assert [item.external_id for item in bundle.episodes] == [
        "memory-1",
        "memory-2",
    ]
