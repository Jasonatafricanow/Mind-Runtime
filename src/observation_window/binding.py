"""OW consumer-side binding context (OW-MULTI-AGENT-BINDING-PHASE01-V1).

Phase 0/1: Observation Window observes exactly ONE authoritative
RuntimeBinding. This module is the generic OW binding seam:

- ``binding_scope_key``            internal cache/source isolation token
- ``StateSurface``                 authoritative dimension descriptor
- ``TelemetrySource``              binding-scoped observation_trace handle
- ``AssistantMessageSource``       binding-scoped durable-message handle
- ``RuntimeStatusProjection``      normalized, display-safe readiness
- ``RuntimeStatusProvider``        port (the compat adapter implements it
                                    over its readiness artifact)
- ``ResolvedObservationBinding``   resolved binding context
- ``BindingResolver``              binding reference → resolved context
- ``SingleBindingRegistryAdapter`` wraps the ONE upstream production
                                    discovery (no scanning, no public id)
- ``CausalTraceStore``             binding-scoped causal cache

HARD BOUNDARIES (Phase 0/1): no public binding_id, no selector, no
``?runtime=``, no scoped API, no registry enumeration. Internal tokens
never leave the process. Deployment path literals live only in the
explicitly named compatibility adapter module (``binding_xiyue``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from mind_runtime.binding_registry import (
    BindingDescriptor,
    BindingRegistryError,
    BindingRegistryReader,
    NoDefaultReason,
    RegistryFailureCode,
)
from mind_runtime.runtime_binding import (
    MR_RUNTIME_BINDING_ENV,
    RuntimeBinding,
    RuntimeBindingError,
    RuntimeEnvironment,
    bind_storage,
    discover_production_binding,
    load_binding_reference,
    resolve_storage_paths,
)

__all__ = [
    "BindingScopeError",
    "binding_scope_key",
    "StateSurface",
    "TelemetrySource",
    "AssistantMessageSource",
    "RuntimeStatusProjection",
    "RuntimeStatusProvider",
    "ResolvedObservationBinding",
    "ObservationContext",
    "BindingResolver",
    "SingleBindingRegistryAdapter",
    "CausalTraceStore",
    "ScopedBindingError",
    "ScopedObservationBinding",
    "ObservationBindingResolver",
    "ProductionObservationBindingResolver",
    "ObservationBindingCatalog",
    "bind_storage",
]


class BindingScopeError(RuntimeBindingError):
    """OW binding-scope composition failure (fail-closed, never guessed)."""


# ---------------------------------------------------------------------------
# Internal scope token (never public: not in URLs, APIs, or bookmarks)
# ---------------------------------------------------------------------------


def binding_scope_key(binding: RuntimeBinding) -> str:
    """Process-internal isolation token for one binding.

    Deliberately NOT named binding_id: this is not a public identity and
    carries no upstream authority. Its only job is cache/source isolation
    inside the OW process.
    """
    return f"{binding.environment.value.lower()}:{binding.storage_namespace}"


# ---------------------------------------------------------------------------
# State surface descriptor (canonical keys / membership / ordering ONLY)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateSurface:
    """Authoritative state-surface membership declared by the binding.

    Canonical keys and ordering only — no localized display strings.
    Product UI renders exactly these members via the display projection
    (``OWDisplay.displayDimension``); unknown keys fail safe to raw.
    """

    fast_dimensions: tuple[str, ...] = ()
    slow_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for group in (self.fast_dimensions, self.slow_dimensions):
            for key in group:
                if not isinstance(key, str) or not key.strip():
                    raise BindingScopeError(
                        "StateSurface dimensions must be non-empty canonical keys"
                    )
        if len(set(self.fast_dimensions)) != len(self.fast_dimensions):
            raise BindingScopeError("StateSurface fast_dimensions must be unique")
        if len(set(self.slow_dimensions)) != len(self.slow_dimensions):
            raise BindingScopeError("StateSurface slow_dimensions must be unique")

    def to_payload(self) -> dict[str, list[str]]:
        return {
            "fast_dimensions": list(self.fast_dimensions),
            "slow_dimensions": list(self.slow_dimensions),
        }


# ---------------------------------------------------------------------------
# Binding-scoped source handles (physical paths are backend-private)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetrySource:
    """Binding-scoped observer telemetry handle.

    ``db_path is None`` means the capability is absent for this binding —
    a component-level degradation (TELEMETRY_UNAVAILABLE), never an
    empty-trace fabrication.
    """

    db_path: Path | None = None


@dataclass(frozen=True)
class AssistantMessageSource:
    """Binding-scoped durable assistant-message handle.

    Exact-linkage matching stays in the causal trace builder (frozen
    truthfulness semantics); this handle only removes global path
    discovery from generic code. ``db_path is None`` = capability absent
    or unreachable (HOST_MESSAGE_UNAVAILABLE degradation).
    """

    db_path: Path | None = None


# ---------------------------------------------------------------------------
# Normalized runtime status (display-safe; raw detail stays debug-only)
# ---------------------------------------------------------------------------

_STATUS_VALUES = ("READY", "DEGRADED", "OFFLINE", "UNAVAILABLE", "UNKNOWN")
#: Whitelisted scalar debug fields (rendered only in the debug channel).
_DETAIL_KEYS = ("gateway_pid", "epoch_id", "runtime_ready_at")


@dataclass(frozen=True)
class RuntimeStatusProjection:
    """Normalized binding readiness (OW-MULTI-AGENT-BINDING-UX-V1 R2-3).

    No arbitrary provider payload passes through: ``detail`` is restricted
    to the whitelisted scalar keys and is rendered only in the debug
    channel of the runtime strip.
    """

    status: str
    summary_code: str
    observed_at: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _STATUS_VALUES:
            raise BindingScopeError(f"RuntimeStatusProjection.status {self.status!r} is not normalized")
        cleaned = {k: v for k, v in dict(self.detail).items() if k in _DETAIL_KEYS and v is not None}
        object.__setattr__(self, "detail", cleaned)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary_code": self.summary_code,
            "observed_at": self.observed_at,
            "detail": dict(self.detail),
        }


@runtime_checkable
class RuntimeStatusProvider(Protocol):
    """Binding-scoped readiness projection port.

    The compatibility adapter implements this over its readiness
    artifact; future runtimes use any mechanism. Generic OW code never
    reads readiness files itself.
    """

    def projection(self) -> RuntimeStatusProjection: ...


# ---------------------------------------------------------------------------
# Resolved binding context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedObservationBinding:
    """One authoritative binding resolved into OW source handles."""

    runtime_binding: RuntimeBinding
    binding_scope_key: str
    state_surface: StateSurface
    facts_db: Path
    state_db: Path
    telemetry_source: TelemetrySource
    assistant_message_source: AssistantMessageSource
    runtime_status_provider: RuntimeStatusProvider
    runtime_dir: Path
    #: Optional deployment-flavored runtime detail (whitelisted fields only);
    #: the compat adapter supplies it from its live collector, synthetic
    #: contexts omit it.
    runtime_detail_provider: Any = None


# ---------------------------------------------------------------------------
# Generic resolver
# ---------------------------------------------------------------------------


class BindingResolver:
    """Resolve an authoritative RuntimeBinding into an OW binding context.

    This is the ONLY generic seam where a binding becomes physical source
    handles. Physical layout knowledge (which files live beside which)
    stays in the binding-specific adapter that supplies the optional
    handles; the resolver itself only knows the upstream namespace
    resolution contract (``resolve_storage_paths``).
    """

    def resolve(
        self,
        binding: RuntimeBinding,
        *,
        runtime_dir: Path | str | None = None,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
        state_surface: StateSurface = StateSurface(),
        telemetry_source: TelemetrySource | None = None,
        assistant_message_source: AssistantMessageSource | None = None,
        runtime_status_provider: RuntimeStatusProvider | None = None,
    ) -> ResolvedObservationBinding:
        paths = resolve_storage_paths(
            binding, production_root=production_root, lab_root=lab_root
        )
        runtime_dir_path = (
            Path(runtime_dir) if runtime_dir is not None else paths.root
        )
        self._verify_manifest_if_present(paths.binding_manifest, binding)
        return ResolvedObservationBinding(
            runtime_binding=binding,
            binding_scope_key=binding_scope_key(binding),
            state_surface=state_surface,
            facts_db=paths.facts_db,
            state_db=paths.state_db,
            telemetry_source=telemetry_source or TelemetrySource(db_path=None),
            assistant_message_source=assistant_message_source
            or AssistantMessageSource(db_path=None),
            runtime_status_provider=runtime_status_provider
            or _UnknownRuntimeStatusProvider(),
            runtime_dir=runtime_dir_path,
        )

    @staticmethod
    def _verify_manifest_if_present(manifest_path: Path, binding: RuntimeBinding) -> None:
        """Read-only manifest verification (composition owns writing).

        Missing manifest = the runtime has not booted its composition seam
        yet; OW tolerates that (status will read OFFLINE). A PRESENT
        manifest claiming a different identity fails closed — OW must not
        observe a namespace owned by another binding.
        """
        if not manifest_path.exists():
            return
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BindingScopeError(
                f"unreadable binding manifest {manifest_path}: {exc}"
            ) from exc
        identity = binding.manifest_identity()
        differing = [
            field for field, value in identity.items() if existing.get(field) != value
        ]
        if differing:
            raise BindingScopeError(
                f"binding manifest mismatch at {manifest_path}; "
                f"differing identity fields: {differing}"
            )


class _UnknownRuntimeStatusProvider:
    def projection(self) -> RuntimeStatusProjection:
        return RuntimeStatusProjection(status="UNKNOWN", summary_code="UNKNOWN")


# ---------------------------------------------------------------------------
# Single-binding registry adapter (Phase 0 compatibility seam)
# ---------------------------------------------------------------------------


class SingleBindingRegistryAdapter:
    """Expose exactly ONE authoritative binding to OW.

    Consumes the existing upstream discovery chain — explicit reference
    (param or ``MR_RUNTIME_BINDING`` env) > ``binding.json`` restart
    manifest in the anchored runtime dir > explicit compat persona.
    Never scans directories, never invents a public identity, fails
    closed when production discovery cannot complete.

    This is NOT ``list_bindings()`` and must not evolve into one.
    """

    def __init__(
        self,
        *,
        runtime_dir: Path | str | None = None,
        persona_id: str | None = None,
        binding_ref: str | Path | None = None,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> None:
        self._production_root = production_root
        self._lab_root = lab_root
        anchor = Path(runtime_dir) if runtime_dir is not None else None

        ref = binding_ref if binding_ref is not None else os.environ.get(MR_RUNTIME_BINDING_ENV)
        if ref is not None:
            persona = persona_id or _persona_from_reference_file(ref)
            if not persona:
                raise BindingScopeError(
                    "binding reference requires a persona authority: supply "
                    "persona_id (the reference file carries no persona_id)"
                )
            self._binding = discover_production_binding(
                persona_id=persona, binding_ref=ref
            )
            return

        if anchor is not None:
            manifest = anchor / "binding.json"
            if manifest.exists():
                self._binding = _binding_from_manifest(manifest)
                return

        if persona_id:
            self._binding = discover_production_binding(persona_id=persona_id)
            return

        raise BindingScopeError(
            "production binding discovery failed closed: no binding reference, "
            "no binding.json in the anchored runtime dir, and no explicit "
            "persona authority. Supply persona_id / binding_ref (or write the "
            "binding manifest by booting the MR composition seam). "
            "OW will not guess a runtime identity."
        )

    @property
    def binding(self) -> RuntimeBinding:
        return self._binding


def _persona_from_reference_file(ref: str | Path) -> str | None:
    try:
        data = json.loads(Path(ref).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    persona = data.get("persona_id") if isinstance(data, dict) else None
    return persona if isinstance(persona, str) and persona.strip() else None


def _binding_from_manifest(manifest_path: Path) -> RuntimeBinding:
    """Reconstruct the authoritative binding from its restart manifest.

    The manifest is written by the upstream composition seam (ADR-0020 §3)
    and is an authority artifact — reading it is not directory scanning.
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingScopeError(
            f"unreadable binding manifest {manifest_path}: {exc}"
        ) from exc
    try:
        from mind_runtime.runtime_binding import RuntimeEnvironment

        return RuntimeBinding(
            persona_id=data["persona_id"],
            agent_id=data["agent_id"],
            runtime_id=data["runtime_id"],
            storage_namespace=data["storage_namespace"],
            environment=RuntimeEnvironment(data["environment"]),
        )
    except (KeyError, RuntimeBindingError, ValueError) as exc:
        raise BindingScopeError(
            f"invalid binding manifest {manifest_path}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Binding-scoped causal cache
# ---------------------------------------------------------------------------


class CausalTraceStore:
    """Binding-scoped causal trace cache.

    Identity is (binding_scope_key, interaction_id) — interaction ids are
    NOT assumed globally unique across bindings. One process may hold
    multiple scopes (tests construct two); a scope never serves another's
    entry.
    """

    def __init__(self, *, max_entries: int = 128) -> None:
        self._max_entries = max_entries
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, scope: str, interaction_id: str) -> dict[str, Any] | None:
        return self._entries.get((scope, interaction_id))

    def put(
        self, scope: str, interaction_id: str, entry: dict[str, Any]
    ) -> None:
        while len(self._entries) >= self._max_entries:
            first_key = next(iter(self._entries))
            del self._entries[first_key]
        self._entries[(scope, interaction_id)] = entry

    def replace_field(
        self, scope: str, interaction_id: str, field_name: str, value: Any
    ) -> bool:
        entry = self._entries.get((scope, interaction_id))
        if entry is None:
            return False
        entry[field_name] = value
        return True

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Router-facing context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservationContext:
    """Everything the generic OW router needs to serve ONE binding.

    Carries no upstream identity authority: ``binding_scope_key`` is the
    process-internal isolation token (never public), and the surface is the
    authoritative descriptor projected by the binding adapter.
    """

    binding_scope_key: str
    state_surface: StateSurface
    telemetry_source: TelemetrySource
    assistant_message_source: AssistantMessageSource
    runtime_status_provider: RuntimeStatusProvider
    facts_db: Path | None = None
    state_db: Path | None = None
    causal_trace_store: CausalTraceStore = field(default_factory=CausalTraceStore)
    #: Optional whitelisted deployment detail (compat adapter live collector); debug channel only.
    runtime_detail_provider: Any = None
    #: Optional binding-scoped live-trace data provider (debug page).
    live_trace_provider: Any = None

    @staticmethod
    def from_resolved(
        resolved: ResolvedObservationBinding,
        *,
        causal_trace_store: CausalTraceStore | None = None,
        live_trace_provider: Any = None,
    ) -> "ObservationContext":
        return ObservationContext(
            binding_scope_key=resolved.binding_scope_key,
            state_surface=resolved.state_surface,
            telemetry_source=resolved.telemetry_source,
            assistant_message_source=resolved.assistant_message_source,
            runtime_status_provider=resolved.runtime_status_provider,
            facts_db=resolved.facts_db,
            state_db=resolved.state_db,
            causal_trace_store=causal_trace_store or CausalTraceStore(),
            runtime_detail_provider=resolved.runtime_detail_provider,
            live_trace_provider=live_trace_provider,
        )


