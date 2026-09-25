"""C5B coverage completion: fail-closed branches, decision paths, wiring.

Complements test_cognitive_tick.py: covers the DENY/supersede decision
branches, build-time fail-closed raises, fact-reader filters, crash-free
persistence edges, and the daemon/CLI tick wiring (gate ON paths).
"""

from __future__ import annotations

import argparse
import json
import subprocess as sp
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.cognition import build_cognitive_ticker
from mind_runtime.cognition.tick import (
    CognitiveTicker,
    observation_fact_reader,
)
from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    IntentStatus,
    PolicyResources,
    ReconsiderationPolicy,
    Scope,
    ScopeDomain,
)
from mind_runtime.dynamics.persona import PersonaProfile
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.intents.engine import DeterministicIntentEngine, IntentRule
from mind_runtime.intents.lifecycle import IntentLifecycleService
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.intents.policy import (
    ActionPolicyConfig,
    DeterministicActionPolicy,
    IntentPolicyRule,
)
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.shadow import daemon as daemon_mod
from mind_runtime.shadow import runtime_loop
from mind_runtime.state.persistence import SqliteStateBackend

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _persona() -> PersonaProfile:
    return PersonaProfile(
        persona_id="synthetic-tick",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )


def _rules() -> tuple[IntentRule, ...]:
    return (
        IntentRule(
            rule_id="reach-out",
            kind="reach_out",
            base_strength=0.1,
            dimension_weights=(("agent.affect.missing", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.8,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
        ),
    )


def _policy_config(*, with_rule: bool = True) -> ActionPolicyConfig:
    return ActionPolicyConfig(
        rules=(
            (
                IntentPolicyRule(
                    intent_kind="reach_out",
                    action_type="proactive_message",
                    proactive=True,
                    interrupts_active_conversation=False,
                    media_counter_fact=None,
                    media_limit=None,
                    required_resource=None,
                ),
            )
            if with_rule
            else ()
        ),
        proactive_cooldown=timedelta(minutes=30),
    )


def _stack(
    tmp_path: Path,
    *,
    persona: PersonaProfile | None = None,
    rules: tuple[IntentRule, ...] | None = None,
    policy_config: ActionPolicyConfig | None = None,
    state_backend: bool = True,
    runtime_id: str = "runtime-1",
) -> dict[str, object]:
    persona = persona or _persona()
    clock = FakeClock(BASE)
    fact_service = FactIngestService(
        clock=clock, backend=SqliteFactBackend(tmp_path / "facts.sqlite")
    )
    backend = SqliteStateBackend(tmp_path / "state.sqlite") if state_backend else None
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id=runtime_id,
        fact_ingest=fact_service,
        persona=persona,
        state_backend=backend,
    )
    ticker: CognitiveTicker = build_cognitive_ticker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(rules or _rules(), runtime_id),
        action_policy=DeterministicActionPolicy(
            policy_config or _policy_config(), runtime_id
        ),
        policy_resources=PolicyResources(("proactive_message", "respond")),
        intent_lifecycle=IntentLifecycleService(SqliteIntentBackend(tmp_path / "intents.sqlite")),
        runtime_id=runtime_id,
        fact_reader=observation_fact_reader(orchestrator),
    )
    return {
        "orchestrator": orchestrator,
        "ticker": ticker,
        "clock": clock,
        "persona": persona,
        "fact_service": fact_service,
        "state_backend": backend,
    }


def _orchestrator(stack: dict[str, object]) -> TurnOrchestrator:
    value = stack["orchestrator"]
    assert isinstance(value, TurnOrchestrator)
    return value


def _ticker(stack: dict[str, object]) -> CognitiveTicker:
    value = stack["ticker"]
    assert isinstance(value, CognitiveTicker)
    return value


def _seed(stack: dict[str, object], value: float, at: datetime) -> None:
    from mind_runtime.contracts import RuntimeState, SyncFields

    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT, agent_id=persona.persona_id, persona_id=persona.persona_id
    )
    state_id = "agent.affect.missing:1:seeded"
    backend.save_state(
        RuntimeState(
            state_id=state_id,
            scope=scope,
            dimension="agent.affect.missing",
            value=value,
            status="active",
            valid_from=at,
            valid_until=None,
            relevant_until=None,
            last_observed_at=at,
            evidence_refs=(),
            transition_refs=(),
            updated_at=at,
            origin_runtime_id="runtime-1",
            version=1,
            sync=SyncFields(scope, "runtime-1", state_id, 1, f"idem-{state_id}"),
        )
    )


# ── decision paths: DENY and supersede ──────────────────────────────────────


def _affect_state(
    scope: Scope,
    *,
    state_id: str,
    value: object,
    version: int = 1,
):
    """Build the minimal RuntimeState used by current-affect contract tests."""
    from mind_runtime.contracts import RuntimeState, SyncFields

    return RuntimeState(
        state_id=state_id,
        scope=scope,
        dimension="agent.affect.missing",
        value=value,
        status="active",
        valid_from=BASE,
        valid_until=None,
        relevant_until=None,
        last_observed_at=BASE,
        evidence_refs=(),
        transition_refs=(),
        updated_at=BASE,
        origin_runtime_id="runtime-1",
        version=version,
        sync=SyncFields(scope, "runtime-1", state_id, version, f"idem-{state_id}"),
    )


