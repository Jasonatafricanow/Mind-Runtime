"""Xiyue compatibility binding adapter (explicitly named, OW-MULTI-AGENT-BINDING-PHASE01-V1).

This module is the ONLY place in generic Observation Window code where
Xiyue physical layout knowledge is allowed:

- ``~/.hermes/profiles/xiyue/runtime``  → state/facts/telemetry/readiness
- ``~/.hermes/profiles/xiyue/state.db`` → Hermes durable assistant messages
- ``readiness.json``                    → RuntimeStatusProvider implementation
- the certified production state surface (4 fast + 1 slow canonical keys),
  explicitly DECLARED here as the Xiyue binding's descriptor — never as
  universal OW ontology.

Generic OW code (routers, pages, caches, causal builders) must import the
generic seams from ``observation_window.binding`` and receive handles from
the resolved context, never these literals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mind_runtime.runtime_binding import RuntimeBinding, RuntimeEnvironment

from observation_window.binding import (
    AssistantMessageSource,
    BindingScopeError,
    BindingResolver,
    RuntimeStatusProjection,
    SingleBindingRegistryAdapter,
    StateSurface,
    TelemetrySource,
)

__all__ = [
    "XIYUE_STATE_SURFACE",
    "XiyueReadinessStatusProvider",
    "resolve_xiyue_observation_binding",
]

# ---------------------------------------------------------------------------
# Xiyue physical layout (compatibility facts, frozen by the deployment)
# ---------------------------------------------------------------------------

XIYUE_PROFILE_DIR = Path.home() / ".hermes" / "profiles" / "xiyue"
XIYUE_RUNTIME_DIR = XIYUE_PROFILE_DIR / "runtime"
XIYUE_HERMES_DB = XIYUE_PROFILE_DIR / "state.db"

# ---------------------------------------------------------------------------
# Authoritative Xiyue state surface (canonical keys / membership / ordering;
# NO localized strings — display goes through the zh projection dictionary)
# ---------------------------------------------------------------------------

XIYUE_STATE_SURFACE = StateSurface(
    fast_dimensions=(
        "agent.affect.irritation",
        "agent.affect.anxiety",
        "agent.affect.excitement",
        "agent.affect.longing",
    ),
    slow_dimensions=("agent.longitudinal.relationship_security",),
)

_STATUS_OK = ("READY", "CORE_READY")
_STATUS_DEGRADED = ("DEGRADED", "CORE_DEGRADED")
_STATUS_OFFLINE = ("OFFLINE", "NOT_READY")
_STATUS_UNKNOWN = ("UNKNOWN", "UNKNOWN")


class XiyueReadinessStatusProvider:
    """RuntimeStatusProvider over the Xiyue readiness.json artifact.

    Generic OW receives only the normalized RuntimeStatusProjection; the
    raw readiness payload never passes through to product UI.
    """

    def __init__(self, readiness_path: Path | None) -> None:
        self._path = readiness_path

    def projection(self) -> RuntimeStatusProjection:
        if self._path is None or not self._path.exists():
            return RuntimeStatusProjection(*_STATUS_OFFLINE, observed_at=_now_iso())
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("readiness payload is not an object")
        except (OSError, ValueError):
            return RuntimeStatusProjection(*_STATUS_UNKNOWN, observed_at=_now_iso())

        detail = {
            "gateway_pid": data.get("gateway_pid"),
            "epoch_id": data.get("epoch_id"),
            "runtime_ready_at": data.get("runtime_ready_at"),
        }
        if data.get("core_ready") is True:
            status, summary = _STATUS_OK
        elif data.get("core_ready") is False:
            status, summary = _STATUS_DEGRADED
        else:
            status, summary = _STATUS_UNKNOWN
        return RuntimeStatusProjection(
            status=status,
            summary_code=summary,
            observed_at=_now_iso(self._path),
            detail=detail,
        )


def _now_iso(path: Path | None = None) -> str | None:
    if path is not None and path.exists():
        return datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _xiyue_runtime_detail_provider() -> dict[str, Any]:
    """Whitelisted deployment detail for /api/overview (semantic/appraisal/
    slow-writer statuses). Xiyue-specific by nature; debug channel only."""
    from observation_window.live_runtime_trace import LiveRuntimeTraceCollector

    try:
        report = LiveRuntimeTraceCollector().collect()
        header = report.header
        return {
            "semantic_status": header.semantic_provider_status,
            "appraisal_status": header.appraisal_provider_status,
            "slow_writer_status": header.slow_writer_status,
        }
    except Exception:
        return {
            "semantic_status": "UNKNOWN",
            "appraisal_status": "UNKNOWN",
            "slow_writer_status": "UNKNOWN",
        }


#: Compat persona default, mirroring the upstream production composition
#: root (``mind_runtime.host.xiyue_adapter.default_adapter``) — the ONLY
#: permitted default, and only inside this explicitly-named Xiyue adapter.
XIYUE_COMPAT_PERSONA_ID = "kayla_v0"


def resolve_xiyue_observation_binding(
    *,
    runtime_dir: Path | str | None = None,
    persona_id: str | None = None,
    binding_ref: str | Path | None = None,
) -> tuple[SingleBindingRegistryAdapter, Any]:
    """Resolve the ONE authoritative Xiyue production binding for OW.

    Returns ``(adapter, resolved)``. Discovery precedence lives in
    :class:`SingleBindingRegistryAdapter` (reference > binding.json >
    explicit persona, else fail-closed). The bundled ``RuntimeBinding`` may
    be handed to :meth:`BindingResolver.resolve` via the returned adapter.
    """
    anchor = Path(runtime_dir) if runtime_dir is not None else XIYUE_RUNTIME_DIR
    adapter = SingleBindingRegistryAdapter(
        runtime_dir=anchor,
        persona_id=persona_id or XIYUE_COMPAT_PERSONA_ID,
        binding_ref=binding_ref,
        production_root=anchor,
    )
    if adapter.binding.environment is not RuntimeEnvironment.PRODUCTION:
        # Production OW composition must never silently observe a LAB binding.
        raise BindingScopeError(
            f"Xiyue production composition requires a PRODUCTION binding; "
            f"anchored dir {anchor} declares "
            f"{adapter.binding.environment.value!r}"
        )
    return adapter, anchor


def build_xiyue_resolved_binding(
    binding: RuntimeBinding,
    *,
    runtime_dir: Path | str | None = None,
    with_live_detail: bool = True,
) -> Any:
    """Resolve a Xiyue binding into the OW binding context (Phase 0 seam)."""
    anchor = Path(runtime_dir) if runtime_dir is not None else XIYUE_RUNTIME_DIR
    resolver = BindingResolver()
    resolved = resolver.resolve(
        binding,
        runtime_dir=anchor,
        production_root=anchor,
        state_surface=XIYUE_STATE_SURFACE,
        telemetry_source=TelemetrySource(db_path=anchor / "observation_trace.sqlite"),
        assistant_message_source=AssistantMessageSource(db_path=XIYUE_HERMES_DB),
        runtime_status_provider=XiyueReadinessStatusProvider(
            anchor / "readiness.json"
        ),
    )
    if with_live_detail:
        object.__setattr__(
            resolved,
            "runtime_detail_provider",
            _xiyue_runtime_detail_provider,
        )
    return resolved
