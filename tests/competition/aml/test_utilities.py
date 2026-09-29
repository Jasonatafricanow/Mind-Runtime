from __future__ import annotations

from pathlib import Path

from mind_runtime.competition.aml.benchmark import (
    minimum_k_at_fraction,
    run_k_sweep,
)
from mind_runtime.competition.aml.contracts import (
    AmlSearchItem,
    AmlSearchRequest,
)
from mind_runtime.competition.aml.namespace import (
    delete_run_namespace,
    run_root,
)


def test_run_namespace_is_addressed_and_deletable(tmp_path: Path) -> None:
    root = run_root(tmp_path, "eval-run-1")
    root.mkdir(parents=True)
    (root / "data.sqlite").write_text("x")
    assert delete_run_namespace(tmp_path, "eval-run-1") is True
    assert root.exists() is False
    assert delete_run_namespace(tmp_path, "eval-run-1") is False


def test_k_sweep_finds_smallest_sufficient_budget() -> None:
    request = AmlSearchRequest("u", "q", 100)

    def search(current: AmlSearchRequest) -> tuple[AmlSearchItem, ...]:
        return tuple(
            AmlSearchItem(
                item_id=f"m-{index}",
                content="target" if index == 0 else "noise",
                score=1.0 / (index + 1),
                created_at="2026-01-01T00:00:00+00:00",
                layer="memory",
            )
            for index in range(current.top_k)
        )

    def score(
        current: AmlSearchRequest,
        results: tuple[AmlSearchItem, ...],
    ) -> float:
        del current
        return 1.0 if any(
            item.content == "target" for item in results
        ) else 0.0

    curves = run_k_sweep(
        search,
        (request,),
        scorer=score,
        k_values=(1, 2, 5),
    )
    assert minimum_k_at_fraction(curves[0]) == 1
