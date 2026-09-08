"""Deterministic canonical state identifiers (D4)."""


def canonical_state_id(dimension: str, version: int) -> str:
    """Return the deterministic state id for a dimension version.

    Every canonical state record of a dimension uses
    ``<dimension>:<version>`` so identical inputs replay to identical ids
    (D4 merge gate: fake clock replay consistent).
    """
    return f"{dimension}:{version}"
