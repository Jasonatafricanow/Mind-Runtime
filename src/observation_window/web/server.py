"""OW-UI-1: ASGI server entry point.

Run with:

    python -m observation_window.web [--port 8765] [--host 127.0.0.1]

Default mode constructs a self-contained Web API over:

  - an in-memory ``StateBackend`` and ``FactBackend`` (so the UI
    works with zero external dependencies), and
  - a ``LiveTraceCache`` plus a small built-in synthetic-turn
    generator that injects one demo turn on startup so the UI
    has content to display.

This standalone mode is **debug-only**. To wire the Web API to a
real MR orchestrator, construct an ``OWDashboardDataSources`` with
real backends and a real `TurnProvider` and call
``build_app(sources).run()`` directly.

OW-UI-1 does not import any MR orchestrator, dynamics engine, or
appraisal provider. The standalone mode is a debug fixture only.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn

from mind_runtime.contracts.common import SyncFields
from mind_runtime.contracts.evidence import Evidence
from mind_runtime.contracts.observation import Observation
from mind_runtime.contracts.scope import (
    Authority,
    AuthorityLevel,
    Scope,
    ScopeDomain,
    WritePolicy,
)
from mind_runtime.contracts.state import (
    RuntimeState,
    StateDefinition,
    StateDomain,
    StateValueType,
)
from mind_runtime.contracts.transition import StateTransition
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.state.persistence import (
    SqliteCommitMarkerStore,
    SqliteStateBackend,
)

from observation_window.causal_trace import CausalChainBuilder
from observation_window.live_trace import OWLiveTraceSource
from observation_window.query_service import ObservationQueryService
from observation_window.web import LiveTraceCache
from observation_window.web.api import build_router
from observation_window.web.sources import (
    CacheTurnProvider,
    OWDashboardDataSources,
)


log = logging.getLogger("observation_window.web")


# ---------------------------------------------------------------------------
# Standalone fixture: in-memory MR runtime seeded with demo data
# ---------------------------------------------------------------------------


def _build_standalone_sources(
    cache_maxlen: int = 200,
    seed_demo: bool = True,
    db_path: Optional[Path] = None,
) -> OWDashboardDataSources:
    """Build a self-contained OWDashboardDataSources over in-memory backends.

    This is a **debug fixture only**. It is NOT wired to a real MR
    orchestrator. Its purpose is to let a developer run the Web UI
    with one command and have something visible.
    """
    if db_path is None:
        # Use a temp DB so the demo data lives only for this process
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = Path(tf.name)
    state_be = SqliteStateBackend(db_path)
    fact_be = SqliteFactBackend(db_path)
    cm_store = SqliteCommitMarkerStore(db_path)

    if seed_demo:
        _seed_demo_data(state_be, fact_be, cm_store)

    query = ObservationQueryService(
        state_backend=state_be,  # type: ignore[arg-type]
        fact_backend=fact_be,    # type: ignore[arg-type]
        commit_marker_store=cm_store,  # type: ignore[arg-type]
    )
    live = OWLiveTraceSource()
    chain_builder = CausalChainBuilder()
    cache = LiveTraceCache(maxlen=cache_maxlen)
    provider = CacheTurnProvider(cache)

    if seed_demo:
        _seed_demo_live_trace(live, cache)

    return OWDashboardDataSources(
        query_service=query,
        live_source=live,
        chain_builder=chain_builder,
        turn_provider=provider,
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _user_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="u-debug")


def _agent_scope() -> Scope:
    return Scope(domain=ScopeDomain.AGENT, agent_id="a-debug", persona_id="p-debug")


def _user_authority() -> Authority:
    return Authority(
        scope=_user_scope(),
        level=AuthorityLevel.ASSERTED,
        source_id="debug-user",
    )


def _agent_authority() -> Authority:
    return Authority(
        scope=_agent_scope(),
        level=AuthorityLevel.SYSTEM,
        source_id="debug-system",
    )


def _seed_demo_data(
    state_be: SqliteStateBackend,
    fact_be: SqliteFactBackend,
    cm_store: SqliteCommitMarkerStore,
) -> None:
    """Seed a small set of canonical states and evidence rows."""
    user_scope = _user_scope()
    agent_scope = _agent_scope()

    state_be.save_definition(
        StateDefinition(
            key="user.sleep.phase",
            domain=StateDomain.USER,
            value_type=StateValueType.CATEGORICAL,
            dynamics_policy="accumulator",
            default_validity_policy=None,
            bounds=None,
        )
    )
    state_be.save_definition(
        StateDefinition(
            key="agent.affect.demo_a",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="continuous_return_to_baseline",
            default_validity_policy=None,
            bounds=None,
        )
    )
    state_be.save_definition(
        StateDefinition(
            key="agent.affect.demo_b",
            domain=StateDomain.AGENT,
            value_type=StateValueType.SCALAR,
            dynamics_policy="continuous_return_to_baseline",
            default_validity_policy=None,
            bounds=None,
        )
    )

    # Two versions of longing to demonstrate the history view
    longing_v1 = RuntimeState(
        state_id="state-longing-1",
        scope=agent_scope,
        dimension="agent.affect.demo_a",
        value=0.5,
        status="superseded",
        valid_from=_now(),
        valid_until=_now(),
        relevant_until=None,
        last_observed_at=_now(),
        evidence_refs=("ev-debug-1",),
        transition_refs=("tr-debug-1",),
        updated_at=_now(),
        origin_runtime_id="rt-debug",
        version=1,
        sync=SyncFields(
            scope=agent_scope, origin_runtime_id="rt-debug",
            object_id="state-longing-1", version=1,
            idempotency_key="idem-longing-1",
        ),
    )
    longing_v2 = RuntimeState(
        state_id="state-longing-2",
        scope=agent_scope,
        dimension="agent.affect.demo_a",
        value=0.65,
        status="active",
        valid_from=_now(),
        valid_until=None,
        relevant_until=None,
        last_observed_at=_now(),
        evidence_refs=("ev-debug-2",),
        transition_refs=("tr-debug-1",),
        updated_at=_now(),
        origin_runtime_id="rt-debug",
        version=2,
        sync=SyncFields(
            scope=agent_scope, origin_runtime_id="rt-debug",
            object_id="state-longing-2", version=2,
            idempotency_key="idem-longing-2",
        ),
    )
    state_be.save_state(longing_v1)
    state_be.save_state(longing_v2)
    state_be.save_transition(
        StateTransition(
            transition_id="tr-debug-1",
            scope=agent_scope,
            origin_runtime_id="rt-debug",
            intent_id="intent-debug-1",
            from_state=longing_v1,
            to_state=longing_v2,
            committed_at=_now(),
            sync=SyncFields(
                scope=agent_scope, origin_runtime_id="rt-debug",
                object_id="tr-debug-1", version=1,
                idempotency_key="idem-tr-debug-1",
            ),
        )
    )

    # Anxiety: single active row
    anxiety = RuntimeState(
        state_id="state-anxiety-1",
        scope=agent_scope,
        dimension="agent.affect.demo_b",
        value=0.18,
        status="active",
        valid_from=_now(),
        valid_until=None,
        relevant_until=None,
        last_observed_at=_now(),
        evidence_refs=(),
        transition_refs=(),
        updated_at=_now(),
        origin_runtime_id="rt-debug",
        version=1,
        sync=SyncFields(
            scope=agent_scope, origin_runtime_id="rt-debug",
            object_id="state-anxiety-1", version=1,
            idempotency_key="idem-anxiety-1",
        ),
    )
    state_be.save_state(anxiety)

    # Sleep phase
    sleep = RuntimeState(
        state_id="state-sleep-1",
        scope=user_scope,
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        valid_from=_now(),
        valid_until=None,
        relevant_until=None,
        last_observed_at=_now(),
        evidence_refs=("ev-debug-1",),
        transition_refs=(),
        updated_at=_now(),
        origin_runtime_id="rt-debug",
        version=1,
        sync=SyncFields(
            scope=user_scope, origin_runtime_id="rt-debug",
            object_id="state-sleep-1", version=1,
            idempotency_key="idem-sleep-1",
        ),
    )
    state_be.save_state(sleep)

    # Evidence rows
    ev1 = Evidence(
        id="ev-debug-1",
        source_type="user_statement",
        source_id="debug-user",
        authority_level=AuthorityLevel.ASSERTED,
        occurred_at=_now(),
        received_at=_now(),
        payload="I just woke up",
        scope=user_scope,
        origin_runtime_id="rt-debug",
        authority=Authority(
            scope=user_scope, level=AuthorityLevel.ASSERTED, source_id="debug-user",
        ),
        sync=SyncFields(
            scope=user_scope, origin_runtime_id="rt-debug",
            object_id="ev-debug-1", version=1,
            idempotency_key="idem-ev-1",
        ),
    )
    ev2 = Evidence(
        id="ev-debug-2",
        source_type="user_statement",
        source_id="debug-user",
        authority_level=AuthorityLevel.ASSERTED,
        occurred_at=_now(),
        received_at=_now(),
        payload="I miss you",
        scope=agent_scope,
        origin_runtime_id="rt-debug",
        authority=Authority(
            scope=agent_scope, level=AuthorityLevel.ASSERTED, source_id="debug-user",
        ),
        sync=SyncFields(
            scope=agent_scope, origin_runtime_id="rt-debug",
            object_id="ev-debug-2", version=1,
            idempotency_key="idem-ev-2",
        ),
    )
    fact_be.save_evidence(ev1, interaction_id="ix-debug-1")
    fact_be.save_evidence(ev2, interaction_id="ix-debug-1")


def _seed_demo_live_trace(
    live: OWLiveTraceSource, cache: LiveTraceCache
) -> None:
    """Seed a synthetic J8-E3 turn snapshot for the demo."""
    from datetime import UTC, datetime
    from mind_runtime.contracts.appraisal import AppraisalPath, AppraisalRouteDecision
    from mind_runtime.contracts.appraisal_affect import AppraisalAffectDecision
    from mind_runtime.contracts.appraisal_result import (
        AbstainReason,
        ApplicabilityLevel,
        AppraisalPolarity,
        AppraisalResult,
        AppraisalStatus,
        CausalStatus,
        RelevanceLevel,
        ResolvedAppraisal,
    )
    from mind_runtime.contracts.emotional_transition import (
        AssessmentContribution,
        AssessmentTrace,
    )
    from mind_runtime.contracts.scope import Scope, ScopeDomain

    scope = Scope(domain=ScopeDomain.AGENT, agent_id="a-debug", persona_id="p-debug")
    now = datetime.now(tz=UTC)

    resolved = ResolvedAppraisal(
        appraisal_id="app-debug-1",
        scope=scope,
        origin_runtime_id="rt-debug",
        source_kind="semantic_meaning",
        source_candidate_id="cand-debug-1",
        polarity=AppraisalPolarity.NEGATIVE,
        status=AppraisalStatus.ACCEPTED,
        meanings=("loss_appraisal",),
        relevance=RelevanceLevel.HIGH,
        applicability=ApplicabilityLevel.FULLY_APPLICABLE,
        causal_status=CausalStatus.ATTRIBUTED,
        confidence=0.85,
        evidence_refs=("ev-debug-2",),
        audit_refs=(),
        authority_ref="auth-debug-1",
        state_decisions=(),
        abstain_code=None,
        reject_code=None,
    )
    appraisal_result = AppraisalResult(resolved=resolved, route_ref="route-debug-1")

    decision = AppraisalAffectDecision(
        appraisal_id="app-debug-1",
        rule_id="rule-loss-debug",
        dimension="agent.affect.demo_a",
        direction=__import__(
            "mind_runtime.contracts.appraisal_affect", fromlist=["AffectDirection"]
        ).AffectDirection.INCREASE,
        base_amount=0.20,
        impulse_amount=0.164,
        provider_confidence=0.85,
        applicability=ApplicabilityLevel.FULLY_APPLICABLE,
        matched_state_refs=("agent.affect.demo_a:rule-loss-debug",),
        evidence_refs=("ev-debug-2",),
        applied=True,
        reason_code="APPLIED",
    )

    contribution = AssessmentContribution(
        dimension="agent.affect.demo_a",
        source_kind="appraisal",
        source_ref="appraisal:app-debug-1:rule-loss-debug:state:agent.affect.demo_a:rule-loss-debug",
        amount=0.15,
        confidence=0.85,
        applied=True,
        reason_code="applied",
    )

    route = AppraisalRouteDecision(
        route_id="rd-debug-1",
        scope=scope,
        path=AppraisalPath.DETERMINISTIC,
        ambiguity_score=0.1,
        confidence=0.85,
        reason_codes=("deterministic_route",),
    )

    trace = AssessmentTrace(
        trace_id="trace-debug-1",
        scope=scope,
        origin_runtime_id="rt-debug",
        context_ref="ctx-debug-1",
        persona_id="p-debug",
        persona_version=1,
        state_before=(("agent.affect.demo_a", 0.5),),
        contributions=(contribution,),
        state_after=(("agent.affect.demo_a", 0.65),),
        evidence_refs=("ev-debug-2",),
        history_refs=(),
        abstention_reasons=(),
        route_decision=route,
        created_at=now,
    )

    from mind_runtime.contracts.appraisal_affect import (
        AppraisalAffectTransitionResult,
    )
    from mind_runtime.contracts.emotional_transition import EmotionalTransitionResult
    from mind_runtime.contracts.projection import ProjectedMindState, SyncFields as _SF

    # Minimal projection with a single state row matching state_after
    from mind_runtime.contracts.state import RuntimeState as _RS
    proj_state = _RS(
        state_id="state-longing-2",
        scope=scope,
        dimension="agent.affect.demo_a",
        value=0.65,
        status="active",
        valid_from=now,
        valid_until=None,
        relevant_until=None,
        last_observed_at=now,
        evidence_refs=("ev-debug-2",),
        transition_refs=("tr-debug-1",),
        updated_at=now,
        origin_runtime_id="rt-debug",
        version=2,
        sync=SyncFields(
            scope=scope, origin_runtime_id="rt-debug",
            object_id="state-longing-2", version=2,
            idempotency_key="idem-proj-state",
        ),
    )
    projected = ProjectedMindState(
        projection_id="proj-debug-1",
        scope=scope,
        origin_runtime_id="rt-debug",
        projected_states=(proj_state,),
        sync=SyncFields(
            scope=scope, origin_runtime_id="rt-debug",
            object_id="proj-debug-1", version=1,
            idempotency_key="idem-proj-debug-1",
        ),
    )
    baseline = EmotionalTransitionResult(
        projected=projected,
        accepted_events=(),
        assessment_trace=trace,
    )
    j8e3_result = AppraisalAffectTransitionResult(
        projected=baseline.projected,
        accepted_events=baseline.accepted_events,
        assessment_trace=trace,
        appraisal_result=appraisal_result,
        appraisal_affect_decisions=(decision,),
    )

    snap = live.observe(
        interaction_id="ix-debug-1",
        result=j8e3_result,
    )
    cache.append(snap)


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------


def build_app(
    sources: OWDashboardDataSources,
    context=None,
) -> "FastAPI":  # type: ignore[name-defined]
    """Construct the FastAPI app bound to the given OW data sources.

    ``context`` is the optional binding context
    (OW-MULTI-AGENT-BINDING-PHASE01-V1); omitted = explicit-source compat.
    """
    # Imported here so the module loads even if FastAPI is missing
    # at import time (e.g. in a CI environment that doesn't install
    # the optional web deps).
    from fastapi import FastAPI

    app = FastAPI(
        title="Mind Runtime Observation Window",
        version="0.1.0",
        description="Read-only Web UI over OW-P1 + OW-3. No MR authority.",
    )
    app.include_router(build_router(sources, context))
    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m observation_window.web",
        description="Mind Runtime read-only observation console.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", default=8765, type=int, help="bind port (default 8765)")
    parser.add_argument(
        "--maxlen",
        default=200,
        type=int,
        help="live trace ring buffer size (default 200)",
    )
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="skip the standalone demo data seed (only the runtime data is shown)",
    )
    args = parser.parse_args(argv)

    sources = _build_standalone_sources(
        cache_maxlen=args.maxlen,
        seed_demo=not args.no_demo,
    )
    app = build_app(sources)

    print("Mind Runtime Observation Window")
    print(f"Listening: http://{args.host}:{args.port}")
    print("READ ONLY")
    print("Pages:")
    print("  /            Overview")
    print("  /timeline    Turn Timeline")
    print("  /causal      Causal Inspector")
    print("  /history     Dimension History")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
