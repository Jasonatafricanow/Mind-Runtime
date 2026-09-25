"""Test-only wire fixtures, digest oracle, and static expected vectors.

NO formula evaluation is provided here. ASTs are pure data.
This module is not a Persona loader, not a Surface projector, and not a production authority.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal, Protocol, TypedDict

D = "agent.affect."
P = "persona.behavioral_disposition."

MANIFEST = {
    "contact_seeking": {
        "dynamics": [D + n for n in ("anger", "closeness_craving", "longing")],
        "disposition": [P + n for n in ("attachment_approach", "expressive_restraint")],
    },
    "initiative": {
        "dynamics": [D + n for n in ("curiosity", "sadness", "sharing_urge")],
        "disposition": [],
    },
    "confrontation": {
        "dynamics": [D + "anger"],
        "disposition": [P + n for n in ("confrontation_readiness", "expressive_restraint")],
    },
    "expressive_warmth": {
        "dynamics": [D + n for n in ("anger", "closeness_craving", "sadness")],
        "disposition": [P + "expressive_warmth_bias"],
    },
    "expressive_restraint": {
        "dynamics": [D + "diligence_pressure"],
        "disposition": [P + "expressive_restraint"],
    },
}
ENABLED = sorted(MANIFEST)
DEFERRED = ["reassurance_seeking", "withdrawal"]

CANDIDATE_RECIPE_ID = "surface-v1-candidate"
CANDIDATE_RECIPE_VERSION = 2
CANDIDATE_RECIPE_DIGEST = "4f37f46f89f6176fd5fefe0167ec7a81e341839f4fb9b98fa3cc348ddeaf9a55"

CANDIDATE_MAP_ID = "surface-v1-candidate-map"
CANDIDATE_MAP_VERSION = 2
CANDIDATE_MAP_DIGEST = "bba6794aeda7a1755f8c79ffe5c88bd100918e6bc979ea29b5aa009e958eddf3"

REFERENCE_RECIPE_ID = "surface-reference-v1"
REFERENCE_RECIPE_VERSION = 1
REFERENCE_RECIPE_DIGEST = "3ef6d193cbb8a72167fe12889a747ca007c58deb17f8d2c90e25c9215c124f30"
REFERENCE_PERSONA_DIGEST = "a0b8eb360c8f74f85d1f371c4d655d759d48c4f506783c13db69c739bf63436a"
REFERENCE_DEP_DIGEST = "5d727ddea4e0d033b91df9fba5d0d641fbb78acfea807b56f8a780d07c53aa8a"

PERSONA_A_DIGEST = "a828cb3c92aa9f88c9370f6eda4c6da8443b2d19339bbe745eff48830d55e1a9"
PERSONA_B_DIGEST = "a725d748712dc7d6a5ea4d75ca1a6fd696d7de7d04e8c538690fc00ff7b767f5"
DEP_A_DIGEST = "f32c0114a01f639a1c73055cc27202ec8cc136248c6df5a0d993bd0dd25a4dc1"
BASELINE_CONTROLS_ID = "surface:5805c1040170d4389c9656300e0cfb412026e7b0a19fa12f6a659b6df48aadc4"

# Statically frozen candidate vectors (LITERALS ONLY, no algorithmic derivation in tests)
STATIC_BASELINE_CONTROLS = {
    "contact_seeking": 0.500,
    "initiative": 0.560,
    "confrontation": 0.290,
    "expressive_warmth": 0.410,
    "expressive_restraint": 0.440,
}

STATIC_PERSONA_COUNTERFACTUAL_CONTROLS = {
    "contact_seeking": 0.650,
    "initiative": 0.560,  # initiative has no persona root in V1
    "confrontation": 0.500,
    "expressive_warmth": 0.575,
    "expressive_restraint": 0.215,
}

STATIC_ROOT_ISOLATION_CONTROLS: dict[str, dict[str, float]] = {
    "longing": {
        "contact_seeking": 0.590,
        "initiative": 0.560,
        "confrontation": 0.290,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.440,
    },
    "closeness_craving": {
        "contact_seeking": 0.570,
        "initiative": 0.560,
        "confrontation": 0.290,
        "expressive_warmth": 0.510,
        "expressive_restraint": 0.440,
    },
    "anger": {
        "contact_seeking": 0.460,
        "initiative": 0.560,
        "confrontation": 0.430,
        "expressive_warmth": 0.360,
        "expressive_restraint": 0.440,
    },
    "attachment_approach": {
        "contact_seeking": 0.560,
        "initiative": 0.560,
        "confrontation": 0.290,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.440,
    },
    "expressive_restraint": {
        "contact_seeking": 0.460,
        "initiative": 0.560,
        "confrontation": 0.230,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.590,
    },
    "sharing_urge": {
        "contact_seeking": 0.500,
        "initiative": 0.680,
        "confrontation": 0.290,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.440,
    },
    "curiosity": {
        "contact_seeking": 0.500,
        "initiative": 0.660,
        "confrontation": 0.290,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.440,
    },
    "sadness": {
        "contact_seeking": 0.500,
        "initiative": 0.510,
        "confrontation": 0.290,
        "expressive_warmth": 0.370,
        "expressive_restraint": 0.440,
    },
    "confrontation_readiness": {
        "contact_seeking": 0.500,
        "initiative": 0.560,
        "confrontation": 0.370,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.440,
    },
    "expressive_warmth_bias": {
        "contact_seeking": 0.500,
        "initiative": 0.560,
        "confrontation": 0.290,
        "expressive_warmth": 0.520,
        "expressive_restraint": 0.440,
    },
    "diligence_pressure": {
        "contact_seeking": 0.500,
        "initiative": 0.560,
        "confrontation": 0.290,
        "expressive_warmth": 0.410,
        "expressive_restraint": 0.510,
    },
}

STATIC_BASELINE_EXPRESSION_BUNDLE = {
    "directness": "low",
    "warmth": "moderate",
    "restraint": "moderate",
}

STATIC_COUNTERFACTUAL_EXPRESSION_BUNDLE = {
    "directness": "moderate",
    "warmth": "moderate",
    "restraint": "low",
}

STATIC_PER_CONTROL_SATURATION = {
    "contact_seeking": {
        "upper": {"unclamped": 1.10, "clamped": True, "value": 1.0},
        "lower": {"unclamped": -0.40, "clamped": True, "value": 0.0},
    },
    "initiative": {
        "upper": {"unclamped": 1.10, "clamped": True, "value": 1.0},
        "lower": {"unclamped": -0.25, "clamped": True, "value": 0.0},
    },
    "confrontation": {
        "upper": {"unclamped": 1.10, "clamped": True, "value": 1.0},
        "lower": {"unclamped": -0.30, "clamped": True, "value": 0.0},
    },
    "expressive_warmth": {
        "upper": {"unclamped": 1.05, "clamped": True, "value": 1.0},
        "lower": {"unclamped": -0.45, "clamped": True, "value": 0.0},
    },
    "expressive_restraint": {
        "upper": {"unclamped": 1.10, "clamped": True, "value": 1.0},
        "lower": {"unclamped": 0.00, "clamped": False, "value": 0.0},
    },
}


class StateFixture(TypedDict):
    dimension: str
    state_id: str
    version: int
    value: float
    bounds: list[float]
    value_type: Literal["scalar"]
    runtime_id: str
    scope: dict[str, Any]
    owner: dict[str, str]


class SurfaceProjectionInput(TypedDict):
    runtime_id: str
    scope: dict[str, Any]
    owner: dict[str, str]
    interaction_or_tick_ref: str
    evaluation_ref: str
    expected_source_projection_id: str
    persona: dict[str, Any]
    projected_dynamics: dict[str, Any]
    recipe: dict[str, Any]
    recipe_bindings: list[dict[str, Any]]


class SurfaceSpecAdapter(Protocol):
    """Test adapter protocol; production seam remains intentionally missing in W3-B0."""

    def project(self, supplied: SurfaceProjectionInput) -> dict[str, Any]: ...

    def restart_probe(self, directory: str, supplied: SurfaceProjectionInput) -> dict[str, Any]: ...

    def abort_probe(self, directory: str, supplied: SurfaceProjectionInput) -> dict[str, Any]: ...

    def forbidden_call_targets(self) -> dict[str, list[tuple[Any, str]]]: ...


def canonical(value: Any) -> bytes:
    """MR-surface-c14n-1 canonical wire serializer."""

    def wire(x: Any) -> Any:
        if type(x) is float:
            if not math.isfinite(x):
                raise ValueError("nonfinite")
            return {"$f64": (0.0 if x == 0 else x).hex()}
        if x is None or type(x) in (str, bool, int):
            return x
        if isinstance(x, (list, tuple)):
            return [wire(v) for v in x]
        if isinstance(x, Mapping) and all(type(k) is str for k in x):
            return {k: wire(v) for k, v in x.items()}
        raise TypeError(type(x))

    return json.dumps(
        wire(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def digest(domain: str, value: Any) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\n" + canonical(value)).hexdigest()


def const(x: float) -> list[Any]:
    return ["const", float(x)]


def ref(path: str) -> list[Any]:
    return ["lookup", path]


def op(name: str, a: Any, b: Any) -> list[Any]:
    return [name, a, b]


def term(coefficient: float, path: str) -> list[Any]:
    return op("mul", const(coefficient), ref(path))


def candidate_recipe() -> dict[str, Any]:
    add, sub = "add", "sub"
    raw = {
        "contact_seeking": op(
            sub,
            op(
                sub,
                op(
                    add,
                    op(add, term(0.45, D + "longing"), term(0.35, D + "closeness_craving")),
                    term(0.30, P + "attachment_approach"),
                ),
                term(0.20, D + "anger"),
            ),
            term(0.20, P + "expressive_restraint"),
        ),
        "initiative": op(
            sub,
            op(add, term(0.60, D + "sharing_urge"), term(0.50, D + "curiosity")),
            term(0.25, D + "sadness"),
        ),
        "confrontation": op(
            sub,
            op(add, term(0.70, D + "anger"), term(0.40, P + "confrontation_readiness")),
            term(0.30, P + "expressive_restraint"),
        ),
        "expressive_warmth": op(
            sub,
            op(
                sub,
                op(
                    add,
                    term(0.55, P + "expressive_warmth_bias"),
                    term(0.50, D + "closeness_craving"),
                ),
                term(0.25, D + "anger"),
            ),
            term(0.20, D + "sadness"),
        ),
        "expressive_restraint": op(
            add,
            term(0.75, P + "expressive_restraint"),
            term(0.35, D + "diligence_pressure"),
        ),
    }
    return {
        "projector_id": "surface-affect",
        "projector_version": 1,
        "recipe_id": CANDIDATE_RECIPE_ID,
        "recipe_version": CANDIDATE_RECIPE_VERSION,
        "status": "SURFACE_V1_CANDIDATE",
        "calibration_status": "UNREPORTED_CANDIDATE",
        "serialization": "MR-surface-c14n-1",
        "dependency_manifest": deepcopy(MANIFEST),
        "rules": [
            {
                "control_id": k,
                "range": [0.0, 1.0],
                "formula": ["clamp", raw[k], const(0.0), const(1.0)],
            }
            for k in ENABLED
        ],
    }


def candidate_expression_map() -> dict[str, Any]:
    return {
        "map_id": CANDIDATE_MAP_ID,
        "map_version": CANDIDATE_MAP_VERSION,
        "status": "SURFACE_V1_CANDIDATE",
        "supported_recipe_id": CANDIDATE_RECIPE_ID,
        "supported_recipe_version": CANDIDATE_RECIPE_VERSION,
        "supported_recipe_digest": CANDIDATE_RECIPE_DIGEST,
        "serialization": "MR-surface-c14n-1",
        "consumed_controls": ["confrontation", "expressive_restraint", "expressive_warmth"],
        "guidance_dimensions": {
            "directness": {
                "source_control": "confrontation",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
            "restraint": {
                "source_control": "expressive_restraint",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
            "warmth": {
                "source_control": "expressive_warmth",
                "bands": [
                    {"band": "low", "range": [0.0, 0.33]},
                    {"band": "moderate", "range": [0.33, 0.66]},
                    {"band": "high", "range": [0.66, 1.0]},
                ],
                "boundary_rule": "lower_closed_except_first_fully_closed_upper_closed",
            },
        },
    }


def reference_recipe() -> dict[str, Any]:
    """Historical reference recipe (surface-reference-v1). TEST_ONLY."""
    add, sub, mul = "add", "sub", "mul"
    raw = {
        "contact_seeking": op(
            mul,
            op(
                add,
                op(add, term(0.5, D + "longing"), term(0.3, D + "closeness_craving")),
                term(0.2, P + "attachment_approach"),
            ),
            op(sub, const(1.0), op(mul, term(0.5, D + "anger"), ref(P + "expressive_restraint"))),
        ),
        "initiative": op(
            add,
            op(add, term(0.4, D + "sharing_urge"), term(0.3, D + "curiosity")),
            op(mul, const(0.3), op(sub, const(1.0), ref(D + "sadness"))),
        ),
        "confrontation": op(
            mul,
            op(add, term(0.8, D + "anger"), term(0.2, P + "confrontation_readiness")),
            op(sub, const(1.0), term(0.6, P + "expressive_restraint")),
        ),
        "expressive_warmth": op(
            sub,
            op(
                sub,
                op(add, ref(P + "expressive_warmth_bias"), term(0.3, D + "closeness_craving")),
                term(0.4, D + "anger"),
            ),
            term(0.2, D + "sadness"),
        ),
        "expressive_restraint": op(
            add, ref(P + "expressive_restraint"), term(0.1, D + "diligence_pressure")
        ),
    }
    return {
        "projector_id": "surface-affect",
        "projector_version": 1,
        "recipe_id": REFERENCE_RECIPE_ID,
        "recipe_version": REFERENCE_RECIPE_VERSION,
        "status": "TEST_ONLY",
        "calibration_status": "PROVISIONAL",
        "serialization": "MR-surface-c14n-1",
        "dependency_manifest": deepcopy(MANIFEST),
        "rules": [
            {
                "control_id": k,
                "range": [0.0, 1.0],
                "formula": ["clamp", raw[k], const(0.0), const(1.0)],
            }
            for k in ENABLED
        ],
    }


def normalized_recipe(r: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(r)
    result["rules"].sort(key=lambda rule: rule["control_id"])
    for manifest in result["dependency_manifest"].values():
        manifest["dynamics"].sort()
        manifest["disposition"].sort()
    return result


def normalized_expression_map(m: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(m)
    result["consumed_controls"].sort()
    result["guidance_dimensions"] = {
        k: result["guidance_dimensions"][k] for k in sorted(result["guidance_dimensions"])
    }
    return result


def normalized_persona_content(content: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(content)
    result["dimensions"].sort(key=lambda item: item["dimension"])
    for dimension in result["dimensions"]:
        for pairs in ("growth_profile", "coupling_profile"):
            dimension[pairs].sort(key=lambda pair: pair[0])
    return result


def bind_persona(x: SurfaceProjectionInput) -> None:
    p = x["persona"]
    p["persona_content_digest"] = digest("persona", normalized_persona_content(p["content"]))
    x["projected_dynamics"]["persona_binding"] = {
        k: p[k] for k in ("persona_id", "persona_version", "persona_content_digest")
    }


def bind_recipe(x: SurfaceProjectionInput) -> None:
    r = normalized_recipe(x["recipe"])
    x["recipe_bindings"] = [
        {
            "recipe_id": r["recipe_id"],
            "recipe_version": r["recipe_version"],
            "recipe_digest": digest("recipe", r),
        }
    ]


def sample_candidate(persona_name: str = "persona-fixture-a") -> SurfaceProjectionInput:
    scope = {
        "domain": "agent",
        "agent_id": "fixture-persona",
        "persona_id": persona_name,
        "user_id": None,
        "relationship_id": None,
        "world_id": None,
        "interaction_id": None,
    }
    owner = {"owner_runtime_id": "fixture-runtime", "owner_persona_id": persona_name}
    vals = dict(
        longing=0.70,
        closeness_craving=0.50,
        anger=0.30,
        sharing_urge=0.60,
        curiosity=0.50,
        sadness=0.20,
        diligence_pressure=0.40,
        social_pull=0.20,
    )
    states: list[StateFixture] = [
        {
            "dimension": D + k,
            "state_id": "state-" + k,
            "version": 1,
            "value": v,
            "bounds": [0.0, 1.0],
            "value_type": "scalar",
            "runtime_id": "fixture-runtime",
            "scope": deepcopy(scope),
            "owner": deepcopy(owner),
        }
        for k, v in sorted(vals.items())
    ]
    if persona_name == "persona-fixture-b":
        disposition = {
            "attachment_approach": 0.80,
            "confrontation_readiness": 0.80,
            "expressive_restraint": 0.10,
            "expressive_warmth_bias": 0.80,
        }
    else:
        disposition = {
            "attachment_approach": 0.50,
            "confrontation_readiness": 0.50,
            "expressive_restraint": 0.40,
            "expressive_warmth_bias": 0.50,
        }
    content = {
        "schema_version": 2,
        "profile_version": 1,
        "persona_id": persona_name,
        "dimensions": [
            {
                "dimension": D + k,
                "baseline": 0.0,
                "initial_value": 0.0,
                "sensitivity": 1.0,
                "recovery_rate": 0.0,
                "floor": 0.0,
                "ceiling": 1.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
            for k in sorted(vals)
        ],
        "behavioral_disposition": disposition,
    }
    x: SurfaceProjectionInput = {
        "runtime_id": "fixture-runtime",
        "scope": scope,
        "owner": owner,
        "interaction_or_tick_ref": "interaction:fixture-1",
        "evaluation_ref": "eval:fixture-1",
        "expected_source_projection_id": "projection:fixture-1",
        "persona": {"persona_id": persona_name, "persona_version": 1, "content": content},
        "projected_dynamics": {
            "source_projection_id": "projection:fixture-1",
            "source_phase": "projected",
            "runtime_id": "fixture-runtime",
            "interaction_or_tick_ref": "interaction:fixture-1",
            "scope": deepcopy(scope),
            "owner": deepcopy(owner),
            "states": states,
        },
        "recipe": candidate_recipe(),
        "recipe_bindings": [],
    }
    bind_persona(x)
    bind_recipe(x)
    return x


def sample_reference() -> SurfaceProjectionInput:
    """Historical sample for reference-v1 fixture tests."""
    scope = {
        "domain": "agent",
        "agent_id": "fixture-persona",
        "persona_id": "fixture-persona",
        "user_id": None,
        "relationship_id": None,
        "world_id": None,
        "interaction_id": None,
    }
    owner = {"owner_runtime_id": "fixture-runtime", "owner_persona_id": "fixture-persona"}
    vals = dict(
        longing=0.8,
        closeness_craving=0.6,
        anger=0.0,
        sharing_urge=0.8,
        curiosity=0.7,
        sadness=0.1,
        diligence_pressure=0.4,
        social_pull=0.2,
    )
    states: list[StateFixture] = [
        {
            "dimension": D + k,
            "state_id": "state-" + k,
            "version": 1,
            "value": v,
            "bounds": [0.0, 1.0],
            "value_type": "scalar",
            "runtime_id": "fixture-runtime",
            "scope": deepcopy(scope),
            "owner": deepcopy(owner),
        }
        for k, v in sorted(vals.items())
    ]
    content = {
        "schema_version": 2,
        "profile_version": 1,
        "persona_id": "fixture-persona",
        "dimensions": [
            {
                "dimension": D + k,
                "baseline": 0.0,
                "initial_value": 0.0,
                "sensitivity": 1.0,
                "recovery_rate": 0.0,
                "floor": 0.0,
                "ceiling": 1.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
            for k in sorted(vals)
        ],
        "behavioral_disposition": {
            "attachment_approach": 0.2,
            "confrontation_readiness": 0.5,
            "expressive_restraint": 0.9,
            "expressive_warmth_bias": 0.4,
        },
    }
    x: SurfaceProjectionInput = {
        "runtime_id": "fixture-runtime",
        "scope": scope,
        "owner": owner,
        "interaction_or_tick_ref": "interaction:fixture-1",
        "evaluation_ref": "eval:fixture-1",
        "expected_source_projection_id": "projection:fixture-1",
        "persona": {"persona_id": "fixture-persona", "persona_version": 1, "content": content},
        "projected_dynamics": {
            "source_projection_id": "projection:fixture-1",
            "source_phase": "projected",
            "runtime_id": "fixture-runtime",
            "interaction_or_tick_ref": "interaction:fixture-1",
            "scope": deepcopy(scope),
            "owner": deepcopy(owner),
            "states": states,
        },
        "recipe": reference_recipe(),
        "recipe_bindings": [],
    }
    bind_persona(x)
    bind_recipe(x)
    return x


def state(x: SurfaceProjectionInput, name: str) -> StateFixture:
    return next(s for s in x["projected_dynamics"]["states"] if s["dimension"] == D + name)


def trait(x: SurfaceProjectionInput, name: str, value: float) -> None:
    x["persona"]["content"]["behavioral_disposition"][name] = value
    x["persona"]["persona_version"] += 1
    x["persona"]["content"]["profile_version"] += 1
    bind_persona(x)


def dependency_payload(x: SurfaceProjectionInput) -> dict[str, Any]:
    states = {s["dimension"]: s for s in x["projected_dynamics"]["states"]}
    traits = x["persona"]["content"]["behavioral_disposition"]
    return {
        k: {
            "dynamics": [
                {
                    f: states[d][f]
                    for f in ("dimension", "state_id", "version", "value", "bounds", "value_type")
                }
                for d in sorted(m["dynamics"])
            ],
            "disposition": [[p, traits[p.removeprefix(P)]] for p in sorted(m["disposition"])],
        }
        for k, m in sorted(MANIFEST.items())
    }


def expect_ok(adapter: SurfaceSpecAdapter, x: SurfaceProjectionInput) -> dict[str, Any]:
    result = adapter.project(x)
    assert set(result) == {"status", "reasons", "controls"}
    assert result["status"] == "AVAILABLE"
    assert tuple(result["reasons"]) == ()
    out = result["controls"]
    assert set(out) == {
        "controls_id",
        "runtime_id",
        "scope",
        "owner",
        "interaction_or_tick_ref",
        "persona_id",
        "persona_version",
        "persona_content_digest",
        "source_projection_id",
        "source_phase",
        "source_states",
        "projector_id",
        "projector_version",
        "recipe_id",
        "recipe_version",
        "recipe_digest",
        "dependency_digest",
        "dependency_digests_by_control",
        "values",
        "dependencies_by_control",
        "evaluation_ref",
        "audit",
        "derived_only",
        "canonical",
    }
    assert sorted(out["values"]) == ENABLED
    assert out["dependencies_by_control"] == MANIFEST
    assert out["recipe_digest"] == digest("recipe", normalized_recipe(x["recipe"]))
    payload = dependency_payload(x)
    assert out["dependency_digest"] == digest("dependencies", payload)
    assert out["dependency_digests_by_control"] == {
        k: digest("control-dependencies", v) for k, v in payload.items()
    }
    for k in ("runtime_id", "scope", "owner", "interaction_or_tick_ref", "evaluation_ref"):
        assert out[k] == x[k]
    for k in ("persona_id", "persona_version", "persona_content_digest"):
        assert out[k] == x["persona"][k]
    for k in ("source_projection_id", "source_phase"):
        assert out[k] == x["projected_dynamics"][k]
    for k in ("projector_id", "projector_version", "recipe_id", "recipe_version"):
        assert out[k] == x["recipe"][k]
    roots = sorted({d for m in MANIFEST.values() for d in m["dynamics"]})
    sources = {s["dimension"]: s for s in x["projected_dynamics"]["states"]}
    assert out["source_states"] == [
        {
            "dimension": d,
            "state_id": sources[d]["state_id"],
            "version": sources[d]["version"],
            "value_digest": digest("state-value", sources[d]["value"]),
        }
        for d in roots
    ]
    assert out["derived_only"] is True
    assert out["canonical"] is False
    assert sorted(out["audit"]) == ENABLED
    for k, v in out["values"].items():
        assert type(v) is float and math.isfinite(v) and 0.0 <= v <= 1.0
        trace = out["audit"][k]
        assert set(trace) == {"unclamped", "clamped"}
        raw = trace["unclamped"]
        assert type(raw) is float and math.isfinite(raw)
        assert trace["clamped"] is (raw < 0.0 or raw > 1.0)
        assert v == max(0.0, min(1.0, raw))
        if v == 0.0:
            assert math.copysign(1.0, v) == 1.0
    semantic = {k: v for k, v in out.items() if k not in ("controls_id", "evaluation_ref")}
    assert out["controls_id"] == "surface:" + digest("controls", semantic)
    return out


def expect_error(adapter: SurfaceSpecAdapter, x: SurfaceProjectionInput, code: str) -> None:
    result = adapter.project(x)
    assert result["status"] == "UNAVAILABLE"
    assert tuple(result["reasons"]) == (code,)
    assert result["controls"] is None


class HistoricalReferenceEvaluator:
    """Test-only AST evaluator strictly for historical reference-v1 fixture tests."""

    def project(self, supplied: SurfaceProjectionInput) -> dict[str, Any]:
        r = normalized_recipe(supplied["recipe"])
        if r["recipe_id"] != REFERENCE_RECIPE_ID or r["recipe_version"] != REFERENCE_RECIPE_VERSION:
            return {
                "status": "UNAVAILABLE",
                "reasons": ["SURFACE_RECIPE_UNSUPPORTED"],
                "controls": None,
            }
        states = {s["dimension"]: s for s in supplied["projected_dynamics"]["states"]}
        traits = supplied["persona"]["content"].get("behavioral_disposition", {})

        def eval_ast(node: list[Any]) -> float:
            op = node[0]
            if op == "const":
                return float(node[1])
            if op == "lookup":
                path = node[1]
                if path.startswith(D):
                    if path not in states:
                        raise KeyError(f"missing state {path}")
                    return float(states[path]["value"])
                if path.startswith(P):
                    name = path.removeprefix(P)
                    if name not in traits:
                        raise KeyError(f"missing trait {name}")
                    return float(traits[name])
                raise ValueError(f"unknown lookup path: {path}")
            if op == "add":
                return eval_ast(node[1]) + eval_ast(node[2])
            if op == "sub":
                return eval_ast(node[1]) - eval_ast(node[2])
            if op == "mul":
                return eval_ast(node[1]) * eval_ast(node[2])
            raise ValueError(f"unknown op: {op}")

        values: dict[str, float] = {}
        audit: dict[str, dict[str, Any]] = {}
        for rule in r["rules"]:
            k = rule["control_id"]
            formula = rule["formula"]
            assert formula[0] == "clamp"
            raw = eval_ast(formula[1])
            lo = eval_ast(formula[2])
            hi = eval_ast(formula[3])
            clamped = raw < lo or raw > hi
            val = max(lo, min(hi, raw))
            if val == 0.0:
                val = 0.0
            values[k] = val
            audit[k] = {"unclamped": raw, "clamped": clamped}

        payload = dependency_payload(supplied)
        roots = sorted({d for m in MANIFEST.values() for d in m["dynamics"]})
        source_states = [
            {
                "dimension": d,
                "state_id": states[d]["state_id"],
                "version": states[d]["version"],
                "value_digest": digest("state-value", states[d]["value"]),
            }
            for d in roots
        ]

        out: dict[str, Any] = {
            "runtime_id": supplied["runtime_id"],
            "scope": supplied["scope"],
            "owner": supplied["owner"],
            "interaction_or_tick_ref": supplied["interaction_or_tick_ref"],
            "persona_id": supplied["persona"]["persona_id"],
            "persona_version": supplied["persona"]["persona_version"],
            "persona_content_digest": supplied["persona"]["persona_content_digest"],
            "source_projection_id": supplied["projected_dynamics"]["source_projection_id"],
            "source_phase": supplied["projected_dynamics"]["source_phase"],
            "source_states": source_states,
            "projector_id": supplied["recipe"]["projector_id"],
            "projector_version": supplied["recipe"]["projector_version"],
            "recipe_id": supplied["recipe"]["recipe_id"],
            "recipe_version": supplied["recipe"]["recipe_version"],
            "recipe_digest": digest("recipe", r),
            "dependency_digest": digest("dependencies", payload),
            "dependency_digests_by_control": {
                k: digest("control-dependencies", v) for k, v in payload.items()
            },
            "values": values,
            "dependencies_by_control": MANIFEST,
            "evaluation_ref": supplied["evaluation_ref"],
            "audit": audit,
            "derived_only": True,
            "canonical": False,
        }
        semantic = {k: v for k, v in out.items() if k not in ("controls_id", "evaluation_ref")}
        out["controls_id"] = "surface:" + digest("controls", semantic)
        return {"status": "AVAILABLE", "reasons": [], "controls": out}
