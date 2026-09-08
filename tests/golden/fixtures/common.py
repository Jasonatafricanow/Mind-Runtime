"""Shared builders for golden scenario fixtures."""

from datetime import UTC, datetime

from mind_runtime.contracts import (
    AffectiveDimensionProfile,
    Authority,
    AuthorityLevel,
    Evidence,
    HistoricalContextBundle,
    RuntimeState,
    Scope,
    ScopeDomain,
    SyncFields,
)
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


def make_scope(*, user_id: str = "user-1") -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id=user_id)


def make_sync(scope: Scope, object_id: str, *, runtime_id: str = "runtime-1") -> SyncFields:
    return SyncFields(scope, runtime_id, object_id, 1, f"idem-{object_id}")


def make_state(
    *,
    dimension: str = "user.sleep.phase",
    value: object = "awake",
    status: str = "active",
    scope: Scope | None = None,
    state_id: str | None = None,
    runtime_id: str = "runtime-1",
    now: datetime = NOW,
) -> RuntimeState:
    factual_scope = scope or make_scope()
    return RuntimeState(
        state_id=state_id or f"state-{dimension}",
        scope=factual_scope,
        origin_runtime_id=runtime_id,
        dimension=dimension,
        value=value,
        status=status,
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=(),
        transition_refs=(),
        updated_at=now,
        version=1,
        sync=make_sync(factual_scope, state_id or f"state-{dimension}", runtime_id=runtime_id),
    )


def make_evidence(
    *,
    text: str,
    source_id: str = "message-1",
    source_type: str = "user_message",
    scope: Scope | None = None,
    runtime_id: str = "runtime-1",
    occurred_at: datetime = NOW,
    received_at: datetime = NOW,
    evidence_id: str = "evidence-1",
    level: AuthorityLevel = AuthorityLevel.ASSERTED,
) -> Evidence:
    factual_scope = scope or make_scope()
    return Evidence(
        id=evidence_id,
        scope=factual_scope,
        origin_runtime_id=runtime_id,
        source_type=source_type,
        source_id=source_id,
        authority_level=level,
        authority=Authority(factual_scope, level, source_id),
        occurred_at=occurred_at,
        received_at=received_at,
        payload={"text": text},
        sync=make_sync(factual_scope, evidence_id, runtime_id=runtime_id),
    )


def make_persona(
    *,
    dimension: str = "agent.affect.longing",
    sensitivity: float = 0.6,
) -> AffectiveDimensionProfile:
    return AffectiveDimensionProfile(
        dimension=dimension,
        baseline=0.3,
        initial_value=0.3,
        sensitivity=sensitivity,
        recovery_rate=0.2,
        ceiling=1.0,
        floor=0.0,
        growth_profile=(("growth", 0.05),),
        coupling_profile=(),
    )


def make_history_bundle() -> HistoricalContextBundle:
    return HistoricalContextBundle(
        bundle_id="hb-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        episodes=(),
        stable_facts=(),
        relationship_events=(),
        pattern_summaries=(),
        source_refs=(),
        provider_trace="fixture",
    )


def make_clock(*, now: datetime = NOW) -> FakeClock:
    return FakeClock(now)
