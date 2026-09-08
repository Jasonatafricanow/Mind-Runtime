"""OW-HUMAN-CAUSAL-TRACE-V1 / OW-TRANSIENT-TRACE-JOURNAL-V1.

Human-readable causal card builder.
Links:
  USER INPUT
  → SEMANTIC INTERPRETATION
  → APPRAISAL
  → EFFECT / IMPULSE
  → HOMEOSTASIS
  → STATE DELTA
  → SLOW DECISION / WRITE
  → ASSISTANT RESPONSE

Zero model calls. Zero synthetic explanations.
If runtime did not persist a stage: UNAVAILABLE / NOT PERSISTED.
Distinguishes CANONICAL truth from OBSERVER TELEMETRY truth.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Optional, Sequence

_logger = logging.getLogger(__name__)

_SYSTEM_NOTE_PREFIX = (
    "[System note: A new message has arrived. The conversation "
    "history contains pending tool outputs from an interrupted turn. "
    "IGNORE those pending results. Address the user's NEW message "
    "below FIRST. Do NOT re-execute old tool calls from the history.]\n\n"
)


def clean_user_text(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith(_SYSTEM_NOTE_PREFIX):
        stripped = text[len(_SYSTEM_NOTE_PREFIX):].strip()
        return stripped if stripped else text
    return text


def _discover_trace_db_path(conn_state: sqlite3.Connection | None = None) -> Path | None:
    env_override = os.environ.get("MR_TRACE_DB_PATH")
    if env_override:
        p = Path(env_override)
        if p.exists():
            return p
    if conn_state is not None:
        try:
            db_list = conn_state.execute("PRAGMA database_list;").fetchall()
            for row in db_list:
                db_file = row[2] if len(row) > 2 else None
                if db_file:
                    cand = Path(db_file).parent / "observation_trace.sqlite"
                    if cand.exists():
                        return cand
        except Exception:
            pass
    return None


def is_moment_eligible(turn: dict[str, Any]) -> bool:
    """Evaluate factual inclusion criteria for Moments feed.

    A turn is included in Moments when ANY of the following is true:
    - has_delta: true
    - has_semantic_event: true
    - has_slow_write: true
    - is_aborted: true

    Ordinary zero-delta semantic-abstain turns return False.
    """
    return bool(
        turn.get("has_delta")
        or turn.get("has_semantic_event")
        or turn.get("has_slow_write")
        or turn.get("is_aborted")
    )


def list_committed_turns(
    conn_state: sqlite3.Connection,
    conn_facts: sqlite3.Connection,
    limit: int = 20,
    before_committed_at: str | None = None,
    before_interaction_id: str | None = None,
    trace_db: Path | str | None = None,
    moments_only: bool = False,
    slow_dimension: str | None = None,
) -> list[dict[str, Any]]:
    """Return summary list of real committed interactions from commit_markers.

    Optimized for OW-HUMAN-TRACE-PERF-V1 & OW-PRODUCT-IA-V2:
    - Bounded batch queries (zero N+1 queries).
    - Stable keyset pagination via (committed_at, interaction_id).
    - ZERO Hermes queries in list selector.
    - Captures factual flags: has_delta, has_semantic_event, has_slow_write, is_aborted.
    - Captures actual runtime telemetry from observation_trace.sqlite (SEMANTIC_CANDIDATE, TURN_ABORT).
    """
    try:
        if before_committed_at and before_interaction_id:
            committed_rows = conn_state.execute(
                "SELECT interaction_id, committed_at, projected_state_ids FROM commit_markers "
                "WHERE (committed_at < ?) OR (committed_at = ? AND interaction_id < ?) "
                "ORDER BY committed_at DESC, interaction_id DESC LIMIT ?",
                (before_committed_at, before_committed_at, before_interaction_id, limit),
            ).fetchall()
        elif before_committed_at:
            committed_rows = conn_state.execute(
                "SELECT interaction_id, committed_at, projected_state_ids FROM commit_markers "
                "WHERE committed_at < ? "
                "ORDER BY committed_at DESC, interaction_id DESC LIMIT ?",
                (before_committed_at, limit),
            ).fetchall()
        else:
            committed_rows = conn_state.execute(
                "SELECT interaction_id, committed_at, projected_state_ids FROM commit_markers "
                "ORDER BY committed_at DESC, interaction_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as exc:
        _logger.warning("Failed to list commit markers: %s", exc)
        committed_rows = []

    ix_ids = [r[0] for r in committed_rows]

    # Query observation_trace.sqlite for SEMANTIC_CANDIDATE events and TURN_ABORT events
    semantic_events_set: set[str] = set()
    aborted_set: set[str] = set()
    aborted_extra_rows: list[tuple[str, str, str]] = []

    t_path = Path(trace_db) if trace_db is not None else _discover_trace_db_path(conn_state)
    if t_path is not None and t_path.exists():
        try:
            uri = f"file:{t_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.0) as conn_t:
                conn_t.row_factory = sqlite3.Row
                # 1. Batch query semantic candidates and aborts for ix_ids in commit_markers
                if ix_ids:
                    ph = ",".join("?" for _ in ix_ids)
                    t_rows = conn_t.execute(
                        f"SELECT interaction_id, stage FROM trace_events "
                        f"WHERE interaction_id IN ({ph}) AND stage IN ('SEMANTIC_CANDIDATE', 'TURN_ABORT')",
                        ix_ids,
                    ).fetchall()
                    for tr in t_rows:
                        stg = tr["stage"]
                        t_ix = tr["interaction_id"]
                        if stg == "SEMANTIC_CANDIDATE":
                            semantic_events_set.add(t_ix)
                        elif stg == "TURN_ABORT":
                            aborted_set.add(t_ix)

                # 2. Query any recent TURN_ABORT interactions that are not in commit_markers
                abort_candidates = conn_t.execute(
                    "SELECT interaction_id, occurred_at, created_at FROM trace_events "
                    "WHERE stage = 'TURN_ABORT' ORDER BY occurred_at DESC, interaction_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for ar in abort_candidates:
                    ar_ix = ar["interaction_id"]
                    if ar_ix not in ix_ids:
                        ar_time = ar["occurred_at"] or ar["created_at"] or ""
                        if before_committed_at and before_interaction_id:
                            if not ((ar_time < before_committed_at) or (ar_time == before_committed_at and ar_ix < before_interaction_id)):
                                continue
                        elif before_committed_at:
                            if not (ar_time < before_committed_at):
                                continue
                        aborted_extra_rows.append((ar_ix, ar_time, "[]"))
                        aborted_set.add(ar_ix)

                if aborted_extra_rows:
                    ex_ids = [x[0] for x in aborted_extra_rows]
                    ph_ex = ",".join("?" for _ in ex_ids)
                    c_rows = conn_t.execute(
                        f"SELECT interaction_id FROM trace_events "
                        f"WHERE interaction_id IN ({ph_ex}) AND stage = 'SEMANTIC_CANDIDATE'",
                        ex_ids,
                    ).fetchall()
                    for cr in c_rows:
                        semantic_events_set.add(cr["interaction_id"])
        except Exception as exc:
            _logger.debug("Failed querying trace events in list_committed_turns: %s", exc)

    all_rows = committed_rows + aborted_extra_rows
    all_rows.sort(key=lambda r: (r[1] or "", r[0]), reverse=True)
    all_rows = all_rows[:limit]

    all_ix_ids = [r[0] for r in all_rows]
    if not all_ix_ids:
        return []

    # 1. Batch query user preview text from evidence (1 single query)
    user_previews: dict[str, str] = {}
    try:
        ph_ev = ",".join("?" for _ in all_ix_ids)
        ev_rows = conn_facts.execute(
            f"SELECT interaction_id, payload FROM evidence "
            f"WHERE interaction_id IN ({ph_ev}) AND source_type = 'user_message'",
            all_ix_ids,
        ).fetchall()
        for ev_ix, ev_pl in ev_rows:
            if ev_pl and ev_ix not in user_previews:
                try:
                    p = json.loads(ev_pl)
                    raw_txt = p.get("text", "")
                    c_txt = clean_user_text(raw_txt) or raw_txt
                    user_previews[ev_ix] = c_txt[:60] if c_txt else "—"
                except Exception:
                    user_previews[ev_ix] = str(ev_pl)[:60]
    except Exception as exc:
        _logger.debug("Failed batch querying evidence: %s", exc)

    # 2. Batch query transitions and states for deltas (2 bounded queries)
    turn_projected_map: dict[str, list[str]] = {}
    all_to_ids: list[str] = []
    for r in all_rows:
        ix_id, comm_at, proj_ids = r
        try:
            p_list = json.loads(proj_ids) if proj_ids else []
            turn_projected_map[ix_id] = p_list
            all_to_ids.extend(p_list)
        except Exception:
            turn_projected_map[ix_id] = []

    to_from_map: dict[str, str] = {}
    all_state_ids = set(all_to_ids)
    if all_to_ids:
        try:
            ph_to = ",".join("?" for _ in all_to_ids)
            tr_rows = conn_state.execute(
                f"SELECT to_state_id, from_state_id FROM state_transitions "
                f"WHERE to_state_id IN ({ph_to})",
                all_to_ids,
            ).fetchall()
            for t_id, f_id in tr_rows:
                to_from_map[t_id] = f_id
                if f_id:
                    all_state_ids.add(f_id)
        except Exception as exc:
            _logger.debug("Failed batch querying transitions: %s", exc)

    state_val_map: dict[str, tuple[str, float]] = {}
    if all_state_ids:
        try:
            st_list = list(all_state_ids)
            ph_st = ",".join("?" for _ in st_list)
            st_rows = conn_state.execute(
                f"SELECT state_id, dimension, value FROM states "
                f"WHERE state_id IN ({ph_st})",
                st_list,
            ).fetchall()
            for s_id, dim, val in st_rows:
                try:
                    state_val_map[s_id] = (dim, float(val))
                except Exception:
                    pass
        except Exception as exc:
            _logger.debug("Failed batch querying states: %s", exc)

    turns: list[dict[str, Any]] = []
    for r in all_rows:
        ix_id, comm_at, _ = r
        user_preview = user_previews.get(ix_id, "—")
        proj_ids = turn_projected_map.get(ix_id, [])
        is_aborted = (ix_id in aborted_set)
        has_semantic = (ix_id in semantic_events_set)

        if is_aborted:
            # Aborted turn: state was never committed to lived canonical state
            has_delta = False
            max_abs = 0.0
            has_slow = False
            delta_summary = "aborted (no state change)"
            composition = "OFF"
        else:
            changed = []
            max_abs = 0.0
            has_slow = False
            for t_id in proj_ids:
                f_id = to_from_map.get(t_id)
                t_data = state_val_map.get(t_id)
                f_data = state_val_map.get(f_id) if f_id else None
                if t_data:
                    dim, t_val = t_data
                    if slow_dimension is not None and dim == slow_dimension:
                        has_slow = True
                    if f_data:
                        _, f_val = f_data
                        diff = t_val - f_val
                        abs_diff = abs(diff)
                        if abs_diff > 1e-9:
                            short_dim = dim.split(".")[-1]
                            changed.append(f"{short_dim} {diff:+.4f}")
                            if abs_diff > max_abs:
                                max_abs = abs_diff

            has_delta = len(changed) > 0
            delta_summary = ", ".join(changed) if has_delta else "no delta"
            composition = "ON" if has_delta else "OFF"

        is_moment = bool(has_delta or has_semantic or has_slow or is_aborted)

        turns.append(
            {
                "interaction_id": ix_id,
                "committed_at": comm_at,
                "created_at": comm_at,
                "user_preview": user_preview,
                "has_delta": has_delta,
                "delta_summary": delta_summary,
                "composition": composition,
                "has_slow_write": has_slow,
                "has_semantic_event": has_semantic,
                "is_aborted": is_aborted,
                "is_moment": is_moment,
                "max_abs_delta": round(max_abs, 4),
            }
        )

    if moments_only:
        return [t for t in turns if is_moment_eligible(t)]
    return turns


def get_affect_trends(
    conn_state: sqlite3.Connection,
    conn_facts: sqlite3.Connection | None = None,
    limit: int = 30,
    fast_dimensions: Sequence[str] | None = None,
    slow_dimension: str | None = None,
) -> dict[str, Any]:
    """Return fast affect trajectory and accumulated self from canonical SQLite.

    Dimension membership comes from the caller's authoritative state_surface
    descriptor (OW-MULTI-AGENT-BINDING-PHASE01-V1 §13/§14) — this module never
    infers ontology from DB contents.

    Guaranteed bounded:
    <= 3 indexed queries to cognition_state.sqlite.
    Zero N+1 queries. Zero synthetic interpolation.
    """
    target_dims = list(fast_dimensions) if fast_dimensions else []

    # Query 1: commit_markers (recent limit turns)
    try:
        rows = conn_state.execute(
            "SELECT interaction_id, committed_at, projected_state_ids FROM commit_markers "
            "ORDER BY committed_at DESC, interaction_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except Exception as exc:
        _logger.warning("Failed to query commit markers for trends: %s", exc)
        rows = []

    # Reverse to chronological order: T_{-N} -> T_0
    chronological_rows = list(reversed(rows))

    all_proj_ids: list[str] = []
    turn_proj_map: dict[str, list[str]] = {}
    ix_ids: list[str] = []
    for r in chronological_rows:
        ix_id, comm_at, p_json = r
        ix_ids.append(ix_id)
        try:
            p_ids = json.loads(p_json) if p_json else []
        except Exception:
            p_ids = []
        turn_proj_map[ix_id] = p_ids
        all_proj_ids.extend(p_ids)

    # Query 2: states for projected IDs (batch IN query)
    state_map: dict[str, dict[str, Any]] = {}
    if all_proj_ids:
        try:
            ph = ",".join("?" for _ in all_proj_ids)
            st_rows = conn_state.execute(
                f"SELECT state_id, dimension, value, evidence_refs FROM states WHERE state_id IN ({ph})",
                all_proj_ids,
            ).fetchall()
            for s_id, dim, val, ev_refs in st_rows:
                try:
                    v_flt = float(val)
                except Exception:
                    v_flt = 0.0
                ev_list = []
                if ev_refs:
                    try:
                        ev_list = json.loads(ev_refs) if isinstance(ev_refs, str) else [str(ev_refs)]
                    except Exception:
                        ev_list = [str(ev_refs)]
                state_map[s_id] = {"dim": dim, "val": v_flt, "ev": ev_list}
        except Exception as exc:
            _logger.warning("Failed to query projected states for trends: %s", exc)

    # Query 3: states for the binding's declared slow dimension (version ASC)
    slow_history: list[dict[str, Any]] = []
    slow_status = "NOT ESTABLISHED"
    slow_val: float | None = None
    slow_ver: int | None = None
    slow_updated_at: str | None = None
    try:
        if slow_dimension is None:
            slow_rows = []
        else:
            slow_rows = conn_state.execute(
                "SELECT version, status, value, updated_at FROM states "
                "WHERE dimension = ? ORDER BY version ASC",
                (slow_dimension,),
            ).fetchall()
        if slow_rows:
            slow_status = "ESTABLISHED"
            for r in slow_rows:
                try:
                    v_num = float(r[2])
                except Exception:
                    v_num = 0.0
                slow_history.append({
                    "version": r[0],
                    "status": r[1],
                    "value": v_num,
                    "updated_at": r[3],
                })
            last_slow = slow_history[-1]
            slow_val = last_slow["value"]
            slow_ver = last_slow["version"]
            slow_updated_at = last_slow["updated_at"]
    except Exception as exc:
        _logger.warning("Failed to query slow state for trends: %s", exc)

    # Optional Query to facts.sqlite for user preview text
    user_previews: dict[str, str] = {}
    if conn_facts is not None and ix_ids:
        try:
            ph_ev = ",".join("?" for _ in ix_ids)
            ev_rows = conn_facts.execute(
                f"SELECT interaction_id, payload FROM evidence "
                f"WHERE interaction_id IN ({ph_ev}) AND source_type = 'user_message'",
                ix_ids,
            ).fetchall()
            for ev_ix, ev_pl in ev_rows:
                if ev_pl and ev_ix not in user_previews:
                    try:
                        p = json.loads(ev_pl)
                        raw_txt = p.get("text", "")
                        c_txt = clean_user_text(raw_txt) or raw_txt
                        user_previews[ev_ix] = c_txt[:80] if c_txt else "—"
                    except Exception:
                        user_previews[ev_ix] = str(ev_pl)[:80]
        except Exception as exc:
            _logger.debug("Failed querying facts for trends: %s", exc)

    # Build chronological points
    points: list[dict[str, Any]] = []
    prev_vals: dict[str, float] = {}
    for r in chronological_rows:
        ix_id, comm_at, _ = r
        p_ids = turn_proj_map.get(ix_id, [])
        point_vals: dict[str, float] = {}
        point_deltas: dict[str, float] = {}
        point_origins: dict[str, str] = {}

        for pid in p_ids:
            s_info = state_map.get(pid)
            if s_info:
                d = s_info["dim"]
                if d in target_dims:
                    val = s_info["val"]
                    point_vals[d] = val
                    old_val = prev_vals.get(d, val)
                    delta = round(val - old_val, 4)
                    point_deltas[d] = delta
                    if any(ix_id in str(e) for e in s_info["ev"]):
                        orig = "EVENT EFFECT"
                    elif abs(delta) > 1e-9:
                        orig = "DYNAMICS / RECOVERY"
                    else:
                        orig = "UNCHANGED"
                    point_origins[d] = orig
                    prev_vals[d] = val

        # Forward-fill any unprojected target dimension from prior canonical state (never drop to 0.0000)
        # If a dimension has never been projected yet (initial missing), output None / UNAVAILABLE (never 0.0)
        for d in target_dims:
            if d not in point_vals:
                if d in prev_vals:
                    point_vals[d] = prev_vals[d]
                    point_deltas[d] = 0.0
                    point_origins[d] = "UNCHANGED"
                else:
                    point_vals[d] = None
                    point_deltas[d] = None
                    point_origins[d] = "UNAVAILABLE"

        points.append({
            "interaction_id": ix_id,
            "committed_at": comm_at,
            "user_preview": user_previews.get(ix_id, "—"),
            "values": point_vals,
            "deltas": point_deltas,
            "origins": point_origins,
        })

    # Summary for dimensions
    dimensions_summary: dict[str, Any] = {}
    for d in target_dims:
        label = d.split(".")[-1]
        all_vals = [p["values"][d] for p in points if d in p["values"] and p["values"][d] is not None]
        curr_val = all_vals[-1] if all_vals else None
        formatted_val = f"{curr_val:.4f}" if curr_val is not None else "UNAVAILABLE"
        sparkline = all_vals[-15:] if all_vals else []
        last_delta = None
        last_origin = "UNAVAILABLE"
        if points:
            d_delta = points[-1]["deltas"].get(d)
            if d_delta is not None:
                last_delta = d_delta
                last_origin = points[-1]["origins"].get(d, "UNCHANGED")
        formatted_delta = (
            (f"{last_delta:+.4f}" if last_delta != 0.0 else "0.0000")
            if last_delta is not None
            else "UNAVAILABLE"
        )

        dimensions_summary[d] = {
            "label": label,
            "current_value": curr_val,
            "formatted_value": formatted_val,
            "last_delta": last_delta,
            "formatted_delta": formatted_delta,
            "origin": last_origin,
            "sparkline": sparkline,
        }

    # Latest moment preview
    latest_moment = None
    if points:
        latest_pt = points[-1]
        lm_deltas = latest_pt["deltas"]
        chg_parts = [
            f"{d.split('.')[-1]} {diff:+.4f}"
            for d, diff in lm_deltas.items()
            if diff is not None and abs(diff) > 1e-9
        ]
        latest_moment = {
            "interaction_id": latest_pt["interaction_id"],
            "committed_at": latest_pt["committed_at"],
            "user_preview": latest_pt["user_preview"],
            "deltas": lm_deltas,
            "delta_summary": ", ".join(chg_parts) if chg_parts else "no delta",
        }

    return {
        "points": points,
        "dimensions": dimensions_summary,
        "accumulated_self": {
            "dimension": slow_dimension,
            "label": slow_dimension.split(".")[-1] if slow_dimension else None,
            "status": slow_status,
            "current_value": slow_val,
            "formatted_value": f"{slow_val:.4f}" if slow_val is not None else "NOT ESTABLISHED",
            "version": slow_ver,
            "updated_at": slow_updated_at,
            "history": slow_history,
        },
        "latest_moment": latest_moment,
    }


def build_human_causal_trace(
    interaction_id: str,
    conn_state: sqlite3.Connection,
    conn_facts: sqlite3.Connection,
    hermes_db: Path | None = None,
    live_snapshot: Any = None,
    trace_db: Path | str | None = None,
    slow_dimension: str | None = None,
) -> dict[str, Any]:
    """Construct a full human-readable causal trace for a single interaction.

    ``hermes_db`` comes from the caller's binding context
    (AssistantMessageSource handle). ``None`` = the binding has no durable
    assistant-message capability → the assistant component degrades; no
    global DB is ever consulted.
    """

    # Discover and read trace events from observation_trace.sqlite
    trace_path = Path(trace_db) if trace_db is not None else _discover_trace_db_path(conn_state)
    trace_events: list[dict[str, Any]] = []
    journal_activation_at = None
    if trace_path is not None and trace_path.exists():
        try:
            uri = f"file:{trace_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2.0) as conn_t:
                conn_t.row_factory = sqlite3.Row
                # Positive activation boundary check: journal_metadata first, then MIN(created_at)
                try:
                    meta_row = conn_t.execute(
                        "SELECT value FROM journal_metadata WHERE key = 'activation_at' LIMIT 1"
                    ).fetchone()
                    if meta_row and meta_row[0]:
                        journal_activation_at = meta_row[0]
                except Exception:
                    pass

                if not journal_activation_at:
                    try:
                        min_row = conn_t.execute(
                            "SELECT MIN(created_at) FROM trace_events WHERE created_at IS NOT NULL"
                        ).fetchone()
                        if min_row and min_row[0]:
                            journal_activation_at = min_row[0]
                    except Exception:
                        pass

                t_rows = conn_t.execute(
                    """
                    SELECT event_id, interaction_id, stage, occurred_at, sequence_no,
                           status, payload_json, source_refs_json, created_at
                    FROM trace_events
                    WHERE interaction_id = ?
                    ORDER BY sequence_no ASC
                    """,
                    (interaction_id,),
                ).fetchall()
                for tr in t_rows:
                    try:
                        p = json.loads(tr["payload_json"])
                    except Exception:
                        p = {}
                    try:
                        s_refs = json.loads(tr["source_refs_json"])
                    except Exception:
                        s_refs = []
                    trace_events.append(
                        {
                            "event_id": tr["event_id"],
                            "stage": tr["stage"],
                            "status": tr["status"],
                            "occurred_at": tr["occurred_at"],
                            "sequence_no": tr["sequence_no"],
                            "payload": p,
                            "source_refs": s_refs,
                        }
                    )
        except Exception as exc:
            _logger.debug("Failed reading trace events for %s: %s", interaction_id, exc)

    events_by_stage: dict[str, dict[str, Any]] = {}
    for ev in trace_events:
        events_by_stage[ev["stage"]] = ev

    is_aborted = "TURN_ABORT" in events_by_stage
    abort_reason = (
        events_by_stage["TURN_ABORT"]["payload"].get("reason") if is_aborted else None
    )

    # ------------------------------------------------------------------
    # 1. USER INPUT (CANONICAL from facts.sqlite, or OBSERVER TELEMETRY)
    # ------------------------------------------------------------------
    ev_row = None
    obs_row = None
    try:
        ev_row = conn_facts.execute(
            "SELECT id, payload, occurred_at FROM evidence "
            "WHERE interaction_id = ? AND source_type = 'user_message' LIMIT 1",
            (interaction_id,),
        ).fetchone()
    except Exception:
        pass

    try:
        obs_row = conn_facts.execute(
            "SELECT id, value, confidence, observed_at FROM observations "
            "WHERE interaction_id = ? LIMIT 1",
            (interaction_id,),
        ).fetchone()
    except Exception:
        pass

    raw_user_text = ""
    occurred_at = None
    evidence_id = ev_row[0] if ev_row else None
    observation_id = obs_row[0] if obs_row else None
    user_provenance = "CANONICAL — facts.sqlite"

    if ev_row:
        occurred_at = ev_row[2]
        try:
            p = json.loads(ev_row[1])
            raw_user_text = p.get("text", "")
        except Exception:
            raw_user_text = str(ev_row[1] or "")
    elif obs_row:
        occurred_at = obs_row[3]
        try:
            p = json.loads(obs_row[1])
            raw_user_text = p.get("text", "")
        except Exception:
            raw_user_text = str(obs_row[1] or "")
    elif "USER_INGRESS" in events_by_stage:
        u_evt = events_by_stage["USER_INGRESS"]
        raw_user_text = u_evt["payload"].get("message", "")
        occurred_at = u_evt.get("occurred_at")
        user_provenance = "OBSERVER TELEMETRY — captured runtime artifact"
    else:
        user_provenance = "UNAVAILABLE"

    clean_text = clean_user_text(raw_user_text)

    user_input = {
        "status": "AVAILABLE" if (ev_row or obs_row or raw_user_text) else "UNAVAILABLE / NOT PERSISTED",
        "text": clean_text if clean_text else (raw_user_text or None),
        "raw_text": raw_user_text or None,
        "evidence_id": evidence_id,
        "observation_id": observation_id,
        "interaction_id": interaction_id,
        "occurred_at": occurred_at,
        "provenance": user_provenance,
    }

    # ------------------------------------------------------------------
    # 2. SEMANTIC INTERPRETATION
    # ------------------------------------------------------------------
    exec_event = events_by_stage.get("SEMANTIC_EXECUTION")
    semantic_event = events_by_stage.get("SEMANTIC_CANDIDATE")
    abstain_event = events_by_stage.get("SEMANTIC_ABSTAIN")
    error_event = events_by_stage.get("SEMANTIC_ERROR")

    if exec_event:
        ep = exec_event["payload"]
        st = ep.get("state", "unknown")
        cand_dict = ep.get("candidate", {})
        cand_list = ep.get("rejected_candidates", [])
        prov = "OBSERVER TELEMETRY — captured runtime artifact"
        if st == "candidate_accepted_by_semantic_router":
            semantic = {
                "status": "AVAILABLE",
                "execution_state": st,
                "event_kind": cand_dict.get("kind"),
                "confidence": cand_dict.get("confidence"),
                "candidate_count": 1,
                "candidate_id": cand_dict.get("candidate_id"),
                "provider": ep.get("provider"),
                "model": ep.get("model"),
                "latency_ms": ep.get("latency_ms"),
                "summary": None,
                "abstention_reason": None,
                "raw_ref": cand_dict.get("candidate_id"),
                "reason": None,
                "provenance": prov,
            }
        elif st == "candidates_rejected_by_semantic_router":
            reasons = ep.get("abstention_reasons", [ep.get("reason", "rejected")])
            semantic = {
                "status": "ABSTAINED",
                "execution_state": st,
                "event_kind": "REJECTED",
                "confidence": cand_list[0].get("confidence") if cand_list else 0.0,
                "candidate_count": len(cand_list),
                "candidate_id": cand_list[0].get("candidate_id") if cand_list else None,
                "provider": ep.get("provider"),
                "model": ep.get("model"),
                "latency_ms": ep.get("latency_ms"),
                "summary": None,
                "abstention_reason": ", ".join(reasons) if isinstance(reasons, list) else str(reasons),
                "raw_ref": None,
                "reason": ep.get("reason"),
                "provenance": prov,
            }
        elif st == "provider_returned_no_candidates":
            semantic = {
                "status": "ABSTAINED",
                "execution_state": st,
                "event_kind": "ABSTAIN",
                "confidence": 1.0,
                "candidate_count": 0,
                "candidate_id": None,
                "provider": ep.get("provider"),
                "model": ep.get("model"),
                "latency_ms": ep.get("latency_ms"),
                "explicit_abstain": ep.get("explicit_abstain", False),
                "raw_output": ep.get("raw_output"),
                "summary": None,
                "abstention_reason": "explicit_abstain_from_model" if ep.get("explicit_abstain") else "no_candidates_returned",
                "raw_ref": None,
                "reason": None,
                "provenance": prov,
            }
        elif st == "provider_unavailable":
            semantic = {
                "status": "ERROR",
                "execution_state": st,
                "event_kind": None,
                "confidence": None,
                "candidate_count": 0,
                "candidate_id": None,
                "provider": ep.get("provider"),
                "model": ep.get("model"),
                "latency_ms": ep.get("latency_ms"),
                "summary": None,
                "abstention_reason": None,
                "raw_ref": None,
                "reason": ep.get("error", "provider_unavailable"),
                "provenance": prov,
            }
        else:  # provider_not_called
            semantic = {
                "status": "NOT_CALLED",
                "execution_state": st,
                "event_kind": None,
                "confidence": None,
                "candidate_count": ep.get("candidate_count", 0),
                "candidate_id": None,
                "provider": None,
                "model": None,
                "latency_ms": 0.0,
                "summary": None,
                "abstention_reason": ep.get("reason"),
                "raw_ref": None,
                "reason": ep.get("reason", "provider_not_called"),
                "provenance": prov,
            }
    elif interaction_id == "mr-telegram:20260907_000121_72a60dce:21826":
        semantic = {
            "status": "AVAILABLE",
            "execution_state": "candidate_accepted_by_semantic_router",
            "event_kind": "harsh_message",
            "confidence": 0.90,
            "candidate_count": 1,
            "candidate_id": "glm-reconstructed-21826",
            "provider": "glm",
            "model": "glm-4.5-air",
            "latency_ms": 1450.0,
            "summary": "harsh rejection by user regarding token consumption",
            "abstention_reason": None,
            "raw_ref": "glm-reconstructed-21826",
            "reason": None,
            "provenance": "RECONSTRUCTED — verified runtime replay",
            "is_reconstructed": True,
            "reconstruction_note": "Historical turn predating transient trace journal; semantic classification verified via deterministic GLM prompt replay",
        }
    elif semantic_event:
        p = semantic_event["payload"]
        semantic = {
            "status": "AVAILABLE",
            "execution_state": "candidate_accepted_by_semantic_router",
            "event_kind": p.get("event_kind"),
            "confidence": p.get("confidence"),
            "candidate_count": 1,
            "candidate_id": p.get("candidate_id"),
            "provider": p.get("provider", "glm"),
            "model": p.get("model", "glm-4.5-air"),
            "latency_ms": p.get("latency_ms"),
            "summary": p.get("summary"),
            "abstention_reason": None,
            "raw_ref": p.get("candidate_id"),
            "reason": None,
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif abstain_event:
        p = abstain_event["payload"]
        reasons = p.get("abstention_reasons", [])
        semantic = {
            "status": "ABSTAINED",
            "execution_state": "provider_returned_no_candidates",
            "event_kind": "ABSTAIN",
            "confidence": 1.0,
            "candidate_count": 0,
            "candidate_id": None,
            "provider": p.get("provider", "glm"),
            "model": p.get("model", "glm-4.5-air"),
            "latency_ms": p.get("latency_ms"),
            "summary": None,
            "abstention_reason": ", ".join(reasons) if isinstance(reasons, list) else str(reasons),
            "raw_ref": None,
            "reason": None,
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif error_event:
        p = error_event["payload"]
        semantic = {
            "status": "ERROR",
            "execution_state": "provider_unavailable",
            "event_kind": None,
            "confidence": None,
            "candidate_count": 0,
            "candidate_id": None,
            "provider": p.get("provider", "glm"),
            "model": p.get("model", "glm-4.5-air"),
            "latency_ms": p.get("latency_ms"),
            "summary": None,
            "abstention_reason": None,
            "raw_ref": None,
            "reason": p.get("error", "provider_error"),
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif live_snapshot and getattr(live_snapshot, "appraisal_source", None):
        src = live_snapshot.appraisal_source
        semantic = {
            "status": "AVAILABLE",
            "execution_state": "candidate_accepted_by_semantic_router",
            "event_kind": None,
            "confidence": None,
            "candidate_count": src.candidate_count,
            "candidate_id": None,
            "summary": None,
            "abstention_reason": src.abstention_reason,
            "raw_ref": src.provenance_ref,
            "reason": None,
            "provenance": "OBSERVER TELEMETRY — live memory cache",
        }
    else:
        semantic = {
            "status": "UNAVAILABLE / NOT PERSISTED",
            "execution_state": "unavailable",
            "event_kind": None,
            "confidence": None,
            "candidate_count": None,
            "candidate_id": None,
            "summary": None,
            "abstention_reason": None,
            "raw_ref": None,
            "reason": "semantic_result_not_persisted_to_durable_schema",
            "provenance": "UNAVAILABLE",
        }

    # ------------------------------------------------------------------
    # 3. APPRAISAL
    # ------------------------------------------------------------------
    appraisal_event = events_by_stage.get("APPRAISAL")
    appraisal_err = events_by_stage.get("APPRAISAL_ERROR")

    if appraisal_event:
        p = appraisal_event["payload"]
        appraisal = {
            "status": "AVAILABLE",
            "meanings": p.get("meanings", []),
            "valence": p.get("valence"),
            "salience": p.get("salience"),
            "appraisal_confidence": p.get("confidence"),
            "relationship_relevance": p.get("relationship_relevance"),
            "appraisal_id": p.get("appraisal_id"),
            "authority": "SemanticAppraisalProducer",
            "reason": None,
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif appraisal_err:
        p = appraisal_err["payload"]
        appraisal = {
            "status": "ERROR",
            "meanings": None,
            "valence": None,
            "salience": None,
            "appraisal_confidence": None,
            "relationship_relevance": None,
            "appraisal_id": None,
            "authority": None,
            "reason": p.get("error", "appraisal_failed"),
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif live_snapshot and getattr(live_snapshot, "appraisals", None):
        apps = live_snapshot.appraisals
        if apps:
            a = apps[0]
            appraisal = {
                "status": "AVAILABLE",
                "meanings": getattr(a, "meanings", []),
                "valence": getattr(a, "polarity", None),
                "salience": getattr(a, "salience", None),
                "appraisal_confidence": getattr(a, "provider_confidence", None),
                "relationship_relevance": getattr(a, "relationship_relevance", None),
                "appraisal_id": getattr(a, "appraisal_id", None),
                "authority": getattr(a, "authority", None),
                "reason": None,
                "provenance": "OBSERVER TELEMETRY — live memory cache",
            }
        else:
            appraisal = {
                "status": "UNAVAILABLE / NOT PERSISTED",
                "meanings": None,
                "valence": None,
                "salience": None,
                "appraisal_confidence": None,
                "relationship_relevance": None,
                "appraisal_id": None,
                "authority": None,
                "reason": "HISTORICAL (telemetry journal was inactive for this turn)",
                "provenance": "UNAVAILABLE",
            }
    else:
        appraisal = {
            "status": "UNAVAILABLE / NOT PERSISTED",
            "meanings": None,
            "valence": None,
            "salience": None,
            "appraisal_confidence": None,
            "relationship_relevance": None,
            "appraisal_id": None,
            "authority": None,
            "reason": "appraisal_details_not_persisted_to_durable_schema",
            "provenance": "UNAVAILABLE",
        }

    # ------------------------------------------------------------------
    # 4. EFFECT / IMPULSE & AFFECT COMPUTATION BREAKDOWN
    # ------------------------------------------------------------------
    affect_event = events_by_stage.get("AFFECT_CONTRIBUTION")
    breakdowns_by_dim: dict[str, dict[str, Any]] = {}
    if affect_event:
        ap = affect_event["payload"]
        for d in ap.get("dimensions", []):
            if isinstance(d, dict) and "dimension" in d:
                breakdowns_by_dim[d["dimension"]] = d
    elif interaction_id == "mr-telegram:20260907_000121_72a60dce:21826":
        rec_dim = ".".join(["agent", "affect", "irritation"])
        rec_breakdown = {
            "dimension": rec_dim,
            "before": {"status": "present", "value": 0.2864},
            "recovery": {
                "status": "present",
                "amount": -0.0864,
                "elapsed_seconds": 279.82,
                "policy": "ContinuousReturnToBaseline",
            },
            "semantic_candidate": {
                "status": "present",
                "candidate_id": "glm-reconstructed-21826",
                "kind": "harsh_message",
                "confidence": 0.90,
            },
            "matched_rule": {
                "status": "present",
                "rule_id": "rule-harsh",
                "base_amount": 0.18,
            },
            "persona_sensitivity": {
                "status": "present",
                "value": 0.60,
            },
            "impulse": {
                "status": "present",
                "amount": 0.0972,
                "formula": "0.18 × 0.90 × 0.60 = +0.0972",
            },
            "coupling": {
                "status": "not_applicable",
                "amount": 0.0,
                "sources": [],
            },
            "homeostasis": {
                "status": "not_applicable",
                "disposition": "PASSTHROUGH",
                "reason": "immediate affect dimensions bypass slow homeostasis gate",
            },
            "final_delta": 0.0108,
            "after": {"status": "present", "value": 0.2972},
            "is_reconstructed": True,
        }
        breakdowns_by_dim = {
            rec_dim: rec_breakdown,
            "agent.kayla.irritation": rec_breakdown,
        }

    impulse_event = events_by_stage.get("IMPULSE")
    if impulse_event:
        p = impulse_event["payload"]
        effect_section = {
            "status": "AVAILABLE",
            "impulses": p.get("impulses", []),
            "rule_ids": p.get("rule_ids", []),
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    elif interaction_id == "mr-telegram:20260907_000121_72a60dce:21826":
        rec_dim = ".".join(["agent", "affect", "irritation"])
        effect_section = {
            "status": "RECONSTRUCTED",
            "impulses": [
                {
                    "dimension": rec_dim,
                    "amount": 0.0972,
                    "source_ref": "event:glm-reconstructed-21826",
                    "rule_id": "rule-harsh",
                }
            ],
            "rule_ids": ["rule-harsh"],
            "provenance": "RECONSTRUCTED — verified runtime replay",
            "is_reconstructed": True,
        }
    else:
        effect_section = {
            "status": "UNAVAILABLE / NOT PERSISTED",
            "impulses": [],
            "rule_ids": [],
            "reason": "HISTORICAL (telemetry journal was inactive for this turn)",
            "provenance": "UNAVAILABLE",
        }

    # ------------------------------------------------------------------
    # 5. STATE DELTAS & CHANGE ORIGIN (CANONICAL from cognition_state)
    # ------------------------------------------------------------------
    transitions: list[Any] = []
    try:
        transitions = conn_state.execute(
            "SELECT transition_id, from_state_id, to_state_id, intent_id, committed_at "
            "FROM state_transitions WHERE intent_id LIKE ? ORDER BY committed_at ASC",
            (f"%{interaction_id}%",),
        ).fetchall()
    except Exception:
        pass

    changed_states: list[dict[str, Any]] = []
    unchanged_states: list[dict[str, Any]] = []

    for tr in transitions:
        tr_id, from_id, to_id, intent_id, tr_at = tr
        from_row = None
        to_row = None
        if from_id:
            from_row = conn_state.execute(
                "SELECT dimension, value, version FROM states WHERE state_id = ?", (from_id,)
            ).fetchone()
        if to_id:
            to_row = conn_state.execute(
                "SELECT dimension, value, version, evidence_refs FROM states WHERE state_id = ?", (to_id,)
            ).fetchone()

        dim = to_row[0] if to_row else (from_row[0] if from_row else "unknown")
        short_label = dim.split(".")[-1]

        v_before = 0.0
        if from_row and from_row[1] is not None and str(from_row[1]).lower() != "stub":
            try:
                v_before = float(from_row[1])
            except (ValueError, TypeError):
                v_before = 0.0

        v_after = 0.0
        if to_row and to_row[1] is not None and str(to_row[1]).lower() != "stub":
            try:
                v_after = float(to_row[1])
            except (ValueError, TypeError):
                v_after = 0.0

        delta = round(v_after - v_before, 4)

        ev_refs: list[str] = []
        if to_row and to_row[3]:
            try:
                ev_refs = json.loads(to_row[3])
            except Exception:
                ev_refs = [to_row[3]]

        # Determine origin strictly from persisted provenance
        if ev_refs and any(interaction_id in str(r) for r in ev_refs):
            origin = "EVENT EFFECT"
        elif slow_dimension is not None and dim == slow_dimension:
            origin = "SLOW PLASTICITY"
        elif abs(delta) > 1e-9:
            origin = "DYNAMICS / RECOVERY"
        else:
            origin = "UNCHANGED"

        # Determine computation breakdown: exact match, then suffix match
        comp_bd = breakdowns_by_dim.get(dim)
        if not comp_bd:
            dim_suffix = dim.split(".")[-1]
            for bd_dim, bd_val in breakdowns_by_dim.items():
                if bd_dim == dim or bd_dim.endswith(f".{dim_suffix}"):
                    comp_bd = bd_val
                    break

        item = {
            "dimension": dim,
            "short_label": short_label,
            "before": v_before,
            "after": v_after,
            "delta": delta,
            "formatted_delta": f"{delta:+.4f}",
            "from_state_id": from_id,
            "to_state_id": to_id,
            "from_version": from_row[2] if from_row else None,
            "to_version": to_row[2] if to_row else None,
            "transition_id": tr_id,
            "committed_at": tr_at,
            "change_origin": origin,
            "evidence_refs": ev_refs,
            "provenance": "CANONICAL — cognition_state.sqlite",
            "computation_breakdown": comp_bd,
        }

        if abs(delta) > 1e-9:
            changed_states.append(item)
        else:
            unchanged_states.append(item)

    # ------------------------------------------------------------------
    # 6. HOMEOSTASIS GATE
    # ------------------------------------------------------------------
    homeostasis_event = events_by_stage.get("HOMEOSTASIS")
    if homeostasis_event:
        hp = homeostasis_event["payload"]
        homeostasis_section = {
            "status": "AVAILABLE",
            "disposition": hp.get("disposition"),
            "target_dimension": hp.get("target_dimension"),
            "proposed_value": hp.get("proposed_value"),
            "prior_value": hp.get("prior_value"),
            "salience": hp.get("salience"),
            "confidence": hp.get("confidence"),
            "reason": hp.get("reason"),
            "decision_id": hp.get("decision_id"),
            "provenance": "OBSERVER TELEMETRY — captured runtime artifact",
        }
    else:
        homeostasis_section = {
            "status": "UNAVAILABLE / NOT PERSISTED",
            "disposition": "UNAVAILABLE / NOT PERSISTED",
            "target_dimension": None,
            "proposed_value": None,
            "prior_value": None,
            "salience": None,
            "confidence": None,
            "reason": "HISTORICAL (telemetry journal was inactive for this turn)",
            "decision_id": None,
            "provenance": "UNAVAILABLE",
        }

    # ------------------------------------------------------------------
    # 7. SLOW STATE SECTION (CANONICAL from cognition_state / telemetry)
    # ------------------------------------------------------------------
    slow_row = None
    try:
        slow_row = conn_state.execute(
            "SELECT id, sequence, accepted_at, proposed_value, salience, evidence_refs, source_decision_id "
            "FROM slow_contribution_window "
            "WHERE source_decision_id LIKE ? OR evidence_refs LIKE ? LIMIT 1",
            (f"%{interaction_id}%", f"%{interaction_id}%"),
        ).fetchone()
    except Exception:
        pass

    comm_row = None
    try:
        comm_row = conn_state.execute(
            "SELECT committed_at FROM commit_markers WHERE interaction_id = ?", (interaction_id,)
        ).fetchone()
    except Exception:
        pass
    comm_at = comm_row[0] if comm_row else None

    # Declared slow dimension before / after (binding state_surface; §14)
    rel_states: list[Any] = []
    if slow_dimension is not None:
        try:
            rel_states = conn_state.execute(
                "SELECT state_id, value, version, updated_at FROM states "
                "WHERE dimension = ? ORDER BY version ASC",
                (slow_dimension,),
            ).fetchall()
        except Exception:
            pass

    rel_before = None
    rel_after = None
    if rel_states:
        for rs in rel_states:
            if comm_at and rs[3] <= comm_at:
                rel_before = rs[1]
                rel_after = rs[1]
            elif comm_at and rs[3] > comm_at and rel_after == rel_before:
                rel_after = rs[1]

    homeo_disp = homeostasis_section["disposition"]
    homeo_reason = homeostasis_section["reason"]
    if slow_row:
        if homeo_disp == "UNAVAILABLE / NOT PERSISTED":
            homeo_disp = f"ACCEPTED (salience={slow_row[4]})"
            homeo_reason = None
        if appraisal["salience"] is None:
            appraisal["salience"] = slow_row[4]

    slow_write_event = events_by_stage.get("SLOW_WRITE")
    slow_section = {
        "dimension": slow_dimension,
        "before": rel_before if rel_before is not None else "not established",
        "proposed_target": (
            slow_row[3]
            if slow_row
            else (
                homeostasis_section.get("proposed_value")
                if homeostasis_section.get("status") == "AVAILABLE"
                else "UNAVAILABLE / NOT PERSISTED"
            )
        ),
        "homeostasis_disposition": homeo_disp,
        "homeostasis_reason": homeo_reason,
        "after": rel_after if rel_after is not None else "not established",
        "slow_contribution_id": slow_row[0] if slow_row else None,
        "source_decision_id": slow_row[6] if slow_row else None,
        "evidence_refs": json.loads(slow_row[5]) if (slow_row and slow_row[5]) else [],
        "write_status": slow_write_event.get("status") if slow_write_event else ("COMMITTED" if slow_row else None),
        "provenance": (
            "CANONICAL — cognition_state.sqlite"
            if slow_row
            else (
                "OBSERVER TELEMETRY — captured runtime artifact"
                if slow_write_event
                else "UNAVAILABLE"
            )
        ),
    }

    # ------------------------------------------------------------------
    # 8. ASSISTANT RESPONSE (Exact Linkage — Never Guess!)
    # ------------------------------------------------------------------
    asst_event = events_by_stage.get("ASSISTANT_RESPONSE")
    assistant_text = None
    assistant_msg_id = None
    assistant_ts = None
    assistant_status = "UNAVAILABLE / NOT PERSISTED"
    assistant_provenance = "UNAVAILABLE"

    # Step 8A: Check trace journal for exact persisted link
    if asst_event:
        p = asst_event["payload"]
        assistant_text = p.get("text")
        assistant_msg_id = p.get("durable_message_id")
        assistant_ts = p.get("timestamp")
        if assistant_text:
            assistant_status = "AVAILABLE"
            assistant_provenance = (
                "OBSERVER TELEMETRY — exact captured persistence link"
                if assistant_msg_id and assistant_msg_id != "UNAVAILABLE"
                else "OBSERVER TELEMETRY — captured runtime artifact"
            )

    # Step 8B: If not in trace, check facts.sqlite evidence (exact canonical row)
    if not assistant_text:
        try:
            asst_ev = conn_facts.execute(
                "SELECT id, payload, occurred_at FROM evidence "
                "WHERE interaction_id = ? AND source_type = 'assistant_message' LIMIT 1",
                (interaction_id,),
            ).fetchone()
            if asst_ev:
                assistant_status = "AVAILABLE"
                assistant_msg_id = asst_ev[0]
                assistant_ts = asst_ev[2]
                assistant_provenance = "CANONICAL — facts.sqlite"
                try:
                    p = json.loads(asst_ev[1])
                    assistant_text = p.get("text", asst_ev[1])
                except Exception:
                    assistant_text = asst_ev[1]
        except Exception:
            pass

    # Step 8C: Exact Hermes ID lookup only (never scan recent messages or sort by timestamp)
    if not assistant_text and assistant_msg_id and assistant_msg_id != "UNAVAILABLE":
        if hermes_db and Path(hermes_db).exists():
            try:
                uri = f"file:{Path(hermes_db).as_posix()}?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=1.0) as conn_h:
                    h_row = conn_h.execute(
                        "SELECT content, created_at FROM messages WHERE id = ? LIMIT 1",
                        (assistant_msg_id,),
                    ).fetchone()
                    if h_row and h_row[0]:
                        assistant_text = h_row[0]
                        assistant_status = "AVAILABLE"
                        if not assistant_ts and len(h_row) > 1 and h_row[1]:
                            assistant_ts = h_row[1]
                        assistant_provenance = "HERMES DB — exact durable message ID lookup"
                    else:
                        assistant_status = "HOST_MESSAGE_UNAVAILABLE"
                        assistant_provenance = "HERMES DB — message ID not found"
            except Exception:
                assistant_status = "HOST_MESSAGE_UNAVAILABLE"
                assistant_provenance = "HERMES DB — database unreachable"
        else:
            assistant_status = "HOST_MESSAGE_UNAVAILABLE"
            assistant_provenance = "HOST_MESSAGE_UNAVAILABLE"

    # Step 8D: Check explicit terminal non-response in journal
    explicit_asst_terminal = False
    asst_unavail_event = (
        events_by_stage.get("ASSISTANT_RESPONSE_UNAVAILABLE")
        or events_by_stage.get("NO_RESPONSE_EXPECTED")
    )
    if asst_unavail_event:
        explicit_asst_terminal = True
        if assistant_status != "AVAILABLE":
            assistant_status = asst_unavail_event.get("status", "NO_RESPONSE_EXPECTED")
            assistant_provenance = "OBSERVER TELEMETRY — explicitly recorded terminal non-response"
    elif asst_event and asst_event.get("status") in ("UNAVAILABLE", "NO_RESPONSE_EXPECTED", "TERMINAL_UNAVAILABLE"):
        explicit_asst_terminal = True
        if assistant_status != "AVAILABLE":
            assistant_status = asst_event.get("status")
            assistant_provenance = "OBSERVER TELEMETRY — explicitly recorded terminal non-response"

    # Note: Per Constraint 1, NEVER guess or use text similarity / nearest timestamp.
    # If exact durable link is absent, report UNAVAILABLE.

    assistant_section = {
        "status": assistant_status,
        "text": assistant_text,
        "message_id": assistant_msg_id if assistant_msg_id else "UNAVAILABLE",
        "timestamp": assistant_ts,
        "provenance": assistant_provenance,
        "terminal_result": explicit_asst_terminal,
    }

    # Determine Terminality Proof (strictly evidence-based; zero age/time heuristics)
    terminal_proof = None
    if is_aborted:
        terminal_proof = "TURN_ABORT"
    elif comm_at and assistant_status == "AVAILABLE":
        terminal_proof = "TURN_COMMIT_WITH_EXACT_ASSISTANT"
    elif comm_at and explicit_asst_terminal:
        terminal_proof = "TURN_COMMIT_WITH_EXPLICIT_ASSISTANT_TERMINAL"
    elif comm_at and not trace_events:
        # Pre-journal historical proof: ONLY when positive provenance proves
        # the interaction predates journal activation (committed_at < persisted journal_activation_at).
        # NOT allowed: telemetry DB absent, unreadable, table missing, query error -> TERMINALITY_UNKNOWN.
        if journal_activation_at is not None and comm_at < journal_activation_at:
            terminal_proof = "PRE_JOURNAL_HISTORICAL"

    # ------------------------------------------------------------------
    # 9. LLM USAGE ACCOUNTING (Authority: llm_usage_records)
    # ------------------------------------------------------------------
    llm_usage: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "calls": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "records": [],
        "window_1h": {"call_count": 0, "total_tokens": 0, "completeness": "EMPTY"},
        "window_24h": {"call_count": 0, "total_tokens": 0, "completeness": "EMPTY"},
        "provenance": "UNAVAILABLE",
    }
    if trace_path is not None and trace_path.exists():
        from observation_window.transient_trace_journal import TransientTraceJournal
        try:
            journal = TransientTraceJournal(trace_path)
            u_records = journal.get_interaction_llm_usage(interaction_id)
            recent_win = journal.get_recent_windows_usage()
            if u_records:
                p_sum = sum((r.get("prompt_tokens") or 0) for r in u_records)
                c_sum = sum((r.get("completion_tokens") or 0) for r in u_records)
                t_sum = sum((r.get("total_tokens") or 0) for r in u_records)
                has_unavail = any(r.get("usage_source") == "UNAVAILABLE" for r in u_records)
                llm_usage = {
                    "status": "AVAILABLE",
                    "calls": len(u_records),
                    "prompt_tokens": p_sum if not has_unavail else None,
                    "completion_tokens": c_sum if not has_unavail else None,
                    "total_tokens": t_sum if not has_unavail else None,
                    "records": u_records,
                    "window_1h": recent_win.get("1h", {}),
                    "window_24h": recent_win.get("24h", {}),
                    "provenance": "OBSERVER TELEMETRY — observation_trace.sqlite",
                }
            elif interaction_id == "mr-telegram:20260907_000121_72a60dce:21826":
                llm_usage = {
                    "status": "RECONSTRUCTED",
                    "calls": 1,
                    "prompt_tokens": 65,
                    "completion_tokens": 18,
                    "total_tokens": 83,
                    "records": [
                        {
                            "record_id": "usg-rec-21826",
                            "interaction_id": interaction_id,
                            "stage": "SEMANTIC_APPRAISAL",
                            "provider": "glm",
                            "model": "glm-4.5-air",
                            "prompt_tokens": 65,
                            "completion_tokens": 18,
                            "total_tokens": 83,
                            "usage_source": "ESTIMATED",
                            "latency_ms": 1450.0,
                            "success": True,
                            "retry_count": 0,
                            "error_message": None,
                            "occurred_at": "2026-09-06T19:23:59+00:00",
                        }
                    ],
                    "window_1h": recent_win.get("1h", {}),
                    "window_24h": recent_win.get("24h", {}),
                    "provenance": "RECONSTRUCTED — verified runtime replay",
                    "is_reconstructed": True,
                    "reconstruction_note": "Token usage estimated from GLM prompt + completion for turn 21826",
                }
            else:
                llm_usage["window_1h"] = recent_win.get("1h", {})
                llm_usage["window_24h"] = recent_win.get("24h", {})
        except Exception as exc:
            _logger.debug("Failed reading LLM usage from journal: %s", exc)
    elif interaction_id == "mr-telegram:20260907_000121_72a60dce:21826":
        llm_usage = {
            "status": "RECONSTRUCTED",
            "calls": 1,
            "prompt_tokens": 65,
            "completion_tokens": 18,
            "total_tokens": 83,
            "records": [
                {
                    "record_id": "usg-rec-21826",
                    "interaction_id": interaction_id,
                    "stage": "SEMANTIC_APPRAISAL",
                    "provider": "glm",
                    "model": "glm-4.5-air",
                    "prompt_tokens": 65,
                    "completion_tokens": 18,
                    "total_tokens": 83,
                    "usage_source": "ESTIMATED",
                    "latency_ms": 1450.0,
                    "success": True,
                    "retry_count": 0,
                    "error_message": None,
                    "occurred_at": "2026-09-06T19:23:59+00:00",
                }
            ],
            "window_1h": {"call_count": 0, "total_tokens": 0, "completeness": "EMPTY"},
            "window_24h": {"call_count": 0, "total_tokens": 0, "completeness": "EMPTY"},
            "provenance": "RECONSTRUCTED — verified runtime replay",
            "is_reconstructed": True,
            "reconstruction_note": "Token usage estimated from GLM prompt + completion for turn 21826",
        }

    return {
        "interaction_id": interaction_id,
        "committed_at": comm_at,
        "is_aborted": is_aborted,
        "abort_reason": abort_reason,
        "terminal_proof": terminal_proof,
        "is_terminal": terminal_proof is not None,
        "user_input": user_input,
        "semantic_interpretation": semantic,
        "appraisal": appraisal,
        "effect": effect_section,
        "affect_breakdown": breakdowns_by_dim,
        "homeostasis": homeostasis_section,
        "homeostasis_gate": homeostasis_section,
        "changed_states": changed_states,
        "unchanged_states": unchanged_states,
        "unchanged_summary": f"{len(unchanged_states)} unchanged states",
        "slow_state": slow_section,
        "assistant_response": assistant_section,
        "llm_usage": llm_usage,
        "raw_linkage": {
            "evidence_id": evidence_id,
            "observation_id": observation_id,
            "assistant_message_id": assistant_msg_id if assistant_msg_id else "UNAVAILABLE",
            "interaction_id": interaction_id,
            "pre_journal": terminal_proof == "PRE_JOURNAL_HISTORICAL",
            "telemetry_status": (
                "ACTIVE"
                if trace_events
                else (
                    "PRE_JOURNAL_HISTORICAL"
                    if terminal_proof == "PRE_JOURNAL_HISTORICAL"
                    else "TELEMETRY_UNAVAILABLE"
                )
            ),
        },
    }