def test_policy_deny_blocks_candidate(tmp_path: Path) -> None:
    """A kind without a policy rule is DENYed (fail-closed), not executed."""
    stack = _stack(tmp_path, policy_config=_policy_config(with_rule=False))
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    _seed(stack, 0.75, BASE)

    report = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))

    assert report.policy_denied == 1
    lifecycle_current = ticker._intent_lifecycle.backend.current(scope)
    assert lifecycle_current[0].status is IntentStatus.BLOCKED


def test_higher_candidate_supersedes_lower(tmp_path: Path) -> None:
    """Two admitted candidates: the stronger is ALLOWED, the lower SUPERSEDED."""
    persona = PersonaProfile(
        persona_id="synthetic-tick",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
            AffectiveDimensionProfile(
                dimension="agent.affect.quiet",
                baseline=0.2,
                initial_value=0.05,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    rules = _rules() + (
        IntentRule(
            rule_id="whisper",
            kind="whisper",
            base_strength=0.05,
            dimension_weights=(("agent.affect.quiet", 1.0),),
            event_kind=None,
            event_bonus=0.0,
            minimum_strength=0.1,
            due_at_attribute=None,
            expires_after=None,
            reconsideration_policy=ReconsiderationPolicy.NEVER,
        ),
    )
    stack = _stack(tmp_path, persona=persona, rules=rules)
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    _seed(stack, 0.75, BASE)

    report = ticker.tick(scope=scope, now=BASE + timedelta(hours=2))

    assert report.policy_allowed == 1
    assert report.superseded == 1
    lifecycle_current = ticker._intent_lifecycle.backend.current(scope)
    statuses = {intent.kind: intent.status for intent in lifecycle_current}
    assert statuses["reach_out"] is IntentStatus.ALLOWED
    assert statuses["whisper"] is IntentStatus.SUPERSEDED


# ── build-time fail-closed branches ─────────────────────────────────────────


def test_build_ticker_rejects_wrong_component_types(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    orchestrator = _orchestrator(stack)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    engine = DeterministicIntentEngine(_rules(), "runtime-1")
    policy = DeterministicActionPolicy(_policy_config(), "runtime-1")
    lifecycle = IntentLifecycleService(SqliteIntentBackend(tmp_path / "l.sqlite"))

    with pytest.raises(ValueError, match="PersonaProfile"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=None,  # type: ignore[arg-type]
            intent_engine=engine,
            action_policy=policy,
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=lifecycle,
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="DeterministicIntentEngine"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=persona,
            intent_engine=None,  # type: ignore[arg-type]
            action_policy=policy,
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=lifecycle,
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="DeterministicActionPolicy"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=persona,
            intent_engine=engine,
            action_policy=None,  # type: ignore[arg-type]
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=lifecycle,
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="IntentLifecycleService"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=persona,
            intent_engine=engine,
            action_policy=policy,
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=None,  # type: ignore[arg-type]
            runtime_id="runtime-1",
        )
    with pytest.raises(ValueError, match="runtime_id"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=persona,
            intent_engine=DeterministicIntentEngine(_rules(), "other"),
            action_policy=policy,
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=lifecycle,
            runtime_id="runtime-1",
        )


def test_build_ticker_rejects_mixed_prefix_personas(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    orchestrator = _orchestrator(stack)
    mixed = PersonaProfile(
        persona_id="mixed",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.5,
                initial_value=0.5,
                sensitivity=1.0,
                recovery_rate=0.1,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
            AffectiveDimensionProfile(
                dimension="user.affect.calm",
                baseline=0.5,
                initial_value=0.5,
                sensitivity=1.0,
                recovery_rate=0.1,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    with pytest.raises(ValueError, match="uniformly"):
        build_cognitive_ticker(
            orchestrator=orchestrator,
            persona=mixed,
            intent_engine=DeterministicIntentEngine(_rules(), "runtime-1"),
            action_policy=DeterministicActionPolicy(_policy_config(), "runtime-1"),
            policy_resources=PolicyResources(("a",)),
            intent_lifecycle=IntentLifecycleService(SqliteIntentBackend(tmp_path / "m.sqlite")),
            runtime_id="runtime-1",
        )


def test_user_domain_persona_tick_requires_scope(tmp_path: Path) -> None:
    """A user-domain persona has no projection scope; the tick fails closed."""
    user_persona = PersonaProfile(
        persona_id="user-side",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="user.affect.calm",
                baseline=0.5,
                initial_value=0.5,
                sensitivity=1.0,
                recovery_rate=0.1,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    user_dir = tmp_path / "u"
    user_dir.mkdir()
    stack = _stack(user_dir, persona=user_persona)
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    with pytest.raises(ValueError, match="projection scope"):
        ticker.tick(scope=scope, now=BASE)


def test_ticker_rejects_future_affect(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    _seed(stack, 0.75, BASE + timedelta(hours=3))
    with pytest.raises(ValueError, match="must not be in the future"):
        ticker.tick(scope=scope, now=BASE)


def test_ticker_without_state_backend_skips_persistence(tmp_path: Path) -> None:
    """No durable backend: the tick still coordinates, persisting nothing."""
    no_backend_dir = tmp_path / "nb"
    no_backend_dir.mkdir()
    stack = _stack(no_backend_dir, state_backend=False)
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")

    report = ticker.tick(scope=scope, now=BASE + timedelta(hours=1))

    assert report.state_rows_persisted == 0
    assert report.intent_candidates_generated == 0  # initial values below threshold


def test_ticker_filters_nonnumeric_and_stale_affect_rows(tmp_path: Path) -> None:
    """Non-numeric affect rows are skipped; higher versions win."""
    from mind_runtime.contracts import RuntimeState, SyncFields

    stack = _stack(tmp_path)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT, agent_id=persona.persona_id, persona_id=persona.persona_id
    )

    def _row(state_id: str, value: object, version: int, at: datetime) -> RuntimeState:
        return RuntimeState(
            state_id=state_id,
            scope=scope,
            dimension="agent.affect.missing",
            value=value,
            status="active",
            valid_from=at,
            valid_until=None,
            relevant_until=None,
            last_observed_at=at,
            evidence_refs=(),
            transition_refs=(),
            updated_at=at,
            origin_runtime_id="runtime-1",
            version=version,
            sync=SyncFields(scope, "runtime-1", state_id, version, f"idem-{state_id}"),
        )

    backend.save_state(_row("a:1:text", "not-a-number", 1, BASE))
    backend.save_state(_row("a:2:low", 0.5, 2, BASE - timedelta(hours=1)))
    backend.save_state(_row("a:3:high", 0.75, 3, BASE))

    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)
    affect = ticker._current_affect(scope=scope)
    assert len(affect) == 1
    assert affect[0].version == 3
    assert affect[0].value == 0.75


# ── fact reader filters ─────────────────────────────────────────────────────


def test_fact_reader_handles_missing_service_and_filters(tmp_path: Path) -> None:
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    # service without an observations store -> empty facts
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=object()))  # type: ignore[arg-type]
    assert reader.facts(Scope(domain=ScopeDomain.USER, user_id="u")) == ()

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    other = Scope(domain=ScopeDomain.USER, user_id="someone-else")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )

    def _admit(evidence_id: str, payload: object, *, fact_scope: Scope = scope) -> None:
        service.admit(
            Evidence(
                id=evidence_id,
                scope=fact_scope,
                origin_runtime_id="runtime-1",
                source_type="typed_event",
                source_id=f"source-{evidence_id}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(fact_scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
                occurred_at=BASE,
                received_at=BASE,
                payload=payload,
                sync=SyncFields(fact_scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
            ),
            interaction_id=f"i-{evidence_id}",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )

    _admit("e-text", "plain text payload")  # non-mapping payload
    _admit("e-num", {"key": "counter.thing", "value": 5})  # non-string value
    _admit("e-key", {"key": "mood.thing", "value": "1"})  # non-counter key
    _admit("e-scope", {"key": "counter.x", "value": "9"}, fact_scope=other)  # other scope
    _admit("e-c1", {"key": "counter.thing", "value": "1"})
    _admit("e-c2", {"key": "counter.thing", "value": "2"})

    orchestrator = SimpleNamespace(fact_ingest=service)
    facts = observation_fact_reader(orchestrator).facts(scope)  # type: ignore[arg-type]
    assert facts == (("counter.thing", "2"),)


def test_ticker_accepts_explicit_none_fact_reader(tmp_path: Path) -> None:
    """A None fact reader degrades to a tick-ref-only Situation."""
    subdir = tmp_path / "nr"
    subdir.mkdir()
    stack = _stack(subdir)
    orchestrator = _orchestrator(stack)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    ticker = CognitiveTicker(
        orchestrator=orchestrator,
        persona=persona,
        intent_engine=DeterministicIntentEngine(_rules(), "runtime-1"),
        action_policy=DeterministicActionPolicy(_policy_config(), "runtime-1"),
        policy_resources=PolicyResources(("proactive_message",)),
        intent_lifecycle=IntentLifecycleService(SqliteIntentBackend(subdir / "i.sqlite")),
        runtime_id="runtime-1",
        fact_reader=None,
        projection_scope=Scope(
            domain=ScopeDomain.AGENT,
            agent_id=persona.persona_id,
            persona_id=persona.persona_id,
        ),
    )
    report = ticker.tick(
        scope=Scope(domain=ScopeDomain.USER, user_id="user-a"), now=BASE + timedelta(hours=1)
    )
    assert report.intent_candidates_generated == 0


def test_persist_counts_refused_rows(tmp_path: Path) -> None:
    """A refusing backend yields zero persisted rows (counter honesty)."""
    from mind_runtime.cognition.tick import TICK_INTERACTION_PREFIX

    stack = _stack(tmp_path)
    ticker = _ticker(stack)
    assert isinstance(ticker, CognitiveTicker)

    class _RefusingBackend(SqliteStateBackend):
        def save_state(self, state: object) -> bool:
            return False

    refusing = _RefusingBackend(tmp_path / "refusing.sqlite")
    object.__setattr__(ticker, "_state_backend", refusing)
    projected = ticker._wrapper_projection(
        ticker._affect_scope(),
        ticker._initial_states(ticker._affect_scope(), interaction_id="x", now=BASE),
        interaction_id=f"{TICK_INTERACTION_PREFIX}x",
        now=BASE,
    )
    assert ticker._persist_projection(projected) == 0


# ── daemon wiring (C5B STEP 8) ──────────────────────────────────────────────


def test_daemon_proactive_tick_gate_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, expected in [("1", True), ("true", True), ("ON", True), ("0", False), ("junk", False)]:
        monkeypatch.setenv(daemon_mod.PROACTIVE_TICK_ENV, raw)
        assert daemon_mod._proactive_tick_enabled() is expected
    monkeypatch.delenv(daemon_mod.PROACTIVE_TICK_ENV, raising=False)
    assert daemon_mod._proactive_tick_enabled() is False


def test_daemon_pass_runs_proactive_tick_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        if any("--proactive-tick" in part for part in cmd):
            tick_calls.append(list(cmd))
            return sp.CompletedProcess(cmd, 0, stdout='{"proactive_tick": {}}', stderr="")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "1")
    monkeypatch.setenv(daemon_mod.PROACTIVE_TICK_ENV, "1")
    ok, msg = daemon_mod.one_pass()
    assert ok and "tick=" in msg
    assert len(tick_calls) == 1


def test_daemon_proactive_tick_failure_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> sp.CompletedProcess[str]:
        if any("--proactive-tick" in part for part in cmd):
            return sp.CompletedProcess(cmd, 3, stdout="", stderr="tick exploded")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv(daemon_mod.PRODUCTION_INGEST_ENV, "1")
    monkeypatch.setenv(daemon_mod.PROACTIVE_TICK_ENV, "1")
    ok, msg = daemon_mod.one_pass()
    assert not ok and "proactive tick error" in msg and "rc=3" in msg


# ── runtime_loop CLI gate-ON wiring ─────────────────────────────────


_TICK_CONFIG = {
    "rules": [
        {
            "rule_id": "reach-out",
            "kind": "reach_out",
            "base_strength": 0.1,
            "dimension_weights": [{"dimension": "agent.affect.missing", "weight": 1.0}],
            "event_kind": None,
            "event_bonus": 0.0,
            "minimum_strength": 0.8,
            "due_at_attribute": None,
            "expires_after_seconds": None,
            "reconsideration_policy": "never",
        }
    ],
    "policy": {
        "rules": [
            {
                "intent_kind": "reach_out",
                "action_type": "proactive_message",
                "proactive": True,
                "interrupts_active_conversation": False,
                "media_counter_fact": None,
                "media_limit": None,
                "required_resource": None,
            }
        ],
        "proactive_cooldown_seconds": 1800,
    },
    "resources": ["proactive_message", "respond"],
}


def _write_config(tmp_path: Path) -> str:
    path = tmp_path / "tick-config.json"
    path.write_text(json.dumps(_TICK_CONFIG), encoding="utf-8")
    return str(path)


def _write_persona_file(tmp_path: Path) -> str:
    persona = {
        "persona_id": "synthetic-tick",
        "profile_version": 1,
        "dimensions": [
            {
                "dimension": "agent.affect.missing",
                "baseline": 0.9,
                "initial_value": 0.6,
                "sensitivity": 1.0,
                "recovery_rate": 0.02,
                "ceiling": 1.0,
                "floor": 0.0,
                "growth_profile": [],
                "coupling_profile": [],
            }
        ],
    }
    path = tmp_path / "persona.json"
    path.write_text(json.dumps(persona), encoding="utf-8")
    return str(path)


def test_cli_tick_gate_on_full_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gate ON: the pass JSON carries a real cognitive tick report."""
    from mind_runtime.shadow.redaction import init_store

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_INGEST", "1")
    monkeypatch.setenv(runtime_loop.PROACTIVE_TICK_ENV, "1")
    monkeypatch.setattr(runtime_loop, "DEFAULT_RUNTIME_DIR", tmp_path / "rt")
    runtime_loop.main(
        [
            "--shadow-db",
            str(shadow_db),
            "--facts-db",
            str(tmp_path / "facts.sqlite"),
            "--cognition-db",
            str(tmp_path / "cog.sqlite"),
            "--blocked-db",
            str(tmp_path / "blocked.sqlite3"),
            "--proactive-tick",
            "--intent-rules-json",
            _write_config(tmp_path),
            "--persona-json",
            _write_persona_file(tmp_path),
            "--intent-db",
            str(tmp_path / "intents.sqlite"),
            "--user-id",
            "user-a",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    tick = payload["proactive_tick"]
    assert str(tick["tick_ref"]).startswith("cognitive-tick-")
    assert (tmp_path / "intents.sqlite").exists()


def test_run_cognitive_tick_unwired_stack_raises(tmp_path: Path) -> None:
    """A stack built without tick components refuses to tick."""
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="not wired"):
        runtime_loop.run_cognitive_tick(
            orchestrator,
            scope=Scope(domain=ScopeDomain.USER, user_id="user-a"),
            now=BASE,
        )


def test_cli_config_loaders_require_config() -> None:
    args = argparse.Namespace(intent_rules_json=None)
    with pytest.raises(ValueError, match="--intent-rules-json"):
        runtime_loop.tick_config_rules(args)
    with pytest.raises(ValueError, match="--intent-rules-json"):
        runtime_loop.tick_config_policy(args)
    with pytest.raises(ValueError, match="--intent-rules-json"):
        runtime_loop.tick_config_resources(args)


# ── micro-branches: report, reader ordering, decision guards ────────────────


def test_report_as_dict_exposes_all_counters(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    report = _ticker(stack).tick(
        scope=Scope(domain=ScopeDomain.USER, user_id="user-a"), now=BASE
    )
    payload = report.as_dict()
    assert payload["tick_ref"] == report.tick_ref
    assert payload["persistent_duplicates_skipped"] == 0
    assert "elapsed_seconds" in payload


def test_fact_reader_ranking_is_deterministic(tmp_path: Path) -> None:
    """Same-instant counters resolve by evidence id, never by insertion luck."""
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )

    def _admit(evidence_id: str, value: str) -> None:
        service.admit(
            Evidence(
                id=evidence_id,
                scope=scope,
                origin_runtime_id="runtime-1",
                source_type="typed_event",
                source_id=f"source-{evidence_id}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
                occurred_at=BASE - timedelta(hours=2),
                received_at=BASE,
                payload={"key": "counter.x", "value": value},
                sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
            ),
            interaction_id=f"i-{evidence_id}",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )

    _admit("e-a", "1")
    _admit("e-b", "2")
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=service))  # type: ignore[arg-type]
    # observed_at ties (both stamped by the admission clock); the highest
    # evidence ref wins deterministically regardless of insertion order.
    assert reader.facts(scope) == (("counter.x", "2"),)


def test_decide_rejects_non_initial_candidate(tmp_path: Path) -> None:
    """The tick decision stage refuses non-version-one engine output."""
    from mind_runtime.cognition.tick import TICK_INTERACTION_PREFIX, _MutableCounters
    from mind_runtime.contracts import Intent, SyncFields

    stack = _stack(tmp_path)
    ticker = _ticker(stack)
    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    interaction_id = f"{TICK_INTERACTION_PREFIX}{BASE.isoformat()}"
    candidate = Intent(
        intent_id="intent-bad",
        scope=scope,
        origin_runtime_id="runtime-1",
        kind="reach_out",
        strength=0.9,
        earliest_at=BASE,
        due_at=None,
        expires_at=None,
        reconsideration_policy=ReconsiderationPolicy.NEVER,
        cause_refs=("c",),
        state_refs=("s",),
        status=IntentStatus.CANDIDATE,
        sync=SyncFields(scope, "runtime-1", "intent-bad", 2, "idem-bad-2"),
    )
    counters = _MutableCounters(
        interaction_id=interaction_id,
        elapsed=timedelta(0),
        generated=1,
        wakes=0,
        expired=0,
        persisted_rows=0,
    )
    situation = ticker._tick_situation(scope=scope, interaction_id=interaction_id, now=BASE)
    with pytest.raises(ValueError, match="version-one"):
        ticker._decide(
            scope=scope,
            now=BASE,
            situation=situation,
            candidates=(candidate,),
            counters=counters,
        )


def test_persist_rejects_non_numeric_state_values(tmp_path: Path) -> None:
    """_as_float fails closed on non-numeric projected values."""
    from mind_runtime.contracts import ProjectedMindState, RuntimeState, SyncFields

    stack = _stack(tmp_path)
    ticker = _ticker(stack)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="synthetic-tick",
        persona_id="synthetic-tick",
    )
    bad = RuntimeState(
        state_id="agent.affect.missing:1:bad",
        scope=scope,
        dimension="agent.affect.missing",
        value=True,
        status="active",
        valid_from=BASE,
        valid_until=None,
        relevant_until=None,
        last_observed_at=BASE,
        evidence_refs=(),
        transition_refs=(),
        updated_at=BASE,
        origin_runtime_id="runtime-1",
        version=1,
        sync=SyncFields(
            scope,
            "runtime-1",
            "agent.affect.missing:1:bad",
            1,
            "idem-agent.affect.missing:1:bad",
        ),
    )
    projected = ProjectedMindState(
        projection_id="projection-x",
        scope=scope,
        origin_runtime_id="runtime-1",
        projected_states=(bad,),
        sync=SyncFields(scope, "runtime-1", "projection-x", 1, "idem-projection-x"),
    )
    with pytest.raises(ValueError, match="finite number"):
        ticker._persist_projection(projected)


# ── build_cognitive_components fail-closed raises (coverage closure) ─────────


def test_build_components_requires_durable_intent_db(tmp_path: Path) -> None:
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="durable intent_db"):
        runtime_loop.build_cognitive_components(
            orchestrator=orchestrator,
            origin_runtime_id="runtime-1",
            intent_rules=_rules(),
            action_policy_config=_policy_config(),
            policy_resources=("proactive_message",),
            intent_db=None,
        )


def test_build_components_requires_policy_config_and_resources(
    tmp_path: Path,
) -> None:
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="action policy config"):
        runtime_loop.build_cognitive_components(
            orchestrator=orchestrator,
            origin_runtime_id="runtime-1",
            intent_rules=_rules(),
            action_policy_config=None,
            policy_resources=("proactive_message",),
            intent_db=tmp_path / "i.sqlite",
        )
    with pytest.raises(ValueError, match="policy resources"):
        runtime_loop.build_cognitive_components(
            orchestrator=orchestrator,
            origin_runtime_id="runtime-1",
            intent_rules=_rules(),
            action_policy_config=_policy_config(),
            policy_resources=None,
            intent_db=tmp_path / "i.sqlite",
        )


def test_run_cognitive_tick_rejects_wrong_wiring_type(tmp_path: Path) -> None:
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    orchestrator.cognitive_tick_components = {"ticker": object()}  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="CognitiveTicker"):
        runtime_loop.run_cognitive_tick(
            orchestrator,
            scope=Scope(domain=ScopeDomain.USER, user_id="user-a"),
            now=BASE,
        )


@pytest.mark.parametrize(
    "bad_value",
    [True, "seventy-percent", "0.75-but-text"],
    ids=["bool", "text", "numeric-looking-text"],
)
def test_current_affect_skips_non_numeric_values(
    tmp_path: Path, bad_value: object
) -> None:
    """Only real numeric affect values are eligible for the current projection."""
    stack = _stack(tmp_path)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )
    backend.save_state(
        _affect_state(
            scope,
            state_id="agent.affect.missing:1:invalid",
            value=bad_value,
        )
    )
    assert _ticker(stack)._current_affect(scope=scope) == ()


def test_current_affect_prefers_highest_version(tmp_path: Path) -> None:
    """Current affect is independent of insertion order and keeps the highest version."""
    stack = _stack(tmp_path)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )
    for state_id, value, version in (
        ("a:v1", 0.6, 1),
        ("a:v3", 0.8, 3),
        ("a:v2", 0.7, 2),
    ):
        backend.save_state(
            _affect_state(scope, state_id=state_id, value=value, version=version)
        )
    affect = _ticker(stack)._current_affect(scope=scope)
    assert [(row.version, row.value) for row in affect] == [(3, 0.8)]


def test_build_components_personaless_orchestrator_raises(tmp_path: Path) -> None:
    """A stack without a Persona refuses component wiring (fail-closed)."""
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=None,
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="Persona-backed"):
        runtime_loop.build_cognitive_components(
            orchestrator=orchestrator,
            origin_runtime_id="runtime-1",
            intent_rules=_rules(),
            action_policy_config=_policy_config(),
            policy_resources=("proactive_message",),
            intent_db=tmp_path / "i.sqlite",
        )






def test_current_affect_ignores_foreign_scope_rows(tmp_path: Path) -> None:
    """Rows in another scope hit the first continue (scope/dim mismatch)."""
    from mind_runtime.contracts import RuntimeState, SyncFields

    subdir = tmp_path / "foreign"
    subdir.mkdir()
    stack = _stack(subdir)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    agent_scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )
    foreign_scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id="someone-else",
        persona_id="someone-else",
    )
    backend.save_state(
        RuntimeState(
            state_id="foreign:1:x",
            scope=foreign_scope,
            dimension="agent.affect.missing",
            value=0.75,
            status="active",
            valid_from=BASE,
            valid_until=None,
            relevant_until=None,
            last_observed_at=BASE,
            evidence_refs=(),
            transition_refs=(),
            updated_at=BASE,
            origin_runtime_id="runtime-1",
            version=1,
            sync=SyncFields(foreign_scope, "runtime-1", "foreign:1:x", 1, "idem-foreign"),
        )
    )
    # query with the agent scope must skip the foreign row entirely
    affect = _ticker(stack)._current_affect(scope=agent_scope)
    assert affect == ()
    # and querying by the foreign scope proves the row exists but is ignored:
    # the dimension IS in persona dims, so the row matches — but foreign
    # scope rows must never leak into a query about another scope. The first
    # continue (scope mismatch) is what protects the agent-scope query.
    affect_foreign = _ticker(stack)._current_affect(scope=foreign_scope)
    assert len(affect_foreign) == 1 and affect_foreign[0].state_id == "foreign:1:x"


def test_reader_known_rank_tie_falls_back_to_evidence_ref(tmp_path: Path) -> None:
    """Two observations at the same observed_at: higher evidence ref wins."""
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )

    def _admit(evidence_id: str, value: str) -> None:
        service.admit(
            Evidence(
                id=evidence_id,
                scope=scope,
                origin_runtime_id="runtime-1",
                source_type="typed_event",
                source_id=f"source-{evidence_id}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
                occurred_at=BASE,
                received_at=BASE,
                payload={"key": "counter.tie", "value": value},
                sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
            ),
            interaction_id=f"i-{evidence_id}",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )

    _admit("ev-aaa", "1")  # admitted first
    _admit("ev-zzz", "2")  # same observed_at, higher ref
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=service))  # type: ignore[arg-type]
    facts = reader.facts(scope)
    assert facts == (("counter.tie", "2"),)


def test_build_components_accepts_stub_turn_engine_with_rules(tmp_path: Path) -> None:
    """The stub-engine notice branch (pass) executes during normal wiring."""
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    components = runtime_loop.build_cognitive_components(
        orchestrator=orchestrator,
        origin_runtime_id="runtime-1",
        intent_rules=_rules(),
        action_policy_config=_policy_config(),
        policy_resources=("proactive_message", "respond"),
        intent_db=tmp_path / "i.sqlite",
    )
    assert "ticker" in components


def test_reader_first_observation_skips_rank_compare(tmp_path: Path) -> None:
    """known is None on the first row -> assignment without comparison."""
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )
    service.admit(
        Evidence(
            id="ev-solo",
            scope=scope,
            origin_runtime_id="runtime-1",
            source_type="typed_event",
            source_id="source-ev-solo",
            authority_level=AuthorityLevel.ASSERTED,
            authority=Authority(scope, AuthorityLevel.ASSERTED, "source-ev-solo"),
            occurred_at=BASE,
            received_at=BASE,
            payload={"key": "counter.solo", "value": "7"},
            sync=SyncFields(scope, "runtime-1", "ev-solo", 1, "idem-ev-solo"),
        ),
        interaction_id="i-ev-solo",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=service))  # type: ignore[arg-type]
    assert reader.facts(scope) == (("counter.solo", "7"),)


def test_current_affect_accepts_first_eligible_row(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )
    backend.save_state(
        _affect_state(
            scope,
            state_id="agent.affect.missing:1:first",
            value=0.75,
        )
    )
    affect = _ticker(stack)._current_affect(scope=scope)
    assert [(row.version, row.value) for row in affect] == [(1, 0.75)]


def test_reader_lower_rank_does_not_replace(tmp_path: Path) -> None:
    """A second observation with a LOWER rank leaves the first value intact."""
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )

    def _admit_at(evidence_id: str, value: str, occurred_at: datetime) -> None:
        service.admit(
            Evidence(
                id=evidence_id,
                scope=scope,
                origin_runtime_id="runtime-1",
                source_type="typed_event",
                source_id=f"source-{evidence_id}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
                occurred_at=occurred_at,
                received_at=BASE,
                payload={"key": "counter.rank", "value": value},
                sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
            ),
            interaction_id=f"i-{evidence_id}",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )

    _admit_at("ev-aaa", "9", BASE)  # admitted first, same observed_at
    _admit_at("ev-zzz", "3", BASE)  # same observed_at, higher ref wins
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=service))  # type: ignore[arg-type]
    # the tie-break keeps ev-zzz (value 3); ev-aaa can never replace it
    assert reader.facts(scope) == (("counter.rank", "3"),)




def test_reader_lower_ref_row_does_not_replace(tmp_path: Path) -> None:
    """Second observation with LOWER ref rank leaves the earlier value intact."""
    from mind_runtime.contracts import Authority, AuthorityLevel, Evidence, SyncFields

    scope = Scope(domain=ScopeDomain.USER, user_id="user-a")
    service = FactIngestService(
        clock=FakeClock(BASE), backend=SqliteFactBackend(tmp_path / "f.sqlite")
    )

    def _admit(evidence_id: str, value: str) -> None:
        service.admit(
            Evidence(
                id=evidence_id,
                scope=scope,
                origin_runtime_id="runtime-1",
                source_type="typed_event",
                source_id=f"source-{evidence_id}",
                authority_level=AuthorityLevel.ASSERTED,
                authority=Authority(scope, AuthorityLevel.ASSERTED, f"source-{evidence_id}"),
                occurred_at=BASE,
                received_at=BASE,
                payload={"key": "counter.lower", "value": value},
                sync=SyncFields(scope, "runtime-1", evidence_id, 1, f"idem-{evidence_id}"),
            ),
            interaction_id=f"i-{evidence_id}",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )

    _admit("ev-zzz", "7")  # higher ref admitted first -> rank leader
    _admit("ev-aaa", "1")  # lower ref -> must NOT replace
    reader = observation_fact_reader(SimpleNamespace(fact_ingest=service))  # type: ignore[arg-type]
    assert reader.facts(scope) == (("counter.lower", "7"),)


def test_current_affect_lower_version_after_higher_loses(tmp_path: Path) -> None:
    """Load order: v2 then v1 -> the v1 row must not replace v2 (273 False)."""
    from mind_runtime.contracts import RuntimeState, StateDefinition, StateTransition, SyncFields

    class _OutOfOrderStateBackend:
        """StateBackend double delivering rows in storage order, not version order.

        The real SQLite backend sorts by version ASC, so a lower-version row
        can never follow a higher one in production; this double makes that
        ordering reachable so the version-comparison false branch is genuinely
        exercised.
        """

        def __init__(self, rows: tuple[RuntimeState, ...]) -> None:
            self._rows = rows

        def load_definitions(self) -> tuple[StateDefinition, ...]:
            return ()

        def save_definition(self, definition: StateDefinition) -> None:
            raise AssertionError("tick never writes definitions")

        def load_states(self) -> tuple[RuntimeState, ...]:
            return self._rows

        def save_state(self, state: RuntimeState) -> bool:
            raise AssertionError("tick never writes through this double")

        def load_transitions(self) -> tuple[StateTransition, ...]:
            return ()

        def save_transition(self, transition: StateTransition) -> bool:
            raise AssertionError("tick never writes transitions through this double")

    subdir = tmp_path / "v2first"
    subdir.mkdir()
    stack = _stack(subdir)
    persona = stack["persona"]
    assert isinstance(persona, PersonaProfile)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )

    def _row(state_id: str, value: float, version: int) -> RuntimeState:
        return RuntimeState(
            state_id=state_id,
            scope=scope,
            dimension="agent.affect.missing",
            value=value,
            status="active",
            valid_from=BASE,
            valid_until=None,
            relevant_until=None,
            last_observed_at=BASE,
            evidence_refs=(),
            transition_refs=(),
            updated_at=BASE,
            origin_runtime_id="runtime-1",
            version=version,
            sync=SyncFields(scope, "runtime-1", state_id, version, f"idem-{state_id}"),
        )

    ticker = _ticker(stack)
    ticker._state_backend = _OutOfOrderStateBackend(
        (_row("a:v2", 0.9, 2), _row("a:v1", 0.4, 1))  # lower version, loaded later
    )
    affect = ticker._current_affect(scope=scope)
    assert len(affect) == 1 and affect[0].version == 2 and affect[0].value == 0.9


def test_build_components_resources_none_after_policy_ok(tmp_path: Path) -> None:
    """policy config present + resources None -> resources raise (fail-closed)."""
    clock = FakeClock(BASE)
    orchestrator = TurnOrchestrator(
        clock=clock,
        trace=TraceRecorder(),
        runtime_id="runtime-1",
        fact_ingest=FactIngestService(
            clock=clock, backend=SqliteFactBackend(tmp_path / "f.sqlite")
        ),
        persona=_persona(),
        state_backend=SqliteStateBackend(tmp_path / "s.sqlite"),
    )
    with pytest.raises(ValueError, match="policy resources"):
        runtime_loop.build_cognitive_components(
            orchestrator=orchestrator,
            origin_runtime_id="runtime-1",
            intent_rules=_rules(),
            action_policy_config=_policy_config(),
            policy_resources=None,
            intent_db=tmp_path / "i.sqlite",
        )


def test_current_affect_first_row_true_branch_assignment(tmp_path: Path) -> None:
    """Two dimensions each hit 'known is None' first-row assignment."""
    from mind_runtime.contracts import RuntimeState, SyncFields

    subdir = tmp_path / "twodim"
    subdir.mkdir()
    persona = PersonaProfile(
        persona_id="synthetic-tick",
        dimensions=(
            AffectiveDimensionProfile(
                dimension="agent.affect.missing",
                baseline=0.9,
                initial_value=0.6,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
            AffectiveDimensionProfile(
                dimension="agent.affect.quiet",
                baseline=0.2,
                initial_value=0.1,
                sensitivity=1.0,
                recovery_rate=0.02,
                ceiling=1.0,
                floor=0.0,
                growth_profile=(),
                coupling_profile=(),
            ),
        ),
    )
    stack = _stack(subdir, persona=persona)
    backend = stack["state_backend"]
    assert isinstance(backend, SqliteStateBackend)
    scope = Scope(
        domain=ScopeDomain.AGENT,
        agent_id=persona.persona_id,
        persona_id=persona.persona_id,
    )
    for dim, value, sid in (
        ("agent.affect.missing", 0.8, "m:1"),
        ("agent.affect.quiet", 0.15, "q:1"),
    ):
        backend.save_state(
            RuntimeState(
                state_id=sid,
                scope=scope,
                dimension=dim,
                value=value,
                status="active",
                valid_from=BASE,
                valid_until=None,
                relevant_until=None,
                last_observed_at=BASE,
                evidence_refs=(),
                transition_refs=(),
                updated_at=BASE,
                origin_runtime_id="runtime-1",
                version=1,
                sync=SyncFields(scope, "runtime-1", sid, 1, f"idem-{sid}"),
            )
        )
    affect = _ticker(stack)._current_affect(scope=scope)
    assert len(affect) == 2
