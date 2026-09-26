#!/usr/bin/env python3
"""HI-2 runtime seam support — loaded by the gateway patch.

This module is imported by gateway/run.py AFTER the MR sys.path is
injected (see apply_mr_patch.py / hermes-0.19.0-mr.patch). It provides
the adapter singleton and the bounded-context renderer the seam calls.

Placed OUTSIDE site-packages so it survives Hermes upgrades; the patch
only references it via an absolute path.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger("xiyue.mr.seam")

_MR_SRC = os.environ.get(
    "MR_SOURCE_ROOT",
    str(Path(__file__).resolve().parents[1] / "src"),
)
_ADAPTER_PATH = None

_RUNTIME_DIR = Path.home() / ".hermes" / "profiles" / "xiyue" / "runtime"
_DEFAULT_READINESS_FILE = _RUNTIME_DIR / "readiness.json"


def get_readiness_file_path() -> Path:
    override = os.environ.get("MR_READINESS_PATH")
    if override:
        return Path(override)
    return _DEFAULT_READINESS_FILE


_TRACE_JOURNAL = None


def get_trace_journal_path() -> Path:
    override = os.environ.get("MR_TRACE_DB_PATH")
    if override:
        return Path(override)
    return _RUNTIME_DIR / "observation_trace.sqlite"


def get_trace_journal(db_path: Path | str | None = None) -> Any | None:
    global _TRACE_JOURNAL
    if db_path is None and _TRACE_JOURNAL is not None:
        return _TRACE_JOURNAL
    try:
        from observation_window.transient_trace_journal import TransientTraceJournal

        target = Path(db_path) if db_path is not None else get_trace_journal_path()
        journal = TransientTraceJournal(target)
        if db_path is None:
            _TRACE_JOURNAL = journal
        return journal
    except Exception as exc:  # noqa: BLE001
        _logger.warning("get_trace_journal failed: %s", exc)
        return None


# INGRESS-DECONTAMINATION (P1, 2026-09-05): the Hermes gateway wraps the
# user message in a "[System note: ...]" recovery note when the previous
# turn was interrupted mid-tool-tail (gateway/run.py around line 20878).
# That wrapper is HOST-DIALOGUE metadata for the LLM — it must never enter
# the MR fact plane as if the user had typed it (it previously leaked into
# Observation.text -> semantic classifier -> appraisal -> evidence rows).
# Strip ONLY the exact known prefix; never touch any other text.
_SYSTEM_NOTE_PREFIX = (
    "[System note: A new message has arrived. The conversation "
    "history contains pending tool outputs from an interrupted turn. "
    "IGNORE those pending results. Address the user's NEW message "
    "below FIRST. Do NOT re-execute old tool calls from the history.]\n\n"
)


def _strip_host_system_note(message: str) -> str:
    """Remove the gateway's host-dialogue system-note wrapper, if present."""
    if isinstance(message, str) and message.startswith(_SYSTEM_NOTE_PREFIX):
        stripped = message[len(_SYSTEM_NOTE_PREFIX) :]
        return stripped if stripped.strip() else message
    return message


def _thread_trace(phase: str, adapter=None, interaction_id: str = "") -> None:
    """MR THREAD TRACE — temporary diagnostic, IDs only, no behavior change."""
    _logger.warning(
        "MR THREAD TRACE pid=%s tid=%s adapter=%s phase=%s interaction=%s",
        os.getpid(),
        threading.get_ident(),
        hex(id(adapter)) if adapter is not None else "None",
        phase,
        interaction_id,
    )


def _ensure_mr_importable() -> bool:
    """Make mind_runtime importable from the gateway process (3.13)."""
    if _MR_SRC not in sys.path:
        sys.path.insert(0, _MR_SRC)
    try:
        import mind_runtime  # noqa: F401

        return True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("mind_runtime not importable: %s", exc)
        return False


_local = threading.local()

# The Gateway process is the sole operational readiness writer. This
# process-local guard prevents one adapter per worker thread from starting
# competing reconciliation loops for the same epoch/readiness artifact.
_bundle_reconciler_lock = threading.Lock()
_bundle_reconciler_thread: threading.Thread | None = None
_bundle_reconciler_stop: threading.Event | None = None


