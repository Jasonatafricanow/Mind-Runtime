"""RuntimeBinding — composition-level runtime identity + storage namespace.

ADR-0020 (MR-RUNTIME-01): one MR Core, many independent runtime consumers.

    MR Core + RuntimeBinding + StorageNamespace = one independently
    reconstructable MR runtime

The four identity dimensions and their authorities:

  * ``persona_id``     — WHO is being modeled. Authority: the existing
    ``PersonaProfile.persona_id`` (dynamics plane, manifest-sourced). The
    binding only carries the reference.
  * ``agent_id``       — WHO is consuming MR (deployment identity of the
    consuming Agent). Authority: this binding, supplied by the composition
    owner. Never wired into canonical ``Scope``.
  * ``runtime_id``     — WHICH logical runtime (durable sync identity).
    Authority: the existing ``origin_runtime_id`` / ``TurnOrchestrator``
    runtime_id; the binding supplies its value.
  * ``storage_namespace`` — WHERE durable state lives. Authority: this
    binding, resolved to one filesystem directory (one set of SQLite files)
    by :func:`resolve_storage_paths`.

Isolation is physical (separate files per namespace), never a WHERE-filter.
A LAB binding missing any identity dimension fails at construction and never
falls back to production storage. ``environment`` is composition-level only:
no code below the composition layer may branch on it (no ``is_lab`` fork of
Core semantics).

This module belongs to the composition/configuration layer. Binding fields
are forbidden from entering Canonical State, Evidence, C10 dimensions,
Memory items, EmotionalTransition, or Expression (ADR-0020 §4).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

DEFAULT_PRODUCTION_ROOT = Path.home() / ".hermes" / "profiles" / "xiyue" / "runtime"
DEFAULT_LAB_ROOT = Path.home() / ".mind-runtime" / "lab"

#: The only PRODUCTION namespace (ADR-0020 §2): maps to the pre-existing
#: production directory so the implicit old configuration becomes an explicit
#: binding with identical physical storage.
PRODUCTION_COMPAT_NAMESPACE = "production/xiyue"

MANIFEST_FILENAME = "binding.json"

_MANIFEST_FIELDS = (
    "environment",
    "persona_id",
    "agent_id",
    "runtime_id",
    "storage_namespace",
)

#: A namespace is a relative label of path-like segments, not a free path.
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class RuntimeBindingError(ValueError):
    """A RuntimeBinding violates the ADR-0020 identity contract."""


class NamespaceIsolationError(RuntimeBindingError):
    """A namespace resolution would cross the production/lab isolation boundary."""


class BindingManifestMismatchError(RuntimeBindingError):
    """A namespace is already owned by a different runtime binding."""


class RuntimeEnvironment(Enum):
    PRODUCTION = "production"
    LAB = "lab"


def validate_storage_namespace(namespace: str) -> None:
    if not isinstance(namespace, str) or not namespace.strip():
        raise RuntimeBindingError("storage_namespace must be a non-empty string")
    if "\\" in namespace or namespace.startswith("/"):
        raise RuntimeBindingError(
            f"storage_namespace must be a relative label, got {namespace!r}"
        )
    segments = namespace.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise RuntimeBindingError(
            f"storage_namespace segments must be non-empty and not '.'/'..': {namespace!r}"
        )
    if not _NAMESPACE_RE.match(namespace):
        raise RuntimeBindingError(
            f"storage_namespace may only contain [A-Za-z0-9._/-]: {namespace!r}"
        )


@dataclass(frozen=True)
class RuntimeBinding:
    """Composition-level binding of one MR runtime to its four identities.

    No field has a default: a missing identity dimension is a construction
    failure (ADR-0020 §1, fail-closed).
    """

    persona_id: str
    agent_id: str
    runtime_id: str
    storage_namespace: str
    environment: RuntimeEnvironment

    def __post_init__(self) -> None:
        for name in ("persona_id", "agent_id", "runtime_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeBindingError(
                    f"RuntimeBinding.{name} must be a non-empty string"
                )
        validate_storage_namespace(self.storage_namespace)
        if not isinstance(self.environment, RuntimeEnvironment):
            raise RuntimeBindingError(
                "RuntimeBinding.environment must be a RuntimeEnvironment"
            )

    def manifest_identity(self) -> dict[str, str]:
        return {
            "environment": self.environment.value,
            "persona_id": self.persona_id,
            "agent_id": self.agent_id,
            "runtime_id": self.runtime_id,
            "storage_namespace": self.storage_namespace,
        }


def production_binding(
    persona_id: str,
    *,
    agent_id: str = "hermes-xiyue",
    runtime_id: str = "xiyue",
) -> RuntimeBinding:
    """Production-compat binding (ADR-0020 §5).

    The ONLY place where default identity values are permitted, and only for
    §11 migration compatibility: the implicit old Xiyue configuration becomes
    the explicit production binding with identical physical storage.
    """
    return RuntimeBinding(
        persona_id=persona_id,
        agent_id=agent_id,
        runtime_id=runtime_id,
        storage_namespace=PRODUCTION_COMPAT_NAMESPACE,
        environment=RuntimeEnvironment.PRODUCTION,
    )


# ---------------------------------------------------------------------------
# Binding discovery (MR-RUNTIME-02): Hermes boot → RuntimeBinding resolution
# ---------------------------------------------------------------------------

#: Explicit binding reference file (single JSON binding). Discovery precedence:
#: explicit ``binding`` param > this env var > the ONE legacy compat default.
MR_RUNTIME_BINDING_ENV = "MR_RUNTIME_BINDING"

_ALLOWED_REFERENCE_FIELDS = frozenset(
    {"environment", "persona_id", "agent_id", "runtime_id", "storage_namespace"}
)


class BindingDiscoveryError(RuntimeBindingError):
    """Binding discovery is ambiguous, partial, environment-invalid, or conflicts
    with the PersonaProfile authority (MR-RUNTIME-02). Production bootstrap must
    reject it — never silently fall back to a different runtime."""


def _load_binding_object(
    data: object, *, persona_id: str
) -> RuntimeBinding:
    if not isinstance(data, dict):
        raise BindingDiscoveryError(
            f"binding reference must be a single JSON object, got {type(data).__name__}"
        )
    unknown = set(data) - _ALLOWED_REFERENCE_FIELDS
    if unknown:
        raise BindingDiscoveryError(
            f"unknown binding reference fields: {sorted(unknown)}"
        )
    missing = [
        field
        for field in ("agent_id", "runtime_id", "storage_namespace", "environment")
        if field not in data
    ]
    if missing:
        # §6.D: partial config is rejected — the only permitted default is the
        # no-reference legacy compat seam, never a partial-fill second fallback.
        raise BindingDiscoveryError(
            f"partial binding reference; missing {missing} (no partial defaults)"
        )
    env_value = data["environment"]
    if env_value != RuntimeEnvironment.PRODUCTION.value:
        raise BindingDiscoveryError(
            f"production bootstrap rejects environment={env_value!r}"
        )
    ref_persona = data.get("persona_id", persona_id)
    if ref_persona != persona_id:
        raise BindingDiscoveryError(
            f"binding reference persona_id {ref_persona!r} conflicts with the "
            f"PersonaProfile authority {persona_id!r}"
        )
    validate_storage_namespace(data["storage_namespace"])
    return RuntimeBinding(
        persona_id=ref_persona,
        agent_id=str(data["agent_id"]),
        runtime_id=str(data["runtime_id"]),
        storage_namespace=data["storage_namespace"],
        environment=RuntimeEnvironment.PRODUCTION,
    )


def load_binding_reference(path: str | Path, *, persona_id: str) -> RuntimeBinding:
    """Load ONE production binding from an explicit reference file.

    Fail-closed: unreadable, multi-candidate (ambiguous), empty, partial, or
    environment-invalid references all raise — nothing is "picked" or guessed.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingDiscoveryError(
            f"unreadable binding reference {path}: {exc}"
        ) from exc
    if isinstance(raw, list):
        if len(raw) != 1:
            raise BindingDiscoveryError(
                f"ambiguous binding reference {path}: {len(raw)} candidates; "
                "refusing to pick one"
            )
        raw = raw[0]
    return _load_binding_object(raw, persona_id=persona_id)


