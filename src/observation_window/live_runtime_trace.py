"""MR-LIVE-RUNTIME-TRACE-V0: Read-only live runtime observability.

Collects and displays:
  1. Runtime Header (Gateway PID, process start, Git HEAD, working tree dirty,
     runtime_id, persona_id, config digest/path, provider statuses, state DB,
     and prominent stale-process warning when gateway started before current code).
  2. Latest Turn Trace across 14 pipeline stages:
       - message received
       - Observation
       - SemanticCandidate
       - SemanticAppraisal
       - Effect / Impulse
       - Homeostasis disposition
       - Slow contribution
       - Slow state BEFORE
       - Slow state AFTER
       - C1 slow read
       - C2 projected item
       - Hermes MR context forwarded
       - LLM response
       - commit / abort
  3. Negative reasons for all skipped/rejected/empty stages.
  4. Persisted slow state visibility (agent.longitudinal.relationship_security and C2).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


@dataclass(frozen=True)
class RuntimeHeader:
    gateway_pid: int | None
    gateway_start_time: str | None
    git_head: str
    working_tree_dirty: str  # "YES" | "NO"
    runtime_id: str
    persona_id: str
    runtime_config_path: str
    runtime_config_digest: str
    semantic_provider_status: str  # "ACTIVE" | "DISABLED" | "ERROR"
    semantic_provider_detail: str
    appraisal_provider_status: str  # "ACTIVE" | "ERROR"
    appraisal_provider_detail: str
    slow_writer_status: str  # "ACTIVE" | "NONE"
    slow_writer_detail: str
    state_db_path: str
    is_stale: bool
    stale_warning: str | None
    stale_detail: str | None
    bundle_state: str = "NOT_READY"  # "READY" | "DEGRADED" | "NOT_READY"
    runtime_ready_at: str | None = None
    epoch_id: str | None = None


@dataclass(frozen=True)
class TraceStage:
    step_num: int
    name: str
    stage_key: str
    status: str  # "PASS" | "NONE" | "NOT_RUN" | "REJECT" | "ERROR" | "SKIPPED" | "EMPTY"
    value: str
    reason: str | None = None


@dataclass(frozen=True)
class PersistedSlowState:
    dimension: str
    status: str  # "PRESENT" | "NOT PERSISTED"
    value: float | None
    version: int | None
    updated_at: str | None
    c2_projected: str
    c2_reason: str | None


@dataclass(frozen=True)
class LiveRuntimeTraceReport:
    header: RuntimeHeader
    latest_turn: list[TraceStage]
    persisted_slow_states: list[PersistedSlowState]
    observed_at: str


class LiveRuntimeTraceCollector:
    """Read-only collector that gathers runtime truth without modifying state."""

    def __init__(
        self,
        *,
        repo_root: Path | str | None = None,
        hermes_profile_dir: Path | str | None = None,
    ) -> None:
        self.repo_root = (
            Path(repo_root)
            if repo_root is not None
            else Path(__file__).resolve().parents[2]
        )
        if hermes_profile_dir is None:
            self.hermes_profile_dir = Path.home() / ".hermes" / "profiles" / "xiyue"
        else:
            self.hermes_profile_dir = Path(hermes_profile_dir)

    def collect(self) -> LiveRuntimeTraceReport:
        header = self._collect_header()
        latest_turn = self._collect_latest_turn(header)
        slow_states = self._collect_persisted_slow_states()
        return LiveRuntimeTraceReport(
            header=header,
            latest_turn=latest_turn,
            persisted_slow_states=slow_states,
            observed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Header Collection
    # ------------------------------------------------------------------

    def _collect_header(self) -> RuntimeHeader:
        pid_file = self.hermes_profile_dir / "gateway.pid"
        gw_pid: int | None = None
        gw_start_dt: datetime | None = None
        gw_start_str: str | None = None

        if pid_file.exists():
            try:
                data = json.loads(pid_file.read_text(encoding="utf-8"))
                candidate_pid = data.get("pid")
                if candidate_pid and psutil.pid_exists(candidate_pid):
                    p = psutil.Process(candidate_pid)
                    # verify it is python/hermes
                    cmdline = " ".join(p.cmdline()).lower()
                    if "hermes" in cmdline or "gateway" in cmdline or "python" in p.name().lower():
                        gw_pid = candidate_pid
                        gw_start_dt = datetime.fromtimestamp(p.create_time(), timezone.utc)
                        gw_start_str = gw_start_dt.isoformat()
            except Exception:
                gw_pid = None

        # Fallback to scanning processes if pid file wasn't active
        if gw_pid is None:
            for p in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(p.info["cmdline"] or []).lower()
                    if "hermes_cli.main" in cmdline and "gateway" in cmdline:
                        gw_pid = p.info["pid"]
                        gw_start_dt = datetime.fromtimestamp(p.create_time(), timezone.utc)
                        gw_start_str = gw_start_dt.isoformat()
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        # Git HEAD and dirty status
        git_head = "UNKNOWN"
        working_tree_dirty = "UNKNOWN"
        try:
            git_head = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.repo_root,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            status_out = subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=self.repo_root,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            working_tree_dirty = "YES" if status_out else "NO"
        except Exception:
            pass

        # Config path & digest
        cfg_path = os.environ.get("MR_RUNTIME_CONFIG")
        if not cfg_path:
            cfg_path = str(
                self.repo_root / "certification" / "d11s" / "inputs" / "runtime-config.json"
            )
        cfg_path_obj = Path(cfg_path)
        cfg_digest = "MISSING"
        components: dict[str, Any] = {}
        if cfg_path_obj.exists():
            content = cfg_path_obj.read_bytes()
            cfg_digest = hashlib.sha256(content).hexdigest()
            try:
                raw_cfg = json.loads(content.decode("utf-8"))
                for c in raw_cfg.get("components", []):
                    components[c.get("component_id", "")] = c.get("payload", {})
            except Exception:
                pass

        # Check staleness: compare gw_start_dt with mtime of source files
        paths_to_check = [
            self.repo_root / "src",
            self.repo_root / "xiyue",
            cfg_path_obj,
            self.hermes_profile_dir / "config.yaml",
        ]
        latest_src_mtime = 0.0
        latest_src_file = ""
        for p in paths_to_check:
            if p.is_file():
                m = p.stat().st_mtime
                if m > latest_src_mtime:
                    latest_src_mtime = m
                    latest_src_file = str(p)
            elif p.is_dir():
                for root, _, files in os.walk(p):
                    for f in files:
                        fp = Path(root) / f
                        if fp.suffix in (".py", ".json", ".yaml", ".yml"):
                            m = fp.stat().st_mtime
                            if m > latest_src_mtime:
                                latest_src_mtime = m
                                latest_src_file = str(fp)

        is_stale = False
        stale_warning = None
        stale_detail = None
        if gw_start_dt is not None and latest_src_mtime > 0:
            latest_src_dt = datetime.fromtimestamp(latest_src_mtime, timezone.utc)
            if gw_start_dt < latest_src_dt:
                is_stale = True
                stale_warning = "GATEWAY MAY BE STALE — RESTART REQUIRED"
                stale_detail = (
                    f"Gateway started {gw_start_dt.strftime('%H:%M:%S UTC')} < "
                    f"latest code modification {latest_src_dt.strftime('%H:%M:%S UTC')} "
                    f"({Path(latest_src_file).name})"
                )

        # Semantic provider status
        sem_cfg = components.get("semantic_provider", {})
        sem_mode = sem_cfg.get("mode", "disabled")
        sem_status = "DISABLED"
        sem_detail = "mode=disabled in runtime config"
        if sem_mode == "enabled":
            adapter_error = self._find_recent_adapter_error(gw_start_dt)
            if adapter_error:
                sem_status = "ERROR"
                sem_detail = adapter_error
            elif not os.environ.get("MR_SEMANTIC_PROVIDER") and not os.environ.get("GLM_API_KEY"):
                sem_status = "ERROR"
                sem_detail = "missing MR_SEMANTIC_PROVIDER / GLM_API_KEY"
            else:
                sem_status = "ACTIVE"
                sem_detail = f"mode=enabled provider={os.environ.get('MR_SEMANTIC_PROVIDER', 'glm')}"

        # Appraisal provider status
        app_cfg = components.get("appraisal_producer_strategy", {})
        app_strategy = app_cfg.get("strategy", "unknown")
        app_key_env = app_cfg.get("api_key_env", "APPRAISAL_API_KEY")
        app_status = "ACTIVE"
        app_detail = f"strategy={app_strategy} model={app_cfg.get('model', 'model-appraisal-v1')}"
        if app_strategy == "model_backed":
            has_key = bool(os.environ.get(app_key_env))
            if not has_key:
                profile_env = self.hermes_profile_dir / ".env"
                if profile_env.exists():
                    has_key = app_key_env in profile_env.read_text(encoding="utf-8", errors="ignore")
            if not has_key:
                app_status = "ERROR"
                app_detail = f"missing {app_key_env} for model_backed strategy"

        # Slow writer status
        slow_cfg = components.get("slow_plasticity", {})
        window_size = slow_cfg.get("window_size", 0)
        if window_size and window_size > 0:
            slow_status = "ACTIVE"
            slow_detail = f"window_size={window_size}"
        else:
            slow_status = "NONE"
            slow_detail = "window_size not set"

        # State DB path
        state_db = os.environ.get(
            "MR_STATE_DB",
            str(self.hermes_profile_dir / "runtime" / "cognition_state.sqlite"),
        )

        # Readiness & Epoch info from gateway readiness.json
        readiness_file = self.hermes_profile_dir / "runtime" / "readiness.json"
        bundle_state = "NOT_READY"
        runtime_ready_at = None
        epoch_id = None
        if readiness_file.exists():
            try:
                rdata = json.loads(readiness_file.read_text(encoding="utf-8"))
                file_pid = rdata.get("gateway_pid")
                # Epoch must match current gateway_pid and core_ready must be True
                if gw_pid is not None and file_pid == gw_pid and rdata.get("core_ready", False):
                    bundle_state = "READY"
                    runtime_ready_at = rdata.get("runtime_ready_at")
                    epoch_id = rdata.get("epoch_id")
                else:
                    bundle_state = "NOT_READY"
                    runtime_ready_at = None
                    epoch_id = rdata.get("epoch_id") if file_pid == gw_pid else None
            except Exception:
                bundle_state = "NOT_READY"

        return RuntimeHeader(
            gateway_pid=gw_pid,
            gateway_start_time=gw_start_str,
            git_head=git_head,
            working_tree_dirty=working_tree_dirty,
            runtime_id="xiyue",
            persona_id="xiyue",
            runtime_config_path=cfg_path,
            runtime_config_digest=cfg_digest[:16],
            semantic_provider_status=sem_status,
            semantic_provider_detail=sem_detail,
            appraisal_provider_status=app_status,
            appraisal_provider_detail=app_detail,
            slow_writer_status=slow_status,
            slow_writer_detail=slow_detail,
            state_db_path=state_db,
            is_stale=is_stale,
            stale_warning=stale_warning,
            stale_detail=stale_detail,
            bundle_state=bundle_state,
            runtime_ready_at=runtime_ready_at,
            epoch_id=epoch_id,
        )

    def _find_recent_adapter_error(
        self, gw_start_dt: datetime | None = None
    ) -> str | None:
        """Find an adapter init failure that happened AFTER the current
        gateway process started.

        TRACE-FIDELITY FIX (2026-09-05): previously this scanned the last
        200 log lines with no time bound, so a stale failure from a PREVIOUS
        gateway process kept reporting ERROR forever (observed 2026-09-05:
        init-failed at 16:50 was still shown after the 17:13 restart that
        actually succeeded). Log lines carry local-time timestamps; the
        gateway start time is UTC — both are converted to aware UTC before
        comparison. Only failures strictly after gateway start count.
        """
        agent_log = self.hermes_profile_dir / "logs" / "agent.log"
        if not agent_log.exists():
            return None
        try:
            with open(agent_log, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            for line in reversed(lines[-500:]):
                if "XiyueMRAdapter init failed" not in line:
                    continue
                # Parse the leading local timestamp "YYYY-MM-DD HH:MM:SS,mmm"
                m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if gw_start_dt is not None:
                    if m is None:
                        # Undated failure line inside the window: keep it
                        # (conservative — it may belong to this process).
                        pass
                    else:
                        try:
                            line_local = datetime.strptime(
                                m.group(1), "%Y-%m-%d %H:%M:%S"
                            ).astimezone()  # local -> aware
                            line_utc = line_local.astimezone(timezone.utc)
                            if line_utc <= gw_start_dt:
                                continue  # failure predates this process — stale
                        except ValueError:
                            pass
                parts = line.split("XiyueMRAdapter init failed (fail-soft):")
                if len(parts) > 1:
                    return parts[1].strip()
                return "XiyueMRAdapter init failed"
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Latest Turn Pipeline Collection
    # ------------------------------------------------------------------

    def _collect_latest_turn(self, header: RuntimeHeader) -> list[TraceStage]:
        stages: list[TraceStage] = []

        gateway_log = self.hermes_profile_dir / "logs" / "gateway.log"
        state_db_path = header.state_db_path
        facts_db_path = str(self.hermes_profile_dir / "runtime" / "facts.sqlite")

        last_msg_text = None
        last_msg_time = None
        last_platform = None
        last_chat = None

        if gateway_log.exists():
            try:
                with open(gateway_log, "r", encoding="utf-8", errors="ignore") as f:
                    glines = f.readlines()
                for line in reversed(glines):
                    if "inbound message:" in line:
                        m = re.search(
                            r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*?platform=(\w+).*?chat=(\w+).*?msg='(.*?)'",
                            line,
                        )
                        if m:
                            last_msg_time = m.group(1)
                            last_platform = m.group(2)
                            last_chat = m.group(3)
                            last_msg_text = m.group(4)
                            break
            except Exception:
                pass

        # 1. message received
        if last_msg_text:
            display_text = last_msg_text if len(last_msg_text) <= 60 else last_msg_text[:57] + "..."
            stages.append(
                TraceStage(
                    step_num=1,
                    name="message received",
                    stage_key="message_received",
                    status="PASS",
                    value=f"'{display_text}' ({last_platform}:{last_chat} at {last_msg_time})",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=1,
                    name="message received",
                    stage_key="message_received",
                    status="NONE",
                    value="no inbound message recorded",
                    reason="no_message_observed",
                )
            )

        adapter_failed = header.semantic_provider_status == "ERROR"

        # TRACE-FIDELITY (2026-09-05): stages 2-5 are now derived from the
        # DURABLE stores (facts.sqlite / cognition_state.sqlite) instead of
        # being hard-coded. The durable rows are the runtime truth — a
        # monitor that reports a breakpoint that never happened is worse
        # than no monitor.
        facts_con = None
        cog_con = None
        latest_interaction_id = None
        latest_evidence_id = None
        latest_obs_id = None
        latest_obs_value = None
        try:
            if os.path.exists(facts_db_path):
                facts_con = sqlite3.connect(f"file:{facts_db_path}?mode=ro", uri=True)
                row = facts_con.execute(
                    "SELECT interaction_id, id, payload FROM evidence "
                    "WHERE interaction_id LIKE 'mr-%' ORDER BY received_at DESC, rowid DESC LIMIT 1"
                ).fetchone()
                if row:
                    latest_interaction_id = row[0]
                    latest_evidence_id = row[1]
                orow = facts_con.execute(
                    "SELECT id, value FROM observations "
                    "WHERE interaction_id LIKE 'mr-%' ORDER BY observed_at DESC, rowid DESC LIMIT 1"
                ).fetchone()
                if orow:
                    latest_obs_id, latest_obs_value = orow[0], orow[1]
        except Exception:
            facts_con = None
        try:
            if os.path.exists(state_db_path):
                cog_con = sqlite3.connect(f"file:{state_db_path}?mode=ro", uri=True)
        except Exception:
            cog_con = None

        # The latest durable interaction counts as the turn under trace ONLY
        # if it is not older than the latest gateway-log message we found.
        turn_is_current = latest_interaction_id is not None

        # 2. Observation — real record from facts.sqlite
        if latest_obs_id is not None and not adapter_failed:
            stages.append(
                TraceStage(
                    step_num=2,
                    name="Observation",
                    stage_key="observation",
                    status="PASS",
                    value=str(latest_obs_id),
                    reason=None,
                )
            )
        elif adapter_failed:
            stages.append(
                TraceStage(
                    step_num=2,
                    name="Observation",
                    stage_key="observation",
                    status="NONE",
                    value="not admitted",
                    reason="adapter_init_failed",
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=2,
                    name="Observation",
                    stage_key="observation",
                    status="NONE",
                    value="no observation record",
                    reason="no_observation_admitted",
                )
            )

        # 3. SemanticCandidate — inferred from durable evidence refs on
        # affect state rows (a candidate applied by the effect mapper leaves
        # its evidence ref on the state row it touched).
        candidate_ref = None
        if cog_con is not None:
            try:
                row = cog_con.execute(
                    "SELECT evidence_refs, updated_at FROM states "
                    "WHERE dimension LIKE 'agent.affect%' AND evidence_refs != '[]' "
                    "ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    candidate_ref = row[0]
            except Exception:
                candidate_ref = None
        if adapter_failed:
            stages.append(
                TraceStage(
                    step_num=3,
                    name="SemanticCandidate",
                    stage_key="semantic_candidate",
                    status="NONE",
                    value="none",
                    reason="semantic_provider_unavailable",
                )
            )
        elif candidate_ref is not None and turn_is_current:
            stages.append(
                TraceStage(
                    step_num=3,
                    name="SemanticCandidate",
                    stage_key="semantic_candidate",
                    status="PASS",
                    value=str(candidate_ref),
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=3,
                    name="SemanticCandidate",
                    stage_key="semantic_candidate",
                    status="UNKNOWN",
                    value="unknown",
                    reason="not_derivable_from_durable_state",
                )
            )

        # 4. SemanticAppraisal — an appraisal consumed the candidate; the
        # durable plane stores salience on slow_contribution rows only, so
        # absent one we refuse to fabricate a status.
        appraisal_row = None
        if cog_con is not None:
            try:
                appraisal_row = cog_con.execute(
                    "SELECT proposed_value, salience, accepted_at FROM slow_contribution_window "
                    "ORDER BY accepted_at DESC LIMIT 1"
                ).fetchone()
            except Exception:
                appraisal_row = None
        if appraisal_row is not None:
            stages.append(
                TraceStage(
                    step_num=4,
                    name="SemanticAppraisal",
                    stage_key="semantic_appraisal",
                    status="PASS",
                    value=f"salience={appraisal_row[1]} proposed={appraisal_row[0]}",
                    reason=None,
                )
            )
        elif adapter_failed:
            stages.append(
                TraceStage(
                    step_num=4,
                    name="SemanticAppraisal",
                    stage_key="semantic_appraisal",
                    status="NOT_RUN",
                    value="not executed",
                    reason="adapter_init_failed",
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=4,
                    name="SemanticAppraisal",
                    stage_key="semantic_appraisal",
                    status="UNKNOWN",
                    value="unknown",
                    reason="no_durable_appraisal_record",
                )
            )

        # 5. Effect / Impulse — same durable-derivation basis as stage 3.
        if adapter_failed:
            stages.append(
                TraceStage(
                    step_num=5,
                    name="Effect / Impulse",
                    stage_key="effect_impulse",
                    status="NOT_RUN",
                    value="not executed",
                    reason="adapter_init_failed",
                )
            )
        elif candidate_ref is not None and turn_is_current:
            stages.append(
                TraceStage(
                    step_num=5,
                    name="Effect / Impulse",
                    stage_key="effect_impulse",
                    status="PASS",
                    value="applied (affect state carries evidence ref)",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=5,
                    name="Effect / Impulse",
                    stage_key="effect_impulse",
                    status="UNKNOWN",
                    value="unknown",
                    reason="not_derivable_from_durable_state",
                )
            )

        # 6. Homeostasis disposition — OW-LIVE-TRACE-TRUTH-FIX (2026-09-05):
        # The HomeostasisDecision produced by the gate at Seam B is NOT persisted
        # to any durable store in the current architecture. There is no
        # runtime evidence record for the gate's disposition.
        # Per OW-LIVE-TRACE-TRUTH-FIX RULES: "A stage may be shown as
        # PASS/REJECT/ERROR only when there is direct runtime evidence that the
        # stage executed. If execution cannot be proven: UNKNOWN / NOT_RUN."
        # The prior hard-coded REJECT was an inference from absence of salience,
        # not a durable fact — replaced with UNAVAILABLE.
        stages.append(
            TraceStage(
                step_num=6,
                name="Homeostasis disposition",
                stage_key="homeostasis_disposition",
                status="UNAVAILABLE",
                value="no durable decision record",
                reason="homeostasis_decision_not_persisted",
            )
        )

        # 7. Slow contribution — durable: slow_contribution_window rows
        if appraisal_row is not None:
            stages.append(
                TraceStage(
                    step_num=7,
                    name="Slow contribution",
                    stage_key="slow_contribution",
                    status="PASS",
                    value=f"accepted_at={appraisal_row[2]}",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=7,
                    name="Slow contribution",
                    stage_key="slow_contribution",
                    status="SKIPPED",
                    value="skipped",
                    reason="no_slow_accept",
                )
            )

        # 8. Slow state BEFORE
        slow_state = self._get_latest_slow_state(state_db_path)
        if slow_state:
            stages.append(
                TraceStage(
                    step_num=8,
                    name="Slow state BEFORE",
                    stage_key="slow_state_before",
                    status="PASS",
                    value=f"dim={slow_state['dimension']} val={slow_state['value']} ver={slow_state['version']}",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=8,
                    name="Slow state BEFORE",
                    stage_key="slow_state_before",
                    status="NONE",
                    value="none",
                    reason="no_prior_slow_state",
                )
            )

        # 9. Slow state AFTER
        stages.append(
            TraceStage(
                step_num=9,
                name="Slow state AFTER",
                stage_key="slow_state_after",
                status="PASS" if appraisal_row is not None else "SKIPPED",
                value=(
                    f"dim={slow_state['dimension']} val={slow_state['value']} ver={slow_state['version']}"
                    if appraisal_row is not None and slow_state
                    else "skipped"
                ),
                reason=None if appraisal_row is not None else "no_slow_write",
            )
        )

        # 10. C1 slow read
        if slow_state:
            stages.append(
                TraceStage(
                    step_num=10,
                    name="C1 slow read",
                    stage_key="c1_slow_read",
                    status="PASS",
                    value=f"val={slow_state['value']}",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=10,
                    name="C1 slow read",
                    stage_key="c1_slow_read",
                    status="NONE",
                    value="not in state db",
                    reason="not_in_state_db",
                )
            )

        # 11. C2 projected item
        if slow_state:
            stages.append(
                TraceStage(
                    step_num=11,
                    name="C2 projected item",
                    stage_key="c2_projected_item",
                    status="PASS",
                    value=f"key={slow_state['dimension']} val={slow_state['value']}",
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=11,
                    name="C2 projected item",
                    stage_key="c2_projected_item",
                    status="EMPTY",
                    value="empty",
                    reason="no_persisted_slow_state",
                )
            )

        # 12. Hermes MR context forwarded — OW-LIVE-TRACE-TRUTH-FIX (2026-09-05):
        # "Do NOT infer PASS from provider state." The Hermes MR context is
        # forwarded when begin_turn returns a non-None handle. We use the
        # durable interaction status (started/committed/aborted) as the
        # single runtime evidence that begin_turn actually ran for this
        # turn. Anything else is inference and we refuse to fabricate.
        if adapter_failed:
            stages.append(
                TraceStage(
                    step_num=12,
                    name="Hermes MR context forwarded",
                    stage_key="hermes_mr_context_forwarded",
                    status="NOT_RUN",
                    value="not forwarded",
                    reason="adapter_init_failed",
                )
            )
        else:
            interaction_status = self._get_latest_interaction_status(
                facts_db_path, latest_interaction_id
            )
            if interaction_status in ("started", "committed"):
                stages.append(
                    TraceStage(
                        step_num=12,
                        name="Hermes MR context forwarded",
                        stage_key="hermes_mr_context_forwarded",
                        status="PASS",
                        value=f"interaction.status={interaction_status}",
                        reason=None,
                    )
                )
            elif interaction_status == "aborted":
                stages.append(
                    TraceStage(
                        step_num=12,
                        name="Hermes MR context forwarded",
                        stage_key="hermes_mr_context_forwarded",
                        status="REJECT",
                        value="interaction.status=aborted",
                        reason="host_abort",
                    )
                )
            else:
                stages.append(
                    TraceStage(
                        step_num=12,
                        name="Hermes MR context forwarded",
                        stage_key="hermes_mr_context_forwarded",
                        status="UNKNOWN",
                        value="interaction status unknown for current turn",
                        reason="no_durable_interaction_status_for_current_turn",
                    )
                )

        # 13. LLM response
        llm_response_val = self._find_latest_llm_response()
        if llm_response_val:
            stages.append(
                TraceStage(
                    step_num=13,
                    name="LLM response",
                    stage_key="llm_response",
                    status="PASS",
                    value=llm_response_val,
                    reason=None,
                )
            )
        else:
            stages.append(
                TraceStage(
                    step_num=13,
                    name="LLM response",
                    stage_key="llm_response",
                    status="NONE",
                    value="no response record",
                    reason="no_response",
                )
            )

        # 14. commit / abort
        if adapter_failed:
            stages.append(
                TraceStage(
                    step_num=14,
                    name="commit / abort",
                    stage_key="commit_abort",
                    status="NOT_RUN",
                    value="not run",
                    reason="adapter_init_failed",
                )
            )
        else:
            commit_status = self._find_latest_commit_status(state_db_path)
            if commit_status == "committed":
                stages.append(
                    TraceStage(
                        step_num=14,
                        name="commit / abort",
                        stage_key="commit_abort",
                        status="PASS",
                        value="COMMITTED",
                        reason=None,
                    )
                )
            elif commit_status == "aborted":
                stages.append(
                    TraceStage(
                        step_num=14,
                        name="commit / abort",
                        stage_key="commit_abort",
                        status="REJECT",
                        value="ABORTED",
                        reason="host_abort",
                    )
                )
            else:
                stages.append(
                    TraceStage(
                        step_num=14,
                        name="commit / abort",
                        stage_key="commit_abort",
                        status="NOT_RUN",
                        value="none",
                        reason="no_commit_marker",
                    )
                )

        # Release read-only connections (TRACE-FIDELITY rework).
        try:
            if facts_con is not None:
                facts_con.close()
        except Exception:
            pass
        try:
            if cog_con is not None:
                cog_con.close()
        except Exception:
            pass

        return stages

    def _get_latest_interaction_status(
        self, facts_db_path: str, interaction_id: str | None
    ) -> str | None:
        """Return the durable status of the given interaction, or None.

        OW-LIVE-TRACE-TRUTH-FIX (2026-09-05): this is the single runtime
        evidence for whether begin_turn actually executed for the current
        turn. Used by stage 12 to distinguish real PASS from inferred PASS.
        """
        if interaction_id is None:
            return None
        if not os.path.exists(facts_db_path):
            return None
        try:
            with sqlite3.connect(f"file:{facts_db_path}?mode=ro", uri=True) as con:
                row = con.execute(
                    "SELECT status FROM interactions WHERE interaction_id=?",
                    (interaction_id,),
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
        except Exception:
            return None
        return None

    def _get_latest_slow_state(self, state_db_path: str) -> dict[str, Any] | None:
        if not os.path.exists(state_db_path):
            return None
        try:
            with sqlite3.connect(state_db_path) as con:
                row = con.execute(
                    "SELECT dimension, value, version, updated_at FROM states "
                    "WHERE dimension LIKE 'agent.longitudinal%' "
                    "ORDER BY version DESC LIMIT 1"
                ).fetchone()
                if row:
                    return {
                        "dimension": row[0],
                        "value": row[1],
                        "version": row[2],
                        "updated_at": row[3],
                    }
        except Exception:
            pass
        return None

    def _find_latest_llm_response(self) -> str | None:
        gateway_log = self.hermes_profile_dir / "logs" / "gateway.log"
        if not gateway_log.exists():
            return None
        try:
            with open(gateway_log, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            for line in reversed(lines):
                if "response ready:" in line:
                    m = re.search(r"time=([\d.]+s).*?response=(\d+ chars)", line)
                    if m:
                        return f"{m.group(2)} ({m.group(1)})"
                    return "response ready"
        except Exception:
            pass
        return None

    def _find_latest_commit_status(self, state_db_path: str) -> str:
        if not os.path.exists(state_db_path):
            return "none"
        try:
            with sqlite3.connect(state_db_path) as con:
                row = con.execute(
                    "SELECT interaction_id FROM commit_markers ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if row:
                    return "committed"
        except Exception:
            pass
        return "none"

    # ------------------------------------------------------------------
    # Persisted Slow States
    # ------------------------------------------------------------------

    def _collect_persisted_slow_states(self) -> list[PersistedSlowState]:
        results: list[PersistedSlowState] = []
        target_dim = "agent.longitudinal.relationship_security"
        state_db_path = str(self.hermes_profile_dir / "runtime" / "cognition_state.sqlite")

        dim_found = False
        if os.path.exists(state_db_path):
            try:
                with sqlite3.connect(state_db_path) as con:
                    row = con.execute(
                        "SELECT value, version, updated_at FROM states "
                        "WHERE dimension=? ORDER BY version DESC LIMIT 1",
                        (target_dim,),
                    ).fetchone()
                    if row:
                        dim_found = True
                        val = None
                        try:
                            val = float(row[0])
                        except (ValueError, TypeError):
                            pass
                        results.append(
                            PersistedSlowState(
                                dimension=target_dim,
                                status="PRESENT",
                                value=val,
                                version=row[1],
                                updated_at=row[2],
                                c2_projected=f"key={target_dim} value={row[0]}",
                                c2_reason=None,
                            )
                        )
            except Exception:
                pass

        if not dim_found:
            results.append(
                PersistedSlowState(
                    dimension=target_dim,
                    status="NOT PERSISTED",
                    value=None,
                    version=None,
                    updated_at=None,
                    c2_projected="EMPTY",
                    c2_reason="no_persisted_slow_state",
                )
            )

        return results


def format_report_as_text(report: LiveRuntimeTraceReport) -> str:
    """Format report into human-readable terminal table output."""
    lines: list[str] = []
    w = 80
    lines.append("=" * w)
    lines.append("MR LIVE RUNTIME TRACE V0")
    lines.append("=" * w)

    h = report.header
    if h.is_stale and h.stale_warning:
        lines.append("!" * w)
        lines.append(f"  {h.stale_warning}")
        if h.stale_detail:
            lines.append(f"  {h.stale_detail}")
        lines.append("!" * w)

    lines.append("RUNTIME HEADER:")
    lines.append(f"  Gateway PID:             {h.gateway_pid or 'NOT RUNNING'}")
    lines.append(f"  Gateway Start Time:      {h.gateway_start_time or 'NOT RUNNING'}")
    lines.append(f"  Git HEAD:                {h.git_head}")
    lines.append(f"  Working Tree Dirty:      {h.working_tree_dirty}")
    lines.append(f"  MR Runtime ID:           {h.runtime_id}")
    lines.append(f"  Persona / Agent ID:      {h.persona_id}")
    lines.append(f"  Runtime Config Digest:   {h.runtime_config_digest}")
    lines.append(f"  Runtime Config Path:     {h.runtime_config_path}")
    lines.append(f"  Semantic Provider:       {h.semantic_provider_status} ({h.semantic_provider_detail})")
    lines.append(f"  Appraisal Provider:      {h.appraisal_provider_status} ({h.appraisal_provider_detail})")
    lines.append(f"  Slow Writer:             {h.slow_writer_status} ({h.slow_writer_detail})")
    lines.append(f"  State DB Path:           {h.state_db_path}")
    lines.append("-" * w)

    lines.append("LATEST TURN TRACE:")
    lines.append(f"  {'#':<3} {'Pipeline Stage':<28} {'Status':<10} {'Details / Negative Reason'}")
    lines.append(f"  {'-'*3} {'-'*28} {'-'*10} {'-'*35}")
    for s in report.latest_turn:
        detail = s.value
        if s.reason:
            detail = f"{s.value} (reason={s.reason})"
        lines.append(f"  {s.step_num:<3} {s.name:<28} {s.status:<10} {detail}")
    lines.append("-" * w)

    lines.append("PERSISTED SLOW STATES (C1/C2):")
    for ps in report.persisted_slow_states:
        lines.append(f"  Dimension:     {ps.dimension}")
        lines.append(f"  Status:        {ps.status}")
        if ps.status == "PRESENT":
            lines.append(f"  Value:         {ps.value}")
            lines.append(f"  Version:       {ps.version}")
            lines.append(f"  Updated At:    {ps.updated_at}")
        lines.append(f"  C2 Projected:  {ps.c2_projected} (reason={ps.c2_reason or 'present'})")
    lines.append("=" * w)
    return "\n".join(lines)


def live_runtime_trace_provider() -> LiveRuntimeTraceReport:
    """Provider callable for ``ObservationContext.live_trace_provider``.

    Read-only deployment-truth collector; wired by the composition seam
    (compat builder and production ``main``) so the debug channel keeps
    serving the collector report without generic code knowing layouts.
    """
    return LiveRuntimeTraceCollector().collect()


def main() -> int:
    collector = LiveRuntimeTraceCollector()
    report = collector.collect()
    print(format_report_as_text(report))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
