"""MR Lab runtime lifecycle (MR-RUNTIME-03) — experimental infrastructure.

Lab is NOT a second MR:

    same MR Core (build_runtime_stack)
    + LAB RuntimeBinding (ADR-0020)
    + isolated storage namespace

Lifecycle: create → inspect → run/use → destroy.

Fork is DEFERRED: the repository has no authoritative snapshot/clone/
export-import primitive (audited in
docs/audits/MR_LAB_RUNTIME_LIFECYCLE_AUDIT.md §3). Copying live SQLite files
is not a snapshot and is deliberately not provided here. Production-derived
seeding therefore stays closed too; a lab runtime starts empty (or is seeded
synthetically by the experiment writing through normal MR paths).

This module lives at the composition/configuration layer. It introduces no
cognition semantics and never branches Core behavior on the environment.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mind_runtime.runtime_binding import (
    DEFAULT_LAB_ROOT,
    PRODUCTION_COMPAT_NAMESPACE,
    BindingManifestMismatchError,
    NamespaceIsolationError,
    RuntimeBinding,
    RuntimeEnvironment,
    StoragePaths,
    bind_storage,
    resolve_storage_paths,
    validate_storage_namespace,
)

if TYPE_CHECKING:
    from mind_runtime.contracts.telemetry import TelemetrySinkProtocol
    from mind_runtime.dynamics.persona import PersonaProfile
    from mind_runtime.pipeline.orchestrator import TurnOrchestrator
    from mind_runtime.providers.clock import Clock

#: The lab's consuming-Agent identity (ADR-0020 §1: "who is using this MR").
LAB_AGENT_ID = "mr-lab"

__all__ = [
    "LAB_AGENT_ID",
    "LabDestroyRefused",
    "LabRuntime",
    "LabRuntimeError",
    "LabRuntimeInfo",
    "LabRuntimeSpec",
    "create_lab_runtime",
    "destroy_lab_runtime",
    "inspect_lab_runtime",
]


class LabRuntimeError(RuntimeError):
    """A lab runtime lifecycle violation."""


class LabDestroyRefused(LabRuntimeError):
    """Destroy refused by a lab-safety guard (ADR-0020 isolation)."""


class _UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class LabRuntimeSpec:
    """Explicit specification of one disposable lab runtime.

    ``persona_id`` and ``storage_namespace`` are mandatory (no defaults —
    fail closed). ``runtime_id`` defaults deterministically to
    ``lab-<storage_namespace>`` (no session ids, safe for parallel
    experiments). The namespace is an experiment label, never a persona
    identity.
    """

    persona_id: str
    storage_namespace: str
    runtime_id: str | None = None
    agent_id: str = LAB_AGENT_ID
    persona: PersonaProfile | None = None
    clock: Clock | None = None
    telemetry_sink: TelemetrySinkProtocol | None = None

    def __post_init__(self) -> None:
        validate_storage_namespace(self.storage_namespace)
        if self.storage_namespace == PRODUCTION_COMPAT_NAMESPACE:
            raise NamespaceIsolationError(
                "a LAB runtime may never use the production namespace "
                f"{PRODUCTION_COMPAT_NAMESPACE!r}"
            )
        if self.runtime_id is not None and not self.runtime_id.strip():
            raise ValueError("runtime_id must be non-empty when provided")

    def to_binding(self) -> RuntimeBinding:
        return RuntimeBinding(
            persona_id=self.persona_id,
            agent_id=self.agent_id,
            runtime_id=self.runtime_id or f"lab-{self.storage_namespace}",
            storage_namespace=self.storage_namespace,
            environment=RuntimeEnvironment.LAB,
        )


@dataclass(frozen=True)
class LabRuntimeInfo:
    """Read-only inspection of a lab runtime's identity and durable state."""

    environment: str
    persona_id: str
    agent_id: str
    runtime_id: str
    storage_namespace: str
    root: Path
    facts_db: Path
    state_db: Path
    namespace_present: bool
    manifest_present: bool
    manifest_matches_binding: bool
    facts_db_present: bool
    state_db_present: bool
    state_count: int
    transition_count: int
    dimensions: tuple[str, ...]


