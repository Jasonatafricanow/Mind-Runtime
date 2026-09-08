"""C2 integration tests: Hermes/shadow source -> production canonical runtime.

Every test drives the REAL TurnOrchestrator with the REAL fact-admission
gate through the C2.1 adapter (src/mind_runtime/shadow/source_bridge.py) —
no mocked runtime, no second cognition pipeline. L1-L12 map to the C2 task
acceptance list.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import EmotionalTransitionInput, EmotionalTransitionResult
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError
from mind_runtime.pipeline.orchestrator import TurnOrchestrator, TurnState
from mind_runtime.pipeline.stubs import StubEmotionalTransition
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.shadow.classifier import EventMeta
from mind_runtime.shadow.source_bridge import (
    AdmissionMode,
    HermesProductionBridge,
    SourceRecord,
)
from mind_runtime.shadow.sources.hermes import HermesEvent, HermesMessageSource
from mind_runtime.state.persistence import SqliteStateBackend

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
HISTORICAL_EPOCH = 1735689600.0  # 2025-01-01T00:00:00Z — long before the clock


# ── fixtures / builders ───────────────────────────────────────────────────


def _clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


def _orchestrator(
    *,
    clock: FakeClock | None = None,
    fact_ingest: FactIngestService | None = None,
    state_backend: SqliteStateBackend | None = None,
    emotional_transition: StubEmotionalTransition | None = None,
) -> TurnOrchestrator:
    return TurnOrchestrator(
        clock=clock or _clock(),
        trace=TraceRecorder(),
        runtime_id="kayla",
        fact_ingest=fact_ingest,
        state_backend=state_backend,
        emotional_transition=emotional_transition,
    )


def _bridge(orchestrator: TurnOrchestrator, user_id: str = "user-a") -> HermesProductionBridge:
    return HermesProductionBridge(
        orchestrator,
        clock=_clock(),
        origin_runtime_id="kayla",
        user_id=user_id,
    )


def _rec(rid: str, *, role: str = "user", text: str = "消息") -> SourceRecord:
    return SourceRecord(
        source_record_id=rid,
        role=role,
        text=text,
        occurred_at=datetime.fromtimestamp(HISTORICAL_EPOCH, tz=UTC),
        channel="telegram",
        session_id="sess-1",
    )


def _fingerprint(orchestrator: TurnOrchestrator) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((s.state_id, s.version) for s in orchestrator.canonical))


def _service(orchestrator: TurnOrchestrator) -> FactIngestService:
    """Narrow the orchestrator's injected port to the real factual service."""
    service = orchestrator.fact_ingest
    assert isinstance(service, FactIngestService)
    return service


def _make_hermes_db(path: Path, rows: list[tuple[int, float, str, str]]) -> str:
    con = sqlite3.connect(str(path))
    try:
        con.executescript(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT, session_key TEXT);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER,"
            " timestamp REAL, role TEXT, content TEXT);"
        )
        con.execute("INSERT INTO sessions VALUES (1, 'telegram', 'chat/1')")
        con.executemany("INSERT INTO messages VALUES (?, 1, ?, ?, ?)", rows)
        con.commit()
    finally:
        con.close()
    return str(path)


def _hermes_event(rid: int, ts: float, role: str, text: str) -> HermesEvent:
    sender = "user" if role == "user" else "agent"
    meta = EventMeta(
        channel="telegram",
        sender=sender,
        session="chat/1",
        trigger="message",
        source_domain="kayla_persona",
    )
    return HermesEvent(meta=meta, text=text, ts=ts, content_id=rid)


# ── L1 — one record, one authority ────────────────────────────────────────


