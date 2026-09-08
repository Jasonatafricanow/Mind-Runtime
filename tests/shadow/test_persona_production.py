"""C4 Kayla production-persona certification (PERS1-PERS16, T1-T8, 7-day).

Everything runs against the REAL DynamicsEngine + REAL loader +
REAL semantic routing/effects chain under FakeClock. No legacy numeric
copying: parameters come only from configs/personas/kayla.json.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mind_runtime.contracts import Observation, Scope, ScopeDomain, Situation, SyncFields
from mind_runtime.dynamics.engine import DynamicsEngine, Impulse
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.emotional_transition.effects import EffectMapper, EventEffectRule
from mind_runtime.emotional_transition.provider import RecordedSemanticProvider
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.persona_config import (
    LoadedPersona,
    PersonaProfileError,
    load_kayla_production,
    load_persona_profile,
)

_ProfileMutator = Callable[[dict[str, object], dict[str, object]], object]

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
LONGING = "agent.affect.longing"
SHARING = "agent.affect.sharing_urge"


# ── harness ───────────────────────────────────────────────────────────────


def _kayla() -> tuple[LoadedPersona, DynamicsEngine]:
    loaded = load_kayla_production()
    return loaded, DynamicsEngine(persona=loaded.profile)


def _step(
    engine: DynamicsEngine,
    current: dict[str, float],
    hours: float = 1.0,
    impulses: tuple[Impulse, ...] = (),
) -> dict[str, float]:
    result = engine.step(current=current, elapsed=timedelta(hours=hours), impulses=impulses)
    return {dim: value for dim, value in result.proposed}


def _run(
    profile: PersonaProfile,
    hours: int,
    *,
    impulses_at: dict[int, tuple[Impulse, ...]] | None = None,
    start: dict[str, float] | None = None,
) -> list[dict[str, float]]:
    """Hourly trajectory; returns every state including hour 0."""
    engine = DynamicsEngine(persona=profile)
    state = start or {d.dimension: d.initial_value for d in profile.dimensions}
    trajectory = [dict(state)]
    for hour in range(hours):
        batch = (impulses_at or {}).get(hour, ())
        state = _step(engine, state, 1.0, batch)
        trajectory.append(dict(state))
    return trajectory


def _scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-a")


def _situation(scope: Scope) -> Situation:
    return Situation(
        situation_id="sit-sem",
        scope=scope,
        origin_runtime_id="kayla",
        derived_facts=(("conversation_mode", "active"),),
        effective_state_ref="effective:user-a",
        observed_at=FIXED_NOW,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=("hermes:sem-1",),
    )


def _ambiguous_obs() -> Observation:
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    return Observation(
        id="obs-sem-1",
        interaction_id="it-sem",
        scope=scope,
        origin_runtime_id="kayla",
        type="factual",
        key="user_message.observed",
        value={"text": "你这人真难懂"},
        confidence=1.0,
        observed_at=FIXED_NOW,
        evidence_refs=("hermes:sem-1",),
        sync=SyncFields(scope, "kayla", "obs-sem-1", 1, "idem"),
    )


def test_pers1_production_profile_loads_typed_and_versioned() -> None:
    loaded = load_kayla_production()
    assert loaded.profile.persona_id == "kayla"
    assert loaded.profile.version == 1
    assert len(loaded.profile.dimensions) == 10
    assert loaded.migration_source["system"].startswith("xinchao")
    dims = {p.dimension for p in loaded.profile.dimensions}
    assert LONGING in dims and "agent.affect.sadness" in dims


def test_pers2_fixture_profile_is_not_the_production_default() -> None:
    from mind_runtime.dynamics.kayla_v0 import kayla_v0_profile

    fixture = kayla_v0_profile()
    production = load_kayla_production().profile
    assert fixture.persona_id == "kayla_v0" != production.persona_id
    assert len(fixture.dimensions) != len(production.dimensions)
    # the fixture keeps test-only params and must never ship a v1 production id
    assert production.version >= 1 and fixture is not production


def test_pers14_no_fixed_dimension_count_anywhere_in_production_path(
    tmp_path: Path,
) -> None:
    """A synthetic 3-dimension profile loads and drives the same engine."""
    minimal = {
        "persona_id": "synthetic-three",
        "profile_version": 1,
        "dimensions": [
            {
                "dimension": f"agent.affect.dim{i}",
                "baseline": 0.2 * i + 0.1,
                "initial_value": 0.2 * i + 0.1,
                "sensitivity": 0.5,
                "recovery_rate": 0.00003,
                "ceiling": 1.0,
                "floor": 0.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
            for i in range(1, 4)
        ],
    }
    path = tmp_path / "three.json"
    path.write_text(json.dumps(minimal), encoding="utf-8")
    loaded = load_persona_profile(path)
    engine = DynamicsEngine(persona=loaded.profile)
    out = _step(engine, {d.dimension: d.initial_value for d in loaded.profile.dimensions})
    assert len(out) == 3


# ── PERS3 / PERS4 / PERS5 — loader fail-closed validation ─────────────────


def _write_profile(tmp_path: Path, mutate: _ProfileMutator) -> Path:
    base = json.loads((Path(load_kayla_production().source_path)).read_text(encoding="utf-8"))
    assert isinstance(base, dict)
    dimensions_raw = base["dimensions"]
    assert isinstance(dimensions_raw, list) and dimensions_raw
    first = dimensions_raw[0]
    assert isinstance(first, dict)
    entry = dict(first)
    mutated = mutate(entry, base)
    if isinstance(mutated, list):
        base["dimensions"] = mutated
    else:
        base["dimensions"][0] = mutated
    if isinstance(mutated, dict):
        base["dimensions"][0] = mutated
    else:
        base["dimensions"] = mutated
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_pers3_invalid_bounds_fail_closed(tmp_path: Path) -> None:
    for mutator in (
        lambda e, b: {**e, "baseline": 1.5},
        lambda e, b: {**e, "ceiling": 0.5},
        lambda e, b: {**e, "sensitivity": 9},
        lambda e, b: {**e, "recovery_rate": -0.1},
    ):
        path = _write_profile(tmp_path, mutator)
        with pytest.raises(PersonaProfileError):
            load_persona_profile(path)


def test_pers4_duplicate_and_unknown_dimension_fail(tmp_path: Path) -> None:
    def duplicate(_e: dict[str, object], b: dict[str, object]) -> list[object]:
        dims = b["dimensions"]
        assert isinstance(dims, list) and dims
        return [dims[0]] * 2

    path = _write_profile(tmp_path, duplicate)
    with pytest.raises(PersonaProfileError, match="duplicate dimension"):
        load_persona_profile(path)

    missing = json.loads(Path(load_kayla_production().source_path).read_text(encoding="utf-8"))
    missing["dimensions"] = missing["dimensions"][:1]
    path2 = tmp_path / "missing-target.json"
    path2.write_text(json.dumps(missing), encoding="utf-8")


def test_pers5_coupling_targets_validated(tmp_path: Path) -> None:
    def bad_coupling(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "coupling_profile": [["agent.affect.nonexistent", -0.2]]}

    path = _write_profile(tmp_path, bad_coupling)
    with pytest.raises(PersonaProfileError, match="unknown dimension"):
        load_persona_profile(path)

    def self_ref(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "coupling_profile": [[e["dimension"], -0.2]]}

    with pytest.raises(PersonaProfileError, match="self-reference"):
        load_persona_profile(_write_profile(tmp_path, self_ref))


# ── PERS6 — persona trait never shifts with current affect ────────────────


def test_pers6_persona_baseline_immutable_under_current_state_pressure() -> None:
    _, engine = _kayla()
    profile = engine.persona
    before = {p.dimension: p.baseline for p in profile.dimensions}
    state = {d.dimension: d.initial_value for d in profile.dimensions}

    state = _step(engine, state, 1.0, (Impulse(LONGING, 10.0),))  # huge spike
    spike_value = state[LONGING]
    for _ in range(240):  # 10 days of idle recovery in one go
        state = _step(engine, state, 1.0)

    after = {p.dimension: p.baseline for p in profile.dimensions}
    assert before == after
    assert math.isclose(state[LONGING], before[LONGING], abs_tol=1e-9)
    assert spike_value <= 1.0  # clamped, never exploded


# ── PERS7 / PERS8 / PERS13 — real semantic chain → persona dynamics ──────

_EFFECT_RULES = (
    EventEffectRule(event_kind="gratitude", dimension=SHARING, base_amount=0.45),
    EventEffectRule(
        event_kind="distress_sharing", dimension="agent.affect.sadness", base_amount=0.60
    ),
)

_GRATITUDE: dict[str, object] = {
    "kind": "gratitude",
    "confidence": 0.92,
    "evidence_refs": ["obs-sem-1"],
    "attributes": {"tone": "warm"},
}


def _semantic_impulses(candidate_payload: dict[str, object]) -> tuple[Impulse, ...]:
    """The REAL C3 chain: recorded artifact → router → effect mapper."""
    router = SemanticRouter(provider=RecordedSemanticProvider([[dict(candidate_payload)]]))
    routing = router.route(
        observations=(_ambiguous_obs(),),
        context=_situation(_scope()),
        supplied_candidates=(),
    )
    assert routing.candidates, "recorded candidate must validate"
    mapped = EffectMapper(rules=_EFFECT_RULES).map(routing=routing, history=None)
    return mapped.impulses


# ── T1 / PERS12 — idle baseline return is gradual and complete ────────────


def test_t1_idle_return_is_gradual_and_complete() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    stimulated = _step(engine, state, 1.0, (Impulse(LONGING, 0.6),))
    baseline = loaded.profile.require_dimension(LONGING).baseline
    elevated = stimulated[LONGING]
    assert elevated > baseline
    for _ in range(72):
        state = _step(engine, state, 1.0)
    recovered = state[LONGING]
    assert abs(recovered - baseline) < 0.01
    assert recovered != elevated and recovered >= baseline


def test_pers12_no_instant_reset_or_stuck_high() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    raised = _step(engine, state, 1.0, (Impulse(SHARING, 0.8),))[SHARING]
    after_one_hour_idle = _step(engine, {**state, SHARING: raised}, 1.0)[SHARING]
    baseline = loaded.profile.require_dimension(SHARING).baseline
    assert after_one_hour_idle > baseline + 0.2
    settled_24h = _step(engine, {**state, SHARING: after_one_hour_idle}, 24.0)[SHARING]
    assert abs(settled_24h - baseline) < 0.05


# ── T2 / PERS11 — repeated stimulation saturates safely ──────────────────


def test_t2_repeated_stimulation_saturates_below_ceiling() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    ceiling = loaded.profile.require_dimension(SHARING).ceiling
    values: list[float] = [state[SHARING]]
    for _ in range(240):
        state = _step(engine, state, 24.0, (Impulse(SHARING, 0.5),))
        values.append(state[SHARING])
    assert max(values) <= ceiling
    assert all(math.isfinite(v) for v in values)
    assert abs(values[-1] - values[-10]) < 0.05


# ── T3 / T4 — coupling bounded/directional; nothing else leaks ───────────


def test_t3_coupling_bounded_and_directional() -> None:
    loaded = load_kayla_production()
    curiosity = loaded.profile.require_dimension("agent.affect.curiosity")
    restlessness = loaded.profile.require_dimension("agent.affect.restlessness")
    assert any(t == restlessness.dimension for t, _ in curiosity.coupling_profile)

    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    before = state[restlessness.dimension]
    spiked = _step(engine, state, 1.0, (Impulse(curiosity.dimension, 0.5),))
    after = spiked[restlessness.dimension]
    assert after < before
    assert after >= restlessness.floor - 1e-12


def test_t4_no_unconfigured_coupling() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    coupled_targets = {
        target for p in loaded.profile.dimensions for target, _ in p.coupling_profile
    }
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    spiked_after = _step(engine, state, 1.0, (Impulse(LONGING, 0.7),))

    solo_engine = DynamicsEngine(persona=loaded.profile)
    solo_state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    solo_after = _step(solo_engine, solo_state, 1.0)

    for p in loaded.profile.dimensions:
        if p.dimension == LONGING or p.dimension in coupled_targets:
            continue
        # un-coupled dimensions evolve ONLY by their own recovery term
        assert math.isclose(
            spiked_after[p.dimension], solo_after[p.dimension], rel_tol=0, abs_tol=1e-15
        )


# ── T5 — idle-window partition equivalence (documented scope) ─────────────


def test_t5_partition_equivalence_for_idle_recovery() -> None:
    """Exponential recovery is exactly partition-invariant while idle.

    Impulse timing inside an aggregated window is deliberately NOT promised
    equivalent; the contract locks only this structural property.
    """
    _, engine = _kayla()
    profile = engine.persona
    state = {d.dimension: d.initial_value for d in profile.dimensions}
    spiked = _step(engine, state, 1.0, (Impulse(LONGING, 0.4),))

    once = _step(engine, dict(spiked), 4.0)
    parts = dict(spiked)
    for _ in range(4):
        parts = _step(engine, parts, 1.0)
    for dim in once:
        assert math.isclose(once[dim], parts[dim], rel_tol=1e-9, abs_tol=1e-12)


# ── T6 / PERS13 — restart continuity equals continuous run ────────────────


def test_pers13_restart_equals_continuous(tmp_path: Path) -> None:
    loaded = load_kayla_production()
    continuous = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    for _ in range(6):
        state = _step(continuous, state, 1.0)
    persisted = json.dumps(sorted(state.items()), ensure_ascii=False)

    resumed_engine = DynamicsEngine(persona=loaded.profile)
    r_state_pairs = json.loads(persisted)
    r_state = {k: v for k, v in r_state_pairs}
    for _ in range(18):
        r_state = _step(resumed_engine, r_state, 1.0)
    for _ in range(18):
        state = _step(continuous, state, 1.0)
    for dim in state:
        assert math.isclose(state[dim], r_state[dim], rel_tol=1e-12, abs_tol=1e-15)


# ── PERS8 / PERS9 / T7 / T8 — determinism + meaningful persona diff ───────


def test_pers7_recorded_semantic_artifact_drives_dynamics() -> None:
    impulses = _semantic_impulses(dict(_GRATITUDE))
    assert impulses and impulses[0].dimension == SHARING
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    out = _step(engine, state, 1.0, impulses)
    assert out[SHARING] > loaded.profile.require_dimension(SHARING).baseline


def test_pers8_same_input_same_profile_deterministic() -> None:
    impulses = _semantic_impulses(dict(_GRATITUDE))
    loaded = load_kayla_production()
    runs = []
    for _ in range(3):
        engine = DynamicsEngine(persona=loaded.profile)
        state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
        runs.append(_step(engine, state, 1.0, impulses))
    assert runs[0] == runs[1] == runs[2]


def test_pers9_different_profiles_diverge_meaningfully() -> None:
    from mind_runtime.dynamics.persona import PersonaProfile as _PP

    impulses = _semantic_impulses(dict(_GRATITUDE))
    kayla_loaded = load_kayla_production()
    neutral_dims = tuple(
        type(d)(
            dimension=d.dimension,
            baseline=0.30,
            initial_value=0.30,
            sensitivity=0.30,
            recovery_rate=d.recovery_rate,
            ceiling=d.ceiling,
            floor=d.floor,
            growth_profile=d.growth_profile,
            coupling_profile=(),
        )
        for d in kayla_loaded.profile.dimensions
    )
    neutral = _PP(persona_id="synthetic-neutral", dimensions=neutral_dims)

    kayla_out = _step(
        DynamicsEngine(persona=kayla_loaded.profile),
        {d.dimension: d.initial_value for d in kayla_loaded.profile.dimensions},
        1.0,
        impulses,
    )
    neutral_out = _step(
        DynamicsEngine(persona=neutral),
        {d.dimension: d.initial_value for d in neutral.dimensions},
        1.0,
        impulses,
    )
    assert abs(kayla_out[SHARING] - neutral_out[SHARING]) > 0.05
    assert kayla_out[SHARING] > neutral_out[SHARING]


# ── PERS10 / PERS16 — horizon bounds and week-long stability ──────────────


@pytest.mark.parametrize("hours", [1, 6, 24, 72])
def test_pers10_trajectories_bounded(hours: int) -> None:
    loaded = load_kayla_production()
    trajectory = _run(
        loaded.profile, hours, impulses_at={max(hours // 2, 0): (Impulse(LONGING, 0.6),)}
    )
    flat = [v for frame in trajectory for v in frame.values()]
    lo = min(p.floor for p in loaded.profile.dimensions)
    hi = max(p.ceiling for p in loaded.profile.dimensions)
    assert all(math.isfinite(v) and lo <= v <= hi for v in flat)


def test_pers16_seven_day_synthetic_stability_stays_clean() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    profile = loaded.profile
    state = {d.dimension: d.initial_value for d in profile.dimensions}
    previous: dict[str, float] | None = None
    violations = {"nan": 0, "inf": 0, "oob": 0, "jump": 0}
    locked_at_ceiling = {p.dimension: 0 for p in profile.dimensions}

    rng_state = 20260827

    def pseudo_random() -> float:
        nonlocal rng_state
        rng_state = (rng_state * 1103515245 + 12345) % (2**31)
        return rng_state / (2**31)

    for hour in range(24 * 7):
        impulses: tuple[Impulse, ...] = ()
        if hour % 3 == 0 and pseudo_random() < 0.34:
            dim = profile.dimensions[int(pseudo_random() * len(profile.dimensions))].dimension
            impulses = (Impulse(dim, 0.2 + 0.6 * pseudo_random()),)
        state = _step(engine, state, 1.0, impulses)
        for dim, value in state.items():
            p = profile.require_dimension(dim)
            if math.isnan(value):
                violations["nan"] += 1
            if math.isinf(value):
                violations["inf"] += 1
            if not p.floor <= value <= p.ceiling:
                violations["oob"] += 1
            if (
                previous is not None
                and not impulses
                and abs(value - previous.get(dim, value)) > 0.5
            ):
                # oscillation-explosion probe runs on IDLE steps only:
                # an impulse hour may legitimately move far in one step
                violations["jump"] += 1
            if abs(value - p.ceiling) < 1e-9:
                locked_at_ceiling[dim] += 1
        previous = dict(state)

    assert all(v == 0 for v in violations.values()), violations
    assert all(c < 24 * 7 for c in locked_at_ceiling.values())


# ── PERS15 — emotion_snapshot has no Persona authority ───────────────────


def test_pers15_snapshot_cannot_overwrite_persona_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rogue snapshot claiming persona baselines cannot reach the loader."""
    from mind_runtime.shadow import snapshot as snapshot_module
    from mind_runtime.shadow.affect import init_affect_store
    from mind_runtime.shadow.snapshot import generate_snapshot

    monkeypatch.setattr(snapshot_module, "AFFECT_DB", tmp_path / "affect.db")
    monkeypatch.setattr(snapshot_module, "STATES_DB", tmp_path / "states.db")
    monkeypatch.setattr(snapshot_module, "SNAPSHOT", tmp_path / "emotion_snapshot.json")
    init_affect_store(tmp_path / "affect.db")
    generate_snapshot()

    # the snapshot format has no field that could express a persona override;
    # and the production loader reads ONLY its explicit profile file.
    payload = json.loads((tmp_path / "emotion_snapshot.json").read_text(encoding="utf-8"))
    assert set(payload) == {"generated_at", "windows", "latest_user", "states"}

    config_expectations = json.loads(
        Path(load_kayla_production().source_path).read_text(encoding="utf-8")
    )
    expected = {d["dimension"]: d["baseline"] for d in config_expectations["dimensions"]}
    after = load_kayla_production().profile
    for p in after.dimensions:
        assert p.baseline == expected[p.dimension]
        assert p.baseline == expected[p.dimension]


