from __future__ import annotations

from pathlib import Path

from mind_runtime.aml.benchmark import (
    minimum_characters_at_fraction,
    minimum_k_at_fraction,
    run_k_sweep,
)
from mind_runtime.aml.contracts import (
    AmlAddRequest,
    AmlMessage,
    AmlRuntimeConfig,
    AmlSearchRequest,
)
from mind_runtime.aml.runtime import AmlMemoryRuntime


def test_budget_curve_measures_smallest_sufficient_context(tmp_path: Path) -> None:
    runtime = AmlMemoryRuntime(
        tmp_path,
        config=AmlRuntimeConfig(
            result_cap=100,
            candidate_limit=100,
            thread_enabled=False,
            lce_enabled=False,
        ),
    )
    runtime.add(
        AmlAddRequest(
            request_id="r1",
            user_id="u1",
            session_id="s1",
            messages=(
                AmlMessage("user", "alpha target fact"),
                AmlMessage("user", "beta distractor"),
            ),
        )
    )
    request = AmlSearchRequest(
        user_id="u1",
        query="alpha",
        top_k=100,
    )

    def score(
        _: AmlSearchRequest,
        results: tuple[object, ...],
    ) -> float:
        return 1.0 if any(
            "alpha target fact" in getattr(item, "content", "")
            for item in results
        ) else 0.0

    curves = run_k_sweep(
        runtime,
        (request,),
        scorer=score,  # type: ignore[arg-type]
        k_values=(1, 2),
    )
    assert len(curves) == 1
    assert minimum_k_at_fraction(curves[0].points) == 1
    assert minimum_characters_at_fraction(curves[0].points) is not None
