import json
import socket
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

import mind_runtime.validation.composition as subject
from mind_runtime.contracts import (
    Authority,
    HistoricalContextQuery,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.emotional_transition.history import HistoryProviderUnavailable
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.pipeline.checkpoints import SqliteCheckpointStore
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.state.persistence import SqliteStateBackend
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDecision,
    HomeostasisDisposition,
)
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)
from mind_runtime.validation import (
    canonical_json_bytes,
    decode_runtime_manifest,
    load_horizon_template,
    load_restart_fixture,
    load_runtime_config_manifest,
    sha256_bytes,
)
from mind_runtime.validation.contracts import HomeostasisConfig
from mind_runtime.validation.schedule import SimulationClock

ROOT = Path(__file__).parents[2]
INPUTS = ROOT / "certification/d11s/inputs"
MANIFEST = INPUTS / "runtime-config.json"
NOW = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def make_runtime_config(tmp_path: Path) -> subject.CertificationRuntimeConfig:
    return subject.CertificationRuntimeConfig(
        repository_root=ROOT,
        manifest_path=MANIFEST,
        manifest_sha256=sha256_bytes(MANIFEST.read_bytes()),
        durable_paths=subject.DurablePaths.under(tmp_path),
        clock=SimulationClock(NOW),
        certification_id="certification-1",
        agent=FakeAgent(("当然。",)),
    )


def test_composition_uses_real_orchestrator_and_existing_backends(tmp_path: Path) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        assert isinstance(composition.orchestrator, TurnOrchestrator)
        assert composition.component_inventory() == {
            "effective_state": "ResolverEffectiveStatePort",
            "situation": "SituationBuilder",
            "transition": "EngineEmotionalTransitionPort",
            "history": "BoundedHistoricalContextAdapter",
            "intent": "DeterministicIntentEngine",
            "policy": "DeterministicActionPolicy",
            "compiler": "DecisionContextCompiler",
            "renderer": "DeterministicContextRenderer",
            "guard": "DeterministicExpressionGuardChain",
            "expression": "DeterministicExpressionCoordinator",
            "previous_expression": "FixedPreviousExpressionPort",
            "facts": "FactIngestService",
            "intent_lifecycle": "IntentLifecycleService",
        }
        assert all("Stub" not in name for name in composition.component_inventory().values())
        assert composition.table_inventory() == {
            "facts": ("evidence", "interactions", "observations"),
            "state": (
                "slow_contribution_window",
                "sqlite_sequence",
                "state_definitions",
                "state_transitions",
                "states",
            ),
            "intents": ("intent_transitions", "intents"),
            "checkpoints": ("checkpoints",),
        }
        assert composition.capture_snapshot().checkpoint_recovery == "no_interaction"

        orchestrator = composition.orchestrator
        assert orchestrator.fact_ingest.__class__.__name__ == "FactIngestService"
        assert orchestrator.effective_state.__class__.__name__ == "ResolverEffectiveStatePort"
        assert orchestrator.emotional_transition.__class__.__name__ == (
            "EngineEmotionalTransitionPort"
        )
        assert orchestrator.intent_engine.__class__.__name__ == "DeterministicIntentEngine"
        assert orchestrator.action_policy.__class__.__name__ == "DeterministicActionPolicy"
        assert orchestrator.context_renderer.__class__.__name__ == ("DeterministicContextRenderer")
        assert orchestrator.expression_guard.__class__.__name__ == (
            "DeterministicExpressionGuardChain"
        )
        assert orchestrator.expression_coordinator.__class__.__name__ == (
            "DeterministicExpressionCoordinator"
        )
    finally:
        composition.close()

    assert {path.name for path in tmp_path.iterdir()} == {
        "facts.sqlite",
        "state.sqlite",
        "intents.sqlite",
        "checkpoints.sqlite",
    }