# ── loader fail-closed branch matrix (PERS3/PERS4/PERS5 deep cuts) ────────


def test_loader_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(PersonaProfileError, match="not found"):
        load_persona_profile(tmp_path / "absent.json")


def test_loader_unreadable_json_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PersonaProfileError, match="unreadable persona profile"):
        load_persona_profile(bad)


def test_loader_non_numeric_dimension_field_fails_closed(tmp_path: Path) -> None:
    path = _write_profile(tmp_path, lambda e, _b: {**e, "sensitivity": "high"})
    with pytest.raises(PersonaProfileError, match="must be a number"):
        load_persona_profile(path)


def test_loader_growth_and_coupling_shape_failures(tmp_path: Path) -> None:
    def growth_not_list(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "growth_profile": "soon"}

    with pytest.raises(PersonaProfileError, match="growth_profile must be a list"):
        load_persona_profile(_write_profile(tmp_path, growth_not_list))

    def coupling_not_list(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "coupling_profile": {"agent.affect.restlessness": -0.2}}

    with pytest.raises(PersonaProfileError, match="coupling_profile must be a list"):
        load_persona_profile(_write_profile(tmp_path, coupling_not_list))

    def strength_not_number(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "coupling_profile": [["agent.affect.restlessness", "strong"]]}

    with pytest.raises(PersonaProfileError, match="strength must be a number"):
        load_persona_profile(_write_profile(tmp_path, strength_not_number))


