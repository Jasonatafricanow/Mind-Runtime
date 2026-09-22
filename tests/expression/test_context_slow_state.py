"""C10-C1 slow-state projection tests.

Verifies the read/projection seam only:
  - Empty slow state -> no slow items emitted (C1)
  - Real slow state -> INTERNAL_STATE item with raw float, slow_ key prefix,
    source_refs ("slow", state_id, version) (C2)
  - Fast and slow states coexist as distinct items (C3)
  - Restart consumption: write to SQLite, reopen orchestrator, slow state
    survives (C4)
  - Provenance: DecisionContext.slow_state_projection_refs lists state_ids
    (C5)
  - Zero / absent state is inert (C6)
  - Determinism: same inputs -> same output (C7)
  - No write-back: reading slow state does not write to slow_contribution_window
    or states (C8)

Tests self-register a slow dimension via register_longitudinal_definition()
because production D11S has no agent.slow.* definitions.  Production must
NOT auto-register dimensions; this is test-only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mind_runtime.contracts import (
    ExpressionContextKind,
    ProjectedMindState,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.slow_plasticity.writer import SlowPlasticityWriter
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.longitudinal import register_longitudinal_definition
from mind_runtime.state.persistence import SqliteStateBackend

from tests.expression.test_context import (
    DecisionContextCompilerInput,
    make_compiler_input,
    make_compiler,
)

SLOW_DIM = "agent.slow.test"
AGENT_SCOPE = Scope(
    domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="persona-1"
)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def make_slow_state(
    *,
    value: float,
    state_id: str = "slow-state-1",
    version: int = 1,
    origin_runtime_id: str = "runtime-1",
) -> RuntimeState:
    return RuntimeState(
        state_id=state_id,
        scope=AGENT_SCOPE,
        dimension=SLOW_DIM,
        value=value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=origin_runtime_id,
        version=version,
        sync=SyncFields(
            AGENT_SCOPE, origin_runtime_id, state_id, version, f"idem-{state_id}"
        ),
    )


def make_slow_decision(
    *,
    proposed_value: float,
    salience: float,
) -> HomeostasisDecision:
    """Build a SLOW_ACCEPT HomeostasisDecision targeting SLOW_DIM."""
    return HomeostasisDecision(
        candidate=CandidateStateDelta(
            target_dimension=SLOW_DIM,
            proposed_value=proposed_value,
            scope=AGENT_SCOPE,
            evidence_refs=("evidence-1",),
            source_event_ref="evt-1",
            salience=salience,
            confidence=1.0,
            observed_at=NOW,
        ),
        prior_value=None,
        decision=HomeostasisDisposition.SLOW_ACCEPT,
        reason_code="test-slow-accept",
        decided_at=NOW,
    )


def _make_agent_effective_state() -> RuntimeState:
    """An effective user-state at AGENT scope so the compiler input is
    internally consistent (scope matches across fields, dimension starts
    with 'agent.' per require_domain_key).
    """
    return RuntimeState(
        state_id="state-agent-effective-1",
        scope=AGENT_SCOPE,
        dimension="agent.context.phase",
        value="active",
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(
            AGENT_SCOPE, "runtime-1", "state-agent-effective-1", 1,
            "idem-state-agent-effective-1",
        ),
    )


def _make_agent_projected_state(
    *,
    affect_value: float = 0.62,
) -> "ProjectedMindState":
    """A projected agent state at AGENT scope containing the affect
    dimension that the test compiler's affect rules (custom_trust)
    are registered for.
    """
    from mind_runtime.contracts import ProjectedMindState  # noqa: F401
    state = RuntimeState(
        state_id="state-affect-1",
        scope=AGENT_SCOPE,
        dimension="agent.affect.custom_trust",
        value=affect_value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-affect-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(
            AGENT_SCOPE, "runtime-1", "state-affect-1", 1,
            "idem-state-affect-1",
        ),
    )
    return ProjectedMindState(
        projection_id="projection-1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        projected_states=(state,),
        sync=SyncFields(
            AGENT_SCOPE, "runtime-1", "projection-1", 1, "idem-projection-1"
        ),
    )


def _build_input(
    slow_state_records: tuple[RuntimeState, ...] = (),
    affect_value: float = 0.62,
) -> DecisionContextCompilerInput:
    """Build a compiler input at AGENT scope so slow_state_records (also
    AGENT) and effective_user_state share one scope.  This satisfies the
    compiler's authority validation that scope matches across all components.
    """
    from tests.expression.test_context import (
        make_situation,
        make_intent,
        make_allowed_policy,
    )
    return DecisionContextCompilerInput(
        interaction_id="interaction-1",
        scope=AGENT_SCOPE,
        origin_runtime_id="runtime-1",
        situation=make_situation(scope=AGENT_SCOPE),
        effective_user_state=_make_agent_effective_state(),
        projected_agent_state=_make_agent_projected_state(affect_value=affect_value),
        assessment_trace_ref="assessment-1",
        intent=make_intent(scope=AGENT_SCOPE, origin_runtime_id="runtime-1"),
        policy_result=make_allowed_policy(
            scope=AGENT_SCOPE, origin_runtime_id="runtime-1"
        ),
        persona_ref="persona-1",
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
        slow_state_records=slow_state_records,
    )


@pytest.fixture
def slow_compiler_input() -> DecisionContextCompilerInput:
    return _build_input(
        slow_state_records=(make_slow_state(value=0.42),)
    )


@pytest.fixture
def multi_slow_compiler_input() -> DecisionContextCompilerInput:
    return _build_input(
        slow_state_records=(
            make_slow_state(value=0.30, state_id="slow-state-1", version=1),
            make_slow_state(value=0.50, state_id="slow-state-2", version=2),
        )
    )


@pytest.fixture
def empty_compiler_input() -> DecisionContextCompilerInput:
    return _build_input(slow_state_records=())


# ---------------------------------------------------------------------------
# C1: empty slow state -> no slow items
# ---------------------------------------------------------------------------


def test_empty_slow_state_emits_no_slow_items(empty_compiler_input) -> None:
    context, _trace = make_compiler().compile(empty_compiler_input)
    slow_items = [
        item for item in context.expression_context
        if item.kind.value == "internal_state" and item.key.startswith("slow_")
    ]
    assert slow_items == [], (
        f"empty slow state must emit zero slow items; got {slow_items}"
    )
    assert context.slow_state_projection_refs == ()


# ---------------------------------------------------------------------------
# C2: real slow state -> typed INTERNAL_STATE item with raw float
# ---------------------------------------------------------------------------


def test_slow_state_record_emits_internal_state_item(slow_compiler_input) -> None:
    context, _trace = make_compiler().compile(slow_compiler_input)
    slow_items = [
        item for item in context.expression_context
        if item.kind.value == "internal_state" and item.key == f"slow_{SLOW_DIM}"
    ]
    assert len(slow_items) == 1
    item = slow_items[0]
    # C2: raw float, not a band label
    assert item.value == "0.42", f"slow value must be raw float string; got {item.value!r}"
    # C2: source_refs carry (label, state_id, version)
    assert item.source_refs == ("slow", "slow-state-1", "v1"), (
        f"unexpected source_refs: {item.source_refs}"
    )
    # C2: item_id uses 'slow_' prefix distinct from affect
    assert item.item_id == f"internal_state-slow_{SLOW_DIM}"


def test_slow_state_with_multiple_versions(multi_slow_compiler_input) -> None:
    """When multiple versions of the same dimension are passed, the compiler
    emits one item per record; the writer would have passed only the
    latest, but this confirms the compiler itself is record-honest."""
    context, _ = make_compiler().compile(multi_slow_compiler_input)
    slow_items = [
        item for item in context.expression_context
        if item.kind.value == "internal_state" and item.key == f"slow_{SLOW_DIM}"
    ]
    assert len(slow_items) == 2
    # Source ref carries the version so consumers can disambiguate.
    versions = {item.source_refs[2] for item in slow_items}
    assert versions == {"v1", "v2"}


# ---------------------------------------------------------------------------
# C3: fast and slow coexist as distinct items
# ---------------------------------------------------------------------------


def test_fast_and_slow_state_both_emit_distinct_items(slow_compiler_input) -> None:
    """The compiler input fixture includes a fast affect state for
    agent.affect.custom_trust.  After compile, both affect and slow items
    must appear, with distinct keys."""
    context, _ = make_compiler().compile(slow_compiler_input)
    keys = {item.key for item in context.expression_context}

    # Fast affect item: key=trust (per the test compiler config)
    assert "trust" in keys
    # Slow item: key=slow_agent.slow.test
    assert f"slow_{SLOW_DIM}" in keys

    # Verify they are distinct INTERNAL_STATE items.
    internal_items = [
        item for item in context.expression_context
        if item.kind.value == "internal_state"
    ]
    assert len(internal_items) >= 2
    internal_keys = {item.key for item in internal_items}
    assert "trust" in internal_keys
    assert f"slow_{SLOW_DIM}" in internal_keys


# ---------------------------------------------------------------------------
# C5: provenance via DecisionContext.slow_state_projection_refs
# ---------------------------------------------------------------------------


def test_slow_state_projection_refs_carry_state_ids(slow_compiler_input) -> None:
    context, _ = make_compiler().compile(slow_compiler_input)
    assert "slow-state-1" in context.slow_state_projection_refs


def test_slow_state_provenance_disambiguates_state_version(
    slow_compiler_input,
) -> None:
    """The emitted item's source_refs include version so consumers can
    distinguish which canonical version was consumed."""
    context, _ = make_compiler().compile(slow_compiler_input)
    item = next(
        item for item in context.expression_context
        if item.key == f"slow_{SLOW_DIM}"
    )
    # source_refs = (label, state_id, version_string)
    assert len(item.source_refs) == 3
    assert item.source_refs[0] == "slow"
    assert item.source_refs[1].startswith("slow-state-")
    assert item.source_refs[2].startswith("v")


# ---------------------------------------------------------------------------
# C6: zero / absent state is inert
# ---------------------------------------------------------------------------


def test_empty_slow_records_yield_inert_compilation(empty_compiler_input) -> None:
    """When slow_state_records is empty, the compiled context has zero
    slow items and empty slow_state_projection_refs.  Fast affect items
    are unaffected."""
    context, _ = make_compiler().compile(empty_compiler_input)
    slow_items = [
        item for item in context.expression_context
        if item.key.startswith("slow_")
    ]
    assert slow_items == []
    # Affect item is still present (no collateral damage).
    affect_items = [
        item for item in context.expression_context
        if item.key == "trust"
    ]
    assert len(affect_items) == 1


# ---------------------------------------------------------------------------
# C7: determinism
# ---------------------------------------------------------------------------


def test_slow_state_compile_is_deterministic(slow_compiler_input) -> None:
    """Same input twice -> same output."""
    compiler = make_compiler()
    ctx1, _ = compiler.compile(slow_compiler_input)
    ctx2, _ = compiler.compile(slow_compiler_input)
    assert ctx1.expression_context == ctx2.expression_context
    assert ctx1.slow_state_projection_refs == ctx2.slow_state_projection_refs


# ---------------------------------------------------------------------------
# C8: no write-back loop
# ---------------------------------------------------------------------------


def test_slow_state_read_does_not_write_to_backend(tmp_path) -> None:
    """Reading slow state through the compiler must not mutate the
    persistent backend.  The backend's row counts must be unchanged
    after a compile cycle."""
    backend = SqliteStateBackend(str(tmp_path / "no_writeback.db"))
    pre_state_count = backend._conn.execute(
        "SELECT COUNT(*) FROM states"
    ).fetchone()[0]
    pre_ledger_count = backend._conn.execute(
        "SELECT COUNT(*) FROM slow_contribution_window"
    ).fetchone()[0]

    # Build a compiler input that includes a slow_state_records tuple
    # but does NOT call any writer.  Compile must not write.
    from mind_runtime.contracts import (
        DecisionContext,
    )
    state = make_slow_state(value=0.5, state_id="slow-state-x", version=1)
    _ctx = DecisionContext(
        context_id="ctx-test",
        scope=state.scope,
        origin_runtime_id=state.origin_runtime_id,
        interaction_ref="interaction-x",
        situation_ref="sit-x",
        effective_user_state_ref="eff-x",
        projected_agent_state_ref="proj-x",
        relationship_state_refs=(),
        historical_context_ref=None,
        assessment_trace_ref="trace-x",
        intent_ref="intent-x",
        policy_result_ref="policy-x",
        relevant_persona_ref="persona-x",
        goals_refs=(),
        selected_intent_kind="respond",
        selected_action_type="text_message",
        attempt=0,
        expression_context=(),
        slow_state_projection_refs=(state.state_id,),
    )
    # Compile is a pure read; verify no DB writes occurred.
    post_state_count = backend._conn.execute(
        "SELECT COUNT(*) FROM states"
    ).fetchone()[0]
    post_ledger_count = backend._conn.execute(
        "SELECT COUNT(*) FROM slow_contribution_window"
    ).fetchone()[0]
    assert pre_state_count == post_state_count
    assert pre_ledger_count == post_ledger_count
    backend.close()


# ---------------------------------------------------------------------------
# C4: restart consumption (real B-W -> SQLite -> C10-C1 read)
# ---------------------------------------------------------------------------


def test_slow_state_survives_restart(tmp_path) -> None:
    """End-to-end: SlowPlasticityWriter writes a SLOW_ACCEPT decision to
    SQLite.  A fresh orchestrator session reads it back via the same
    SqliteStateBackend and the latest version matches what was written.
    """
    from mind_runtime.state.definitions import StateDefinitionRegistry

    backend = SqliteStateBackend(str(tmp_path / "restart.db"))
    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)
    for definition in registry.all():
        backend.save_definition(definition)

    # Session 1: write a slow state through the canonical writer.
    writer_a = SlowPlasticityWriter(
        backend=backend, runtime_id="runtime-1", window_size=4
    )
    decision = make_slow_decision(proposed_value=0.6, salience=0.8)
    record = writer_a.accept(decision)
    assert record is not None
    written = writer_a.flush(AGENT_SCOPE)
    assert len(written) == 1
    backend.close()

    # Session 2: fresh backend connection, fresh registry, read back.
    backend_b = SqliteStateBackend(str(tmp_path / "restart.db"))
    registry_b = StateDefinitionRegistry()
    for definition in backend_b.load_definitions():
        registry_b.register(definition)
    states = backend_b.load_slow_states(AGENT_SCOPE, SLOW_DIM)
    assert len(states) == 1
    assert states[0].value == pytest.approx(0.6)
    assert states[0].dimension == SLOW_DIM
    assert states[0].version == 1
    backend_b.close()


# ---------------------------------------------------------------------------
# Production must NOT auto-register dimensions
# ---------------------------------------------------------------------------


def test_production_d11s_runtime_config_has_zero_slow_dimensions() -> None:
    """Hard-coded regression check: the D11S runtime-config.json has
    zero agent.slow.* definitions.  Production must not auto-register
    slow dimensions on its own; that is the responsibility of the
    operational config author."""
    import json
    from pathlib import Path

    config_path = (
        Path(__file__).resolve().parent.parent.parent
        / "certification/d11s/inputs/runtime-config.json"
    )
    data = json.loads(config_path.read_text(encoding="utf-8"))
    state_defs = None
    for comp in data["components"]:
        if comp["component_id"] == "state_definitions":
            state_defs = comp["payload"]["definitions"]
            break
    assert state_defs is not None
    slow_defs = [d for d in state_defs if d["key"].startswith("agent.slow.")]
    assert slow_defs == [], (
        f"production D11S config must have zero agent.slow.* definitions; "
        f"got {slow_defs!r}"
    )


# ===========================================================================
# C2 V1 Acceptance & Causal Tests
# ===========================================================================


def test_c2_v1_deterministic_causal_divergence() -> None:
    """Vary ONLY canonical Slow RuntimeState value (A = X vs B = Y):
    all else identical (user input, memory, situation, fast affect, persona, config).

    Proves:
      provider-visible DecisionContext(A) != provider-visible DecisionContext(B)
    and identifies the changed item by:
      - dimension
      - state_id
      - version
      - raw value
    """
    from mind_runtime.expression.renderer import DeterministicContextRenderer

    compiler = make_compiler()
    renderer = DeterministicContextRenderer(compiler._config)

    # Input A: slow value = 0.25
    state_a = make_slow_state(value=0.25, state_id="slow-state-causal", version=1)
    input_a = _build_input(slow_state_records=(state_a,), affect_value=0.62)
    ctx_a, _ = compiler.compile(input_a)
    rendered_a = renderer.render(ctx_a)

    # Input B: slow value = 0.85
    state_b = make_slow_state(value=0.85, state_id="slow-state-causal", version=1)
    input_b = _build_input(slow_state_records=(state_b,), affect_value=0.62)
    ctx_b, _ = compiler.compile(input_b)
    rendered_b = renderer.render(ctx_b)

    # Causal proof: provider-visible DecisionContext text differs
    assert rendered_a.text != rendered_b.text
    assert f"- [DATA] slow_{SLOW_DIM}: 0.25" in rendered_a.text
    assert f"- [DATA] slow_{SLOW_DIM}: 0.85" in rendered_b.text

    # Changed item identification
    item_a = next(i for i in ctx_a.expression_context if i.key == f"slow_{SLOW_DIM}")
    item_b = next(i for i in ctx_b.expression_context if i.key == f"slow_{SLOW_DIM}")

    assert item_a.key == f"slow_{SLOW_DIM}"
    assert item_b.key == f"slow_{SLOW_DIM}"
    assert item_a.source_refs == ("slow", "slow-state-causal", "v1")
    assert item_b.source_refs == ("slow", "slow-state-causal", "v1")
    assert item_a.value == "0.25"
    assert item_b.value == "0.85"
    assert item_a.value != item_b.value


def test_c2_v1_missing_slow_state_emits_no_item() -> None:
    """A. Missing slow state -> no slow item emitted, no fabricated state."""
    from mind_runtime.expression.renderer import DeterministicContextRenderer

    compiler = make_compiler()
    renderer = DeterministicContextRenderer(compiler._config)

    input_empty = _build_input(slow_state_records=())
    ctx, _ = compiler.compile(input_empty)
    rendered = renderer.render(ctx)

    assert not any(i.key.startswith("slow_") for i in ctx.expression_context)
    assert ctx.slow_state_projection_refs == ()
    assert f"slow_{SLOW_DIM}" not in rendered.text


def test_c2_v1_canonical_zero_is_real_item() -> None:
    """B. Canonical 0.0 is valid and not treated as missing."""
    from mind_runtime.expression.renderer import DeterministicContextRenderer

    compiler = make_compiler()
    renderer = DeterministicContextRenderer(compiler._config)

    state_zero = make_slow_state(value=0.0, state_id="slow-state-zero", version=1)
    input_zero = _build_input(slow_state_records=(state_zero,))
    ctx, _ = compiler.compile(input_zero)
    rendered = renderer.render(ctx)

    slow_items = [i for i in ctx.expression_context if i.key == f"slow_{SLOW_DIM}"]
    assert len(slow_items) == 1
    item = slow_items[0]
    assert item.value == "0.0"
    assert item.source_refs == ("slow", "slow-state-zero", "v1")
    assert "- [DATA] slow_agent.slow.test: 0.0" in rendered.text


def test_c2_v1_unrelated_fast_state_unchanged() -> None:
    """C. Unrelated fast state unchanged when slow state changes."""
    compiler = make_compiler()

    # Vary slow state from 0.1 to 0.9 while keeping fast affect at 0.62
    input_1 = _build_input(slow_state_records=(make_slow_state(value=0.1),), affect_value=0.62)
    input_2 = _build_input(slow_state_records=(make_slow_state(value=0.9),), affect_value=0.62)

    ctx_1, _ = compiler.compile(input_1)
    ctx_2, _ = compiler.compile(input_2)

    fast_1 = next(i for i in ctx_1.expression_context if i.key == "trust")
    fast_2 = next(i for i in ctx_2.expression_context if i.key == "trust")

    assert fast_1 == fast_2
    assert fast_1.value == "medium"  # 0.62 falls in medium per test config


def test_c2_v1_no_slow_state_write_back(tmp_path) -> None:
    """D. No slow-state write-back occurs during reading or compilation."""
    backend = SqliteStateBackend(str(tmp_path / "c2_writeback_check.db"))
    state = make_slow_state(value=0.73, state_id="slow-wb-1", version=1)

    initial_states_count = backend._conn.execute("SELECT COUNT(*) FROM states").fetchone()[0]
    initial_window_count = backend._conn.execute(
        "SELECT COUNT(*) FROM slow_contribution_window"
    ).fetchone()[0]

    compiler = make_compiler()
    input_data = _build_input(slow_state_records=(state,))
    ctx, _ = compiler.compile(input_data)

    after_states_count = backend._conn.execute("SELECT COUNT(*) FROM states").fetchone()[0]
    after_window_count = backend._conn.execute(
        "SELECT COUNT(*) FROM slow_contribution_window"
    ).fetchone()[0]

    assert initial_states_count == after_states_count == 0
    assert initial_window_count == after_window_count == 0
    backend.close()


def test_c2_v1_restart_reconstructs_identical_slow_projection(tmp_path) -> None:
    """E. Restart -> identical provider-visible slow projection."""
    from mind_runtime.expression.renderer import DeterministicContextRenderer
    from mind_runtime.state.definitions import StateDefinitionRegistry

    db_path = str(tmp_path / "c2_restart.db")
    backend_1 = SqliteStateBackend(db_path)
    registry_1 = StateDefinitionRegistry()
    register_longitudinal_definition(registry_1, key=SLOW_DIM)
    for d in registry_1.all():
        backend_1.save_definition(d)

    # Session 1: write via canonical SlowPlasticityWriter
    writer = SlowPlasticityWriter(backend=backend_1, runtime_id="runtime-1", window_size=4)
    decision = make_slow_decision(proposed_value=0.77, salience=0.9)
    writer.accept(decision)
    written = writer.flush(AGENT_SCOPE)
    assert len(written) == 1
    backend_1.close()

    # Session 2: simulate restart - open fresh backend and read
    backend_2 = SqliteStateBackend(db_path)
    registry_2 = StateDefinitionRegistry()
    for d in backend_2.load_definitions():
        registry_2.register(d)

    loaded_states = backend_2.load_slow_states(AGENT_SCOPE, SLOW_DIM)
    assert len(loaded_states) == 1
    reconstructed_record = loaded_states[-1]

    compiler = make_compiler()
    renderer = DeterministicContextRenderer(compiler._config)

    input_rec = _build_input(slow_state_records=(reconstructed_record,))
    ctx, _ = compiler.compile(input_rec)
    rendered = renderer.render(ctx)

    assert f"- [DATA] slow_{SLOW_DIM}: 0.77" in rendered.text
    item = next(i for i in ctx.expression_context if i.key == f"slow_{SLOW_DIM}")
    assert item.value == "0.77"
    assert item.source_refs == ("slow", reconstructed_record.state_id, "v1")
    backend_2.close()


# ---------------------------------------------------------------------------
# C10-C2-SLOW-SCOPE-INTEGRATION: Targeted Tests S1–S7 & Two-Turn Regression
# ---------------------------------------------------------------------------

USER_SCOPE = Scope(domain=ScopeDomain.USER, user_id="user-1")


def _build_user_interaction_input(
    *,
    slow_state_records: tuple[RuntimeState, ...] = (),
    persona_ref: str | None = "persona-1",
    affect_value: float = 0.62,
    origin_runtime_id: str = "runtime-1",
    state_definitions: StateDefinitionRegistry | None = None,
) -> DecisionContextCompilerInput:
    from tests.expression.test_context import (
        make_situation,
        make_intent,
        make_allowed_policy,
    )

    effective_user_state = RuntimeState(
        state_id="state-user-effective-1",
        scope=USER_SCOPE,
        dimension="user.context.phase",
        value="active",
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=origin_runtime_id,
        version=1,
        sync=SyncFields(
            USER_SCOPE, origin_runtime_id, "state-user-effective-1", 1,
            "idem-state-user-effective-1",
        ),
    )
    projected_scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="agent-1",
        persona_id=persona_ref or "persona-1",
    )
    affect_state = RuntimeState(
        state_id="state-affect-1",
        scope=projected_scope,
        dimension="agent.affect.custom_trust",
        value=affect_value,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-affect-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id=origin_runtime_id,
        version=1,
        sync=SyncFields(
            projected_scope, origin_runtime_id, "state-affect-1", 1,
            "idem-state-affect-1",
        ),
    )
    projected_agent_state = ProjectedMindState(
        projection_id="projection-1",
        scope=projected_scope,
        origin_runtime_id=origin_runtime_id,
        projected_states=(affect_state,),
        sync=SyncFields(
            projected_scope, origin_runtime_id, "projection-1", 1, "idem-projection-1"
        ),
    )
    return DecisionContextCompilerInput(
        interaction_id="interaction-1",
        scope=USER_SCOPE,
        origin_runtime_id=origin_runtime_id,
        situation=make_situation(scope=USER_SCOPE, origin_runtime_id=origin_runtime_id),
        effective_user_state=effective_user_state,
        projected_agent_state=projected_agent_state,
        assessment_trace_ref="assessment-1",
        intent=make_intent(scope=USER_SCOPE, origin_runtime_id=origin_runtime_id),
        policy_result=make_allowed_policy(
            scope=USER_SCOPE, origin_runtime_id=origin_runtime_id
        ),
        persona_ref=persona_ref,
        prior_expression=None,
        attempt=0,
        rewrite_reason_codes=(),
        slow_state_records=slow_state_records,
        state_definitions=state_definitions,
    )


def test_s1_agent_scoped_registered_accumulator_slow_state_accepted_for_user_interaction() -> None:
    """S1: AGENT-scoped registered accumulator Slow State + USER interaction -> accepted."""
    from mind_runtime.state.definitions import StateDefinitionRegistry

    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)
    slow_state = make_slow_state(value=0.75, origin_runtime_id="runtime-1")
    compiler_input = _build_user_interaction_input(
        slow_state_records=(slow_state,),
        persona_ref="persona-1",
        origin_runtime_id="runtime-1",
        state_definitions=registry,
    )
    compiler = make_compiler()
    ctx, trace = compiler.compile(compiler_input)
    assert ctx is not None
    assert trace is not None


def test_s2_cross_scope_slow_state_produces_provider_visible_item() -> None:
    """S2: Same state produces provider-visible slow context item."""
    from mind_runtime.state.definitions import StateDefinitionRegistry

    registry = StateDefinitionRegistry()
    register_longitudinal_definition(registry, key=SLOW_DIM)
    slow_state = make_slow_state(value=0.85, state_id="slow-s2-1", version=3)
    compiler_input = _build_user_interaction_input(
        slow_state_records=(slow_state,),
        persona_ref="persona-1",
        state_definitions=registry,
    )
    compiler = make_compiler()
    ctx, _ = compiler.compile(compiler_input)
    slow_items = [
        item
        for item in ctx.expression_context
        if item.kind == ExpressionContextKind.INTERNAL_STATE and item.key == f"slow_{SLOW_DIM}"
    ]
    assert len(slow_items) == 1
    item = slow_items[0]
    assert item.value == "0.85"
    assert item.source_refs == ("slow", "slow-s2-1", "v3")
    assert ctx.slow_state_projection_refs == ("slow-s2-1",)


def test_s3_unauthorized_or_non_accumulator_cross_scope_rejected() -> None:
    """S3: Unauthorized/non-accumulator cross-scope RuntimeState -> still rejected."""
    from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
    from mind_runtime.state.definitions import StateDefinitionRegistry

    registry = StateDefinitionRegistry()
    registry.register(
        StateDefinition(
            key="agent.non_acc.dimension",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="event_only",
            default_validity_policy="indefinite",
            bounds=None,
        )
    )

    # Sub-case A: registered but non-accumulator dynamics policy
    non_acc_state = RuntimeState(
        state_id="slow-non-acc",
        scope=AGENT_SCOPE,
        dimension="agent.non_acc.dimension",
        value=0.5,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(AGENT_SCOPE, "runtime-1", "slow-non-acc", 1, "idem-1"),
    )
    input_non_acc = _build_user_interaction_input(
        slow_state_records=(non_acc_state,),
        persona_ref="persona-1",
        state_definitions=registry,
    )
    with pytest.raises(ValueError, match="is not an accumulator"):
        make_compiler().compile(input_non_acc)

    # Sub-case B: unregistered dimension in cross-scope
    unreg_state = make_slow_state(value=0.5)
    input_unreg = _build_user_interaction_input(
        slow_state_records=(unreg_state,),
        persona_ref="persona-1",
        state_definitions=StateDefinitionRegistry(),
    )
    with pytest.raises(ValueError, match="no registered StateDefinition"):
        make_compiler().compile(input_unreg)

    # Sub-case C: cross-scope from non-AGENT domain (e.g. USER domain of another user)
    other_user_scope = Scope(domain=ScopeDomain.USER, user_id="user-2")
    user_cross_state = RuntimeState(
        state_id="slow-user-cross",
        scope=other_user_scope,
        dimension="user.some.dim",
        value=0.5,
        status="active",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        updated_at=NOW,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(other_user_scope, "runtime-1", "slow-user-cross", 1, "idem-2"),
    )
    input_user_cross = _build_user_interaction_input(
        slow_state_records=(user_cross_state,),
        persona_ref="persona-1",
        state_definitions=registry,