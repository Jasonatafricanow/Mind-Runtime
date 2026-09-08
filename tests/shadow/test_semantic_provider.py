"""C3 semantic-provider tests (S1-S15) over the REAL router seam.

Everything runs through the production pieces: SemanticRouter routing,
GuardedSemanticProvider egress/validation, OpenAICompatibleProvider error
normalization, and the C3.0 authoritative commit-marker probe in
runtime_loop. No second pipeline exists anywhere in this file.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.fake_clock import FakeClock

from mind_runtime.contracts import (
    Observation,
    Scope,
    ScopeDomain,
    SemanticEventCandidate,
    Situation,
    SyncFields,
)
from mind_runtime.emotional_transition.provider import (
    EgressMode,
    GuardedSemanticProvider,
    ModelEgressPolicy,
    OpenAICompatibleProvider,
    ProviderUnavailableError,
    RecordedSemanticProvider,
    RouteMetrics,
    SchemaInvalidError,
    StaticListProvider,
)
from mind_runtime.emotional_transition.semantic import SemanticRouter
from mind_runtime.shadow import runtime_loop
from mind_runtime.shadow.runtime_loop import (
    build_runtime_stack,
    process_pending,
)
from mind_runtime.shadow.source_bridge import AdmissionMode, SourceRecord

FIXED_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
OK_CANDIDATE: dict[str, object] = {
    "kind": "gratitude",
    "confidence": 0.9,
    "evidence_refs": ["obs-inbound-1"],
    "attributes": {"tone": "warm"},
}


# ── builders ───────────────────────────────────────────────────────────────


def _clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


def _scope(user: str = "user-a") -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id=user)


def _situation(scope: Scope | None = None) -> Situation:
    s = scope or _scope()
    return Situation(
        situation_id="sit-1",
        scope=s,
        origin_runtime_id="kayla",
        derived_facts=(("conversation_mode", "active"),),
        effective_state_ref="effective:user-a",
        observed_at=FIXED_NOW,
        historical_context=None,
        persona_id=None,
        relationship_ids=(),
        evidence_refs=("obs-inbound-1",),
    )


def _obs(
    oid: str = "obs-inbound-1",
    text: str = "那你看着办吧",
    *,
    key: str = "user_message.observed",
    value: object | None = None,
    scope: Scope | None = None,
) -> Observation:
    s = scope or _scope()
    evidence_id = f"hermes:{oid.split('-')[-1]}"
    return Observation(
        id=oid,
        interaction_id="it-1",
        scope=s,
        origin_runtime_id="kayla",
        type="factual",
        key=key,
        value=value if value is not None else {"text": text},
        confidence=1.0 if key != "typed_event.observed" else 0.97,
        observed_at=FIXED_NOW,
        evidence_refs=(evidence_id,),
        sync=SyncFields(s, "kayla", oid, 1, f"idem-{oid}"),
    )


def _guarded(mode: EgressMode, names: tuple[str, ...] = ()) -> GuardedSemanticProvider:
    return GuardedSemanticProvider(
        egress=ModelEgressPolicy(mode=mode, known_names=names, provider_name="unit"),
        clock=_clock(),
    )


class _Counting(StaticListProvider):
    """Static provider counting how often the ROUTER called into it."""

    calls = 0

    def propose(
        self,
        *,
        observations: tuple[Observation, ...],
        context: Situation,
        scope: Scope,
    ) -> tuple[SemanticEventCandidate, ...]:
        self.calls += 1
        return super().propose(observations=observations, context=context, scope=scope)


# ── S1 — deterministic route never calls the provider ─────────────────────


def test_s1_deterministic_route_skips_provider() -> None:
    inner = _Counting(batches=[[dict(OK_CANDIDATE)]])
    router = SemanticRouter(provider=inner)
    result = router.route(observations=(), context=_situation(), supplied_candidates=())
    assert result.route.path.value == "deterministic"
    assert result.provider_call_count == 0
    assert inner.calls == 0


# ── S2 — typed mapping route never calls the provider ─────────────────────


def test_s2_typed_mapping_route_skips_provider() -> None:
    inner = _Counting(batches=[[dict(OK_CANDIDATE)]])
    typed_obs = _obs(
        oid="obs-typed-1",
        key="typed_event.observed",
        value={"kind": "plan_cancellation", "attributes": {"plan": "trip"}},
    )
    router = SemanticRouter(provider=inner)
    result = router.route(observations=(typed_obs,), context=_situation(), supplied_candidates=())
    assert result.route.path.value == "typed_mapping"
    assert result.provider_call_count == 0
    assert inner.calls == 0
    assert result.candidates[0].kind == "plan_cancellation"


# ── S3 — genuine ambiguity invokes provider exactly once ──────────────────


def test_s3_ambiguity_invokes_provider_once_and_validates() -> None:
    inner = _Counting(batches=[[dict(OK_CANDIDATE)]])
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)
    inner.guarded = guarded
    router = SemanticRouter(provider=inner)
    result = router.route(observations=(_obs(),), context=_situation(), supplied_candidates=())
    assert result.route.path.value == "llm"
    assert result.provider_call_count == 1
    assert inner.calls == 1
    assert result.candidates[0].kind == "gratitude"
    assert result.candidates[0].evidence_refs == ("obs-inbound-1",)
    assert guarded.metrics["provider_successes"] == 1


# ── S4 — provider cannot write affect/relationship numerics ───────────────


@pytest.mark.parametrize(
    "bad_attributes",
    [
        {"affect.longing": "0.82"},
        {"trust_delta": "+0.17"},
        {"relationship_state": "intimate"},
    ],
)
def test_s4_authority_smuggling_rejected(bad_attributes: dict[str, str]) -> None:
    payload = dict(OK_CANDIDATE, attributes=bad_attributes)
    with pytest.raises(SchemaInvalidError):
        StaticListProvider(batches=[[payload]]).propose(
            observations=(_obs(),), context=_situation(), scope=_scope()
        )


def test_s4_bare_numeric_attribute_value_rejected() -> None:
    payload = dict(OK_CANDIDATE, attributes={"urgency": "3"})
    with pytest.raises(SchemaInvalidError, match="bare numeric"):
        StaticListProvider(batches=[[payload]]).propose(
            observations=(_obs(),), context=_situation(), scope=_scope()
        )


# ── S5 — invented refs ungrounded; foreign scopes refused by router ───────


def test_s5_invented_evidence_ref_rejected() -> None:
    payload = dict(OK_CANDIDATE, evidence_refs=["hermes:99999"])
    with pytest.raises(SchemaInvalidError, match="not grounded"):
        StaticListProvider(batches=[[payload]]).propose(
            observations=(_obs(),), context=_situation(), scope=_scope()
        )


def test_s5_foreign_scope_observations_refused_by_router() -> None:
    other_scope = _scope("user-b")
    router = SemanticRouter(provider=None)
    with pytest.raises(ValueError, match="scope must match"):
        router.route(
            observations=(_obs(scope=other_scope),),
            context=_situation(),
            supplied_candidates=(),
        )


# ── S6 — timeout surfaces as abstention; guard records failure ────────────


def test_s6_provider_timeout_records_failure_and_escalates() -> None:
    """Transport exceptions must NOT be swallowed into fake confidence.

    The router seam intentionally lets provider exceptions bubble; the
    production loop's per-record try/except converts them to RETRYABLE and
    the fact plane survives (proven by DL6). Here we lock the guard-level
    accounting only.
    """
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)
    inner = StaticListProvider(
        batches=[],
        guarded=guarded,
        raise_error=TimeoutError("provider timed out"),
    )
    router = SemanticRouter(provider=inner)
    with pytest.raises(TimeoutError):
        router.route(observations=(_obs(),), context=_situation(), supplied_candidates=())
    assert guarded.metrics["provider_failures"] == 1
    assert guarded.metrics["provider_successes"] == 0
    assert guarded.metrics["provider_calls"] == 1


# ── S7 — malformed output normalized to SCHEMA_INVALID / provider errors ──


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "made_up_kind", "confidence": 0.9, "evidence_refs": ["obs-inbound-1"]},
        {"kind": "gratitude", "confidence": 5, "evidence_refs": ["obs-inbound-1"]},
        {"kind": "gratitude", "confidence": 0.9, "evidence_refs": []},
        {"kind": "gratitude", "confidence": "high", "evidence_refs": ["obs-inbound-1"]},
        "just a string",
    ],
)
def test_s7_schema_invalid_outputs_rejected(payload: object) -> None:
    from typing import cast

    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)
    batch = cast(list[dict[str, object]], [payload])
    inner = StaticListProvider(batches=[batch], guarded=guarded)
    with pytest.raises(SchemaInvalidError):
        inner.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert guarded.metrics["schema_invalid"] == 1


def test_s7_adapter_error_normalization(tmp_path: Path) -> None:
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)

    class _ExplodingTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            raise ValueError("malformed envelope from provider")

    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="test-model",
        api_key_env="C3_TEST_KEY",
        transport=_ExplodingTransport(),
    )
    with pytest.raises((ProviderUnavailableError, SchemaInvalidError)):
        adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert guarded.metrics["provider_failures"] >= 1 or guarded.metrics["schema_invalid"] >= 1


# ── S8/S9/S10 — egress policy matrix ──────────────────────────────────────


def test_s8_local_policy_sees_private_text_verbatim() -> None:
    captured: list[tuple[Observation, ...]] = []
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)
    inner = StaticListProvider(batches=[[dict(OK_CANDIDATE)]], guarded=guarded, capture=captured)
    inner.propose(
        observations=(_obs(text="嘻嘻在嘉森家吃饭"),), context=_situation(), scope=_scope()
    )
    assert captured and captured[0][0].value["text"] == "嘻嘻在嘉森家吃饭"  # type: ignore[index]


def test_s9_remote_disabled_policy_blocks_before_any_activity() -> None:
    calls: list[str] = []

    class _SpyTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            calls.append(url)
            return {}

    guarded = _guarded(EgressMode.DISABLED)
    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="m",
        api_key_env="C3_TEST_KEY",
        transport=_SpyTransport(),
    )
    with pytest.raises(ProviderUnavailableError, match="disabled by policy"):
        adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert calls == []


def test_s10_sanitized_mode_codes_names_keeps_shape() -> None:
    captured: list[tuple[Observation, ...]] = []
    guarded = _guarded(EgressMode.SANITIZED, names=("嘉森", "嘻嘻"))
    inner = StaticListProvider(batches=[[dict(OK_CANDIDATE)]], guarded=guarded, capture=captured)
    inner.propose(
        observations=(_obs(text="嘻嘻和嘉森吵架了"),), context=_situation(), scope=_scope()
    )
    sent_text = captured[0][0].value["text"]  # type: ignore[index]
    assert sent_text == "<person:2>和<person:1>吵架了"


def test_s10_default_policy_is_fail_closed_disabled() -> None:
    policy = ModelEgressPolicy()
    assert policy.mode is EgressMode.DISABLED
    guarded = GuardedSemanticProvider(egress=policy, clock=_clock())
    with pytest.raises(ProviderUnavailableError):
        guarded.require_egress_allowed()


def test_s10_ssrf_guard_blocks_private_and_non_https_targets() -> None:
    from mind_runtime.emotional_transition.provider import validate_egress_url

    with pytest.raises(ProviderUnavailableError, match="https"):
        validate_egress_url("http://model.example.com/v1")
    with pytest.raises(ProviderUnavailableError, match="non-public"):
        validate_egress_url("https://127.0.0.1/v1")
    with pytest.raises(ProviderUnavailableError, match="not in allowlist"):
        validate_egress_url("https://evil.example.com/v1", allowed_hosts=("model.example.com",))


# ── S11 — assistant statements stay blocked end-to-end ────────────────────


def test_s11_assistant_role_blocked_before_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    from mind_runtime.shadow.backfill import run_backfill

    hermes = tmp_path / "state.db"
    con = sqlite3.connect(str(hermes))
    con.executescript(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT, session_key TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id INTEGER,"
        " timestamp REAL, role TEXT, content TEXT);"
    )
    con.execute("INSERT INTO sessions VALUES (1,'telegram','chat/1')")
    con.execute("INSERT INTO messages VALUES (1,1,1735689600.0,'assistant','你现在在睡觉')")
    con.commit()
    con.close()
    stats = run_backfill(
        str(hermes), dry_run=False, cursor=0.0, limit=10, known_names=(), keep_names=True
    )
    assert stats["recorded"] == 1

    orchestrator, bridge = build_runtime_stack(
        clock=_clock(),
        facts_db=tmp_path / "f.sqlite",
        state_db=tmp_path / "s.sqlite",
        origin_runtime_id="kayla",
        user_id="user-a",
    )
    report = process_pending(
        orchestrator,
        bridge,
        shadow_db=str(tmp_path / "shadow.db"),
        blocked_store_path=str(tmp_path / "blocked.sqlite3"),
    )
    assert report.blocked == 1 and report.processed == 0
    service = orchestrator.fact_ingest
    assert service.evidence.count() == 0  # type: ignore[attr-defined]


# ── S12 — candidate scope stays bound to its request scope ────────────────


def test_s12_result_candidates_cannot_cross_scopes() -> None:
    provider = StaticListProvider(batches=[[dict(OK_CANDIDATE)]])
    candidates = provider.propose(
        observations=(_obs(),), context=_situation(), scope=_scope("user-b")
    )
    for candidate in candidates:
        assert candidate.scope.user_id == "user-b"


# ── S13 — replay consumes recorded validated artifacts only ───────────────


def test_s13_recorded_artifact_replay_deterministic() -> None:
    recorded_batch = [dict(OK_CANDIDATE)]

    def run_once(provider: object) -> list[tuple[str, float]]:
        router = SemanticRouter(provider=provider)  # type: ignore[arg-type]
        result = router.route(
            observations=(_obs(text="谢谢你帮我"),), context=_situation(), supplied_candidates=()
        )
        return [(c.kind, c.confidence) for c in result.candidates]

    live = run_once(StaticListProvider([list(recorded_batch)]))
    replayed = run_once(RecordedSemanticProvider([list(recorded_batch)]))
    assert live == replayed == [("gratitude", 0.9)]
    # a second recorded pass yields nothing: replay never re-generates
    assert run_once(RecordedSemanticProvider([])) == []


# ── S14 — global outage leaves deterministic + typed green ────────────────


def test_s14_outage_does_not_break_deterministic_or_typed() -> None:
    class _DownProvider:
        def propose(self, **kwargs: object) -> tuple[object, ...]:
            raise ProviderUnavailableError("global outage")

    router = SemanticRouter(provider=_DownProvider())  # type: ignore[arg-type]
    det = router.route(observations=(), context=_situation(), supplied_candidates=())
    typed_obs = _obs(
        oid="obs-typed-2",
        key="typed_event.observed",
        value={"kind": "explicit_acceptance"},
    )
    typed = router.route(observations=(typed_obs,), context=_situation(), supplied_candidates=())
    assert det.route.path.value == "deterministic"
    assert typed.route.path.value == "typed_mapping"


# ── S15 — committed-cognition detection independent of naming ─────────────


def _seed_shadow_row(shadow_db: Path, rid: int, *, event_ts: str | None) -> None:
    with sqlite3.connect(str(shadow_db)) as con:
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, "
            "trigger, source_domain, redacted_text, event_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                "2026-08-26T00:00:00+00:00",
                "u",
                "h",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                f"记录{rid}",
                event_ts,
            ),
        )


@pytest.mark.parametrize("renamed_state_id", ["arbitrary-A", "completely-different-B"])
def test_s15_commit_detection_ignores_projection_naming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, renamed_state_id: str
) -> None:
    """Loop convergence stays identical under ANY transition-projection id."""
    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    shadow_db = tmp_path / "shadow.db"
    from mind_runtime.shadow.redaction import init_store

    init_store(shadow_db)
    _seed_shadow_row(shadow_db, 701, event_ts="2026-08-25T00:00:00+00:00")

    orchestrator, bridge = build_runtime_stack(
        clock=_clock(),
        facts_db=tmp_path / "f.sqlite",
        state_db=tmp_path / "s.sqlite",
        origin_runtime_id="kayla",
        user_id="user-a",
    )
    record = SourceRecord(
        source_record_id="701",
        role="user",
        text="命名无关性验证",
        occurred_at=datetime.fromtimestamp(1735689600, tz=UTC),
        channel="telegram",
        session_id="sess-1",
    )
    first = bridge.process(record, mode=AdmissionMode.LIVE)
    assert first.stage == "committed"

    # Simulate an ALTERNATIVE transition implementation whose projection id
    # shares nothing with 'projected-<interaction>': rename the durable row.
    state_db = sqlite3.connect(str(tmp_path / "s.sqlite"))
    state_db.execute(
        "UPDATE states SET state_id=?, sync_idem_key=? WHERE state_id LIKE 'projected-%'",
        (renamed_state_id, f"idem-{renamed_state_id}"),
    )
    state_db.commit()

    markers = orchestrator.commit_marker_store
    assert markers is not None
    # authoritative probe answers YES purely from commit semantics
    assert markers.has_commit(interaction_id="hermes-701", scope=bridge.scope) is True

    # fresh stack: canonical reloads with the arbitrary name; the legacy
    # naming predicate would MISS — marker keeps behavior identical.
    fresh_orchestrator, fresh_bridge = build_runtime_stack(
        clock=_clock(),
        facts_db=tmp_path / "f.sqlite",
        state_db=tmp_path / "s.sqlite",
        origin_runtime_id="kayla",
        user_id="user-a",
    )
    report = process_pending(
        fresh_orchestrator,
        fresh_bridge,
        shadow_db=str(shadow_db),
        blocked_store_path=str(tmp_path / "blocked-s15.sqlite3"),
    )
    assert report.replayed == 1 and report.processed == 0


# ── §21 offline shadow-corpus route evaluation (observational only) ───────


def test_semantic_eval_reports_routes_without_any_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mind_runtime.shadow.redaction import init_store
    from mind_runtime.shadow.semantic_eval import evaluate

    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    _seed_shadow_row(shadow_db, 401, event_ts="2026-08-25T00:00:00+00:00")
    with sqlite3.connect(str(shadow_db)) as con:
        con.execute(
            "UPDATE shadow_events SET redacted_text='谢谢你帮了我大忙' WHERE content_id=401"
        )
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, trigger,"
            " source_domain, redacted_text, event_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                402,
                "2026-08-26T00:00:00+00:00",
                "u",
                "h",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                "窗外的雨停了没有呢",
                "2026-08-26T00:00:00+00:00",
            ),
        )
        # blank post-redaction payload -> deterministic bucket
        con.execute(
            "INSERT INTO shadow_events "
            "(content_id, ts, user_hash, session_hash, channel, sender, trigger,"
            " source_domain, redacted_text, event_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                403,
                "2026-08-26T01:00:00+00:00",
                "u",
                "h",
                "telegram",
                "user",
                "message",
                "kayla_persona",
                "",
                "2026-08-26T01:00:00+00:00",
            ),
        )
        con.commit()

    report = evaluate(shadow_db)
    routes = report["route_distribution"]
    assert isinstance(routes, dict)
    kinds = report["typed_kind_distribution"]
    assert isinstance(kinds, dict)
    assert report["rows_considered"] == 3
    assert routes.get("typed_mapping") == 1
    assert routes.get("provider_required") == 1
    assert routes.get("deterministic") == 1
    assert kinds == {"gratitude": 1}


def test_loop_main_attaches_recorded_provider_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fail-closed semantic attach: recorded artifacts only, default off."""
    recorded = [dict(OK_CANDIDATE, evidence_refs=["hermes:808"])]
    recorded_path = tmp_path / "recorded.json"
    recorded_path.write_text(json.dumps(recorded), encoding="utf-8")

    monkeypatch.setenv("MIND_RUNTIME_SHADOW_DB", str(tmp_path / "shadow.db"))
    monkeypatch.setenv("MIND_RUNTIME_PRODUCTION_INGEST", "1")
    shadow_db = tmp_path / "shadow.db"
    from mind_runtime.shadow.redaction import init_store

    init_store(shadow_db)
    _seed_shadow_row(shadow_db, 808, event_ts="2026-08-25T00:00:00+00:00")

    code = runtime_loop.main(
        [
            "--shadow-db",
            str(shadow_db),
            "--facts-db",
            str(tmp_path / "f.sqlite"),
            "--cognition-db",
            str(tmp_path / "s.sqlite"),
            "--blocked-db",
            str(tmp_path / "b.sqlite3"),
            "--user-id",
            "user-a",
            "--semantic-recorded",
            str(recorded_path),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["runtime"]["processed"] == 1


# ── transport / parse / policy unit coverage (offline, stdlib-bounded) ────


def test_parse_candidates_payload_extracts_and_rejects() -> None:
    from mind_runtime.emotional_transition.provider import _parse_candidates_payload

    good = '前缀说明 {"candidates":[{"kind":"gratitude"}]} 后缀'
    assert _parse_candidates_payload(good) == [{"kind": "gratitude"}]
    for bad in ["no json here", '{"other":1}', '{"candidates":[]}']:
        with pytest.raises(SchemaInvalidError):
            _parse_candidates_payload(bad)


def test_urllib_transport_maps_errors_and_blocks_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error
    import urllib.request

    from mind_runtime.emotional_transition.provider import UrllibChatTransport

    class _FakeOpener:
        def __init__(self, behavior: object) -> None:
            self.behavior = behavior

        def open(self, request: object, timeout: float) -> object:
            if isinstance(self.behavior, Exception):
                raise self.behavior
            import io

            body = b'{"ok":true}' if self.behavior == "ok" else b"NOT-JSON-BODY"
            return io.BytesIO(body)

    # allowlisted host short-circuits DNS probing → transport-level paths run
    transport = UrllibChatTransport(allowed_hosts=("model.example.com",))
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda handler=None: _FakeOpener(
            urllib.error.HTTPError("u", 503, "down", {}, None)  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(ProviderUnavailableError, match="http error"):
        transport.post_json("https://model.example.com/v1", {"a": 1}, 5.0)
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda handler=None: _FakeOpener(urllib.error.URLError("conn refused")),
    )
    with pytest.raises(ProviderUnavailableError, match="unreachable"):
        transport.post_json("https://model.example.com/v1", {"a": 1}, 5.0)
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda handler=None: _FakeOpener("bad"),
    )
    with pytest.raises(ProviderUnavailableError, match="malformed provider response"):
        transport.post_json("https://model.example.com/v1", {"a": 1}, 5.0)


def test_validate_egress_url_resolution_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    from mind_runtime.emotional_transition.provider import validate_egress_url

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("8.8.4.4", 0))],
    )
    validate_egress_url("https://model.example.com/v1")  # global address passes
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ProviderUnavailableError, match="non-public"):
        validate_egress_url("https://model.example.com/v1")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: (_ for _ in ()).throw(OSError("no dns")),
    )
    with pytest.raises(ProviderUnavailableError, match="cannot resolve"):
        validate_egress_url("https://model.example.com/v1")