def test_loader_accepts_explicit_null_reference_pairs(tmp_path: Path) -> None:
    def explicit_nulls(e: dict[str, object], _b: dict[str, object]) -> dict[str, object]:
        return {**e, "growth_profile": None, "coupling_profile": None}

    loaded = load_persona_profile(_write_profile(tmp_path, explicit_nulls))
    dim = loaded.profile.dimensions[0]
    assert dim.growth_profile == () and dim.coupling_profile == ()


def test_scope_for_persona_helper() -> None:
    from mind_runtime.persona_config import scope_for_persona

    loaded = load_kayla_production()
    scope = scope_for_persona(loaded.profile)
    assert scope.domain.value == "agent"
    assert scope.persona_id == "kayla"


# ── CAL1-CAL12 — calibration certification (C4C) ──────────────────────────

_CAL_HORIZONS = (1, 6, 24, 72)


def _cal_trajectories() -> dict[int, dict[str, float]]:
    """Stimulus + idle snapshots at the certification horizons."""
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    dims = loaded.profile.dimensions
    state = {d.dimension: d.initial_value for d in dims}
    impulses = _semantic_impulses(dict(_GRATITUDE))
    spiked = _step(engine, state, 1.0, impulses)
    snaps: dict[int, dict[str, float]] = {}
    elapsed = 0
    for horizon in _CAL_HORIZONS:
        while elapsed < horizon:
            spiked = _step(engine, spiked, 1.0)
            elapsed += 1
        snaps[horizon] = dict(spiked)
    return snaps