def test_close_is_idempotent_and_use_after_close_fails(tmp_path: Path) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))

    composition.close()
    composition.close()

    with pytest.raises(RuntimeError, match="closed"):
        composition.capture_snapshot()
    with pytest.raises(RuntimeError, match="closed"):
        composition.tick()
    with pytest.raises(RuntimeError, match="closed"):
        composition.apply_event(load_horizon_template(INPUTS / "horizon-30.json").events[0])


def test_apply_event_uses_manifest_interaction_binding_and_real_pipeline(tmp_path: Path) -> None:
    config = make_runtime_config(tmp_path)
    composition = subject.build_composition(config)
    event = load_horizon_template(INPUTS / "horizon-30.json").events[1]
    config.clock.advance_to(NOW + event.at_offset)

    composition.apply_event(event)
    snapshot = composition.capture_snapshot()
    composition.close()

    assert snapshot.accepted_event_refs == ("semantic-observation-h30-evidence-positive",)
    assert snapshot.transition_refs
    assert snapshot.canonical_state_refs
    assert snapshot.candidate_intent_refs
    assert snapshot.selected_intent_ref is not None
    assert snapshot.policy_result_ref is not None

    backend = SqliteFactBackend(config.durable_paths.facts_db)
    try:
        interactions = backend.load_interactions()
    finally:
        backend.close()
    assert len(interactions) == 1
    interaction = interactions[0]
    assert interaction.channel == "d11s-fixed-clock"
    assert interaction.scope == Scope(ScopeDomain.USER, user_id="user-1")
    assert "certification-1" in interaction.interaction_id
    assert event.event_id in interaction.interaction_id
    assert interaction.status.value == "committed"


def test_apply_event_rejects_evidence_outside_manifest_scope(tmp_path: Path) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))
    event = load_horizon_template(INPUTS / "horizon-30.json").events[1]
    evidence = event.evidence[0]
    other_scope = Scope(ScopeDomain.USER, user_id="user-2")
    changed = replace(
        evidence,
        scope=other_scope,
        authority=Authority(other_scope, evidence.authority.level, evidence.authority.source_id),
        sync=SyncFields(
            other_scope,
            evidence.sync.origin_runtime_id,
            evidence.sync.object_id,
            evidence.sync.version,
            evidence.sync.idempotency_key,
        ),
    )

    try:
        with pytest.raises(ValueError, match="certification scope"):
            composition.apply_event(replace(event, evidence=(changed,)))
    finally:
        composition.close()


def test_build_verifies_whole_manifest_hash_before_opening_stores(tmp_path: Path) -> None:
    config = replace(make_runtime_config(tmp_path), manifest_sha256="0" * 64)

    with pytest.raises(ValueError, match="runtime-config.json byte hash"):
        subject.build_composition(config)

    assert not tmp_path.exists() or tuple(tmp_path.iterdir()) == ()


def test_build_decodes_the_exact_once_verified_manifest_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = MANIFEST.read_bytes()
    raw = json.loads(original)
    fact_ingest = next(item for item in raw["components"] if item["component_id"] == "fact_ingest")
    fact_ingest["payload"]["certification_channel"] = "swapped-after-verification"
    fact_ingest["payload_sha256"] = sha256_bytes(canonical_json_bytes(fact_ingest["payload"]))
    swapped = json.dumps(raw, separators=(",", ":")).encode()
    manifest_path = tmp_path / "runtime-config.json"
    real_read_bytes = Path.read_bytes
    authoritative_reads = 0

    def attacked_read_bytes(path: Path) -> bytes:
        nonlocal authoritative_reads
        if path == manifest_path:
            authoritative_reads += 1
            return original if authoritative_reads == 1 else swapped
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", attacked_read_bytes)
    stores = tmp_path / "stores"
    config = replace(
        make_runtime_config(stores),
        manifest_path=manifest_path,
        manifest_sha256=sha256_bytes(original),
    )

    composition = subject.build_composition(config)
    event = load_horizon_template(INPUTS / "horizon-30.json").events[0]
    try:
        composition.apply_event(event)
    finally:
        composition.close()

    backend = SqliteFactBackend(config.durable_paths.facts_db)
    try:
        assert backend.load_interactions()[0].channel == "d11s-fixed-clock"
    finally:
        backend.close()
    assert authoritative_reads == 1


