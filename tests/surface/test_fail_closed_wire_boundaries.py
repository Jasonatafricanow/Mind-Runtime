"""W3 migration checks for malformed wires at Surface authority boundaries."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from mind_runtime.expression.expression_map import (
    canonical_surface_wire,
    evaluate_control_band,
    map_surface_to_qualitative_guidance,
)
from mind_runtime.surface.evaluator import (
    eval_ast,
    extract_ast_lookups,
    validate_ast_primitives,
)
from tests.surface.spec_support import bind_persona, expect_error, sample_candidate


@pytest.mark.parametrize(
    ("node", "error"),
    [
        (["lookup", "other.root"], ValueError),
        (["lookup", "agent.affect.absent"], KeyError),
        (["lookup", "persona.behavioral_disposition.absent"], KeyError),
        (["unapproved", ["const", 1.0]], ValueError),
    ],
)
def test_closed_ast_rejects_malformed_or_unowned_roots(node, error):
    with pytest.raises(error):
        eval_ast(node, {}, {})


def test_closed_ast_evaluates_only_declared_primitives():
    states = {"agent.affect.anger": {"value": 0.4}}
    traits = {"expressive_restraint": 0.2}
    expression = [
        "clamp",
        [
            "sub",
            ["add", ["lookup", "agent.affect.anger"], ["const", 0.3]],
            [
                "mul",
                ["lookup", "persona.behavioral_disposition.expressive_restraint"],
                ["const", 0.5],
            ],
        ],
        ["const", 0.0],
        ["const", 1.0],
    ]
    assert validate_ast_primitives(expression)
    assert extract_ast_lookups(expression) == {
        "agent.affect.anger",
        "persona.behavioral_disposition.expressive_restraint",
    }
    assert eval_ast(expression, states, traits) == pytest.approx(0.6)
    assert (
        eval_ast(
            ["lookup", "agent.affect.anger"], {"agent.affect.anger": SimpleNamespace(value=0.4)}, {}
        )
        == 0.4
    )
    with pytest.raises(ValueError, match="missing dynamics value"):
        eval_ast(["lookup", "agent.affect.anger"], {"agent.affect.anger": {}}, {})
    assert eval_ast(["clamp", ["const", -1.0], ["const", 0.0], ["const", 1.0]], {}, {}) == 0.0


@pytest.mark.parametrize(
    "node",
    [
        None,
        [],
        ["unknown", ["const", 1.0]],
        ["const", True],
        ["const", "1"],
        ["const"],
        ["lookup", 1],
        ["lookup", "x", "y"],
        ["add", ["const", 1.0]],
        ["sub", ["const", 1.0], ["unknown"]],
        ["mul", ["const", 1.0], ["lookup", 1]],
        ["clamp", ["const", 1.0], ["const", 0.0]],
        ["clamp", ["const", 1.0], ["const", 0.0], ["unknown"]],
    ],
)
def test_ast_admission_rejects_invalid_shapes(node):
    assert validate_ast_primitives(node) is False
    if node is None or node == []:
        assert extract_ast_lookups(node) == set()


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("runtime_id",), "", "SURFACE_LINEAGE_MISMATCH"),
        (("scope", "domain"), "user", "SURFACE_SCOPE_MISMATCH"),
        (("owner", "owner_persona_id"), "other", "SURFACE_PERSONA_BINDING_MISMATCH"),
        (("projected_dynamics", "source_projection_id"), "", "SURFACE_SOURCE_PROJECTION_MISMATCH"),
        (("projected_dynamics", "source_phase"), "forged", "SURFACE_SOURCE_PHASE_INVALID"),
        (("recipe_bindings",), [], "SURFACE_RECIPE_BINDING_MISMATCH"),
        (("projected_dynamics", "states", 0, "state_id"), "", "SURFACE_STATE_AUTHORITY_MISMATCH"),
        (
            ("projected_dynamics", "states", 0, "value_type"),
            "categorical",
            "SURFACE_STATE_DEFINITION_MISMATCH",
        ),
        (
            ("projected_dynamics", "states", 0, "bounds"),
            [0, 2],
            "SURFACE_STATE_DEFINITION_MISMATCH",
        ),
        (("persona", "content", "schema_version"), 1, "SURFACE_INELIGIBLE_PERSONA"),
        (("projected_dynamics",), None, "SURFACE_MISSING_STATE"),
        (("recipe",), None, "SURFACE_RECIPE_UNSUPPORTED"),
    ],
)
def test_surface_rejects_wrong_authority_or_wire(surface, path, value, reason):
    wire = sample_candidate()
    target = wire
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    expect_error(surface, wire, reason)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("version", True, "SURFACE_STATE_AUTHORITY_MISMATCH"),
        ("value", True, "SURFACE_NUMERIC_TYPE"),
        ("value", 1.1, "SURFACE_RANGE"),
    ],
)
def test_surface_rejects_malformed_state(surface, field, value, reason):
    wire = sample_candidate()
    wire["projected_dynamics"]["states"][0][field] = value
    expect_error(surface, wire, reason)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("scope",), None, "SURFACE_LINEAGE_MISMATCH"),
        (("persona",), None, "SURFACE_INELIGIBLE_PERSONA"),
        (("projected_dynamics", "states"), (), "SURFACE_STATE_DEFINITION_MISMATCH"),
        (("projected_dynamics", "states", 0), None, "SURFACE_STATE_AUTHORITY_MISMATCH"),
        (
            ("projected_dynamics", "states", 0, "dimension"),
            "agent.affect.unknown",
            "SURFACE_STATE_DEFINITION_MISMATCH",
        ),
    ],
)
def test_surface_rejects_structural_authority_gaps(surface, path, value, reason):
    wire = sample_candidate()
    target = wire
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    expect_error(surface, wire, reason)


def test_surface_rejects_duplicate_state_identity(surface):
    wire = sample_candidate()
    wire["projected_dynamics"]["states"].append(deepcopy(wire["projected_dynamics"]["states"][0]))
    expect_error(surface, wire, "SURFACE_STATE_AUTHORITY_MISMATCH")


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("high", "SURFACE_NUMERIC_TYPE"),
        (1.5, "SURFACE_RANGE"),
    ],
)
def test_surface_rejects_malformed_published_disposition(surface, value, reason):
    wire = sample_candidate()
    wire["persona"]["content"]["behavioral_disposition"]["attachment_approach"] = value
    bind_persona(wire)
    expect_error(surface, wire, reason)


def test_surface_rejects_missing_published_disposition_trait(surface):
    wire = sample_candidate()
    del wire["persona"]["content"]["behavioral_disposition"]["attachment_approach"]
    bind_persona(wire)
    expect_error(surface, wire, "SURFACE_INELIGIBLE_PERSONA")


def test_surface_rejects_non_mapping_input(surface):
    result = surface.project(None)
    assert result.status == "UNAVAILABLE"
    assert tuple(result.reasons) == ("SURFACE_SCHEMA_MISMATCH",)


@pytest.mark.parametrize("value", [object(), float("nan"), {1: "value"}])
def test_surface_canonical_wire_rejects_unserializable_values(value):
    with pytest.raises((TypeError, ValueError)):
        canonical_surface_wire(value)


@pytest.mark.parametrize("value", [True, float("nan"), -0.1])
def test_expression_band_rejects_invalid_controls(value):
    with pytest.raises((TypeError, ValueError)):
        evaluate_control_band(value)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("status", "UNAVAILABLE", "not AVAILABLE"),
        ("controls", None, "controls block missing"),
        ("recipe_id", "other", "recipe mismatch"),
        ("values", None, "values mapping missing"),
    ],
)
def test_expression_consumer_rejects_unavailable_or_wrong_lineage(surface, field, value, error):
    result = surface.project(sample_candidate())
    wire = {"status": "AVAILABLE", "controls": dict(result.controls)}
    if field in wire:
        wire[field] = value
    else:
        wire["controls"][field] = value
    with pytest.raises(ValueError, match=error):
        map_surface_to_qualitative_guidance(wire)


def test_expression_consumer_rejects_missing_control(surface):
    result = surface.project(sample_candidate())
    controls = dict(result.controls)
    controls["values"] = deepcopy(dict(controls["values"]))
    del controls["values"]["confrontation"]
    with pytest.raises(ValueError, match="control .* missing"):
        map_surface_to_qualitative_guidance({"status": "AVAILABLE", "controls": controls})