def test_l1_same_record_sync_twice_replay_once_is_one_authority() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)
    record = _rec("777", text="今晚哄嘻嘻睡觉")

    first = bridge.process(record, mode=AdmissionMode.LIVE)
    assert first.disposition == "new"
    assert first.stage == "committed"
    assert first.projection_committed is True
    after_first = _fingerprint(orch)

    replayed = bridge.process(record, mode=AdmissionMode.REPLAY)
    assert replayed.disposition == "replay"
    assert replayed.projection_committed is False
    assert _fingerprint(orch) == after_first  # zero canonical delta on replay
    # exactly one durable factual authority for the source record
    evidence_ids = [e.id for e in _service(orch).evidence.all()]
    assert evidence_ids == ["hermes:777"]
    # the replay turn still completed its lifecycle as a non-causal audit run
    assert orch.state is TurnState.COMMITTED


# ── L2 — backfill overlap ─────────────────────────────────────────────────


def test_l2_backfill_overlap_does_not_duplicate_authority() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)

    first_batch = tuple(_rec(str(i), text=f"重叠测试{i}") for i in range(95, 101))
    done = bridge.process_many(first_batch, mode=AdmissionMode.BACKFILL)
    assert all(o.disposition == "new" and o.projection_committed for o in done)

    overlap_batch = tuple(_rec(str(i), text=f"重叠测试{i}") for i in range(95, 111))
    second = bridge.process_many(overlap_batch, mode=AdmissionMode.BACKFILL)
    by_id = {o.source_record_id: o for o in second}
    # 95..100 dedupe to non-causal replays; 101..110 admit exactly once each
    for i in range(95, 101):
        assert by_id[str(i)].disposition == "replay"
        assert not by_id[str(i)].projection_committed
    for i in range(101, 111):
        assert by_id[str(i)].disposition == "new"
        assert by_id[str(i)].projection_committed
    assert _service(orch).evidence.count() == 16


def test_l2_overlap_canonical_end_state_matches_single_pass() -> None:
    """A double backfill pass ends at the same authority as one clean pass."""
    corpus = tuple(_rec(str(i), text=f"语料{i}") for i in range(95, 111))

    single = _orchestrator()
    single_bridge = _bridge(single)
    single_bridge.process_many(corpus, mode=AdmissionMode.BACKFILL)

    double = _orchestrator()
    double_bridge = _bridge(double)
    head = tuple(r for r in corpus if int(r.source_record_id) <= 100)
    double_bridge.process_many(head, mode=AdmissionMode.BACKFILL)
    double_bridge.process_many(corpus, mode=AdmissionMode.BACKFILL)

    assert sorted(_fingerprint(single)) == sorted(_fingerprint(double))


# ── L3 — real production integration, no mocks ────────────────────────────


def test_l3_hermes_source_reaches_real_orchestrator(tmp_path: Path) -> None:
    db = _make_hermes_db(
        tmp_path / "state.db",
        [
            (11, HISTORICAL_EPOCH, "user", "嘻嘻晚饭吃了烤串"),
            (12, HISTORICAL_EPOCH + 60, "assistant", "替你记下啦"),
            (13, HISTORICAL_EPOCH + 120, "user", "嘉森明天要加班"),
        ],
    )
    source = HermesMessageSource(db)
    try:
        page = source.fetch_page(after_ts=0.0, limit=50)
    finally:
        source.close()
    records = [SourceRecord.from_hermes_event(e) for e in page.events]
    # the read-only Hermes adapter normalizes roles to its user/agent senders
    assert [r.role for r in records] == ["user", "agent", "user"]

    orch = _orchestrator()
    bridge = _bridge(orch)
    outcomes = bridge.process_many(
        [r for r in records if r.role == "user"], mode=AdmissionMode.BACKFILL
    )
    assert [o.stage for o in outcomes] == ["committed", "committed"]
    assert [o.disposition for o in outcomes] == ["new", "new"]

    # the agent reply cannot enter as authoritative evidence at all
    blocked = bridge.process(records[1], mode=AdmissionMode.BACKFILL)
    assert blocked.stage == "blocked"
    assert blocked.projection_committed is False

    # real runtime result: two committed turns; per production supersession
    # semantics one CURRENT affect projection remains for (scope, dimension),
    # while both factual authorities persist
    assert [s.dimension for s in orch.canonical] == ["user.affect.stub"]
    assert len(orch.canonical) == 1
    assert {s.scope.user_id for s in orch.canonical} == {"user-a"}
    assert _service(orch).evidence.count() == 2

    # production trace ledger carries the lifecycle stages per interaction
    entry_stages = {t.stage for t in orch.trace.trace("hermes-11")}
    assert {"begin", "ingest", "commit"} <= entry_stages
    ingest_outcomes = [t.outcome for t in orch.trace.trace("hermes-11") if t.stage == "ingest"]
    assert ingest_outcomes == ["fact_new"]