def test_build_rejects_hash_only_component_even_with_matching_outer_hash(tmp_path: Path) -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["components"][0].pop("payload")
    changed = tmp_path / "runtime-config.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    stores = tmp_path / "stores"
    config = replace(
        make_runtime_config(stores),
        manifest_path=changed,
        manifest_sha256=sha256_bytes(changed.read_bytes()),
    )

    with pytest.raises(ValueError, match="component schema drift"):
        subject.build_composition(config)

    assert not stores.exists() or tuple(stores.iterdir()) == ()


def test_composition_does_not_open_network_or_start_background_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket, "socket", lambda *_args, **_kwargs: pytest.fail("network forbidden")
    )
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _self: pytest.fail("background thread forbidden"),
    )

    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        composition.apply_event(load_horizon_template(INPUTS / "horizon-30.json").events[0])
    finally:
        composition.close()


@pytest.mark.parametrize(
    ("paths", "message"),
    [
        (("not-a-path", Path("b"), Path("c"), Path("d")), "Path values"),
        ((Path("a"), Path("a"), Path("c"), Path("d")), "distinct"),
        (
            (Path("receipts.sqlite"), Path("b"), Path("c"), Path("d")),
            "cannot be durable",
        ),
        ((Path("a"), Path("memory.sqlite"), Path("c"), Path("d")), "cannot be durable"),
    ],
)
def test_durable_paths_reject_non_paths_aliases_and_forbidden_planes(
    paths: tuple[object, object, object, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        subject.DurablePaths(*cast(Any, paths))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"repository_root": "not-a-path"}, "Path values"),
        ({"manifest_path": "not-a-path"}, "Path values"),
        ({"manifest_sha256": "0"}, "SHA-256"),
        ({"manifest_sha256": "z" * 64}, "SHA-256"),
        ({"durable_paths": object()}, "DurablePaths"),
        ({"clock": object()}, "SimulationClock"),
        ({"certification_id": ""}, "non-empty"),
        ({"certification_id": object()}, "non-empty"),
        ({"agent": object()}, "AgentPort"),
    ],
)
def test_runtime_config_rejects_unbound_values(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(make_runtime_config(tmp_path), **cast(Any, changes))


def test_scheduled_history_provider_fails_closed_without_or_across_scope() -> None:
    provider = subject._ScheduledHistoricalProvider()
    configured = Scope(ScopeDomain.USER, user_id="user-1")
    other = Scope(ScopeDomain.USER, user_id="user-2")
    query = HistoricalContextQuery("query-1", configured, "runtime-1", None, None, (), 8)
    with pytest.raises(HistoryProviderUnavailable):
        provider.query(query)

    bundle = load_horizon_template(INPUTS / "horizon-30.json").events[4].historical_context
    assert bundle is not None
    provider.current = bundle
    with pytest.raises(ValueError, match="scope"):
        provider.query(replace(query, scope=other))


def test_apply_event_aborts_real_interaction_when_pipeline_rejects_payload(
    tmp_path: Path,
) -> None:
    config = make_runtime_config(tmp_path)
    composition = subject.build_composition(config)
    event = load_horizon_template(INPUTS / "horizon-30.json").events[1]
    malformed = replace(event.evidence[0], payload={"attributes": {}})
    try:
        with pytest.raises(ValueError, match="kind"):
            composition.apply_event(replace(event, evidence=(malformed,)))
    finally:
        composition.close()

    backend = SqliteFactBackend(config.durable_paths.facts_db)
    try:
        assert backend.load_interactions()[0].status.value == "aborted"
    finally:
        backend.close()


def test_apply_event_rejects_history_outside_manifest_scope(tmp_path: Path) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))
    event = load_horizon_template(INPUTS / "horizon-30.json").events[4]
    assert event.historical_context is not None
    changed_history = replace(
        event.historical_context,
        scope=Scope(ScopeDomain.USER, user_id="user-2"),
    )
    try:
        with pytest.raises(ValueError, match="historical context"):
            composition.apply_event(replace(event, historical_context=changed_history))
    finally:
        composition.close()