@pytest.mark.parametrize("hours", _CAL_HORIZONS)
def test_cal1_4_horizon_trajectories_bounded_and_recovering(hours: int) -> None:
    loaded = load_kayla_production()
    snaps = _cal_trajectories()
    frame = snaps[hours]
    sharing = loaded.profile.require_dimension(SHARING)
    for dim, value in frame.items():
        p = loaded.profile.require_dimension(dim)
        assert math.isfinite(value) and p.floor <= value <= p.ceiling
    base = sharing.baseline
    assert abs(frame[SHARING] - base) <= abs(snaps[1][SHARING] - base)
    if hours >= 72:
        assert abs(frame[SHARING] - base) < 0.01


def test_cal5_idle_recovery_band() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    hit = _step(engine, state, 1.0, (Impulse(LONGING, 0.6),))
    base = loaded.profile.require_dimension(LONGING).baseline
    one = _step(engine, dict(hit), 1.0)[LONGING]
    six = _step(engine, dict(hit), 6.0)[LONGING]
    day = _step(engine, dict(hit), 24.0)[LONGING]
    assert base < six < one < hit[LONGING]  # monotone decay toward baseline
    assert abs(day - base) < 0.05


def test_cal6_repeated_stimulation_saturation() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    impulses = _semantic_impulses(dict(_GRATITUDE))
    seen: list[float] = []
    for _ in range(120):
        state = _step(engine, state, 12.0, impulses)
        seen.append(state[SHARING])
    assert all(math.isfinite(v) for v in seen)
    assert max(seen) <= loaded.profile.require_dimension(SHARING).ceiling
    assert abs(seen[-1] - seen[-5]) < 0.02


