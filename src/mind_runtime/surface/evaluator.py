"""Closed AST Evaluator for Candidate Recipe v2.

Pure, deterministic evaluation of AST expressions.
No eval, no lambdas, no I/O, no hidden dependencies.
Allowed primitives: const, lookup, add, sub, mul, clamp.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

D_PREFIX = "agent.affect."
P_PREFIX = "persona.behavioral_disposition."
ALLOWED_OPS = {"const", "lookup", "add", "sub", "mul", "clamp"}


def eval_ast(
    node: list[Any] | tuple[Any, ...],
    states: Mapping[str, Any],
    traits: Mapping[str, Any],
) -> float:
    """Evaluate an AST expression node against given dynamics states and disposition traits."""
    if not isinstance(node, (list, tuple)) or len(node) == 0:
        raise ValueError(f"invalid AST node: {node}")

    op = node[0]
    if op == "const":
        if len(node) != 2:
            raise ValueError(f"invalid const node: {node}")
        return float(node[1])

    if op == "lookup":
        if len(node) != 2:
            raise ValueError(f"invalid lookup node: {node}")
        path = str(node[1])
        if path.startswith(D_PREFIX):
            if path not in states:
                raise KeyError(f"missing dynamics state: {path}")
            st = states[path]
            val = st.get("value") if isinstance(st, Mapping) else getattr(st, "value", None)
            return float(val)
        if path.startswith(P_PREFIX):
            trait_name = path[len(P_PREFIX) :]
            if trait_name not in traits:
                raise KeyError(f"missing persona disposition trait: {trait_name}")
            return float(traits[trait_name])
        raise ValueError(f"unknown lookup prefix: {path}")

    if op == "add":
        if len(node) != 3:
            raise ValueError(f"invalid add node: {node}")
        return eval_ast(node[1], states, traits) + eval_ast(node[2], states, traits)

    if op == "sub":
        if len(node) != 3:
            raise ValueError(f"invalid sub node: {node}")
        return eval_ast(node[1], states, traits) - eval_ast(node[2], states, traits)

    if op == "mul":
        if len(node) != 3:
            raise ValueError(f"invalid mul node: {node}")
        return eval_ast(node[1], states, traits) * eval_ast(node[2], states, traits)

    if op == "clamp":
        if len(node) != 4:
            raise ValueError(f"invalid clamp node: {node}")
        raw = eval_ast(node[1], states, traits)
        lo = eval_ast(node[2], states, traits)
        hi = eval_ast(node[3], states, traits)
        val = max(lo, min(hi, raw))
        if val == 0.0:
            val = 0.0
        return val

    raise ValueError(f"unsupported AST operator: {op}")


def extract_ast_lookups(node: Any) -> set[str]:
    """Recursively extract all lookup paths present in an AST."""
    if not isinstance(node, (list, tuple)) or len(node) == 0:
        return set()
    op = node[0]
    if op == "lookup":
        return {str(node[1])}
    lookups: set[str] = set()
    for child in node[1:]:
        lookups.update(extract_ast_lookups(child))
    return lookups


def validate_ast_primitives(node: Any) -> bool:
    """Verify that an AST uses only the declared allowed primitives."""
    if not isinstance(node, (list, tuple)) or len(node) == 0:
        return False
    op = node[0]
    if op not in ALLOWED_OPS:
        return False
    if op == "const":
        return (
            len(node) == 2
            and isinstance(node[1], (int, float))
            and not isinstance(node[1], bool)
        )
    if op == "lookup":
        return len(node) == 2 and isinstance(node[1], str)
    if op in ("add", "sub", "mul"):
        return (
            len(node) == 3
            and validate_ast_primitives(node[1])
            and validate_ast_primitives(node[2])
        )
    if op == "clamp":
        return (
            len(node) == 4
            and validate_ast_primitives(node[1])
            and validate_ast_primitives(node[2])
            and validate_ast_primitives(node[3])
        )
    return False