def test_build_rejects_non_config_and_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CertificationRuntimeConfig"):
        subject.build_composition(cast(Any, object()))

    config = replace(make_runtime_config(tmp_path), manifest_path=tmp_path / "missing.json")
    with pytest.raises(ValueError, match="unavailable"):
        subject.build_composition(config)


def test_build_rejects_stub_component_and_closes_opened_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubFactIngestService(FactIngestService):
        pass

    monkeypatch.setattr(subject, "FactIngestService", StubFactIngestService)
    with pytest.raises(ValueError, match="Stub components"):
        subject.build_composition(make_runtime_config(tmp_path))

    paths = subject.DurablePaths.under(tmp_path)
    for path in (paths.facts_db, paths.state_db, paths.intents_db, paths.checkpoints_db):
        path.rename(path.with_suffix(".closed"))


@pytest.mark.parametrize(
    ("backend_name", "backend_type", "tables", "opened_planes"),
    [
        ("facts", SqliteFactBackend, ("evidence", "interactions"), ("facts",)),
        ("state", SqliteStateBackend, ("state_definitions", "states"), ("facts", "state")),
        ("intents", SqliteIntentBackend, ("intents",), ("facts", "state", "intents")),
        (
            "checkpoints",
            SqliteCheckpointStore,
            (),
            ("facts", "state", "intents", "checkpoints"),
        ),
    ],
)
def test_build_rejects_nonexact_sqlite_table_inventory_and_closes_partial_owners(
    backend_name: str,
    backend_type: type[object],
    tables: tuple[str, ...],
    opened_planes: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_type, "table_names", lambda _self: tables)

    with pytest.raises(ValueError, match=f"{backend_name} SQLite table inventory"):
        subject.build_composition(make_runtime_config(tmp_path))

    paths = subject.DurablePaths.under(tmp_path)
    for plane in opened_planes:
        path = getattr(paths, f"{plane}_db")
        path.rename(path.with_suffix(".closed"))


def test_build_rejects_actual_rogue_native_memory_table(tmp_path: Path) -> None:
    paths = subject.DurablePaths.under(tmp_path)
    backend = SqliteFactBackend(paths.facts_db)
    backend.close()
    connection = sqlite3.connect(paths.facts_db)
    try:
        connection.execute("CREATE TABLE rogue_native_memory (id TEXT PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="facts SQLite table inventory"):
        subject.build_composition(make_runtime_config(tmp_path))

    paths.facts_db.rename(paths.facts_db.with_suffix(".closed"))


def ambiguous_states() -> tuple[RuntimeState, RuntimeState]:
    state = load_restart_fixture(INPUTS / "restart-g12.json").states[-1]
    conflicting_id = f"{state.state_id}-same-version-conflict"
    conflicting = replace(
        state,
        state_id=conflicting_id,
        sync=replace(
            state.sync,
            object_id=conflicting_id,
            idempotency_key=f"{state.sync.idempotency_key}-same-version-conflict",
        ),
    )
    return state, conflicting


@pytest.mark.parametrize("reverse_insertion", [False, True])
def test_build_rejects_insertion_order_independent_current_state_ambiguity(
    reverse_insertion: bool, tmp_path: Path
) -> None:
    paths = subject.DurablePaths.under(tmp_path)
    states = ambiguous_states()
    backend = SqliteStateBackend(paths.state_db)
    try:
        for state in reversed(states) if reverse_insertion else states:
            assert backend.save_state(state)
    finally:
        backend.close()

    with pytest.raises(ValueError, match="ambiguous current State"):
        subject.build_composition(make_runtime_config(tmp_path))

    paths.state_db.rename(paths.state_db.with_suffix(".closed"))


def test_daily_capture_rejects_new_equal_version_current_state_ambiguity(
    tmp_path: Path,
) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))
    backend = SqliteStateBackend(subject.DurablePaths.under(tmp_path).state_db)
    try:
        for state in ambiguous_states():
            assert backend.save_state(state)
    finally:
        backend.close()

    try:
        with pytest.raises(ValueError, match="ambiguous current State"):
            composition.capture_snapshot()
    finally:
        composition.close()