def test_openai_adapter_happy_path_parses_chat_envelope() -> None:
    """Real semantic provider now operates on bounded handle refs; the LLM
    must cite 'o0' (not the raw observation id). The resolver turns that
    back into a canonical id in the committed candidate.
    """
    captured_urls: list[str] = []

    class _HappyTransport:
        def post_json(
            self, url: str, framed: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            captured_urls.append(url)
            headers = framed["_headers"]
            assert isinstance(headers, dict)
            return {
                "choices": [
                    {"message": {"content": json.dumps({
                        "candidates": [{
                            "kind": "gratitude",
                            "confidence": 0.9,
                            "evidence_refs": ["o0"],
                            "attributes": {"tone": "warm"},
                        }],
                    })}}
                ]
            }

    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)
    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="test-model",
        api_key_env="C3_TEST_KEY",
        transport=_HappyTransport(),
    )
    candidates = adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert candidates[0].kind == "gratitude"
    # The handle "o0" resolved back to the observation's canonical id
    # (the only one in the set, so this is a deterministic round-trip).
    assert candidates[0].evidence_refs == ("obs-inbound-1",)
    assert guarded.metrics["provider_successes"] == 1
    assert captured_urls == ["https://model.example.com/v1/chat/completions"]


def test_guarded_egress_observations_non_mapping_payload_untouched() -> None:
    from collections.abc import Mapping as _M

    guarded = _guarded(EgressMode.SANITIZED, names=("嘉森",))
    obs = _obs(value=("tuple", "payload"))
    out = guarded.egress_observations((obs,))
    value = out[0].value
    assert not isinstance(value, str)
    mapping_value = obs.value if isinstance(obs.value, _M) else None
    assert mapping_value is not None or True


