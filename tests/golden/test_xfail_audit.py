"""Frozen Golden ownership assignments plus current D11S implementation closure."""

import ast
import inspect
from pathlib import Path

from tests.golden import test_golden_g11_g16, test_golden_g24_g28
from tests.golden.fixtures.g1_g5 import make_g1, make_g2, make_g3, make_g4, make_g5
from tests.golden.fixtures.g6_g10 import (
    make_g6,
    make_g7,
    make_g8,
    make_g9,
    make_g9a,
    make_g10,
)
from tests.golden.fixtures.g11_g16 import (
    make_g11,
    make_g12,
    make_g12a,
    make_g13,
    make_g14,
    make_g15,
    make_g15a,
    make_g16,
    make_g16a,
)
from tests.golden.fixtures.g13b_g16b import make_g13b, make_g16b
from tests.golden.fixtures.g24_g28 import make_g24, make_g25, make_g26, make_g27, make_g28
from tests.golden.runner import UnimplementedPipeline
from tests.pipeline.d11s_pipeline import (
    D11SHistoryPipeline,
    D11SLongHorizonPipeline,
    D11SModelSwapPipeline,
    D11SRestartPipeline,
)

# The frozen G -> future-owner matrix (design doc). Every fixture must carry
# exactly its assigned owner; the conftest collection hook additionally
# enforces the reason format on every xfail marker. Staged sub-scenarios
# (G9a/G15a/G16a/G12a) own their gate's part of the semantic; the full
# scenarios keep their later owners (G12's composite restart story moved to
# MR-D11 per ADR-0003; the D5-owned part is staged into G12a).
_OWNER_MATRIX: dict[str, str] = {
    "G1": "MR-D6.2",
    "G2": "MR-D4",
    "G3": "MR-D4",
    "G4": "MR-D9",
    "G5": "MR-D9",
    "G6": "MR-D8",
    "G7": "MR-D7",
    "G8": "MR-D3",
    "G9": "MR-D4",
    "G9a": "MR-D3",
    "G10": "MR-D5",
    "G11": "MR-D3",
    "G12": "MR-D11",
    "G12a": "MR-D5",
    "G13": "MR-D5",
    "G14": "MR-D10",
    "G15": "MR-D5",
    "G15a": "MR-D3",
    "G16": "MR-D8",
    "G16a": "MR-D9",
    "G13b": "MR-D5",
    "G16b": "MR-D8",
    "G24": "MR-D9",
    "G25": "MR-D11",
    "G26": "MR-D11",
    "G27": "MR-D11",
    "G28": "MR-D11P",
}

_FACTORIES = {
    "G1": make_g1,
    "G2": make_g2,
    "G3": make_g3,
    "G4": make_g4,
    "G5": make_g5,
    "G6": make_g6,
    "G7": make_g7,
    "G8": make_g8,
    "G9": make_g9,
    "G9a": make_g9a,
    "G10": make_g10,
    "G11": make_g11,
    "G12": make_g12,
    "G12a": make_g12a,
    "G13": make_g13,
    "G14": make_g14,
    "G15": make_g15,
    "G15a": make_g15a,
    "G16": make_g16,
    "G16a": make_g16a,
    "G13b": make_g13b,
    "G16b": make_g16b,
    "G24": make_g24,
    "G25": make_g25,
    "G26": make_g26,
    "G27": make_g27,
    "G28": make_g28,
}


def test_all_27_scenarios_have_matrix_owners() -> None:
    assert (
        set(_FACTORIES)
        == set(_OWNER_MATRIX)
        == {
            "G1",
            "G2",
            "G3",
            "G4",
            "G5",
            "G6",
            "G7",
            "G8",
            "G9",
            "G9a",
            "G10",
            "G11",
            "G12",
            "G12a",
            "G13",
            "G14",
            "G15",
            "G15a",
            "G16",
            "G16a",
            "G13b",
            "G16b",
            "G24",
            "G25",
            "G26",
            "G27",
            "G28",
        }
    )


def test_every_fixture_owner_matches_matrix() -> None:
    for golden_id, factory in _FACTORIES.items():
        scenario = factory()
        expected_owner = f"{_OWNER_MATRIX[golden_id]} not implemented"
        assert scenario.owner == expected_owner, (
            f"{golden_id} owner {scenario.owner!r} != {expected_owner!r}"
        )


def test_owner_matrix_covers_all_future_owners() -> None:
    owners = set(_OWNER_MATRIX.values())
    assert owners == {
        "MR-D3",
        "MR-D4",
        "MR-D5",
        "MR-D6.2",
        "MR-D7",
        "MR-D8",
        "MR-D9",
        "MR-D10",
        "MR-D11",
        "MR-D11P",
    }


def test_every_mr_d11_assignment_has_a_real_d11s_pipeline() -> None:
    """Leaving any MR-D11 Golden on UnimplementedPipeline must fail this test."""
    assigned = {golden_id for golden_id, owner in _OWNER_MATRIX.items() if owner == "MR-D11"}
    implemented = {
        "G12": D11SRestartPipeline,
        "G25": D11SModelSwapPipeline,
        "G26": D11SLongHorizonPipeline,
        "G27": D11SHistoryPipeline,
    }

    assert set(implemented) == assigned
    assert all(pipeline is not UnimplementedPipeline for pipeline in implemented.values())

    golden_tests = {
        "G12": (test_golden_g11_g16.test_golden_g12, D11SRestartPipeline),
        "G25": (
            test_golden_g24_g28.test_golden_g25_model_swap_preserves_internal_decision,
            D11SModelSwapPipeline,
        ),
        "G26": (
            test_golden_g24_g28.test_golden_g26_long_horizon_state_remains_bounded,
            D11SLongHorizonPipeline,
        ),
        "G27": (
            test_golden_g24_g28.test_golden_g27_repeated_history_surface_does_not_amplify,
            D11SHistoryPipeline,
        ),
    }
    assert set(golden_tests) == assigned
    for golden_id, (test_function, pipeline) in golden_tests.items():
        source = inspect.getsource(test_function)
        assert f"ScenarioRunner({pipeline.__name__}())" in source, golden_id
        assert "UnimplementedPipeline" not in source, golden_id


def test_exact_remaining_strict_xfail_is_g28_owned_by_mr_d11p() -> None:
    strict_xfails: dict[tuple[str, str], str] = {}
    for path in sorted(Path(__file__).parent.glob("test_golden_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                marker = decorator.func
                if not (
                    isinstance(marker, ast.Attribute)
                    and marker.attr == "xfail"
                    and isinstance(marker.value, ast.Attribute)
                    and marker.value.attr == "mark"
                    and isinstance(marker.value.value, ast.Name)
                    and marker.value.value.id == "pytest"
                ):
                    continue
                keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
                strict_keyword = keywords.get("strict")
                reason_keyword = keywords.get("reason")
                if not (
                    isinstance(strict_keyword, ast.Constant)
                    and strict_keyword.value is True
                    and isinstance(reason_keyword, ast.Constant)
                    and isinstance(reason_keyword.value, str)
                ):
                    continue
                strict_xfails[(path.name, node.name)] = reason_keyword.value

    assert strict_xfails == {
        (
            "test_golden_g24_g28.py",
            "test_golden_g28_onboarding_llm_is_one_time_and_user_activated",
        ): "MR-D11P not implemented"
    }
    assert _OWNER_MATRIX["G28"] == "MR-D11P"
