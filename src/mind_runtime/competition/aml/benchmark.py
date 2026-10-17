"""Budget-sweep helpers for public-development benchmark runs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from mind_runtime.competition.aml.contracts import (
    AmlSearchItem,
    AmlSearchRequest,
)

DEFAULT_K_VALUES = (5, 10, 20, 30, 50, 70, 100)


@dataclass(frozen=True, slots=True)
class BudgetCurvePoint:
    k: int
    score: float
    returned_items: int
    returned_characters: int


SearchFunction = Callable[
    [AmlSearchRequest],
    tuple[AmlSearchItem, ...],
]
SearchScorer = Callable[
    [AmlSearchRequest, tuple[AmlSearchItem, ...]],
    float,
]


def run_k_sweep(
    search: SearchFunction,
    requests: Iterable[AmlSearchRequest],
    *,
    scorer: SearchScorer,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> tuple[tuple[BudgetCurvePoint, ...], ...]:
    if (
        not k_values
        or tuple(sorted(set(k_values))) != k_values
        or any(type(k) is not int or not 1 <= k <= 100 for k in k_values)
    ):
        raise ValueError(
            "k_values must be unique ascending integers in [1, 100]"
        )
    curves: list[tuple[BudgetCurvePoint, ...]] = []
    for request in requests:
        points = []
        for k in k_values:
            bounded = replace(request, top_k=k)
            results = search(bounded)
            points.append(
                BudgetCurvePoint(
                    k=k,
                    score=float(scorer(bounded, results)),
                    returned_items=len(results),
                    returned_characters=sum(
                        len(item.content) for item in results
                    ),
                )
            )
        curves.append(tuple(points))
    return tuple(curves)


def minimum_k_at_fraction(
    points: tuple[BudgetCurvePoint, ...],
    *,
    fraction: float = 0.95,
) -> int | None:
    if not points:
        return None
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not 0 < float(fraction) <= 1
    ):
        raise ValueError("fraction must be in (0, 1]")
    target = max(point.score for point in points) * float(fraction)
    for point in sorted(points, key=lambda item: item.k):
        if point.score >= target:
            return point.k
    return None