def discover_production_binding(
    *,
    persona_id: str,
    binding_ref: str | Path | None = None,
) -> RuntimeBinding:
    """Resolve the production binding for a Hermes boot (MR-RUNTIME-02 §3).

    Single composition authority chain, no directory scanning and no
    newest-file heuristic:

      1. explicit ``binding_ref`` argument (from the caller);
      2. ``MR_RUNTIME_BINDING`` env var → one JSON reference file;
      3. the legacy compat default ``production_binding(persona_id)`` — the
         ONLY fallback, and only in this seam (ADR-0020 §5).
    """
    ref = (
        binding_ref
        if binding_ref is not None
        else os.environ.get(MR_RUNTIME_BINDING_ENV)
    )
    if not ref:
        return production_binding(persona_id)
    return load_binding_reference(ref, persona_id=persona_id)


@dataclass(frozen=True)
class StoragePaths:
    """Physical storage addresses resolved from a binding's namespace."""

    root: Path
    facts_db: Path
    state_db: Path
    binding_manifest: Path

    @property
    def memory_db(self) -> Path:
        """Canonical Memory shares the resolved namespace (ADR-0023)."""
        return self.root / "memory.sqlite"

    @property
    def semantic_index_root(self) -> Path:
        """Optional derived provider state inside the same Runtime namespace."""
        return self.root / "semantic_index"

    @property
    def lce_root(self) -> Path:
        """Optional LCE persistence; composition partitions authorized Scopes."""
        return self.root / "lce"


