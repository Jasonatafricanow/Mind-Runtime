"""OW-UI-1: HTTP API.

GET-only. Maps each endpoint to a pure read on the OW data sources.

The endpoints follow the spec (§14):

  GET /api/health
  GET /api/overview
  GET /api/states
  GET /api/states/{dimension}
  GET /api/states/{dimension}/history
  GET /api/turns
  GET /api/turns/{turn_id}
  GET /api/turns/{turn_id}/causal
  GET /api/evidence/{id}
  GET /api/provenance/{id}

Plus a small set of static-file routes for the four pages.

This module does NOT import any MR orchestrator, dynamics engine,
appraisal provider, or memory system. The only MR imports are the
OW read-model types (contracts) and the existing OW read modules
(query_service, live_trace, causal_trace).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from observation_window.causal_contracts import (
    CausalChainLink,
    ObservedTurnSnapshot,
    ResolvedCausalChain,
)
from observation_window.human_causal_trace import (
    build_human_causal_trace,
    get_affect_trends,
    list_committed_turns,
)
from observation_window.binding import (
    AssistantMessageSource,
    CausalTraceStore,
    ObservationBindingCatalog,
    ObservationContext,
    ScopedBindingError,
    ScopedObservationBinding,
    StateSurface,
    TelemetrySource,
)
from observation_window.web.sources import OWDashboardDataSources

_logger = logging.getLogger(__name__)

# Default single-binding compat store (OW-MULTI-AGENT-BINDING-PHASE01-V1 §15):
# identity is already (binding_scope_key, interaction_id); explicit-source
# constructions (server.build_app / build_ow_app_from_db_dir) without a
# composed binding context share this store. Production composition
# (BindingResolver) supplies a per-binding store instead.
_CAUSAL_TRACE_CACHE = CausalTraceStore(max_entries=500)


def _default_context() -> ObservationContext:
    """Explicit-source compat context: empty surface, degraded optional sources.

    Deliberately carries NO dimension membership and NO path knowledge —
    product surfaces that need ontology must compose a real binding context
    (BindingResolver / the binding compat adapter).
    """
    return ObservationContext(
        binding_scope_key="default",
        state_surface=StateSurface(),
        telemetry_source=TelemetrySource(db_path=None),
        assistant_message_source=AssistantMessageSource(db_path=None),
        runtime_status_provider=_UnknownRuntimeStatusProvider(),
        causal_trace_store=_CAUSAL_TRACE_CACHE,
    )


class _UnknownRuntimeStatusProvider:
    def projection(self):
        from observation_window.binding import RuntimeStatusProjection

        return RuntimeStatusProjection(status="UNKNOWN", summary_code="UNKNOWN")


def _is_terminal_trace(ht: dict[str, Any] | None) -> bool:
    """Determine if a causal trace is complete/terminal before immutable caching.

    Per FINAL PERF FIX constraint:
    Zero age/time heuristics. Only cache when proven by runtime evidence:
    1. TURN_ABORT exists -> terminal
    2. TURN_COMMIT exists AND exact assistant linkage exists -> terminal
    3. TURN_COMMIT exists AND runtime explicitly recorded an assistant-linkage
       terminal result (ASSISTANT_RESPONSE_UNAVAILABLE / NO_RESPONSE_EXPECTED) -> terminal
    4. Provenance explicitly proves the turn predates journal activation -> terminal

    Incomplete current-era turns (committed but assistant linkage not yet known)
    must NOT be immutable-cached; they will rebuild on the next selected request.
    """
    if not ht:
        return False
    if ht.get("terminal_proof") is not None:
        return True
    if ht.get("is_aborted"):
        return True
    comm_at = ht.get("committed_at")
    if not comm_at:
        return False
    asst = ht.get("assistant_response", {})
    if asst.get("status") == "AVAILABLE":
        return True
    if asst.get("terminal_result") is True or asst.get("status") in (
        "NO_RESPONSE_EXPECTED",
        "ASSISTANT_RESPONSE_UNAVAILABLE",
        "TERMINAL_UNAVAILABLE",
    ):
        return True
    if ht.get("raw_linkage", {}).get("pre_journal") is True:
        return True
    return False


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

def _json_default(o: Any) -> Any:
    """JSON-friendly coercion of OW dataclasses, datetimes, enums."""
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "value"):
        return o.value
    if hasattr(o, "name"):
        return o.name
    return str(o)


def _json(payload: Any) -> dict[str, Any]:
    """Helper that round-trips through json to ensure dict-shape."""
    text = json.dumps(payload, default=_json_default)
    return json.loads(text)


# ---------------------------------------------------------------------------
# HTML rendering (server-rendered; no Node, no build)
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"
_RUNTIME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _render_page(name: str, context: dict[str, Any] | None = None) -> HTMLResponse:
    path = _STATIC_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"page {name!r} not found")
    html = path.read_text(encoding="utf-8")
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def _extract_bundle_header(context: ObservationContext) -> dict[str, Any]:
    try:
        projection = context.runtime_status_provider.projection()
        detail_provider = context.runtime_detail_provider
        deploy_detail = detail_provider() if callable(detail_provider) else {}
        bundle_state = (
            projection.status
            if projection.status in ("READY", "DEGRADED")
            else ("NOT_READY" if projection.status in ("OFFLINE", "UNAVAILABLE") else "UNKNOWN")
        )
        return {
            "bundle_state": bundle_state,
            "gateway_pid": projection.detail.get("gateway_pid"),
            "mr_status": (
                "ACTIVE"
                if projection.status in ("READY", "DEGRADED")
                else ("UNKNOWN" if projection.status == "UNKNOWN" else "NOT_READY")
            ),
            "semantic_status": deploy_detail.get("semantic_status", "UNKNOWN"),
            "appraisal_status": deploy_detail.get("appraisal_status", "UNKNOWN"),
            "slow_writer_status": deploy_detail.get("slow_writer_status", "UNKNOWN"),
            "ow_status": "ONLINE",
            "runtime_ready_at": projection.detail.get("runtime_ready_at"),
            "epoch_id": projection.detail.get("epoch_id"),
            "runtime_status": projection.to_payload(),
        }
    except Exception:
        return {
            "bundle_state": "NOT_READY",
            "gateway_pid": None,
            "mr_status": "UNKNOWN",
            "semantic_status": "UNKNOWN",
            "appraisal_status": "UNKNOWN",
            "slow_writer_status": "UNKNOWN",
            "ow_status": "ONLINE",
            "runtime_ready_at": None,
            "epoch_id": None,
        }


def _extract_turn_stats(sources: OWDashboardDataSources, ready_at: str | None) -> dict[str, Any]:
    commits_store = getattr(sources.query_service, "_commits", None)
    state_backend = getattr(sources.query_service, "_state", None)
    conn = None
    if commits_store is not None and hasattr(commits_store, "_conn"):
        conn = commits_store._conn
    elif state_backend is not None and hasattr(state_backend, "_conn"):
        conn = state_backend._conn

    total_committed = 0
    epoch_turns = 0
    last_committed = None

    if conn is not None:
        try:
            table_check = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commit_markers'"
            ).fetchone()
            if table_check:
                total_committed = conn.execute("SELECT COUNT(1) FROM commit_markers").fetchone()[0]
                last_row = conn.execute(
                    "SELECT interaction_id, committed_at FROM commit_markers ORDER BY committed_at DESC LIMIT 1"
                ).fetchone()
                if last_row:
                    last_committed = {
                        "interaction_id": last_row[0],
                        "committed_at": last_row[1],
                    }
                if ready_at:
                    epoch_turns = conn.execute(
                        "SELECT COUNT(1) FROM commit_markers WHERE committed_at >= ?", (ready_at,)
                    ).fetchone()[0]
        except Exception:
            pass

    return {
        "persisted_committed_turns": total_committed,
        "current_epoch_turns": epoch_turns,
        "last_committed_turn": last_committed,
    }


def _extract_connections(
    sources: OWDashboardDataSources,
    context: ObservationContext | None = None,
) -> tuple[Any, Any]:
    conn_state = None
    conn_facts = None

    state_backend = getattr(sources.query_service, "_state", None)
    if state_backend is not None and hasattr(state_backend, "_conn"):
        conn_state = state_backend._conn
    if conn_state is None:
        commits_store = getattr(sources.query_service, "_commits", None)
        if commits_store is not None and hasattr(commits_store, "_conn"):
            conn_state = commits_store._conn

    fact_backend = getattr(sources.query_service, "_fact", None)
    if fact_backend is not None and hasattr(fact_backend, "_conn"):
        conn_facts = fact_backend._conn

    if (conn_state is None or conn_facts is None) and context is not None:
        # Fall back to the binding context's own resolved sources — never to
        # any filesystem guessing (OW-MULTI-AGENT-BINDING-PHASE01-V1 §8).
        import sqlite3
        try:
            if conn_state is None and context.state_db.exists():
                conn_state = sqlite3.connect(
                    f"file:{Path(context.state_db).as_posix()}?mode=ro", uri=True, timeout=1.0
                )
            if conn_facts is None and context.facts_db.exists():
                conn_facts = sqlite3.connect(
                    f"file:{Path(context.facts_db).as_posix()}?mode=ro", uri=True, timeout=1.0
                )
        except Exception:
            pass

    return conn_state, conn_facts


def _group_latest_states(
    raw_states: Any,
    *,
    slow_dimensions: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    slow_set = set(slow_dimensions)
    by_key: dict[tuple[str, str, str, str], list[Any]] = {}
    for s in raw_states:
        scope = getattr(s, "scope", None)
        s_domain = scope.domain.value if scope and hasattr(scope, "domain") else ""
        s_user = getattr(scope, "user_id", "") or ""
        s_agent = getattr(scope, "agent_id", "") or ""
        key = (s_domain, s_user, s_agent, s.dimension)
        by_key.setdefault(key, []).append(s)

    current_states: list[dict[str, Any]] = []
    has_surfaced_slow: set[str] = set()

    for key, versions in by_key.items():
        versions.sort(key=lambda item: getattr(item, "version", 0) or 0)
        latest = versions[-1]
        dim = latest.dimension
        val = latest.value

        delta = None
        if len(versions) >= 2 and isinstance(val, (int, float)):
            prev_val = versions[-2].value
            if isinstance(prev_val, (int, float)):
                delta = round(val - prev_val, 4)

        is_placeholder = (
            dim.endswith(".stub")
            or ".stub." in dim
            or "placeholder" in dim.lower()
            or "test" in dim.lower()
        )

        if dim in slow_set:
            cat = "slow"
        elif is_placeholder:
            cat = "placeholder"
        else:
            cat = "fast"

        if dim in slow_set:
            has_surfaced_slow.add(dim)

        short_label = dim.split(".")[-1]

        current_states.append({
            "state_id": latest.state_id,
            "dimension": dim,
            "display_name": short_label,
            "value": val,
            "delta": delta,
            "version": latest.version,
            "status": latest.status,
            "updated_at": latest.updated_at.isoformat() if isinstance(latest.updated_at, datetime) else str(latest.updated_at),
            "category": cat,
            "is_placeholder": is_placeholder,
            "evidence_refs": list(latest.evidence_refs) if hasattr(latest, "evidence_refs") else [],
            "transition_refs": list(latest.transition_refs) if hasattr(latest, "transition_refs") else [],
        })

    # Requirement 4 (descriptor-scoped): explicitly surface each DECLARED slow
    # dimension that has no canonical row yet ("not established"), instead of
    # silently hiding it. Membership comes from the binding's state_surface.
    for declared in slow_dimensions:
        if declared in has_surfaced_slow:
            continue
        current_states.append({
            "state_id": None,
            "dimension": declared,
            "display_name": declared.split(".")[-1],
            "value": None,
            "delta": None,
            "version": None,
            "status": "not established",
            "updated_at": None,
            "category": "slow",
            "is_placeholder": False,
            "evidence_refs": [],
            "transition_refs": [],
        })

    order = {"fast": 0, "slow": 1, "placeholder": 2}
    current_states.sort(key=lambda s: (order.get(s["category"], 99), s["dimension"]))
    return current_states


def register_scoped_binding_error_handler(app: Any) -> None:
    """Install ScopedBindingError handler at FastAPI application boundary."""

    @app.exception_handler(ScopedBindingError)
    async def _handle_scoped_error(request: Request, exc: ScopedBindingError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )


def _scoped_error_response(exc: ScopedBindingError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


# ---------------------------------------------------------------------------
# Shared Query / Projection Services (Shared between Legacy & Scoped Routes)
# ---------------------------------------------------------------------------


def get_overview_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    *,
    binding_id: str | None = None,
) -> dict[str, Any]:
    slow_dimensions = context.state_surface.slow_dimensions
    raw_states = sources.query_service.list_current_states(status_filter="current_like")
    grouped_states = _group_latest_states(raw_states, slow_dimensions=slow_dimensions)
    bundle_header = _extract_bundle_header(context)
    turn_stats = _extract_turn_stats(sources, bundle_header.get("runtime_ready_at"))

    recent = sources.recent_turns(1)
    last_turn = recent[0] if recent else None
    last_appraisal = None
    if last_turn is not None and last_turn.appraisals:
        a = last_turn.appraisals[0]
        last_appraisal = {
            "appraisal_id": a.appraisal_id,
            "polarity": a.polarity,
            "authority": a.authority,
            "causal_status": a.causal_status,
            "provider_confidence": a.provider_confidence,
        }
    last_decision = None
    if last_turn is not None and last_turn.decisions:
        d = last_turn.decisions[0]
        last_decision = {
            "appraisal_id": d.appraisal_id,
            "rule_id": d.rule_id,
            "applied": d.applied,
            "reason_code": d.reason_code,
            "abstention_reason": d.abstention_reason,
            "source_ref": d.source_ref,
        }
    last_change = None
    if last_turn is not None:
        for dim in sorted(last_turn.assessment_trace.state_after.keys()):
            before = last_turn.assessment_trace.state_before.get(dim, 0.0)
            after = last_turn.assessment_trace.state_after.get(dim, 0.0)
            if abs(after - before) > 1e-9:
                last_change = {
                    "dimension": dim,
                    "before": before,
                    "after": after,
                    "delta": after - before,
                }
                break

    data: dict[str, Any] = {
        "bundle_header": bundle_header,
        "turn_stats": turn_stats,
        "current_states": grouped_states,
        "last_turn": {
            "interaction_id": last_turn.interaction_id if last_turn else None,
            "composition": last_turn.composition.value if last_turn else None,
            "trace_id": last_turn.assessment_trace.trace_id if last_turn else None,
            "created_at": last_turn.trace_created_at if last_turn else None,
            "last_appraisal": last_appraisal,
            "last_decision": last_decision,
            "last_change": last_change,
        } if last_turn is not None else None,
        "turn_count": turn_stats["persisted_committed_turns"],
        "state_surface": context.state_surface.to_payload(),
    }
    if binding_id is not None:
        data["binding_id"] = binding_id
    return data


def get_trends_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    limit: int = 30,
    *,
    binding_id: str | None = None,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        limit = 30
    conn_state, conn_facts = _extract_connections(sources, context)
    slow_primary = context.state_surface.slow_dimensions[0] if context.state_surface.slow_dimensions else None
    fast_dims = context.state_surface.fast_dimensions

    if conn_state is not None:
        try:
            data = get_affect_trends(
                conn_state=conn_state,
                conn_facts=conn_facts,
                limit=limit,
                fast_dimensions=fast_dims,
                slow_dimension=slow_primary,
            )
            if binding_id is not None:
                data["binding_id"] = binding_id
            return data
        except Exception as exc:
            _logger.warning("Failed generating affect trends: %s", exc)

    data = {
        "points": [],
        "dimensions": {},
        "accumulated_self": {
            "dimension": slow_primary,
            "label": slow_primary.split(".")[-1] if slow_primary else None,
            "status": "NOT ESTABLISHED",
            "current_value": None,
            "formatted_value": "NOT ESTABLISHED",
            "version": None,
            "updated_at": None,
            "history": [],
        },
        "latest_moment": None,
    }
    if binding_id is not None:
        data["binding_id"] = binding_id
    return data


def get_states_payload(sources: OWDashboardDataSources) -> dict[str, Any]:
    states = sources.query_service.list_current_states()
    return {
        "states": [
            {
                "state_id": s.state_id,
                "dimension": s.dimension,
                "value": s.value,
                "status": s.status,
                "lifecycle_class": s.lifecycle_class,
                "version": s.version,
                "updated_at": s.updated_at,
                "evidence_refs": list(s.evidence_refs),
                "transition_refs": list(s.transition_refs),
            }
            for s in states
        ]
    }


def get_single_state_payload(sources: OWDashboardDataSources, dimension: str) -> dict[str, Any]:
    rows = sources.query_service.list_current_states(dimension=dimension)
    current = next((r for r in rows if r.status in ("active", "improving")), None)
    if current is None:
        raise HTTPException(status_code=404, detail=f"no current state for {dimension!r}")
    return {
        "state_id": current.state_id,
        "dimension": current.dimension,
        "value": current.value,
        "status": current.status,
        "lifecycle_class": current.lifecycle_class,
        "version": current.version,
        "updated_at": current.updated_at,
        "evidence_refs": list(current.evidence_refs),
        "transition_refs": list(current.transition_refs),
    }


def get_state_history_payload(sources: OWDashboardDataSources, dimension: str) -> dict[str, Any]:
    all_rows = sources.query_service.list_current_states(dimension=dimension)
    versions = sorted(all_rows, key=lambda r: r.version)
    history = []
    for r in versions:
        history.append({
            "state_id": r.state_id,
            "version": r.version,
            "value": r.value,
            "status": r.status,
            "updated_at": r.updated_at,
            "evidence_refs": list(r.evidence_refs),
            "transition_refs": list(r.transition_refs),
        })
    return {"dimension": dimension, "history": history}


def get_turns_head_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext | None = None,
) -> dict[str, Any]:
    conn_state, _ = _extract_connections(sources, context)
    latest_id = None
    comm_at = None
    total = 0
    if conn_state is not None:
        try:
            row = conn_state.execute(
                "SELECT interaction_id, committed_at FROM commit_markers "
                "ORDER BY committed_at DESC, interaction_id DESC LIMIT 1"
            ).fetchone()
            if row:
                latest_id = row[0]
                comm_at = row[1]
            count_row = conn_state.execute("SELECT COUNT(1) FROM commit_markers").fetchone()
            if count_row:
                total = count_row[0]
        except Exception:
            pass
    return {
        "latest_interaction_id": latest_id,
        "committed_at": comm_at,
        "total_committed": total,
        "epoch_turns": total,
    }


def get_turns_list_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    limit: int = 20,
    before: str | None = None,
    moments_only: bool = False,
    *,
    binding_id: str | None = None,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        limit = 20

    before_comm_at = None
    before_ix_id = None
    if before:
        if binding_id is not None:
            if ":" not in before:
                raise ScopedBindingError(
                    400,
                    "CURSOR_BINDING_MISMATCH",
                    "cursor is missing binding identity or was issued for a different binding",
                )
            cursor_bid, cursor_body = before.split(":", 1)
            if cursor_bid != binding_id:
                raise ScopedBindingError(
                    400,
                    "CURSOR_BINDING_MISMATCH",
                    f"cursor issued for binding {cursor_bid!r} cannot be used for {binding_id!r}",
                )
            if "|" in cursor_body:
                before_comm_at, before_ix_id = cursor_body.split("|", 1)
            else:
                before_comm_at = cursor_body
        else:
            if "|" in before:
                before_comm_at, before_ix_id = before.split("|", 1)
            else:
                before_comm_at = before

    conn_state, conn_facts = _extract_connections(sources, context)
    slow_primary = context.state_surface.slow_dimensions[0] if context.state_surface.slow_dimensions else None
    trace_db = context.telemetry_source.db_path

    if conn_state is not None and conn_facts is not None:
        try:
            db_turns = list_committed_turns(
                conn_state=conn_state,
                conn_facts=conn_facts,
                limit=limit,
                before_committed_at=before_comm_at,
                before_interaction_id=before_ix_id,
                trace_db=trace_db,
                moments_only=moments_only,
                slow_dimension=slow_primary,
            )
            next_cursor = None
            has_more = False
            if len(db_turns) == limit:
                has_more = True
                last_item = db_turns[-1]
                raw_cursor = f"{last_item['committed_at']}|{last_item['interaction_id']}"
                if binding_id is not None:
                    next_cursor = f"{binding_id}:{raw_cursor}"
                else:
                    next_cursor = raw_cursor

            res = {
                "turns": db_turns,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
            if binding_id is not None:
                res["binding_id"] = binding_id
            return res
        except Exception as exc:
            _logger.warning("Failed listing committed turns from DB: %s", exc)

    snaps = sources.recent_turns(limit)
    ordered = tuple(reversed(snaps))
    in_memory_turns = [
        {
            "interaction_id": s.interaction_id,
            "composition": s.composition.value,
            "trace_id": s.assessment_trace.trace_id,
            "created_at": s.trace_created_at,
            "decisions": len(s.decisions),
            "applied": sum(1 for d in s.decisions if d.applied),
            "abstained": sum(1 for d in s.decisions if not d.applied),
            "changed_dimensions": _changed_dims(s),
        }
        for s in ordered
    ]
    res = {
        "turns": in_memory_turns,
        "next_cursor": None,
        "has_more": False,
    }
    if binding_id is not None:
        res["binding_id"] = binding_id
    return res


def get_turn_detail_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    turn_id: str,
) -> dict[str, Any]:
    snap = sources.get_turn(turn_id)
    if snap is None:
        conn_state, conn_facts = _extract_connections(sources, context)
        slow_primary = context.state_surface.slow_dimensions[0] if context.state_surface.slow_dimensions else None
        hermes_db = context.assistant_message_source.db_path
        trace_db = context.telemetry_source.db_path
        if conn_state is not None and conn_facts is not None:
            trace = build_human_causal_trace(
                turn_id,
                conn_state,
                conn_facts,
                hermes_db=hermes_db,
                trace_db=trace_db,
                slow_dimension=slow_primary,
            )
            if trace and trace.get("user_input", {}).get("status") == "AVAILABLE":
                return {"turn": {"interaction_id": turn_id, "human_trace": trace}}
        raise HTTPException(status_code=404, detail=f"turn {turn_id!r} not found")
    return {"turn": _serialize_turn(snap)}


def get_causal_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    turn_id: str,
) -> dict[str, Any]:
    scope_key = context.binding_scope_key
    causal_store = context.causal_trace_store
    cached = causal_store.get(scope_key, turn_id)
    if cached is not None:
        return cached

    conn_state, conn_facts = _extract_connections(sources, context)
    slow_primary = context.state_surface.slow_dimensions[0] if context.state_surface.slow_dimensions else None
    trace_db = context.telemetry_source.db_path
    hermes_db = context.assistant_message_source.db_path
    live_snap = sources.get_turn(turn_id)
    human_trace = None

    if conn_state is not None and conn_facts is not None:
        try:
            human_trace = build_human_causal_trace(
                interaction_id=turn_id,
                conn_state=conn_state,
                conn_facts=conn_facts,
                hermes_db=hermes_db,
                live_snapshot=live_snap,
                trace_db=trace_db,
                slow_dimension=slow_primary,
            )
        except Exception:
            pass

    chains = sources.chains_for_turn(turn_id)
    chains_list: list[dict[str, Any]] = []
    if chains is not None:
        chains_list = [
            {
                "dimension": c.dimension,
                "state_before": c.state_before,
                "state_after": c.state_after,
                "delta": c.delta,
                "has_appraisal": c.has_appraisal,
                "has_applied_decision": c.has_applied_decision,
                "has_abstention": c.has_abstention,
                "abstention_reasons": list(c.abstention_reasons),
                "chain": [
                    {
                        "kind": link.kind,
                        "identifier": link.identifier,
                        "label": link.label,
                        "amount": link.amount,
                        "confidence": link.confidence,
                        "source_ref": link.source_ref,
                        "applied": link.applied,
                        "reason_code": link.reason_code,
                    }
                    for link in c.chain
                ],
            }
            for c in chains
        ]

    has_data = (
        (human_trace is not None and (
            human_trace.get("user_input", {}).get("status") == "AVAILABLE"
            or bool(human_trace.get("changed_states"))
            or bool(human_trace.get("unchanged_states"))
        ))
        or bool(chains_list)
    )
    if not has_data:
        exists = False
        if conn_state is not None:
            try:
                row = conn_state.execute(
                    "SELECT 1 FROM commit_markers WHERE interaction_id = ?", (turn_id,)
                ).fetchone()
                exists = bool(row)
            except Exception:
                pass
        if not exists and live_snap is None:
            raise HTTPException(status_code=404, detail=f"turn {turn_id!r} not found")

    resp = {
        "turn_id": turn_id,
        "human_trace": human_trace,
        "chains": chains_list,
    }

    if _is_terminal_trace(human_trace):
        causal_store.put(scope_key, turn_id, resp)

    return resp


def get_human_causal_trace_payload(
    sources: OWDashboardDataSources,
    context: ObservationContext,
    turn_id: str,
) -> dict[str, Any]:
    scope_key = context.binding_scope_key
    causal_store = context.causal_trace_store
    cached = causal_store.get(scope_key, turn_id)
    if cached is not None:
        ht = cached.get("human_trace")
        if ht:
            return ht

    conn_state, conn_facts = _extract_connections(sources, context)
    slow_primary = context.state_surface.slow_dimensions[0] if context.state_surface.slow_dimensions else None
    trace_db = context.telemetry_source.db_path
    hermes_db = context.assistant_message_source.db_path
    live_snap = sources.get_turn(turn_id)

    if conn_state is None or conn_facts is None:
        raise HTTPException(status_code=503, detail="Durable databases unavailable")

    trace = build_human_causal_trace(
        interaction_id=turn_id,
        conn_state=conn_state,
        conn_facts=conn_facts,
        hermes_db=hermes_db,
        live_snapshot=live_snap,
        trace_db=trace_db,
        slow_dimension=slow_primary,
    )
    if not trace:
        raise HTTPException(status_code=404, detail=f"turn {turn_id!r} not found")

    has_data = (
        trace.get("user_input", {}).get("status") == "AVAILABLE"
        or bool(trace.get("changed_states"))
        or bool(trace.get("unchanged_states"))
    )
    if not has_data:
        exists = False
        try:
            row = conn_state.execute("SELECT 1 FROM commit_markers WHERE interaction_id = ?", (turn_id,)).fetchone()
            exists = bool(row)
        except Exception:
            pass
        if not exists and live_snap is None:
            raise HTTPException(status_code=404, detail=f"turn {turn_id!r} not found")

    if _is_terminal_trace(trace):
        if not causal_store.replace_field(scope_key, turn_id, "human_trace", trace):
            causal_store.put(
                scope_key,
                turn_id,
                {"turn_id": turn_id, "human_trace": trace, "chains": []},
            )
    return trace


def get_live_trace_payload(context: ObservationContext) -> dict[str, Any]:
    provider = context.live_trace_provider
    if not callable(provider):
        return {
            "status": "CAPABILITY_UNAVAILABLE",
            "header": None,
            "latest_turn": [],
            "persisted_slow_states": [],
        }
    return provider()


def get_evidence_payload(sources: OWDashboardDataSources, id: str) -> dict[str, Any]:
    ev = sources.query_service.get_evidence(id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"evidence {id!r} not found")
    return {
        "evidence_id": ev.evidence_id,
        "scope": str(ev.scope),
        "source_kind": ev.source_kind.value,
        "source_id": ev.source_id,
        "source_type": ev.source_type,
        "occurred_at": ev.occurred_at,
        "received_at": ev.received_at,
        "payload": ev.payload,
        "origin_runtime_id": ev.origin_runtime_id,
    }


def get_provenance_payload(sources: OWDashboardDataSources, id: str) -> dict[str, Any]:
    from observation_window.provenance import ProvenanceBuilder
    state = sources.query_service.get_state(id)
    if state is not None:
        pb = ProvenanceBuilder(
            state_backend=sources.query_service._state,  # type: ignore[attr-defined]
            fact_backend=sources.query_service._fact,  # type: ignore[attr-defined]
        )
        graph = pb.graph_for_state(id)
        return {
            "root_kind": graph.root_kind.value,
            "root_id": graph.root_id,
            "incomplete": graph.incomplete,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "kind": n.provenance_kind.value,
                    "raw_id": n.raw_id,
                    "label": n.label,
                    "extra": n.extra,
                    "upstream": list(n.upstream),
                    "lifecycle_note": n.lifecycle_note,
                }
                for n in graph.nodes
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation": e.relation,
                }
                for e in graph.edges
            ],
        }
    ev = sources.query_service.get_evidence(id)
    if ev is not None:
        pb = ProvenanceBuilder(
            state_backend=sources.query_service._state,  # type: ignore[attr-defined]
            fact_backend=sources.query_service._fact,  # type: ignore[attr-defined]
        )
        graph = pb.graph_for_evidence(id)
        return {
            "root_kind": graph.root_kind.value,
            "root_id": graph.root_id,
            "incomplete": graph.incomplete,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "kind": n.provenance_kind.value,
                    "raw_id": n.raw_id,
                    "label": n.label,
                    "extra": n.extra,
                    "upstream": list(n.upstream),
                    "lifecycle_note": n.lifecycle_note,
                }
                for n in graph.nodes
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation": e.relation,
                }
                for e in graph.edges
            ],
        }
    raise HTTPException(status_code=404, detail=f"no provenance for {id!r}")


# ---------------------------------------------------------------------------
# Router Construction
# ---------------------------------------------------------------------------


def build_router(
    sources: OWDashboardDataSources,
    context: ObservationContext | None = None,
    catalog: ObservationBindingCatalog | None = None,
) -> APIRouter:
    """Construct the FastAPI router bound to data sources and optional binding catalog.

    ``context`` is the binding context (OW-MULTI-AGENT-BINDING-PHASE01-V1).
    When absent, an explicit-source compat context is used: no ontology
    membership, optional sources degraded, single shared cache scope.
    ``catalog`` exposes multi-agent binding-scoped APIs (Phase 2).
    """
    if context is None:
        context = _default_context()

    router = APIRouter()

    def _scoped(binding_id: str) -> ScopedObservationBinding:
        if catalog is None:
            raise ScopedBindingError(
                503,
                "BINDING_REGISTRY_UNAVAILABLE",
                "binding registry catalog is not configured",
            )
        return catalog.resolve(binding_id)

    def _legacy_binding(request: Request) -> ScopedObservationBinding | None:
        """Resolve the binding for a legacy API request.

        Production legacy APIs are aliases for the explicit PRODUCTION
        default when ``runtime`` is absent. A present runtime query always
        wins, including malformed/ambiguous values (which fail closed without
        consulting the default).
        """
        if catalog is None:
            return None
        values = request.query_params.getlist("runtime")
        if not values:
            return catalog.resolve_default()
        if len(values) != 1 or not _RUNTIME_ID_RE.fullmatch(values[0]):
            raise ScopedBindingError(
                400,
                "INVALID_RUNTIME_SELECTION",
                "runtime query parameter is empty, ambiguous, or malformed",
            )
        return catalog.resolve(values[0])

    def _legacy_page(request: Request, page_name: str) -> HTMLResponse | RedirectResponse:
        """Render explicit pages or redirect absent-runtime aliases.

        Only the registry descriptor is read before the 307 is built. The
        physical binding is resolved after the browser reloads the scoped URL.
        """
        if catalog is None or "runtime" in request.query_params:
            return _render_page(page_name)
        descriptor = catalog.default_descriptor()
        query = list(parse_qsl(request.url.query, keep_blank_values=True))
        query.append(("runtime", descriptor.binding_id))
        location = request.url.path + "?" + urlencode(query, doseq=True)
        return RedirectResponse(url=location, status_code=307)

    # ------------------------------------------------------------------
    # Public Binding Enumeration (Phase 2)
    # ------------------------------------------------------------------

    @router.get("/api/runtime-bindings")
    def list_runtime_bindings() -> Any:
        if catalog is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "BINDING_REGISTRY_UNAVAILABLE",
                    "message": "binding registry catalog is not configured",
                    "detail": "binding registry catalog is not configured",
                },
            )
        try:
            descriptors = catalog.list_descriptors()
            return _json({
                "bindings": [
                    {
                        "binding_id": d.binding_id,
                        "environment": d.environment.value,
                        "agent_id": d.agent_id,
                        "runtime_id": d.runtime_id,
                    }
                    for d in descriptors
                ]
            })
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    # ------------------------------------------------------------------
    # Scoped Read Routes (Phase 2)
    # ------------------------------------------------------------------

    @router.get("/api/runtime-bindings/{binding_id}/overview")
    def scoped_overview(binding_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            return _json(get_overview_payload(b.sources, b.context, binding_id=b.binding_id))
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/trends")
    def scoped_trends(binding_id: str, limit: int = 30) -> Any:
        try:
            b = _scoped(binding_id)
            return _json(get_trends_payload(b.sources, b.context, limit, binding_id=b.binding_id))
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/states")
    def scoped_list_states(binding_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_states_payload(b.sources)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/states/{dimension}")
    def scoped_get_state(binding_id: str, dimension: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_single_state_payload(b.sources, dimension)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/states/{dimension}/history")
    def scoped_state_history(binding_id: str, dimension: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_state_history_payload(b.sources, dimension)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/turns/head")
    def scoped_turns_head(binding_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_turns_head_payload(b.sources, b.context)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/turns")
    def scoped_list_turns(
        binding_id: str,
        limit: int = 20,
        before: str | None = None,
        moments_only: bool = False,
    ) -> Any:
        try:
            b = _scoped(binding_id)
            return _json(get_turns_list_payload(
                b.sources, b.context, limit, before, moments_only, binding_id=b.binding_id
            ))
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/turns/{turn_id}")
    def scoped_get_turn(binding_id: str, turn_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_turn_detail_payload(b.sources, b.context, turn_id)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/turns/{turn_id}/causal")
    def scoped_get_turn_causal(binding_id: str, turn_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_causal_payload(b.sources, b.context, turn_id)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/turns/{turn_id}/human-causal-trace")
    def scoped_get_turn_human_causal_trace(binding_id: str, turn_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_human_causal_trace_payload(b.sources, b.context, turn_id)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/live-trace")
    def scoped_api_live_trace(binding_id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = _json(get_live_trace_payload(b.context))
            res["binding_id"] = b.binding_id
            return res
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/evidence/{id}")
    def scoped_get_evidence(binding_id: str, id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_evidence_payload(b.sources, id)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    @router.get("/api/runtime-bindings/{binding_id}/provenance/{id}")
    def scoped_get_provenance(binding_id: str, id: str) -> Any:
        try:
            b = _scoped(binding_id)
            res = get_provenance_payload(b.sources, id)
            res["binding_id"] = b.binding_id
            return _json(res)
        except ScopedBindingError as exc:
            return _scoped_error_response(exc)

    # ------------------------------------------------------------------
    # Legacy Endpoints (Phase 0/1 Unchanged)
    # ------------------------------------------------------------------

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "read_only": True,
            "ow_p1": True,
            "ow_3": True,
        }

    @router.get("/api/live-trace")
    def api_live_trace(request: Request) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            res = _json(get_live_trace_payload(b.context))
            res["binding_id"] = b.binding_id
            return res
        return _json(get_live_trace_payload(context))

    @router.get("/api/overview")
    def overview(request: Request) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            return _json(get_overview_payload(b.sources, b.context, binding_id=b.binding_id))
        return _json(get_overview_payload(sources, context))

    @router.get("/api/states")
    def list_states(request: Request) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_states_payload(b.sources)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_states_payload(sources))

    @router.get("/api/states/{dimension}")
    def get_state(request: Request, dimension: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_single_state_payload(b.sources, dimension)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_single_state_payload(sources, dimension))

    @router.get("/api/states/{dimension}/history")
    def state_history(request: Request, dimension: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_state_history_payload(b.sources, dimension)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_state_history_payload(sources, dimension))

    @router.get("/api/turns/head")
    def get_turns_head(request: Request) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_turns_head_payload(b.sources, b.context)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_turns_head_payload(sources, context))

    @router.get("/api/trends")
    def get_trends(request: Request, limit: int = 30) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            return _json(get_trends_payload(b.sources, b.context, limit, binding_id=b.binding_id))
        return _json(get_trends_payload(sources, context, limit))

    @router.get("/api/turns")
    def list_turns(
        request: Request,
        limit: int = 20,
        before: str | None = None,
        moments_only: bool = False,
    ) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            return _json(get_turns_list_payload(
                b.sources, b.context, limit, before, moments_only, binding_id=b.binding_id
            ))
        return _json(get_turns_list_payload(sources, context, limit, before, moments_only))

    @router.get("/api/turns/{turn_id}")
    def get_turn(request: Request, turn_id: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_turn_detail_payload(b.sources, b.context, turn_id)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_turn_detail_payload(sources, context, turn_id))

    @router.get("/api/turns/{turn_id}/causal")
    def get_turn_causal(request: Request, turn_id: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_causal_payload(b.sources, b.context, turn_id)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_causal_payload(sources, context, turn_id))

    @router.get("/api/turns/{turn_id}/human-causal-trace")
    def get_turn_human_causal_trace(request: Request, turn_id: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_human_causal_trace_payload(b.sources, b.context, turn_id)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_human_causal_trace_payload(sources, context, turn_id))

    @router.get("/api/evidence/{id}")
    def get_evidence(request: Request, id: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_evidence_payload(b.sources, id)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_evidence_payload(sources, id))

    @router.get("/api/provenance/{id}")
    def get_provenance(request: Request, id: str) -> Any:
        b = _legacy_binding(request)
        if b is not None:
            result = get_provenance_payload(b.sources, id)
            result["binding_id"] = b.binding_id
            return _json(result)
        return _json(get_provenance_payload(sources, id))

    # ------------------------------------------------------------------
    # Pages (server-rendered)
    # ------------------------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    def page_state(request: Request) -> Any:
        return _legacy_page(request, "state.html")

    @router.get("/overview", response_class=HTMLResponse)
    def page_overview_alias(request: Request) -> Any:
        return _legacy_page(request, "state.html")

    @router.get("/state", response_class=HTMLResponse)
    def page_state_alias(request: Request) -> Any:
        return _legacy_page(request, "state.html")

    @router.get("/moments", response_class=HTMLResponse)
    def page_moments(request: Request) -> Any:
        return _legacy_page(request, "moments.html")

    @router.get("/timeline", response_class=HTMLResponse)
    def page_timeline_alias(request: Request) -> Any:
        return _legacy_page(request, "moments.html")

    @router.get("/debug/causal", response_class=HTMLResponse)
    def page_debug_causal(request: Request) -> Any:
        return _legacy_page(request, "causal.html")

    @router.get("/causal", response_class=HTMLResponse)
    def page_causal_alias(request: Request) -> Any:
        return _legacy_page(request, "causal.html")

    @router.get("/debug/ledger", response_class=HTMLResponse)
    def page_debug_ledger(request: Request) -> Any:
        return _legacy_page(request, "ledger.html")

    @router.get("/history", response_class=HTMLResponse)
    def page_history_alias(request: Request) -> Any:
        return _legacy_page(request, "ledger.html")

    @router.get("/debug/live-trace", response_class=HTMLResponse)
    def page_debug_live_trace(request: Request) -> Any:
        return _legacy_page(request, "live_trace.html")

    @router.get("/debug/runtime", response_class=HTMLResponse)
    def page_debug_runtime_alias(request: Request) -> Any:
        return _legacy_page(request, "live_trace.html")

    @router.get("/live-trace", response_class=HTMLResponse)
    def page_live_trace_alias(request: Request) -> Any:
        return _legacy_page(request, "live_trace.html")

    @router.get("/live", response_class=HTMLResponse)
    def page_live_alias(request: Request) -> Any:
        return _legacy_page(request, "live_trace.html")

    @router.get("/static/{file_path:path}")
    def static_file(file_path: str):
        from fastapi.responses import FileResponse
        full = (_STATIC_DIR / file_path).resolve()
        if not str(full).startswith(str(_STATIC_DIR.resolve())):
            raise HTTPException(status_code=400, detail="path escapes static dir")
        if not full.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(str(full))

    return router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _changed_dims(snap: ObservedTurnSnapshot) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dim in sorted(snap.assessment_trace.state_after.keys()):
        before = snap.assessment_trace.state_before.get(dim, 0.0)
        after = snap.assessment_trace.state_after.get(dim, 0.0)
        if abs(after - before) > 1e-9:
            out.append({
                "dimension": dim,
                "before": before,
                "after": after,
                "delta": after - before,
            })
    return out


def _serialize_turn(snap: ObservedTurnSnapshot) -> dict[str, Any]:
    return {
        "interaction_id": snap.interaction_id,
        "scope": str(snap.scope),
        "origin_runtime_id": snap.origin_runtime_id,
        "composition": snap.composition.value,
        "trace_id": snap.assessment_trace.trace_id,
        "created_at": snap.trace_created_at,
        "snapshot_at": snap.snapshot_at,
        "appraisals": [
            {
                "appraisal_id": a.appraisal_id,
                "polarity": a.polarity,
                "authority": a.authority,
                "causal_status": a.causal_status,
                "provider_confidence": a.provider_confidence,
                "primary_evidence_refs": list(a.primary_evidence_refs),
                "secondary_evidence_refs": list(a.secondary_evidence_refs),
            }
            for a in snap.appraisals
        ],
        "appraisal_source": (
            {
                "abstention_reason": snap.appraisal_source.abstention_reason,
                "reject_reason": snap.appraisal_source.reject_reason,
                "candidate_count": snap.appraisal_source.candidate_count,
                "rejected_count": snap.appraisal_source.rejected_count,
                "provenance_ref": snap.appraisal_source.provenance_ref,
            }
            if snap.appraisal_source is not None
            else None
        ),
        "decisions": [
            {
                "decision_index": d.decision_index,
                "appraisal_id": d.appraisal_id,
                "rule_id": d.rule_id,
                "matched_state_refs": list(d.matched_state_refs),
                "evidence_refs": list(d.evidence_refs),
                "provider_confidence": d.provider_confidence,
                "applied": d.applied,
                "reason_code": d.reason_code,
                "abstention_reason": d.abstention_reason,
                "effective_dimension": d.effective_dimension,
                "source_ref": d.source_ref,
            }
            for d in snap.decisions
        ],
        "state_before": dict(snap.assessment_trace.state_before),
        "state_after": dict(snap.assessment_trace.state_after),
        "abstention_reasons": list(snap.assessment_trace.abstention_reasons),
        "evidence_refs": list(snap.assessment_trace.evidence_refs),
        "history_refs": list(snap.assessment_trace.history_refs),
        "contributions": [
            {
                "dimension": c.dimension,
                "source_kind": c.source_kind,
                "source_ref": c.source_ref,
                "amount": c.amount,
                "confidence": c.confidence,
                "applied": c.applied,
                "reason_code": c.reason_code,
            }
            for c in snap.assessment_trace.contributions
        ],
        "changed_dimensions": _changed_dims(snap),
    }