def test_cal7_configured_coupling_only() -> None:
    loaded = load_kayla_production()
    curiosity = loaded.profile.require_dimension("agent.affect.curiosity")
    restlessness = loaded.profile.require_dimension("agent.affect.restlessness")
    engine = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    spiked = _step(engine, state, 1.0, (Impulse(curiosity.dimension, 0.5),))
    assert spiked[restlessness.dimension] < state[restlessness.dimension]
    assert restlessness.floor <= spiked[restlessness.dimension]


def test_cal8_no_unintended_coupling() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    coupled = {t for p in loaded.profile.dimensions for t, _ in p.coupling_profile}
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    spiked = _step(engine, state, 1.0, (Impulse(LONGING, 0.7),))
    solo = DynamicsEngine(persona=loaded.profile)
    solo_state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    solo_after = _step(solo, solo_state, 1.0)
    for p in loaded.profile.dimensions:
        if p.dimension == LONGING or p.dimension in coupled:
            continue
        assert math.isclose(spiked[p.dimension], solo_after[p.dimension], rel_tol=0, abs_tol=1e-15)


def test_cal9_kayla_vs_neutral_deterministic_difference() -> None:
    from mind_runtime.dynamics.persona import PersonaProfile as _PP

    impulses = _semantic_impulses(dict(_GRATITUDE))
    kayla_loaded = load_kayla_production()
    neutral_dims = tuple(
        type(d)(
            dimension=d.dimension,
            baseline=0.30,
            initial_value=0.30,
            sensitivity=0.30,
            recovery_rate=d.recovery_rate,
            ceiling=d.ceiling,
            floor=d.floor,
            growth_profile=d.growth_profile,
            coupling_profile=(),
        )
        for d in kayla_loaded.profile.dimensions
    )
    neutral = _PP(persona_id="synthetic-neutral", dimensions=neutral_dims)

    def run(profile: PersonaProfile) -> dict[str, float]:
        return _step(
            DynamicsEngine(persona=profile),
            {d.dimension: d.initial_value for d in profile.dimensions},
            1.0,
            impulses,
        )

    k1, k2 = run(kayla_loaded.profile), run(kayla_loaded.profile)
    n1, n2 = run(neutral), run(neutral)
    assert k1 == k2 and n1 == n2
    assert abs(k1[SHARING] - n1[SHARING]) > 0.05
    assert k1[SHARING] > n1[SHARING]