def _load_production_composition() -> dict[str, object]:
    """Decode the certified runtime-config manifest and assemble the
    emotional-composition pieces for the host adapter.

    This lives OUTSIDE the ``mind_runtime`` package so it may import
    ``validation`` (the certified manifest decoder is the final import layer
    and no production domain module may depend on it). Fail-closed: any
    decode / strategy error raises, and the caller (``get_mr_adapter``) fails
    soft and logs it rather than silently building a stub emotional path.
    """
    from pathlib import Path

    from mind_runtime.homeostasis.policy import (
        FixedSalienceThresholdConfig,
        SalienceThresholdPolicy,
    )
    from mind_runtime.validation.contracts import (
        decode_runtime_manifest,
        load_runtime_config_manifest,
    )

    config_path = os.environ.get("MR_RUNTIME_CONFIG")
    if not config_path:
        # Repo-located certified manifest (the closed production runtime config).
        config_path = str(
            Path(_MR_SRC).parent / "certification" / "d11s" / "inputs" / "runtime-config.json"
        )
    decoded = decode_runtime_manifest(load_runtime_config_manifest(Path(config_path)))

    # Online semantic interpretation belongs to the Body/Host LLM. The
    # certified manifest still decodes the legacy provider fields for
    # compatibility, but production composition no longer constructs or
    # requires an MR-local semantic/appraisal model.
    semantic_provider = None
    appraisal_producer = None

    # Homeostasis gate with config-owned thresholds (NOT the default 0.85).
    homeostasis_gate = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(
            salience_floor_fast_apply=decoded.homeostasis.salience_floor_fast_apply,
            salience_floor_slow_accept=decoded.homeostasis.salience_floor_slow_accept,
            confidence_floor_slow=decoded.homeostasis.confidence_floor_slow,
        )
    )

    from mind_runtime.expression.guards import DeterministicExpressionGuardChain

    expression_guard = DeterministicExpressionGuardChain(config=decoded.expression_guard)

    return {
        "persona": decoded.persona_profile,
        "situation": decoded.situation,
        "decision_context_config": decoded.decision_context,
        "effect_rules": decoded.emotional_effects,
        "definitions": decoded.state_definitions,
        "appraisal_producer": appraisal_producer,
        "homeostasis_gate": homeostasis_gate,
        "semantic_provider": semantic_provider,
        "slow_plasticity_window_size": decoded.slow_plasticity.window_size,
        "intent_rules": decoded.intent_engine.rules,
        "action_policy_config": decoded.action_policy,
        "policy_resources": decoded.policy_resources.available_actions,
        "expression_guard": expression_guard,
    }


def get_mr_adapter():
    """Return a thread-local XiyueMRAdapter (lazy per worker thread).

    Each worker thread gets its OWN adapter → its own TurnOrchestrator →
    its own SQLite connections created in that thread. Canonical continuity
    across threads is guaranteed by the shared durable MR state/database,
    NOT by a long-lived Python orchestrator object.

    No adapter is created on the main/import thread; creation happens on
    the first real message handled by each worker.
    """
    adapter = getattr(_local, "adapter", None)
    if adapter is None:
        if os.environ.get("MR_ENABLED", "false").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            adapter = None
        elif not _ensure_mr_importable():
            adapter = None
        else:
            try:
                from mind_runtime.host.xiyue_adapter import default_adapter

                composition = _load_production_composition()
                adapter = default_adapter(
                    persona=composition["persona"],
                    situation=composition["situation"],
                    decision_context_config=composition["decision_context_config"],
                    effect_rules=composition["effect_rules"],
                    definitions=composition["definitions"],
                    appraisal_producer=composition["appraisal_producer"],
                    homeostasis_gate=composition["homeostasis_gate"],
                    semantic_provider=composition["semantic_provider"],
                    slow_plasticity_window_size=composition["slow_plasticity_window_size"],
                    intent_rules=composition.get("intent_rules"),
                    action_policy_config=composition.get("action_policy_config"),
                    policy_resources=composition.get("policy_resources"),
                    expression_guard=composition.get("expression_guard"),
                    telemetry_sink=get_trace_journal(),
                )
                _logger.info("XiyueMRAdapter initialized (thread %s)", threading.get_ident())
                _thread_trace("ADAPTER_CREATE", adapter)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("XiyueMRAdapter init failed (fail-soft): %s", exc)
                adapter = None
        # Cache per-thread (including None so each worker only attempts once).
        _local.adapter = adapter
        # Gateway-owned readiness evaluation upon successful adapter creation
        # (re-entrancy safe), followed by the process-local OW reconciliation
        # loop. OW remains a read-only observer and never writes this file.
        if adapter is not None and not getattr(_local, "_updating_readiness", False):
            current = load_readiness()
            cur_pid = os.getpid()
            if current.get("gateway_pid") == cur_pid:
                _local._updating_readiness = True
                try:
                    reconcile_bundle_readiness(adapter=adapter)
                except Exception as _r_err:
                    _logger.warning("Auto-readiness update failed: %s", _r_err)
                finally:
                    _local._updating_readiness = False
                start_bundle_readiness_reconciler(adapter=adapter)
    return adapter