# ---------------------------------------------------------------------------
# Phase 2: Scoped Binding Error & Narrow Observation Catalog
# ---------------------------------------------------------------------------


class ScopedBindingError(RuntimeBindingError):
    """Scoped binding failure mapped to explicit HTTP status codes."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail or message
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True)
class ScopedObservationBinding:
    """Request-local resolved binding and its observation services."""

    binding_id: str
    resolved_binding: ResolvedObservationBinding
    context: ObservationContext
    sources: Any

    @property
    def binding_scope_key(self) -> str:
        return self.resolved_binding.binding_scope_key


@runtime_checkable
class ObservationBindingResolver(Protocol):
    """Port for resolving a RuntimeBinding into a ResolvedObservationBinding."""

    def resolve(self, binding: RuntimeBinding) -> ResolvedObservationBinding: ...


class ProductionObservationBindingResolver:
    """Production resolver implementing ObservationBindingResolver protocol.

    Resolves a production RuntimeBinding into ResolvedObservationBinding.
    For the compatibility namespace, delegates to build_xiyue_resolved_binding.
    For other bindings, resolves canonical paths and default status/sources.
    """

    def __init__(
        self,
        *,
        production_root: Path | str | None = None,
    ) -> None:
        self._production_root = Path(production_root) if production_root is not None else None

    def resolve(self, binding: RuntimeBinding) -> ResolvedObservationBinding:
        if binding.environment != RuntimeEnvironment.PRODUCTION:
            raise ScopedBindingError(
                404,
                "UNKNOWN_BINDING",
                f"binding {binding.storage_namespace!r} is not a production binding",
            )
        from mind_runtime.runtime_binding import PRODUCTION_COMPAT_NAMESPACE

        if binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE:
            from observation_window.binding_xiyue import build_xiyue_resolved_binding

            return build_xiyue_resolved_binding(
                binding,
                runtime_dir=self._production_root,
                with_live_detail=True,
            )
        resolver = BindingResolver()
        return resolver.resolve(
            binding,
            production_root=self._production_root,
        )


class ObservationBindingCatalog:
    """Narrow catalog for binding-scoped Observation Window orchestration.

    Owns ONLY orchestration:
      binding_id -> registry resolution -> binding resolver -> scoped OW binding
    """

    def __init__(
        self,
        *,
        reader: BindingRegistryReader,
        environment: RuntimeEnvironment,
        resolver: ObservationBindingResolver,
        causal_trace_store: CausalTraceStore | None = None,
        sources_factory: Any | None = None,
    ) -> None:
        self._reader = reader
        self._environment = environment
        self._resolver = resolver
        self._causal_store = causal_trace_store or CausalTraceStore()
        self._sources_factory = sources_factory

    @property
    def environment(self) -> RuntimeEnvironment:
        return self._environment

    def list_descriptors(self) -> tuple[BindingDescriptor, ...]:
        """List binding descriptors admitted to current environment."""
        try:
            return self._reader.list_bindings(environment=self._environment)
        except BindingRegistryError as exc:
            raise ScopedBindingError(
                503,
                "BINDING_REGISTRY_UNAVAILABLE",
                f"failed listing binding registry: {exc}",
            ) from exc

    def default_descriptor(self) -> BindingDescriptor:
        """Read the explicit environment-scoped default descriptor.

        This is deliberately a descriptor-only operation: page aliases use it
        to build a canonical URL without opening any physical runtime source.
        No default is inferred from catalog cardinality or descriptor fields.
        """
        try:
            result = self._reader.default_binding(environment=self._environment)
        except BindingRegistryError as exc:
            raise ScopedBindingError(
                503,
                "BINDING_REGISTRY_UNAVAILABLE",
                f"binding registry error: {exc}",
            ) from exc

        if result.status == "DEFAULT_BINDING" and result.descriptor is not None:
            return result.descriptor

        if result.reason is NoDefaultReason.REGISTRY_EMPTY:
            raise ScopedBindingError(
                503,
                "NO_BINDINGS_AVAILABLE",
                "no PRODUCTION bindings are registered",
            )
        if result.reason is NoDefaultReason.NO_DEFAULT_DECLARED:
            raise ScopedBindingError(
                409,
                "DEFAULT_BINDING_UNDECLARED",
                "no explicit default binding is declared for this environment",
            )
        raise ScopedBindingError(
            503,
            "BINDING_REGISTRY_UNAVAILABLE",
            "binding registry returned an invalid default result",
        )

    def resolve_default(self) -> ScopedObservationBinding:
        """Resolve the explicit default through the normal scoped read path."""
        return self.resolve(self.default_descriptor().binding_id)

    def resolve(self, binding_id: str) -> ScopedObservationBinding:
        """Resolve a binding_id exactly once for a scoped request.

        Fails closed with typed ScopedBindingError.
        """
        try:
            binding = self._reader.resolve_binding(
                binding_id, environment=self._environment
            )
        except BindingRegistryError as exc:
            if exc.code in (
                RegistryFailureCode.BINDING_ID_UNKNOWN,
                RegistryFailureCode.ADMISSION_DENIED,
            ):
                raise ScopedBindingError(
                    404,
                    "UNKNOWN_BINDING",
                    f"binding {binding_id!r} not found",
                ) from exc
            raise ScopedBindingError(
                503,
                "BINDING_REGISTRY_UNAVAILABLE",
                f"binding registry error: {exc}",
            ) from exc

        try:
            resolved = self._resolver.resolve(binding)
        except Exception as exc:
            raise ScopedBindingError(
                503,
                "BINDING_UNAVAILABLE",
                f"failed resolving binding {binding_id!r}: {exc}",
            ) from exc

        # Check required canonical physical sources
        if not resolved.state_db.is_file() or not resolved.facts_db.is_file():
            raise ScopedBindingError(
                503,
                "BINDING_UNAVAILABLE",
                f"required canonical sources missing for binding {binding_id!r}",
            )

        try:
            if self._sources_factory is not None:
                sources = self._sources_factory(resolved)
            else:
                from mind_runtime.facts.persistence import SqliteFactBackend
                from mind_runtime.state.persistence import (
                    SqliteCommitMarkerStore,
                    SqliteStateBackend,
                )
                from observation_window.live_trace import OWLiveTraceSource
                from observation_window.web import LiveTraceCache
                from observation_window.web.wiring import (
                    OrchestratorLiveTraceSink,
                    build_dashboard_data_sources,
                )

                state_be = SqliteStateBackend(str(resolved.state_db))
                fact_be = SqliteFactBackend(str(resolved.facts_db))
                cm_be = SqliteCommitMarkerStore(str(resolved.state_db))
                cache = LiveTraceCache(maxlen=200)
                live_source = OWLiveTraceSource()
                sink = OrchestratorLiveTraceSink(cache=cache, live_source=live_source)
                sources = build_dashboard_data_sources(
                    state_backend=state_be,
                    fact_backend=fact_be,
                    commit_markers=cm_be,
                    sink=sink,
                    cache=cache,
                )
        except Exception as exc:
            raise ScopedBindingError(
                503,
                "BINDING_UNAVAILABLE",
                f"cannot open canonical sources for binding {binding_id!r}: {exc}",
            ) from exc

        context = ObservationContext.from_resolved(
            resolved,
            causal_trace_store=self._causal_store,
            live_trace_provider=getattr(resolved, "live_trace_provider", None),
        )

        return ScopedObservationBinding(
            binding_id=binding_id,
            resolved_binding=resolved,
            context=context,
            sources=sources,
        )