def inspect_lab_runtime(
    binding: RuntimeBinding,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LabRuntimeInfo:
    """Inspect identity, storage paths, existence, and durable-state presence.

    Reuses the ADR-0020 resolution guards and the existing
    ``SqliteStateBackend`` read APIs — no second canonical interpretation.
    """
    from mind_runtime.state.persistence import SqliteStateBackend
    paths = resolve_storage_paths(
        binding, production_root=production_root, lab_root=lab_root
    )
    manifest = paths.binding_manifest
    manifest_present = manifest.exists()
    manifest_matches = False
    if manifest_present:
        try:
            manifest_matches = (
                json.loads(manifest.read_text(encoding="utf-8"))
                == binding.manifest_identity()
            )
        except (OSError, ValueError):
            manifest_matches = False

    state_count = 0
    transition_count = 0
    dimensions: tuple[str, ...] = ()
    if paths.state_db.exists():
        backend = SqliteStateBackend(paths.state_db)
        try:
            states = backend.load_states()
            transitions = backend.load_transitions()
        finally:
            backend.close()
        state_count = len(states)
        transition_count = len(transitions)
        dimensions = tuple(sorted({state.dimension for state in states}))

    return LabRuntimeInfo(
        environment=binding.environment.value,
        persona_id=binding.persona_id,
        agent_id=binding.agent_id,
        runtime_id=binding.runtime_id,
        storage_namespace=binding.storage_namespace,
        root=paths.root,
        facts_db=paths.facts_db,
        state_db=paths.state_db,
        namespace_present=paths.root.exists(),
        manifest_present=manifest_present,
        manifest_matches_binding=manifest_matches,
        facts_db_present=paths.facts_db.exists(),
        state_db_present=paths.state_db.exists(),
        state_count=state_count,
        transition_count=transition_count,
        dimensions=dimensions,
    )


class LabRuntime:
    """A live lab runtime handle: binding + storage paths + one MR Core stack.

    The handle owns nothing semantic: the orchestrator IS the production
    ``TurnOrchestrator`` built by ``build_runtime_stack``. ``close()`` releases
    the durable connections (required before filesystem removal on Windows);
    ``destroy()`` closes and then removes ONLY this binding's namespace, after
    re-verifying every lab-safety guard.
    """

    def __init__(
        self,
        *,
        binding: RuntimeBinding,
        storage_paths: StoragePaths,
        lab_root: Path,
        orchestrator: TurnOrchestrator,
    ) -> None:
        self._binding = binding
        self._storage_paths = storage_paths
        self._lab_root = lab_root
        self._orchestrator = orchestrator
        self._closed = False

    @property
    def binding(self) -> RuntimeBinding:
        return self._binding

    @property
    def storage_paths(self) -> StoragePaths:
        return self._storage_paths

    @property
    def orchestrator(self) -> TurnOrchestrator:
        return self._orchestrator

    def inspect(self) -> LabRuntimeInfo:
        return inspect_lab_runtime(self._binding, lab_root=self._lab_root)

    def close(self) -> None:
        """Release the stack's durable connections. Idempotent."""
        if self._closed:
            return
        self._closed = True
        orchestrator = self._orchestrator
        # The durable backends are constructed inside build_runtime_stack and
        # held by the orchestrator; close each one that carries a connection.
        state_backend = getattr(orchestrator, "_state_backend", None)
        if state_backend is not None and hasattr(state_backend, "close"):
            state_backend.close()
        marker_store = getattr(orchestrator, "commit_marker_store", None)
        if marker_store is not None and hasattr(marker_store, "close"):
            marker_store.close()
        fact_service = getattr(orchestrator, "fact_ingest", None)
        fact_backend = getattr(fact_service, "_backend", None)
        if fact_backend is not None and hasattr(fact_backend, "close"):
            fact_backend.close()

    def destroy(self) -> None:
        """Close, then remove this binding's namespace (LAB-only, guarded)."""
        self.close()
        destroy_lab_runtime(self._binding, lab_root=self._lab_root)

    def __enter__(self) -> LabRuntime:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def create_lab_runtime(
    spec: LabRuntimeSpec,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> LabRuntime:
    """Create (or reconnect to) one lab runtime over the real MR Core.

    Creating with the same spec twice is a restart/reconnect, not a fork: the
    binding manifest is re-verified and the durable namespace is reloaded.
    """
    from mind_runtime.shadow.runtime_loop import build_runtime_stack

    binding = spec.to_binding()
    persona_id = getattr(spec.persona, "persona_id", None)
    if spec.persona is not None and persona_id != binding.persona_id:
        raise LabRuntimeError(
            f"spec.persona ({persona_id!r}) does not match spec.persona_id "
            f"({binding.persona_id!r})"
        )

    resolved_lab_root = Path(lab_root) if lab_root is not None else DEFAULT_LAB_ROOT
    paths = bind_storage(
        binding, production_root=production_root, lab_root=resolved_lab_root
    )
    clock = spec.clock if spec.clock is not None else _UtcClock()
    orchestrator, _bridge = build_runtime_stack(
        clock=clock,
        facts_db=paths.facts_db,
        state_db=paths.state_db,
        origin_runtime_id=binding.runtime_id,
        user_id="user",
        persona=spec.persona,
        telemetry_sink=spec.telemetry_sink,
    )
    return LabRuntime(
        binding=binding,
        storage_paths=paths,
        lab_root=resolved_lab_root,
        orchestrator=orchestrator,
    )


def destroy_lab_runtime(
    binding: RuntimeBinding,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> None:
    """Destroy a lab runtime's namespace. Hard-guarded, fail-closed.

    Guards (in order):
      1. only LAB bindings may be destroyed (never production);
      2. ADR-0020 resolution guards: production namespace refused, production
         root overlap refused (structural path disjointness, never a string
         contains-check);
      3. the target must be a strict namespace directory under the lab root;
      4. the binding manifest must exist and match this binding exactly.
    """
    if binding.environment is not RuntimeEnvironment.LAB:
        raise LabDestroyRefused(
            "destroy is LAB-only; binding environment is "
            f"{binding.environment.value!r}"
        )
    paths = resolve_storage_paths(
        binding, production_root=production_root, lab_root=lab_root
    )
    resolved_lab_root = (
        Path(lab_root) if lab_root is not None else DEFAULT_LAB_ROOT
    ).resolve()
    resolved_root = paths.root.resolve()
    if resolved_lab_root not in resolved_root.parents:
        raise LabDestroyRefused(
            f"refusing to destroy {resolved_root}: it is not a namespace "
            f"directory strictly under the lab root {resolved_lab_root}"
        )
    manifest = paths.binding_manifest
    if not manifest.exists():
        raise BindingManifestMismatchError(
            f"namespace {binding.storage_namespace!r} has no binding manifest; "
            "refusing to destroy an unclaimed directory"
        )
    try:
        existing = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingManifestMismatchError(
            f"unreadable binding manifest {manifest}: {exc}"
        ) from exc
    if existing != binding.manifest_identity():
        raise BindingManifestMismatchError(
            f"namespace {binding.storage_namespace!r} is owned by a different "
            f"binding (manifest={existing}, binding={binding.manifest_identity()}); "
            "refusing to destroy"
        )
    shutil.rmtree(paths.root)
