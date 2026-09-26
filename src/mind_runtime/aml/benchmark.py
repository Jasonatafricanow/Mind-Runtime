"""Small benchmark harness for context-budget ablations.

This module deliberately knows nothing about AML gold labels. Public benchmark
adapters may supply a scorer; Full evaluation remains external and blind.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from mind_runtime.aml.contracts import AmlSearchItem, AmlSearchRequest
from mind_runtime.aml.runtime import AmlMemoryRuntime

DEFAULT_K_VALUES = (5, 10, 20, 30, 50, 70, 100)


@dataclass(frozen=True, slots=True)
class BudgetCurvePoint:
    k: int
    score: float
    returned_items: int
    returned_characters: int

    def __post_init__(self) -> None:
        if type(self.k) is not int or self.k < 1:
            raise ValueError("k must be a positive integer")
        if isinstance(self.score, bool) or not isinstance(
            self.score, (int, float)
        ):
            raise TypeError("score must be numeric")
        if (
            type(self.returned_items) is not int
            or self.returned_items < 0
            or type(self.returned_characters) is not int
            or self.returned_characters < 0
        ):
            raise ValueError("returned budget values must be nonnegative")


@dataclass(frozen=True, slots=True)
class QueryBudgetCurve:
    user_id: str
    query: str
    points: tuple[BudgetCurvePoint, ...]


SearchScorer = Callable[
    [AmlSearchRequest, tuple[AmlSearchItem, ...]],
    float,
]


def run_k_sweep(
    runtime: AmlMemoryRuntime,
    requests: Iterable[AmlSearchRequest],
    *,
    scorer: SearchScorer,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> tuple[QueryBudgetCurve, ...]:
    if (
        not k_values
        or tuple(sorted(set(k_values))) != k_values
        or any(type(k) is not int or not 1 <= k <= 100 for k in k_values)
    ):
        raise ValueError(
            "k_values must be unique ascending integers in [1, 100]"
        )
    curves: list[QueryBudgetCurve] = []
    for request in requests:
        points = []
        for k in k_values:
            bounded = replace(request, top_k=k)
            results = runtime.search(bounded)
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
        curves.append(
            QueryBudgetCurve(
                user_id=request.user_id,
                query=request.query,
                points=tuple(points),
            )
        )
    return tuple(curves)


def minimum_k_at_fraction(
    points: tuple[BudgetCurvePoint, ...],
    *,
    fraction: float = 0.95,
) -> int | None:
    """Return the smallest K reaching a fraction of this curve's best score."""
    if not points:
        return None
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not 0 < float(fraction) <= 1
    ):
        raise ValueError("fraction must be in (0, 1]")
    best = max(point.score for point in points)
    target = best * float(fraction)
    for point in sorted(points, key=lambda item: item.k):
        if point.score >= target:
            return point.k
    return None


def minimum_characters_at_fraction(
    points: tuple[BudgetCurvePoint, ...],
    *,
    fraction: float = 0.95,
) -> int | None:
    """Character-budget proxy for Token@95 without tokenizer coupling."""
    if not points:
        return None
    best = max(point.score for point in points)
    target = best * float(fraction)
    eligible = [
        point.returned_characters
        for point in points
        if point.score >= target
    ]
    return min(eligible) if eligible else None