def render_bounded(bounded) -> str | None:
    """Render a HostDecisionContext to a prompt block (fail-soft)."""
    try:
        from mind_runtime.host.xiyue_adapter import render_bounded_context

        return render_bounded_context(bounded)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("render_bounded failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Gateway Runtime Epoch & Readiness Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngressVerdict:
    admitted: bool
    status: str  # "READY" | "NOT_READY" | "PRE_READY_BACKLOG" | "FAILED"
    reason: str
    error_message: str | None = None


def coerce_source_timestamp(ts: Any) -> datetime | None:
    """Coerce platform event timestamp to timezone-aware UTC datetime.

    Never synthesizes now() if ts is None or invalid.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except Exception:
            return None
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return None
    return None


def get_gateway_process_identity() -> tuple[int, str]:
    """Return (pid, start_time_iso) for the current process."""
    pid = os.getpid()
    started_iso = ""
    try:
        import psutil

        p = psutil.Process(pid)
        dt = datetime.fromtimestamp(p.create_time(), tz=UTC)
        started_iso = dt.isoformat()
    except Exception:
        started_iso = ""
    return pid, started_iso


def save_readiness(data: dict[str, Any]) -> None:
    """Persist readiness record to disk atomically.

    GATEWAY / TESTS ONLY: Must never be called by read-only viewers or evaluators.
    """
    target = get_readiness_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(".tmp")
    data["updated_at"] = datetime.now(UTC).isoformat()
    content = json.dumps(data, indent=2)
    temp_target.write_text(content, encoding="utf-8")
    temp_target.replace(target)


def begin_runtime_epoch(pid: int | None = None, started_at: str | None = None) -> dict[str, Any]:
    """Establish a new process epoch. Starts strictly as NOT_READY with runtime_ready_at=None.

    GATEWAY OWNED: Only called by the real gateway process startup hook
    (or explicit test fixtures). Non-gateway processes must never call this.
    """
    cur_pid, cur_started = get_gateway_process_identity()
    target_pid = pid if pid is not None else cur_pid
    target_started = started_at if started_at is not None else cur_started

    epoch_ts = 0
    if target_started:
        try:
            epoch_ts = int(datetime.fromisoformat(target_started).timestamp())
        except Exception:
            epoch_ts = 0
    epoch_id = f"epoch-{target_pid}-{epoch_ts}"

    record = {
        "epoch_id": epoch_id,
        "gateway_pid": target_pid,
        "gateway_started_at": target_started,
        "runtime_ready_at": None,
        "bundle_state": "NOT_READY",
        "core_ready": False,
        "ow_ready": False,
        "checks": {
            "mr_adapter_initialized": False,
            "runtime_db_available": False,
            "semantic_provider_available": False,
            "appraisal_provider_available": False,
            "slow_writer_active": False,
            "observation_window_up": False,
        },
        "reasons": ["epoch_initialized"],
    }
    save_readiness(record)
    return record


init_gateway_epoch = begin_runtime_epoch


def load_readiness() -> dict[str, Any]:
    """Load the readiness record from disk.

    PURE / READ-ONLY: Never creates, modifies, or repairs readiness.json.
    Calling from pytest, python -c, Observation Window, or status scripts has
    zero side effects on disk.
    """
    path = get_readiness_file_path()
    if not path.exists():
        return {
            "epoch_id": "epoch-none-0",
            "gateway_pid": None,
            "gateway_started_at": None,
            "runtime_ready_at": None,
            "bundle_state": "NOT_READY",
            "core_ready": False,
            "ow_ready": False,
            "checks": {
                "mr_adapter_initialized": False,
                "runtime_db_available": False,
                "semantic_provider_available": False,
                "appraisal_provider_available": False,
                "slow_writer_active": False,
                "observation_window_up": False,
            },
            "reasons": ["readiness_file_not_found"],
        }

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _logger.warning("Error reading readiness file (%s): %s", path, exc)
        return {
            "epoch_id": "epoch-corrupt-0",
            "gateway_pid": None,
            "gateway_started_at": None,
            "runtime_ready_at": None,
            "bundle_state": "NOT_READY",
            "core_ready": False,
            "ow_ready": False,
            "checks": {
                "mr_adapter_initialized": False,
                "runtime_db_available": False,
                "semantic_provider_available": False,
                "appraisal_provider_available": False,
                "slow_writer_active": False,
                "observation_window_up": False,
            },
            "reasons": [f"corrupt_file: {exc}"],
        }


def evaluate_mr_core_readiness(adapter=None) -> tuple[bool, dict[str, bool], list[str]]:
    """Pure, read-only evaluation of the 5 MR core components:

    1. mr_adapter_initialized
    2. runtime_db_available
    3. semantic_provider_available
    4. appraisal_provider_available
    5. slow_writer_active

    Zero disk side effects (never writes readiness.json).
    Zero network API requests (no LLM connectivity probes).
    Separated from gateway alive (evaluated independently by bundle supervisor/watchers).
    """
    checks = {
        "mr_adapter_initialized": False,
        "runtime_db_available": False,
        "semantic_provider_available": False,
        "appraisal_provider_available": False,
        "slow_writer_active": False,
    }
    reasons = []

    # 1. MR adapter initialized
    if adapter is None:
        adapter = getattr(_local, "adapter", None)
    if adapter is not None:
        checks["mr_adapter_initialized"] = True
    else:
        if os.environ.get("MR_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            reasons.append("MR_ENABLED_not_true")
        elif not _ensure_mr_importable():
            reasons.append("mind_runtime_not_importable")
        else:
            try:
                # Check composition object construction without side effects
                comp = _load_production_composition()
                checks["mr_adapter_initialized"] = True
            except Exception as exc:
                reasons.append(f"adapter_composition_error: {exc}")

    # 2. Runtime DB available
    state_db = _RUNTIME_DIR / "cognition_state.sqlite"
    facts_db = _RUNTIME_DIR / "facts.sqlite"
    try:
        _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        conn1 = sqlite3.connect(str(state_db), timeout=1.0)
        conn1.execute("SELECT 1")
        conn1.close()

        conn2 = sqlite3.connect(str(facts_db), timeout=1.0)
        conn2.execute("SELECT 1")
        conn2.close()

        checks["runtime_db_available"] = True
    except Exception as db_exc:
        reasons.append(f"db_unavailable: {db_exc}")

    # 3 & 4 & 5. Semantic, Appraisal, and Slow Writer
    try:
        comp = _load_production_composition()

        # 3 & 4. Legacy readiness keys now represent the typed Body semantic
        # and appraisal input seams. No local provider or credential is a
        # production prerequisite.
        checks["semantic_provider_available"] = True
        checks["appraisal_provider_available"] = True

        # 5. Slow writer
        slow_size = comp.get("slow_plasticity_window_size", 0)
        if slow_size and slow_size > 0:
            checks["slow_writer_active"] = True
        else:
            reasons.append("slow_plasticity_window_size_zero")
    except Exception as comp_exc:
        reasons.append(f"composition_failed: {comp_exc}")

    all_ok = all(checks.values())
    return all_ok, checks, reasons


evaluate_core_readiness = evaluate_mr_core_readiness


def check_observation_window_up(port: int = 8766) -> bool:
    """Check if Observation Window is reachable on HTTP port."""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mr_seam_health_probe"})
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("status") == "ok"
    except Exception:
        return False
    return False


def mark_runtime_ready(
    *,
    force_ready_at: datetime | None = None,
    ow_port: int = 8766,
    adapter: Any = None,
    _allow_test_write: bool = False,
) -> dict[str, Any]:
    """Gateway-owned transition of runtime readiness to READY or DEGRADED.

    GATEWAY OWNED: Reads current epoch from disk. Only the gateway process
    owning the current epoch (or tests with _allow_test_write=True) may persist ready state.
    """
    current = load_readiness()
    cur_pid, _ = get_gateway_process_identity()
    file_pid = current.get("gateway_pid")

    # If epoch does not belong to cur_pid, reject write from foreign process
    if not _allow_test_write and (file_pid is None or file_pid != cur_pid):
        _logger.debug(
            "mark_runtime_ready called from PID %s but epoch belongs to PID %s; write ignored",
            cur_pid,
            file_pid,
        )
        return current

    core_ok, checks, reasons = evaluate_mr_core_readiness(adapter=adapter)
    ow_up = check_observation_window_up(port=ow_port)

    checks["observation_window_up"] = ow_up
    current["checks"] = checks
    current["core_ready"] = core_ok
    current["ow_ready"] = ow_up
    current["reasons"] = reasons

    if core_ok:
        if current.get("runtime_ready_at") is None:
            ready_dt = force_ready_at or datetime.now(UTC)
            current["runtime_ready_at"] = ready_dt.isoformat()
        current["bundle_state"] = "READY" if ow_up else "DEGRADED"
    else:
        current["runtime_ready_at"] = None
        current["bundle_state"] = "NOT_READY"

    save_readiness(current)
    return current


evaluate_and_update_readiness = mark_runtime_ready


def reconcile_bundle_readiness(
    *,
    adapter: Any = None,
    ow_port: int = 8766,
    force_ready_at: datetime | None = None,
    _allow_test_write: bool = False,
) -> dict[str, Any]:
    """Refresh the Gateway-owned bundle projection for the current epoch.

    This is deliberately a thin operational seam over ``mark_runtime_ready``:
    it performs no cognition work and grants no write authority to OW. The
    caller must be the Gateway that owns the epoch (or an explicit test
    fixture using the existing test-only escape hatch).
    """
    return mark_runtime_ready(
        adapter=adapter,
        ow_port=ow_port,
        force_ready_at=force_ready_at,
        _allow_test_write=_allow_test_write,
    )


def _bundle_reconciliation_loop(
    adapter: Any,
    stop_event: threading.Event,
    ow_port: int,
    interval_s: float,
) -> None:
    """Continuously reconcile OW health from the Gateway-owned process."""
    while not stop_event.is_set():
        current = load_readiness()
        if current.get("gateway_pid") != os.getpid():
            return
        try:
            reconcile_bundle_readiness(adapter=adapter, ow_port=ow_port)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Bundle readiness reconciliation failed: %s", exc)
        stop_event.wait(interval_s)


def start_bundle_readiness_reconciler(
    *,
    adapter: Any,
    ow_port: int = 8766,
    interval_s: float = 1.0,
) -> threading.Event:
    """Start one Gateway-owned readiness reconciler for this process.

    The returned event is test/controlled-shutdown support. The thread is a
    daemon because it is strictly an operational projection refresher and
    must never keep the Gateway alive during process shutdown.
    """
    global _bundle_reconciler_thread, _bundle_reconciler_stop
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    with _bundle_reconciler_lock:
        if (
            _bundle_reconciler_thread is not None
            and _bundle_reconciler_thread.is_alive()
            and _bundle_reconciler_stop is not None
        ):
            return _bundle_reconciler_stop
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_bundle_reconciliation_loop,
            args=(adapter, stop_event, ow_port, interval_s),
            name="xiyue-bundle-readiness",
            daemon=True,
        )
        _bundle_reconciler_stop = stop_event
        _bundle_reconciler_thread = thread
        thread.start()
        return stop_event


def stop_bundle_readiness_reconciler() -> None:
    """Stop the process-local reconciliation loop (shutdown/test support)."""
    global _bundle_reconciler_thread, _bundle_reconciler_stop
    with _bundle_reconciler_lock:
        stop_event = _bundle_reconciler_stop
        thread = _bundle_reconciler_thread
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        _bundle_reconciler_thread = None
        _bundle_reconciler_stop = None


def on_gateway_process_startup() -> dict[str, Any]:
    """Gateway boot hook: establish process epoch (NOT_READY) then evaluate readiness."""
    cur_pid, cur_started = get_gateway_process_identity()
    epoch_rec = begin_runtime_epoch(cur_pid, cur_started)
    try:
        return mark_runtime_ready()
    except Exception as exc:
        _logger.warning("on_gateway_process_startup mark_runtime_ready failed: %s", exc)
        return epoch_rec


def check_ingress_admission(
    profile: str,
    source_occurred_at: datetime | None,
) -> IngressVerdict:
    """Pre-turn gating executed strictly before adapter.begin_turn()."""
    if profile != "xiyue":
        return IngressVerdict(admitted=True, status="READY", reason="non_xiyue_profile")

    ready_data = load_readiness()
    if not ready_data.get("core_ready", False):
        return IngressVerdict(
            admitted=False,
            status="NOT_READY",
            reason=f"core_runtime_not_ready ({', '.join(ready_data.get('reasons', []))})",
            error_message="Mind Runtime is temporarily unavailable. (MR_NOT_READY)",
        )

    runtime_ready_at_str = ready_data.get("runtime_ready_at")
    if runtime_ready_at_str and source_occurred_at is not None:
        try:
            ready_dt = datetime.fromisoformat(runtime_ready_at_str)
            if source_occurred_at < ready_dt:
                _logger.warning(
                    "[BACKLOG QUARANTINE] source_occurred_at=%s < runtime_ready_at=%s; classified PRE_READY_BACKLOG",
                    source_occurred_at.isoformat(),
                    runtime_ready_at_str,
                )
                return IngressVerdict(
                    admitted=False,
                    status="PRE_READY_BACKLOG",
                    reason=f"source_occurred_at ({source_occurred_at.isoformat()}) < runtime_ready_at ({runtime_ready_at_str})",
                )
        except Exception as exc:
            _logger.warning("Error parsing runtime_ready_at (%s): %s", runtime_ready_at_str, exc)

    return IngressVerdict(admitted=True, status="READY", reason="admitted_live")


def begin_turn_clean(
    message: str,
    channel: str,
    session_id: str,
    message_id: str = "",
    occurred_at: datetime | None = None,
    profile: str = "xiyue",
    agent: Any = None,
) -> tuple[Any | None, IngressVerdict]:
    """Gateway seam entrypoint.

    1. Gating (readiness + backlog) BEFORE adapter.begin_turn().
    2. Strips host system-note wrappers.
    3. Invokes adapter.begin_turn(..., occurred_at=occurred_at).
    4. Enforces fail-closed on profile xiyue on processing/provider failure.
    """
    verdict = check_ingress_admission(profile=profile, source_occurred_at=occurred_at)
    if not verdict.admitted:
        return None, verdict

    adapter = get_mr_adapter()
    if adapter is None:
        return None, IngressVerdict(
            admitted=False,
            status="NOT_READY",
            reason="adapter_none",
            error_message="Mind Runtime is temporarily unavailable. (MR_NOT_READY)",
        )

    # Wrap agent._session_db.append_message if available to capture exact assistant message id
    if agent is not None:
        try:
            session_db = getattr(agent, "_session_db", None)
            if session_db is not None:
                session_db._mr_current_assistant_msg_id = None
                if not getattr(session_db, "_mr_tracked", False):
                    _orig_append = session_db.append_message

                    def _tracking_append(*args, **kwargs):
                        row_id = _orig_append(*args, **kwargs)
                        role = kwargs.get("role")
                        if role is None and len(args) >= 2:
                            role = args[1]
                        if role == "assistant":
                            session_db._mr_current_assistant_msg_id = row_id
                        return row_id

                    session_db.append_message = _tracking_append
                    session_db._mr_tracked = True
        except Exception as _wrap_exc:
            _logger.debug("Failed to wrap session_db.append_message (fail-soft): %s", _wrap_exc)

    clean_msg = _strip_host_system_note(message)
    try:
        handle = adapter.begin_turn(
            message=clean_msg,
            channel=channel,
            session_id=session_id,
            message_id=message_id,
            occurred_at=occurred_at,
        )
        if handle is None:
            # begin_turn returned None or FAILED
            journal = get_trace_journal()
            if journal is not None:
                try:
                    journal.record(
                        interaction_id=f"ingress-{session_id}-{message_id}",
                        stage="USER_INGRESS",
                        status="REJECTED",
                        occurred_at=occurred_at or datetime.now(UTC),
                        payload={
                            "message": clean_msg,
                            "channel": channel,
                            "session_id": session_id,
                            "message_id": message_id,
                            "verdict": "FAILED",
                        },
                        source_refs=((message_id,) if message_id else ()),
                    )
                except Exception:
                    pass
            if profile == "xiyue":
                return None, IngressVerdict(
                    admitted=False,
                    status="FAILED",
                    reason="adapter_begin_turn_failed",
                    error_message="Mind Runtime processing failed. (MR_TURN_FAILED)",
                )
            return None, IngressVerdict(admitted=True, status="READY", reason="fail_soft_non_xiyue")

        journal = get_trace_journal()
        if journal is not None:
            try:
                interaction_id = getattr(
                    handle, "interaction_id", f"ingress-{session_id}-{message_id}"
                )
                journal.record(
                    interaction_id=interaction_id,
                    stage="USER_INGRESS",
                    status="ADMITTED",
                    occurred_at=occurred_at or datetime.now(UTC),
                    payload={
                        "message": clean_msg,
                        "channel": channel,
                        "session_id": session_id,
                        "message_id": message_id,
                        "verdict": "READY",
                    },
                    source_refs=((message_id,) if message_id else ()),
                )
            except Exception:
                pass

        return handle, IngressVerdict(admitted=True, status="READY", reason="ok")
    except Exception as exc:
        _logger.exception("begin_turn_clean failure: %s", exc)
        journal = get_trace_journal()
        if journal is not None:
            try:
                journal.record(
                    interaction_id=f"ingress-{session_id}-{message_id}",
                    stage="USER_INGRESS",
                    status="REJECTED",
                    occurred_at=occurred_at or datetime.now(UTC),
                    payload={
                        "message": clean_msg,
                        "channel": channel,
                        "session_id": session_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                    source_refs=((message_id,) if message_id else ()),
                )
            except Exception:
                pass
        if profile == "xiyue":
            return None, IngressVerdict(
                admitted=False,
                status="FAILED",
                reason=f"exception: {exc}",
                error_message="Mind Runtime processing failed. (MR_TURN_FAILED)",
            )
        return None, IngressVerdict(admitted=True, status="READY", reason="fail_soft_non_xiyue")


def on_turn_commit(
    handle: Any,
    agent: Any = None,
    final_response: str | None = None,
) -> None:
    """Invoked at the Hermes commit seam after final_response is extracted."""
    journal = get_trace_journal()
    if journal is None or handle is None:
        return
    try:
        interaction_id = getattr(handle, "interaction_id", str(handle))
        session_db = getattr(agent, "_session_db", None) if agent is not None else None
        last_row_id = (
            getattr(session_db, "_mr_current_assistant_msg_id", None) if session_db else None
        )

        if last_row_id is not None:
            durable_msg_id = f"hermes-msg:{last_row_id}"
        else:
            durable_msg_id = "UNAVAILABLE"

        journal.record(
            interaction_id=interaction_id,
            stage="ASSISTANT_RESPONSE",
            status="COMMITTED",
            occurred_at=datetime.now(UTC),
            payload={
                "text": final_response,
                "durable_message_id": durable_msg_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            source_refs=((durable_msg_id,) if durable_msg_id != "UNAVAILABLE" else ()),
        )
    except Exception as exc:
        _logger.warning("on_turn_commit telemetry failed: %s", exc)


def on_turn_abort(
    handle: Any,
    reason: str = "empty_response",
) -> None:
    """Invoked at the Hermes abort seam when response is empty or failed."""
    journal = get_trace_journal()
    if journal is None or handle is None:
        return
    try:
        interaction_id = getattr(handle, "interaction_id", str(handle))
        journal.record(
            interaction_id=interaction_id,
            stage="TURN_ABORT",
            status="ABORTED",
            occurred_at=datetime.now(UTC),
            payload={"reason": reason},
            source_refs=(),
        )
    except Exception as exc:
        _logger.warning("on_turn_abort telemetry failed: %s", exc)