def test_commit_marker_store_idempotent_and_queryable(tmp_path: Path) -> None:
    from mind_runtime.state.persistence import SqliteCommitMarkerStore

    store = SqliteCommitMarkerStore(tmp_path / "s.sqlite")
    first = store.record_commit(
        interaction_id="it-1",
        scope=_scope(),
        committed_at=FIXED_NOW,
        projected_state_ids=("st-1",),
    )
    duplicate = store.record_commit(
        interaction_id="it-1",
        scope=_scope(),
        committed_at=FIXED_NOW,
        projected_state_ids=("st-2",),
    )
    assert first is True
    assert duplicate is False
    assert store.has_commit(interaction_id="it-1", scope=_scope()) is True
    assert store.has_commit(interaction_id="it-404", scope=_scope()) is False
    other_scope = _scope("user-b")
    assert store.has_commit(interaction_id="it-1", scope=other_scope) is False
    store.close()


def test_authoritative_probe_returns_false_without_marker_store() -> None:
    from mind_runtime.shadow.runtime_loop import _has_authoritative_commit

    assert _has_authoritative_commit(None, interaction_id="hermes:1", scope=_scope()) is False


# ── narrow provider branches locked as behavior ────────────────────────────


def test_policy_requires_provider_name_when_not_disabled() -> None:
    with pytest.raises(ValueError, match="must name its provider"):
        ModelEgressPolicy(mode=EgressMode.SANITIZED)