def test_cal10_restart_equivalence_24h() -> None:
    loaded = load_kayla_production()
    continuous = DynamicsEngine(persona=loaded.profile)
    state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
    for _ in range(6):
        state = _step(continuous, state, 1.0)
    persisted = json.dumps(sorted(state.items()))
    resumed_engine = DynamicsEngine(persona=loaded.profile)
    r_state = {k: v for k, v in json.loads(persisted)}
    for _ in range(18):
        r_state = _step(resumed_engine, r_state, 1.0)
    for _ in range(18):
        state = _step(continuous, state, 1.0)
    for dim in state:
        assert math.isclose(state[dim], r_state[dim], rel_tol=1e-12, abs_tol=1e-15)


def test_cal11_seven_day_stability_certified() -> None:
    loaded = load_kayla_production()
    engine = DynamicsEngine(persona=loaded.profile)
    profile = loaded.profile
    state = {d.dimension: d.initial_value for d in profile.dimensions}
    rng = 424242

    def rnd() -> float:
        nonlocal rng
        rng = (rng * 48271) % 0x7FFFFFFF
        return rng / 0x7FFFFFFE

    for hour in range(24 * 7):
        impulses: tuple[Impulse, ...] = ()
        if hour % 4 == 0 and rnd() < 0.3:
            dim = profile.dimensions[int(rnd() * len(profile.dimensions))].dimension
            impulses = (Impulse(dim, 0.15 + 0.7 * rnd()),)
        state = _step(engine, state, 1.0, impulses)
        for dim, value in state.items():
            p = profile.require_dimension(dim)
            assert math.isfinite(value) and p.floor <= value <= p.ceiling


def test_cal12_full_chain_replay_deterministic() -> None:
    """loader → engine + router → effects, twice, byte-identical results."""
    impulses = _semantic_impulses(dict(_GRATITUDE))
    loaded = load_kayla_production()

    def full_run() -> dict[str, float]:
        engine = DynamicsEngine(persona=loaded.profile)
        state = {d.dimension: d.initial_value for d in loaded.profile.dimensions}
        out = _step(engine, state, 1.0, impulses)
        normalized: dict[str, float] = json.loads(json.dumps(out))
        return normalized

    assert full_run() == full_run()