def _assert_disjoint(a: Path, b: Path, *, boundary: str) -> None:
    a_res = a.resolve()
    b_res = b.resolve()
    if a_res == b_res or a_res in b_res.parents or b_res in a_res.parents:
        raise NamespaceIsolationError(
            f"{boundary}: {a_res} and {b_res} must be disjoint storage roots"
        )


def resolve_storage_paths(
    binding: RuntimeBinding,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> StoragePaths:
    """Resolve a binding's namespace to physical storage (ADR-0020 §2).

    PRODUCTION: the compat namespace maps to the existing production directory;
    the pre-existing ``MR_FACTS_DB`` / ``MR_STATE_DB`` env relocation contract
    is honored unchanged. LAB: resolves to ``<lab_root>/<storage_namespace>/``
    and IGNORES the production env relocation. Both environments are guarded
    against any production/lab root overlap (fail closed).
    """
    production_root = (
        Path(production_root) if production_root is not None else DEFAULT_PRODUCTION_ROOT
    )
    lab_root = Path(lab_root) if lab_root is not None else DEFAULT_LAB_ROOT

    if binding.environment is RuntimeEnvironment.PRODUCTION:
        if binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE:
            # Preserve the legacy Xiyue physical layout and relocation seam.
            facts_env = os.environ.get("MR_FACTS_DB")
            state_env = os.environ.get("MR_STATE_DB")
            facts_db = Path(facts_env) if facts_env else production_root / "facts.sqlite"
            state_db = (
                Path(state_env) if state_env else production_root / "cognition_state.sqlite"
            )
            root = state_db.parent
        else:
            # Explicit production bindings from BindingRegistry get their own
            # physically isolated namespace. The legacy compat binding remains
            # the only implicit fallback in discover_production_binding().
            root = production_root / binding.storage_namespace
            facts_db = root / "facts.sqlite"
            state_db = root / "cognition_state.sqlite"
        _assert_disjoint(facts_db.parent, lab_root, boundary="production/lab isolation")
        _assert_disjoint(state_db.parent, lab_root, boundary="production/lab isolation")
    else:
        if binding.storage_namespace == PRODUCTION_COMPAT_NAMESPACE:
            raise NamespaceIsolationError(
                "LAB bindings may not use the production namespace "
                f"{PRODUCTION_COMPAT_NAMESPACE!r}"
            )
        root = lab_root / binding.storage_namespace
        facts_db = root / "facts.sqlite"
        state_db = root / "cognition_state.sqlite"
        _assert_disjoint(lab_root, production_root, boundary="production/lab isolation")

    return StoragePaths(
        root=root,
        facts_db=facts_db,
        state_db=state_db,
        binding_manifest=root / MANIFEST_FILENAME,
    )


def _write_or_verify_manifest(manifest_path: Path, binding: RuntimeBinding) -> None:
    identity = binding.manifest_identity()
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BindingManifestMismatchError(
                f"unreadable binding manifest {manifest_path}: {exc}"
            ) from exc
        differing = [
            field
            for field in _MANIFEST_FIELDS
            if existing.get(field) != identity.get(field)
        ]
        if differing:
            raise BindingManifestMismatchError(
                f"namespace {binding.storage_namespace!r} is owned by a different "
                f"binding; differing identity fields: {differing} "
                f"(existing={existing}, requested={identity})"
            )
        return
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def bind_storage(
    binding: RuntimeBinding,
    *,
    production_root: Path | str | None = None,
    lab_root: Path | str | None = None,
) -> StoragePaths:
    """Resolve the namespace, create it, and claim/verify the binding manifest.

    This is the restart reconstruction seam (ADR-0020 §3): re-supplying the
    same binding reconnects to the same durable namespace; a different binding
    into an occupied namespace fails closed.
    """
    paths = resolve_storage_paths(
        binding, production_root=production_root, lab_root=lab_root
    )
    _write_or_verify_manifest(paths.binding_manifest, binding)
    return paths