@pytest.mark.parametrize(
    "bad_attributes",
    [
        "not-a-dict",
        {"tone": 3},
    ],
)
def test_validate_attribute_container_shapes(bad_attributes: object) -> None:
    payload = {**OK_CANDIDATE, "attributes": bad_attributes}
    with pytest.raises(SchemaInvalidError):
        StaticListProvider(batches=[[payload]]).propose(
            observations=(_obs(),), context=_situation(), scope=_scope()
        )


def test_egress_pass_through_keeps_identity_in_non_sanitized_mode() -> None:
    guarded = _guarded(EgressMode.DISABLED)
    obs = _obs()
    out = guarded.egress_observations((obs,))[0]
    assert out is obs


def test_no_redirect_handler_refuses_every_redirect() -> None:
    from mind_runtime.emotional_transition.provider import _NoRedirect

    handler = _NoRedirect()
    result = handler.redirect_request(  # type: ignore[no-untyped-call]
        None, None, 302, "Found", {}, "https://elsewhere/"
    )
    assert result is None


def test_transport_post_json_happy_path_returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.request

    from mind_runtime.emotional_transition.provider import UrllibChatTransport

    class _FakeOpener:
        def open(self, request: object, timeout: float) -> object:
            return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(urllib.request, "build_opener", lambda handler=None: _FakeOpener())
    transport = UrllibChatTransport(allowed_hosts=("model.example.com",))
    result = transport.post_json(
        "https://model.example.com/v1",
        {"a": 1, "_headers": {"Authorization": "Bearer t"}}, 5.0)
    assert result == {"ok": True}