# ── L4 — historical timestamp preserved ───────────────────────────────────


def test_l4_historical_event_time_not_rewritten_to_processing_time() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)
    outcome = bridge.process(_rec("900"), mode=AdmissionMode.REPLAY)

    assert outcome.disposition == "new"
    scope = bridge.scope
    observation = _service(orch).observations.get(scope, "observation-hermes:900")
    evidence = _service(orch).evidence.get(scope, "hermes:900")
    assert observation is not None and evidence is not None
    # contract split held: event time stays original; observed_at is the
    # processing-time reading from the injected clock
    assert evidence.occurred_at == datetime.fromtimestamp(HISTORICAL_EPOCH, tz=UTC)
    assert evidence.received_at == FIXED_NOW
    assert observation.observed_at == FIXED_NOW


# ── L5 — read-your-writes inside the same processing unit ─────────────────


def test_l5_admitted_fact_visible_to_cognition_in_same_unit() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)
    outcome = bridge.process(_rec("950", text="同一单元可见性"))

    assert outcome.disposition == "new"
    # this unit's admitted Observation entered the turn BEFORE cognition ran;
    # the committed downstream lineage references its evidence id.
    assert outcome.downstream_evidence_refs == ("hermes:950",)


# ── L6 — abort keeps facts, discards projection ───────────────────────────


class _ExplodingTransition(StubEmotionalTransition):
    def transition(self, transition_input: EmotionalTransitionInput) -> EmotionalTransitionResult:
        raise RuntimeError("semantic provider down")


def test_l6_downstream_failure_keeps_fact_discards_projection() -> None:
    exploding = _ExplodingTransition(clock=_clock())
    orch = _orchestrator(emotional_transition=exploding)
    bridge = _bridge(orch)
    before = _fingerprint(orch)

    with pytest.raises(RuntimeError, match="semantic provider down"):
        bridge.process(_rec("600", text="会触发下游故障"), mode=AdmissionMode.LIVE)

    assert orch.state is TurnState.ABORTED
    assert _fingerprint(orch) == before  # no cognitive commit happened
    # the fact plane survived the abort (G13b semantics)
    assert [e.id for e in _service(orch).evidence.all()] == ["hermes:600"]
    assert _service(orch).observations.get(bridge.scope, "observation-hermes:600") is not None


# ── L7 — restart/replay idempotency over durable backends ─────────────────


def test_l7_crash_and_restart_leaves_one_authority_one_commit(tmp_path: Path) -> None:
    fact_db = tmp_path / "facts.sqlite"
    state_db = tmp_path / "states.sqlite"

    svc_a = FactIngestService(clock=_clock(), backend=SqliteFactBackend(fact_db))
    orch_a = _orchestrator(fact_ingest=svc_a, state_backend=SqliteStateBackend(state_db))
    bridge_a = _bridge(orch_a)
    record = _rec("5000", text="崩溃前已入账")
    first = bridge_a.process(record, mode=AdmissionMode.LIVE)
    assert first.disposition == "new"
    states_after_first = tuple((s.state_id, s.version) for s in orch_a.canonical)

    # simulate a brand-new process over the same durable stores
    svc_b = FactIngestService(clock=_clock(), backend=SqliteFactBackend(fact_db))
    orch_b = _orchestrator(fact_ingest=svc_b, state_backend=SqliteStateBackend(state_db))
    bridge_b = _bridge(orch_b)
    replayed = bridge_b.process(record, mode=AdmissionMode.REPLAY)

    assert replayed.disposition == "replay"
    assert not replayed.projection_committed
    assert svc_b.evidence.count() == 1
    assert tuple((s.state_id, s.version) for s in orch_b.canonical) == states_after_first