def test_apply_event_rejects_non_event(tmp_path: Path) -> None:
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        with pytest.raises(ValueError, match="SimulationEvent"):
            composition.apply_event(cast(Any, object()))
    finally:
        composition.close()


class MockAppraisalTransport:
    """Offline test transport returning structured model appraisal response."""

    def __init__(self, response_payload: dict[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.response_payload = response_payload or {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "meanings": ["relational_commitment"],
                                "valence": "positive",
                                "relationship_relevance": "relational_security",
                                "salience": 0.88,
                                "appraisal_confidence": 0.82,
                                "supporting_evidence_refs": ["h30-evidence-positive"],
                            }
                        )
                    }
                }
            ]
        }

    def post_json(
        self, url: str, framed: dict[str, object], timeout_s: float
    ) -> dict[str, object]:
        self.calls.append({"url": url, "framed": framed, "timeout_s": timeout_s})
        return self.response_payload


def test_production_appraisal_activation_e2e_persists_slow_state_with_value_proof(
    tmp_path: Path,
) -> None:
    """Mandatory real production E2E and value proof:

    runtime-config.json -> build_composition() -> apply_event() -> SQLite slow state persisted.
    Proves candidate.confidence, appraisal.confidence, salience, proposed_value, disposition,
    and persisted value across the entire closed pipeline.
    """
    transport = MockAppraisalTransport()
    config = replace(make_runtime_config(tmp_path), appraisal_transport=transport)
    composition = subject.build_composition(config)

    event = load_horizon_template(INPUTS / "horizon-30.json").events[1]
    config.clock.advance_to(NOW + event.at_offset)

    try:
        composition.apply_event(event)

        # 1. Transport was invoked exactly once with candidate context
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert "model-appraisal-v1" in str(call["framed"])
        assert "h30-evidence-positive" in str(call["framed"])

        # 2. Transition produced slow decisions
        turn = composition.orchestrator._turn
        assert turn is not None
        assert turn.slow_decisions

        # Verify decoded thresholds used by production composition
        transition_port = composition.orchestrator.emotional_transition
        gate = getattr(transition_port, "_homeostasis_gate", None)
        assert gate is not None
        assert gate.config.salience_floor_fast_apply == 0.70
        assert gate.config.salience_floor_slow_accept == 0.60
        assert gate.config.confidence_floor_slow == 0.80

        # Find the longitudinal decision
        long_decision = next(
            d for d in turn.slow_decisions
            if d.candidate.target_dimension == "agent.longitudinal.relationship_security"
        )

        # Value Proof Assertions:
        # Carrier A: candidate attribution certainty
        assert long_decision.candidate.confidence == 1.0
        # Carrier B: appraisal certainty (from model proposal, distinct from attribution)
        # Sourced from proposal appraisal_confidence = 0.82
        # Gate candidate carries salience and proposed_value
        assert long_decision.candidate.salience == 0.88
        assert long_decision.candidate.proposed_value == 0.80
        assert long_decision.decision.value == "slow_accept"
        assert long_decision.candidate.evidence_refs == ("h30-evidence-positive",)

        # 3. Canonical Slow State persisted to SQLite state backend
        state_backend = SqliteStateBackend(config.durable_paths.state_db)
        try:
            agent_scope = Scope(
                domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"
            )
            slow_states = state_backend.load_slow_states(
                agent_scope, "agent.longitudinal.relationship_security"
            )
            assert len(slow_states) >= 1
            persisted = slow_states[-1]
            assert persisted.dimension == "agent.longitudinal.relationship_security"
            assert persisted.value == 0.80
            assert persisted.status == "active"
            assert persisted.evidence_refs == ("h30-evidence-positive",)

            # Rolling-window table verification
            cursor = state_backend._conn.cursor()
            rows = cursor.execute(
                "SELECT target_dimension, proposed_value, salience, evidence_refs "
                "FROM slow_contribution_window "
                "WHERE target_dimension = 'agent.longitudinal.relationship_security'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "agent.longitudinal.relationship_security"
            assert rows[0][1] == 0.80
            assert rows[0][2] == 0.88
        finally:
            state_backend.close()

    finally:
        composition.close()


def test_production_appraisal_negative_e2e_forced_failure_zero_slow_write(
    tmp_path: Path,
) -> None:
    """Negative E2E: forced model failure -> salience=None -> REJECT -> zero slow write."""
    class FailingAppraisalTransport:
        def post_json(
            self, url: str, framed: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            raise RuntimeError("forced provider transport outage")

    transport = FailingAppraisalTransport()
    config = replace(make_runtime_config(tmp_path), appraisal_transport=transport)
    composition = subject.build_composition(config)

    event = load_horizon_template(INPUTS / "horizon-30.json").events[1]
    config.clock.advance_to(NOW + event.at_offset)

    try:
        composition.apply_event(event)

        turn = composition.orchestrator._turn
        assert turn is not None
        assert turn.slow_decisions

        for decision in turn.slow_decisions:
            assert decision.decision.value == "reject"
            assert decision.reason_code == "salience_unavailable_reject"

        # Verify zero writes to SQLite state backend
        state_backend = SqliteStateBackend(config.durable_paths.state_db)
        try:
            agent_scope = Scope(
                domain=ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"
            )
            slow_states = state_backend.load_slow_states(
                agent_scope, "agent.longitudinal.relationship_security"
            )
            assert slow_states == ()

            cursor = state_backend._conn.cursor()
            rows = cursor.execute(
                "SELECT * FROM slow_contribution_window"
            ).fetchall()
            assert len(rows) == 0
        finally:
            state_backend.close()

    finally:
        composition.close()


def test_production_appraisal_config_negative_missing_strategy_fails(
    tmp_path: Path,
) -> None:
    """Config negative test: missing appraisal_producer_strategy fails validation."""
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["components"] = [
        c for c in raw["components"] if c["component_id"] != "appraisal_producer_strategy"
    ]
    missing_manifest_path = tmp_path / "runtime-config.json"
    missing_manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    stores = tmp_path / "stores"
    config = replace(
        make_runtime_config(stores),
        manifest_path=missing_manifest_path,
        manifest_sha256=sha256_bytes(missing_manifest_path.read_bytes()),
    )

    with pytest.raises(ValueError, match="closed registry"):
        subject.build_composition(config)


def test_h1_production_manifest_decodes_homeostasis_thresholds() -> None:
    """H1: production manifest decodes: 0.70 / 0.60 / 0.80."""
    manifest = load_runtime_config_manifest(MANIFEST)
    decoded = decode_runtime_manifest(manifest)
    assert isinstance(decoded.homeostasis, HomeostasisConfig)
    assert decoded.homeostasis.salience_floor_fast_apply == 0.70
    assert decoded.homeostasis.salience_floor_slow_accept == 0.60
    assert decoded.homeostasis.confidence_floor_slow == 0.80


def test_h2_missing_homeostasis_config_fails_validation(tmp_path: Path) -> None:
    """H2: missing Homeostasis config -> validation failure before runtime starts."""
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["components"] = [
        c for c in raw["components"] if c["component_id"] != "homeostasis"
    ]
    missing_manifest_path = tmp_path / "runtime-config.json"
    missing_manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    stores = tmp_path / "stores"
    config = replace(
        make_runtime_config(stores),
        manifest_path=missing_manifest_path,
        manifest_sha256=sha256_bytes(missing_manifest_path.read_bytes()),
    )

    with pytest.raises(ValueError, match="closed registry"):
        subject.build_composition(config)


@pytest.mark.parametrize(
    "missing_field",
    [
        "salience_floor_fast_apply",
        "salience_floor_slow_accept",
        "confidence_floor_slow",
    ],
)
def test_h3_missing_any_homeostasis_field_fails_validation(missing_field: str) -> None:
    """H3: missing any one of the three fields -> validation failure."""
    from mind_runtime.validation.contracts import _homeostasis

    payload = {
        "salience_floor_fast_apply": 0.70,
        "salience_floor_slow_accept": 0.60,
        "confidence_floor_slow": 0.80,
    }
    del payload[missing_field]

    with pytest.raises(ValueError, match="payload keys must exactly match schema"):
        _homeostasis(payload)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("salience_floor_fast_apply", -0.01),
        ("salience_floor_fast_apply", 1.01),
        ("salience_floor_slow_accept", -0.5),
        ("salience_floor_slow_accept", 2.0),
        ("confidence_floor_slow", -0.1),
        ("confidence_floor_slow", 1.1),
        ("salience_floor_fast_apply", "not_a_number"),
        ("salience_floor_slow_accept", True),
        ("confidence_floor_slow", False),
        ("confidence_floor_slow", float("nan")),
        ("confidence_floor_slow", float("inf")),
    ],
)
def test_h4_out_of_range_homeostasis_values_rejected(
    field_name: str, bad_value: object
) -> None:
    """H4: out-of-range or non-numeric values rejected."""
    from mind_runtime.validation.contracts import _homeostasis

    payload: dict[str, object] = {
        "salience_floor_fast_apply": 0.70,
        "salience_floor_slow_accept": 0.60,
        "confidence_floor_slow": 0.80,
    }
    payload[field_name] = bad_value

    with pytest.raises(ValueError):
        _homeostasis(payload)