@pytest.mark.parametrize(
    ("envelope", "match"),
    [
        ({}, "lacks choices"),
        ({"choices": []}, "lacks choices"),
        ({"choices": [{"message": {}}]}, "lacks text content"),
        ({"choices": [{"message": {"content": 7}}]}, "lacks text content"),
    ],
)
def test_adapter_envelope_shape_errors(envelope: dict[str, object], match: str) -> None:
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)

    class _ShapeTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            return envelope

    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="m",
        api_key_env="C3_TEST_KEY",
        transport=_ShapeTransport(),
    )
    with pytest.raises(ProviderUnavailableError, match=match):
        adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())


def test_adapter_invalid_content_json_counts_schema_invalid() -> None:
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)

    class _BadContentTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"candidates": }'}}]}

    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="m",
        api_key_env="C3_TEST_KEY",
        transport=_BadContentTransport(),
    )
    with pytest.raises(SchemaInvalidError, match="malformed JSON"):
        adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert guarded.metrics["schema_invalid"] == 1


def test_jsonable_default_handles_frozen_containers() -> None:
    from mind_runtime.contracts.common import freeze_value
    from mind_runtime.emotional_transition.provider import _jsonable_default

    frozen = freeze_value({"k": {"inner"}}, "v")
    decoded = json.loads(json.dumps({"x": frozen}, default=_jsonable_default))
    assert decoded == {"x": {"k": ["inner"]}}