# ── L8 — shadow artifacts have no canonical authority ────────────────────


def test_l8_shadow_artifacts_cannot_mutate_production_cognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from datetime import timedelta

    from mind_runtime.shadow import snapshot as snapshot_module
    from mind_runtime.shadow.affect import init_affect_store
    from mind_runtime.shadow.redaction import init_store
    from mind_runtime.shadow.snapshot import generate_snapshot
    from mind_runtime.shadow.states import active_states, extract_states

    affect_db = tmp_path / "affect.db"
    states_db = tmp_path / "states.db"
    snapshot_file = tmp_path / "emotion_snapshot.json"
    monkeypatch.setattr(snapshot_module, "AFFECT_DB", affect_db)
    monkeypatch.setattr(snapshot_module, "STATES_DB", states_db)
    monkeypatch.setattr(snapshot_module, "SNAPSHOT", snapshot_file)
    init_affect_store(affect_db)

    # 1) empty artifacts: the persona-facing snapshot renders empty windows
    generate_snapshot()
    empty_payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert "latest_user" in empty_payload and empty_payload["latest_user"] is None
    assert empty_payload["states"] == []

    # 2) populated artifacts: the derived report carries user-affect data —
    #    yet it stays a derived REPORT, feeding nothing below.
    now = datetime.now(UTC)
    with sqlite3.connect(str(affect_db)) as con:
        con.execute(
            "INSERT INTO shadow_affect "
            "(content_id, ts, session_hash, channel, sender, dimension, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            (1, now.isoformat(timespec="seconds"), "s", "telegram", "user", "joy", 0.9),
        )
    init_store(tmp_path / "shadow.db")
    with sqlite3.connect(str(tmp_path / "shadow.db")) as con:
        for extra_row in (
            (
                5,
                now.isoformat(timespec="seconds"),
                "u",
                "s",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                "我去哄嘻嘻睡觉了",
            ),
            # a second child-sleep event: same (category,key), distinct
            # record — exercises the snapshot dedupe of repeated states
            (
                6,
                (now + timedelta(minutes=1)).isoformat(timespec="seconds"),
                "u2",
                "s2",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                "刚刚又哄嘻嘻上床睡了",
            ),
        ):
            con.execute(
                "INSERT INTO shadow_events "
                "(content_id, ts, user_hash, session_hash, channel, sender, "
                "trigger, source_domain, redacted_text) VALUES (?,?,?,?,?,?,?,?,?)",
                extra_row,
            )
    extract_states(tmp_path / "shadow.db", states_db)
    assert any(s[1] == "child_sleep" for s in active_states(states_db))
    rich = generate_snapshot()
    latest = rich.get("latest_user")
    assert isinstance(latest, dict)
    assert latest.get("dimension") == "joy"
    snapshot_states = rich.get("states", [])
    assert isinstance(snapshot_states, list)
    state_keys = {str(entry.get("key")) for entry in snapshot_states if isinstance(entry, dict)}
    assert state_keys >= {"child_sleep"}

    # 3) a brand-new production runtime with those shadow artifacts present
    #    starts EMPTY: nothing loads shadow stores into the canonical pipeline.
    orch = _orchestrator()
    assert orch.canonical == ()
    assert _service(orch).evidence.count() == 0


# ── L9 — entity identity survives the production path ─────────────────────


def test_l9_two_persons_remain_distinct_through_production_path() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)
    person_a = bridge.process(_rec("801", text="嘉森在加班写代码"))
    person_b = bridge.process(_rec("802", text="我去哄嘻嘻睡觉了"))

    assert person_a.projection_committed and person_b.projection_committed
    service = _service(orch)
    stored_a = service.evidence.get(bridge.scope, "hermes:801")
    stored_b = service.evidence.get(bridge.scope, "hermes:802")
    assert stored_a is not None and stored_b is not None
    # identity preserved verbatim — no <person:N> re-coding anywhere
    assert stored_a.payload == {"text": "嘉森在加班写代码"}
    assert stored_b.payload == {"text": "我去哄嘻嘻睡觉了"}
    for stored in service.evidence.all():
        assert "<person:" not in repr(stored.payload)
    obs_ids = sorted(o.id for o in service.observations.all())
    assert obs_ids == ["observation-hermes:801", "observation-hermes:802"]


