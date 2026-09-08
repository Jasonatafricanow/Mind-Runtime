"""Golden fixture schema validation: every scenario declares all D2 fields."""

from dataclasses import fields

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    AppraisalPath,
    Evidence,
    HistoricalContextBundle,
    RuntimeState,
)
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
    make_g13,
    make_g14,
    make_g15,
    make_g15a,
    make_g16,
    make_g16a,
)
from tests.golden.fixtures.g13b_g16b import make_g13b, make_g16b
from tests.golden.fixtures.g24_g28 import make_g24, make_g25, make_g26, make_g27, make_g28
from tests.golden.scenario import GoldenScenario

_FIXTURE_FACTORIES = {
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

_REQUIRED_FIELDS = {
    "clock",
    "runtime_id",
    "scope",
    "persona",
    "initial_canonical_state",
    "historical_context",
    "input_evidence",
    "expected_deterministic_outputs",
    "expected_allowed_llm_path",
    "expected_canonical_changes",
    "expected_projected_changes",
}


def test_schema_has_all_d2_required_fields() -> None:
    schema_fields = {field.name for field in fields(GoldenScenario)}
    assert _REQUIRED_FIELDS <= schema_fields


def test_every_fixture_is_complete() -> None:
    for golden_id, factory in _FIXTURE_FACTORIES.items():
        scenario = factory()
        assert scenario.golden_id == golden_id
        assert scenario.title
        assert scenario.owner
        assert scenario.runtime_id
        assert all(isinstance(item, AffectiveDimensionProfile) for item in scenario.persona)
        assert all(isinstance(item, RuntimeState) for item in scenario.initial_canonical_state)
        assert all(isinstance(item, Evidence) for item in scenario.input_evidence)
        if scenario.historical_context is not None:
            assert isinstance(scenario.historical_context, HistoricalContextBundle)
        if scenario.expected_allowed_llm_path is not None:
            assert isinstance(scenario.expected_allowed_llm_path, AppraisalPath)


def test_every_fixture_owner_names_a_future_w() -> None:
    for factory in _FIXTURE_FACTORIES.values():
        assert factory().owner.endswith("not implemented")