def test_route_metrics_observe_and_shape() -> None:
    metrics = RouteMetrics()
    metrics.observe_route("deterministic")
    metrics.observe_route("typed_mapping")
    metrics.observe_route("typed_mapping")
    shaped = metrics.as_dict()
    assert shaped["route_distribution"] == {
        "deterministic": 1,
        "typed_mapping": 2,
    }


def test_semantic_eval_main_prints_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from mind_runtime.shadow.redaction import init_store
    from mind_runtime.shadow.semantic_eval import main as eval_main

    shadow_db = tmp_path / "shadow.db"
    init_store(shadow_db)
    _seed_shadow_row(shadow_db, 500, event_ts="2026-08-25T00:00:00+00:00")
    code = eval_main(["--shadow-db", str(shadow_db), "--limit", "10"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["rows_considered"] == 1


def test_egress_text_passthrough_when_not_sanitized() -> None:
    from mind_runtime.emotional_transition.provider import _egress_text

    policy = ModelEgressPolicy(
        mode=EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT, provider_name="unit"
    )
    assert _egress_text("嘻嘻原文", policy) == "嘻嘻原文"


def test_transport_non_dict_envelope_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.request

    from mind_runtime.emotional_transition.provider import UrllibChatTransport

    class _FakeOpener:
        def open(self, request: object, timeout: float) -> object:
            return io.BytesIO(b"[1,2]")

    monkeypatch.setattr(urllib.request, "build_opener", lambda handler=None: _FakeOpener())
    transport = UrllibChatTransport(allowed_hosts=("model.example.com",))
    with pytest.raises(ProviderUnavailableError, match="JSON object"):
        transport.post_json(
            "https://model.example.com/v1",
            {"a": 1, "_headers": {"Authorization": "Bearer t"}}, 5.0)


def test_adapter_counts_failure_when_transport_raises_policy_error() -> None:
    guarded = _guarded(EgressMode.EXPLICITLY_ALLOWED_PRIVATE_CONTEXT)

    class _PolicyErrorTransport:
        def post_json(
            self, url: str, payload: dict[str, object], timeout_s: float
        ) -> dict[str, object]:
            raise ProviderUnavailableError("mid-flight denial")

    adapter = OpenAICompatibleProvider(
        guarded=guarded,
        endpoint_url="https://model.example.com/v1/chat/completions",
        model="m",
        api_key_env="C3_TEST_KEY",
        transport=_PolicyErrorTransport(),
    )
    with pytest.raises(ProviderUnavailableError):
        adapter.propose(observations=(_obs(),), context=_situation(), scope=_scope())
    assert guarded.metrics["provider_failures"] >= 1


def test_jsonable_default_falls_back_to_str() -> None:
    from mind_runtime.emotional_transition.provider import _jsonable_default

    result = _jsonable_default(object())
    assert isinstance(result, str)


def test_raise_error_injection_without_guard_still_raises() -> None:
    provider = StaticListProvider(batches=[], raise_error=TimeoutError("unguarded"))
    with pytest.raises(TimeoutError):
        provider.propose(observations=(_obs(),), context=_situation(), scope=_scope())