# ── L10 — assistant output cannot self-authorize a user fact ──────────────


def test_l10_assistant_statement_replay_creates_no_user_state() -> None:
    orch = _orchestrator()
    bridge = _bridge(orch)
    statement = _rec("909", role="assistant", text="你现在在睡觉")

    outcome = bridge.process(statement, mode=AdmissionMode.REPLAY)
    assert outcome.stage == "blocked"
    assert outcome.blocked_reason is not None
    assert "assistant_message" in outcome.blocked_reason
    assert outcome.reason_codes == ("authority_not_user_fact",)
    assert _service(orch).evidence.count() == 0
    assert _service(orch).observations.count() == 0
    assert orch.canonical == ()

    # belt: even bypassing the bridge, the production AuthorityValidator
    # rejects an assistant_message at admission (G8 lineage).
    forged = bridge.to_evidence(
        _rec("910", role="assistant", text="你现在在睡觉"),
        received_at=FIXED_NOW,
    )
    direct_bridge = _bridge(
        TurnOrchestrator(clock=_clock(), trace=TraceRecorder(), runtime_id="kayla")
    )
    direct = direct_bridge._orchestrator
    direct.begin_turn(direct_bridge.interaction_for(_rec("910")))
    with pytest.raises(AuthorityError):
        direct.ingest(forged)


# ── L11 — scope isolation ─────────────────────────────────────────────────


def test_l11_scope_a_evidence_never_touches_scope_b() -> None:
    orch = _orchestrator()
    bridge_a = _bridge(orch, user_id="user-a")
    bridge_b = _bridge(orch, user_id="user-b")

    out_a = bridge_a.process(_rec("701", text="A 的私密日程"))
    out_b = bridge_b.process(_rec("702", text="B 的另一个话题"))

    assert out_a.stage == out_b.stage == "committed"
    evidence_scope_by_id = {e.id: e.scope.user_id for e in _service(orch).evidence.all()}
    assert evidence_scope_by_id == {"hermes:701": "user-a", "hermes:702": "user-b"}
    canonical_scope_user_ids = {s.scope.user_id for s in orch.canonical}
    assert canonical_scope_user_ids == {"user-a", "user-b"}
    state_ids = sorted(s.state_id for s in orch.canonical)
    assert len(set(state_ids)) == len(state_ids)  # no shared/crossed projection ids


# ── L12 — replay determinism over identical replicas ──────────────────────


def _process_corpus(corpus: tuple[SourceRecord, ...], mode: AdmissionMode) -> TurnOrchestrator:
    """One fresh deterministic runtime processing the corpus once."""
    orchestrator = _orchestrator()
    bridge = _bridge(orchestrator)
    bridge.process_many(corpus, mode=mode)
    return orchestrator


def test_l12_deterministic_corpus_yields_identical_canonical_results() -> None:
    corpus = tuple(_rec(str(i), text=f"确定性语料{i}") for i in range(20, 25))

    replicas = [_process_corpus(corpus, AdmissionMode.BACKFILL) for _ in range(3)]
    fingerprints = {_fingerprint(replica) for replica in replicas}
    assert len(fingerprints) == 1  # same corpus + fixed clock => same result

    # replaying the identical corpus again on an existing stack changes
    # nothing (idempotent authority, deterministic end state holds)
    replayed = replicas[0]
    bridge_again = _bridge(replayed)
    bridge_again.process_many(corpus, mode=AdmissionMode.REPLAY)
    assert all(o.disposition == "replay" for o in bridge_again.outcomes)
    assert _fingerprint(replayed) in fingerprints