def test_h5_production_composition_constructs_policy_from_decoded_explicit_config(
    tmp_path: Path,
) -> None:
    """H5: production composition constructs policy from decoded explicit config."""
    config = make_runtime_config(tmp_path)
    composition = subject.build_composition(config)
    try:
        gate = getattr(composition.orchestrator.emotional_transition, "_homeostasis_gate", None)
        assert isinstance(gate, SalienceThresholdPolicy)
        assert isinstance(gate.config, FixedSalienceThresholdConfig)
        assert gate.config.salience_floor_fast_apply == 0.70
        assert gate.config.salience_floor_slow_accept == 0.60
        assert gate.config.confidence_floor_slow == 0.80
    finally:
        composition.close()


def test_h6_production_does_not_rely_on_fixed_threshold_config_defaults(
    tmp_path: Path,
) -> None:
    """H6: production does NOT rely on FixedSalienceThresholdConfig() defaults.

    FixedSalienceThresholdConfig default salience_floor_slow_accept is 0.85.
    Production decoded salience_floor_slow_accept is 0.60.
    A candidate with salience=0.75 and confidence=0.85:
    - Under bare defaults (floor=0.85): salience < floor -> REJECT
    - Under production composition (floor=0.60): salience >= floor -> SLOW_ACCEPT
    """
    candidate = CandidateStateDelta(
        target_dimension="agent.longitudinal.relationship_security",
        proposed_value=0.80,
        scope=Scope(ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"),
        evidence_refs=("ev-1",),
        source_event_ref="evt-1",
        salience=0.75,
        confidence=0.85,
        observed_at=NOW,
    )

    # 1. Bare defaults policy
    bare_policy = SalienceThresholdPolicy(config=FixedSalienceThresholdConfig())
    assert bare_policy.config.salience_floor_slow_accept == 0.85
    bare_decision = bare_policy.decide(candidate, prior_value=None)
    assert bare_decision.decision is not HomeostasisDisposition.SLOW_ACCEPT

    # 2. Production policy from composition
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        gate = getattr(composition.orchestrator.emotional_transition, "_homeostasis_gate", None)
        assert gate is not None
        assert gate.config.salience_floor_slow_accept == 0.60
        prod_decision = gate.decide(candidate, prior_value=None)
        assert prod_decision.decision is HomeostasisDisposition.SLOW_ACCEPT
        assert prod_decision.reason_code == "high_salience_high_confidence_slow_accept"
    finally:
        composition.close()


def test_h7_salience_at_slow_floor_qualifies_boundary(tmp_path: Path) -> None:
    """H7: salience == 0.60 with confidence >= 0.80 qualifies for slow threshold boundary."""
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        gate = getattr(composition.orchestrator.emotional_transition, "_homeostasis_gate", None)
        assert gate is not None

        # At boundary: salience == 0.60, confidence == 0.80 -> SLOW_ACCEPT
        cand_boundary = CandidateStateDelta(
            target_dimension="agent.longitudinal.relationship_security",
            proposed_value=0.80,
            scope=Scope(ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"),
            evidence_refs=("ev-1",),
            source_event_ref="evt-1",
            salience=0.60,
            confidence=0.80,
            observed_at=NOW,
        )
        dec_boundary = gate.decide(cand_boundary, prior_value=None)
        assert dec_boundary.decision is HomeostasisDisposition.SLOW_ACCEPT

        # Just below boundary: salience == 0.599 -> NOT SLOW_ACCEPT
        cand_below = replace(cand_boundary, salience=0.599)
        dec_below = gate.decide(cand_below, prior_value=None)
        assert dec_below.decision is not HomeostasisDisposition.SLOW_ACCEPT
    finally:
        composition.close()


def test_h8_confidence_at_slow_floor_qualifies_boundary(tmp_path: Path) -> None:
    """H8: confidence == 0.80 with salience >= 0.60 qualifies for slow threshold boundary."""
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        gate = getattr(composition.orchestrator.emotional_transition, "_homeostasis_gate", None)
        assert gate is not None

        # At boundary: confidence == 0.80, salience == 0.60 -> SLOW_ACCEPT
        cand_boundary = CandidateStateDelta(
            target_dimension="agent.longitudinal.relationship_security",
            proposed_value=0.80,
            scope=Scope(ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"),
            evidence_refs=("ev-1",),
            source_event_ref="evt-1",
            salience=0.60,
            confidence=0.80,
            observed_at=NOW,
        )
        dec_boundary = gate.decide(cand_boundary, prior_value=None)
        assert dec_boundary.decision is HomeostasisDisposition.SLOW_ACCEPT

        # Just below boundary: confidence == 0.799 -> NOT SLOW_ACCEPT (FAST_ONLY)
        cand_below = replace(cand_boundary, confidence=0.799)
        dec_below = gate.decide(cand_below, prior_value=None)
        assert dec_below.decision is not HomeostasisDisposition.SLOW_ACCEPT
        assert dec_below.decision is HomeostasisDisposition.FAST_ONLY
    finally:
        composition.close()


def test_h9_salience_none_rejects(tmp_path: Path) -> None:
    """H9: salience=None -> REJECT."""
    composition = subject.build_composition(make_runtime_config(tmp_path))
    try:
        gate = getattr(composition.orchestrator.emotional_transition, "_homeostasis_gate", None)
        assert gate is not None

        cand_none = CandidateStateDelta(
            target_dimension="agent.longitudinal.relationship_security",
            proposed_value=0.80,
            scope=Scope(ScopeDomain.AGENT, agent_id="kayla_v0", persona_id="kayla_v0"),
            evidence_refs=("ev-1",),
            source_event_ref="evt-1",
            salience=None,
            confidence=1.0,
            observed_at=NOW,
        )
        dec_none = gate.decide(cand_none, prior_value=None)
        assert dec_none.decision is HomeostasisDisposition.REJECT
        assert dec_none.reason_code == "salience_unavailable_reject"
    finally:
        composition.close()

