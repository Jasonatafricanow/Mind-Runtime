"""Upstream Multi-Binding Registry Authority (W2-B / W2-C).

Normative authority:
- ADR-0021 (ACCEPTED at R1, 2026-09-06)
- ADR-0020 (Runtime identity binding & storage isolation)
- docs/OW_PHASE02_W2B_BINDING_REGISTRY_CONTRACT.md

Reader Port: list_bindings, resolve_binding, default_binding
Writer Port: initialize, register, set_default, clear_default
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from mind_runtime.runtime_binding import (
    RuntimeBinding,
    RuntimeBindingError,
    RuntimeEnvironment,
    resolve_storage_paths,
)
from mind_runtime.persona_publication import (
    PersonaRevisionConflict,
    PersonaRevisionRef,
    ReplayUnavailable,
)

__all__ = [
    "RegistryFailureCode",
    "BindingRegistryError",
    "BindingDescriptor",
    "NoDefaultReason",
    "DefaultBindingResult",
    "check_environment_admission",
    "BindingRegistryReader",
    "BindingRegistryWriter",
    "BindingRegistry",
    "build_binding_registry",
]

_BINDING_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _serialized_write(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def wrapped(self: BindingRegistry, *args: Any, **kwargs: Any) -> Any:
        with self._write_lock():
            return method(self, *args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# 1. Typed Failure Contract
# ---------------------------------------------------------------------------


class RegistryFailureCode(StrEnum):
    """Named, explicit failure conditions for Upstream BindingRegistry."""

    REGISTRY_UNINITIALIZED = "REGISTRY_UNINITIALIZED"
    REGISTRY_ALREADY_INITIALIZED = "REGISTRY_ALREADY_INITIALIZED"
    REGISTRY_CORRUPT = "REGISTRY_CORRUPT"
    DUPLICATE_BINDING_ID = "DUPLICATE_BINDING_ID"
    DUPLICATE_ACTIVE_IDENTITY = "DUPLICATE_ACTIVE_IDENTITY"
    MULTIPLE_DEFAULTS = "MULTIPLE_DEFAULTS"
    IDENTITY_MANIFEST_DIVERGENCE = "IDENTITY_MANIFEST_DIVERGENCE"
    BINDING_ID_UNKNOWN = "BINDING_ID_UNKNOWN"
    ADMISSION_DENIED = "ADMISSION_DENIED"


class BindingRegistryError(RuntimeBindingError):
    """Authoritative failure contract for Upstream BindingRegistry."""

    def __init__(
        self,
        code: RegistryFailureCode | str,
        message: str | None = None,
    ) -> None:
        if isinstance(code, str) and not isinstance(code, RegistryFailureCode):
            try:
                code_enum = RegistryFailureCode(code)
            except ValueError:
                code_enum = RegistryFailureCode.REGISTRY_CORRUPT
        else:
            code_enum = code
        self.code = code_enum
        msg = f"[{self.code.value}] {message}" if message else self.code.value
        super().__init__(msg)


# ---------------------------------------------------------------------------
# 2. Descriptors and Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BindingDescriptor:
    """The Phase 2 descriptor, frozen to ADR-0021 §4."""

    binding_id: str
    environment: RuntimeEnvironment
    agent_id: str
    runtime_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, str) or not _BINDING_ID_RE.match(self.binding_id):
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"binding_id must match ^[a-z0-9][a-z0-9-]{{0,63}}$, got {self.binding_id!r}",
            )
        if not isinstance(self.environment, RuntimeEnvironment):
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"environment must be a RuntimeEnvironment, got {self.environment!r}",
            )
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT, "agent_id must be non-empty string"
            )
        if not isinstance(self.runtime_id, str) or not self.runtime_id.strip():
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT, "runtime_id must be non-empty string"
            )


class NoDefaultReason(StrEnum):
    """Diagnostic reason for NO_DEFAULT_BINDING."""

    REGISTRY_EMPTY = "REGISTRY_EMPTY"
    NO_DEFAULT_DECLARED = "NO_DEFAULT_DECLARED"


@dataclass(frozen=True)
class DefaultBindingResult:
    """Explicit result of default_binding (never inferred)."""

    status: str
    descriptor: BindingDescriptor | None = None
    reason: NoDefaultReason | None = None


def check_environment_admission(
    entry_environment: RuntimeEnvironment,
    admission_environment: RuntimeEnvironment,
) -> bool:
    """Exact environment equality admission guard."""
    return entry_environment is admission_environment


# ---------------------------------------------------------------------------
# 3. Ports / Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class BindingRegistryReader(Protocol):
    """Read port for Upstream BindingRegistry (consumed by OW / runtime)."""

    def list_bindings(
        self, *, environment: RuntimeEnvironment
    ) -> tuple[BindingDescriptor, ...]: ...

    def resolve_binding(
        self,
        binding_id: str,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> RuntimeBinding: ...

    def default_binding(
        self,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> DefaultBindingResult: ...

    def resolve_persona_revision(
        self, binding_id: str, *, environment: RuntimeEnvironment,
    ) -> PersonaRevisionRef: ...


@runtime_checkable
class BindingRegistryWriter(Protocol):
    """Writer / Admin port for Upstream BindingRegistry (upstream-only)."""

    def initialize(self) -> None: ...

    def register(
        self, binding: RuntimeBinding, binding_id: str
    ) -> BindingDescriptor: ...

    def set_default(self, binding_id: str) -> None: ...

    def clear_default(self, environment: RuntimeEnvironment) -> None: ...

    def pin_persona_revision(
        self, binding_id: str, ref: PersonaRevisionRef,
    ) -> PersonaRevisionRef: ...


# ---------------------------------------------------------------------------
# 4. Implementation: Persistent Binding Registry
# ---------------------------------------------------------------------------


class _ReaderView:
    def __init__(self, registry: BindingRegistry) -> None:
        self._reg = registry

    def list_bindings(
        self, *, environment: RuntimeEnvironment
    ) -> tuple[BindingDescriptor, ...]:
        return self._reg.list_bindings(environment=environment)

    def resolve_binding(
        self,
        binding_id: str,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> RuntimeBinding:
        return self._reg.resolve_binding(
            binding_id,
            environment=environment,
            production_root=production_root,
            lab_root=lab_root,
        )

    def default_binding(
        self,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> DefaultBindingResult:
        return self._reg.default_binding(
            environment=environment,
            production_root=production_root,
            lab_root=lab_root,
        )

    def resolve_persona_revision(
        self, binding_id: str, *, environment: RuntimeEnvironment,
    ) -> PersonaRevisionRef:
        return self._reg.resolve_persona_revision(binding_id, environment=environment)


class _WriterView:
    def __init__(self, registry: BindingRegistry) -> None:
        self._reg = registry

    def initialize(self) -> None:
        self._reg.initialize()

    def register(
        self, binding: RuntimeBinding, binding_id: str
    ) -> BindingDescriptor:
        return self._reg.register(binding, binding_id)

    def set_default(self, binding_id: str) -> None:
        self._reg.set_default(binding_id)

    def clear_default(self, environment: RuntimeEnvironment) -> None:
        self._reg.clear_default(environment)

    def pin_persona_revision(
        self, binding_id: str, ref: PersonaRevisionRef,
    ) -> PersonaRevisionRef:
        return self._reg.pin_persona_revision(binding_id, ref)


class BindingRegistry:
    """Persistent Upstream BindingRegistry implementation."""

    _STORE_FILENAME = "registry.json"

    def __init__(self, store_dir: Path | str) -> None:
        path = Path(store_dir)
        if path.suffix == ".json":
            self._store_file = path
            self._store_dir = path.parent
        else:
            self._store_dir = path
            self._store_file = path / self._STORE_FILENAME

        self._reader = _ReaderView(self)
        self._writer = _WriterView(self)

    @property
    def reader(self) -> BindingRegistryReader:
        return self._reader

    @property
    def writer(self) -> BindingRegistryWriter:
        return self._writer

    @contextmanager
    def _write_lock(self):
        """Serialize read-modify-replace across processes, including Persona pins.

        The lock file is coordination only; the registry JSON remains the sole
        durable binding authority. OS locks are released after process death.
        """
        self._store_dir.mkdir(parents=True, exist_ok=True)
        with (self._store_dir / ".binding-registry.lock").open("a+b") as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    # -----------------------------------------------------------------------
    # Storage Engine (atomic, fail-closed)
    # -----------------------------------------------------------------------

    def _load_store(self) -> dict[str, Any]:
        if not self._store_file.exists():
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_UNINITIALIZED,
                f"registry store absent at {self._store_file}",
            )
        try:
            raw = self._store_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"unreadable registry store {self._store_file}: {exc}",
            ) from exc

        if (
            not isinstance(data, dict)
            or "entries" not in data
            or not isinstance(data["entries"], list)
        ):
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"invalid registry schema at {self._store_file}",
            )

        entries = data["entries"]

        # Invariant I3: at most one default per environment in store
        defaults_by_env: dict[str, list[str]] = {}
        for e in entries:
            if e.get("is_default") is True:
                env_val = e.get("identity", {}).get("environment", "")
                defaults_by_env.setdefault(env_val, []).append(e.get("binding_id", ""))
        for env_val, bids in defaults_by_env.items():
            if len(bids) > 1:
                raise BindingRegistryError(
                    RegistryFailureCode.MULTIPLE_DEFAULTS,
                    f"multiple defaults ({len(bids)}) found in environment {env_val!r}: {bids}",
                )

        # Invariant I1: Bijective 1:1 check on load
        seen_ids: set[str] = set()
        seen_identities: set[tuple[str, str, str, str, str]] = set()

        for entry in entries:
            bid = entry.get("binding_id")
            if not isinstance(bid, str) or not _BINDING_ID_RE.match(bid):
                raise BindingRegistryError(
                    RegistryFailureCode.REGISTRY_CORRUPT,
                    f"invalid binding_id in store: {bid!r}",
                )
            if bid in seen_ids:
                raise BindingRegistryError(
                    RegistryFailureCode.DUPLICATE_BINDING_ID,
                    f"duplicate binding_id {bid!r} in registry store",
                )
            seen_ids.add(bid)

            ident = entry.get("identity")
            if not isinstance(ident, dict):
                raise BindingRegistryError(
                    RegistryFailureCode.REGISTRY_CORRUPT,
                    f"entry {bid} has invalid identity payload",
                )
            pinned = entry.get("persona_revision_ref")
            if pinned is not None:
                if not isinstance(pinned, dict) or set(pinned) != {
                    "persona_id", "profile_version", "effective_content_digest"
                }:
                    raise BindingRegistryError(
                        RegistryFailureCode.REGISTRY_CORRUPT,
                        f"entry {bid} has malformed Persona revision reference",
                    )
                try:
                    ref = PersonaRevisionRef(**pinned)
                except (TypeError, ValueError) as exc:
                    raise BindingRegistryError(
                        RegistryFailureCode.REGISTRY_CORRUPT,
                        f"entry {bid} has invalid Persona revision reference",
                    ) from exc
                if ref.persona_id != ident.get("persona_id"):
                    raise BindingRegistryError(
                        RegistryFailureCode.REGISTRY_CORRUPT,
                        f"entry {bid} Persona revision does not match binding Persona",
                    )
            ident_key = (
                ident.get("environment", ""),
                ident.get("persona_id", ""),
                ident.get("agent_id", ""),
                ident.get("runtime_id", ""),
                ident.get("storage_namespace", ""),
            )
            if ident_key in seen_identities:
                raise BindingRegistryError(
                    RegistryFailureCode.DUPLICATE_ACTIVE_IDENTITY,
                    f"duplicate active identity {ident_key!r} in registry store",
                )
            seen_identities.add(ident_key)

        return data

    def _save_store(self, data: dict[str, Any]) -> None:
        self._store_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = self._store_dir / f"{self._store_file.name}.tmp"
        payload = json.dumps(data, indent=2, sort_keys=True)
        tmp_file.write_text(payload, encoding="utf-8")
        tmp_file.replace(self._store_file)

    # -----------------------------------------------------------------------
    # Reader Implementation
    # -----------------------------------------------------------------------

    def list_bindings(
        self, *, environment: RuntimeEnvironment
    ) -> tuple[BindingDescriptor, ...]:
        data = self._load_store()
        descriptors: list[BindingDescriptor] = []
        for entry in data["entries"]:
            ident = entry["identity"]
            try:
                env = RuntimeEnvironment(ident["environment"])
            except ValueError:
                raise BindingRegistryError(
                    RegistryFailureCode.REGISTRY_CORRUPT,
                    f"unknown environment {ident.get('environment')!r}",
                )
            if not check_environment_admission(env, environment):
                continue
            descriptors.append(
                BindingDescriptor(
                    binding_id=entry["binding_id"],
                    environment=env,
                    agent_id=ident["agent_id"],
                    runtime_id=ident["runtime_id"],
                )
            )
        return tuple(descriptors)

    def resolve_binding(
        self,
        binding_id: str,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> RuntimeBinding:
        data = self._load_store()
        matched = None
        for entry in data["entries"]:
            if entry.get("binding_id") == binding_id:
                matched = entry
                break

        if matched is None:
            raise BindingRegistryError(
                RegistryFailureCode.BINDING_ID_UNKNOWN,
                f"binding_id {binding_id!r} not found in registry",
            )

        ident = matched["identity"]
        try:
            entry_env = RuntimeEnvironment(ident["environment"])
        except ValueError:
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"unknown environment {ident.get('environment')!r}",
            )

        if not check_environment_admission(entry_env, environment):
            raise BindingRegistryError(
                RegistryFailureCode.ADMISSION_DENIED,
                f"binding {binding_id!r} has environment {entry_env.value!r}, "
                f"which cannot be admitted into {environment.value!r}",
            )

        binding = RuntimeBinding(
            persona_id=ident["persona_id"],
            agent_id=ident["agent_id"],
            runtime_id=ident["runtime_id"],
            storage_namespace=ident["storage_namespace"],
            environment=entry_env,
        )

        # Cross-check with namespace manifest (ADR-0020 / Invariant I7)
        paths = resolve_storage_paths(
            binding, production_root=production_root, lab_root=lab_root
        )
        if paths.binding_manifest.exists():
            try:
                manifest_data = json.loads(
                    paths.binding_manifest.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise BindingRegistryError(
                    RegistryFailureCode.IDENTITY_MANIFEST_DIVERGENCE,
                    f"unreadable binding manifest at {paths.binding_manifest}: {exc}",
                ) from exc

            manifest_ident = binding.manifest_identity()
            differing = [
                k
                for k, v in manifest_ident.items()
                if manifest_data.get(k) != v
            ]
            if differing:
                raise BindingRegistryError(
                    RegistryFailureCode.IDENTITY_MANIFEST_DIVERGENCE,
                    f"binding manifest at {paths.binding_manifest} diverges from registry: {differing}",
                )

        return binding

    def resolve_persona_revision(
        self, binding_id: str, *, environment: RuntimeEnvironment,
    ) -> PersonaRevisionRef:
        """Read the exact pinned config revision; never resolve a current alias."""
        data = self._load_store()
        for entry in data["entries"]:
            if entry["binding_id"] != binding_id:
                continue
            if entry["identity"]["environment"] != environment.value:
                raise BindingRegistryError(
                    RegistryFailureCode.ADMISSION_DENIED,
                    f"Persona revision binding {binding_id!r} has another environment",
                )
            pinned = entry.get("persona_revision_ref")
            if pinned is None:
                raise ReplayUnavailable(
                    f"REPLAY_UNAVAILABLE: binding {binding_id!r} has no published Persona revision"
                )
            return PersonaRevisionRef(**pinned)
        raise BindingRegistryError(
            RegistryFailureCode.BINDING_ID_UNKNOWN,
            f"binding_id {binding_id!r} not found in registry",
        )

    def default_binding(
        self,
        *,
        environment: RuntimeEnvironment,
        production_root: Path | str | None = None,
        lab_root: Path | str | None = None,
    ) -> DefaultBindingResult:
        data = self._load_store()
        admitted_entries = [
            e
            for e in data["entries"]
            if e.get("identity", {}).get("environment") == environment.value
        ]
        if not admitted_entries:
            return DefaultBindingResult(
                status="NO_DEFAULT_BINDING",
                reason=NoDefaultReason.REGISTRY_EMPTY,
            )

        default_entries = [e for e in admitted_entries if e.get("is_default") is True]
        if not default_entries:
            return DefaultBindingResult(
                status="NO_DEFAULT_BINDING",
                reason=NoDefaultReason.NO_DEFAULT_DECLARED,
            )

        default_entry = default_entries[0]
        ident = default_entry["identity"]
        try:
            entry_env = RuntimeEnvironment(ident["environment"])
        except ValueError:
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"unknown environment {ident.get('environment')!r}",
            )
        descriptor = BindingDescriptor(
            binding_id=default_entry["binding_id"],
            environment=entry_env,
            agent_id=ident["agent_id"],
            runtime_id=ident["runtime_id"],
        )
        return DefaultBindingResult(
            status="DEFAULT_BINDING",
            descriptor=descriptor,
        )

    # -----------------------------------------------------------------------
    # Writer Implementation
    # -----------------------------------------------------------------------

    @_serialized_write
    def initialize(self) -> None:
        if self._store_file.exists():
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_ALREADY_INITIALIZED,
                f"registry store already exists at {self._store_file}",
            )
        data = {"version": 1, "entries": []}
        self._save_store(data)

    @_serialized_write
    def register(
        self, binding: RuntimeBinding, binding_id: str
    ) -> BindingDescriptor:
        if not isinstance(binding_id, str) or not _BINDING_ID_RE.match(binding_id):
            raise BindingRegistryError(
                RegistryFailureCode.REGISTRY_CORRUPT,
                f"binding_id must match ^[a-z0-9][a-z0-9-]{{0,63}}$, got {binding_id!r}",
            )

        data = self._load_store()

        for entry in data["entries"]:
            if entry.get("binding_id") == binding_id:
                raise BindingRegistryError(
                    RegistryFailureCode.DUPLICATE_BINDING_ID,
                    f"binding_id {binding_id!r} is already registered",
                )
            ident = entry.get("identity", {})
            if (
                ident.get("environment") == binding.environment.value
                and ident.get("persona_id") == binding.persona_id
                and ident.get("agent_id") == binding.agent_id
                and ident.get("runtime_id") == binding.runtime_id
                and ident.get("storage_namespace") == binding.storage_namespace
            ):
                raise BindingRegistryError(
                    RegistryFailureCode.DUPLICATE_ACTIVE_IDENTITY,
                    f"active identity is already registered under binding_id {entry.get('binding_id')!r}",
                )

        new_entry = {
            "binding_id": binding_id,
            "is_default": False,
            "identity": binding.manifest_identity(),
        }
        data["entries"].append(new_entry)
        self._save_store(data)

        return BindingDescriptor(
            binding_id=binding_id,
            environment=binding.environment,
            agent_id=binding.agent_id,
            runtime_id=binding.runtime_id,
        )

    @_serialized_write
    def pin_persona_revision(
        self, binding_id: str, ref: PersonaRevisionRef,
    ) -> PersonaRevisionRef:
        """Admin-only, create-once reference pin; never publishes content."""
        if not isinstance(ref, PersonaRevisionRef):
            raise TypeError("ref must be PersonaRevisionRef")
        data = self._load_store()
        for entry in data["entries"]:
            if entry["binding_id"] != binding_id:
                continue
            if entry["identity"]["persona_id"] != ref.persona_id:
                raise BindingRegistryError(
                    RegistryFailureCode.ADMISSION_DENIED,
                    "Persona revision reference does not match RuntimeBinding",
                )
            existing = entry.get("persona_revision_ref")
            wire = {
                "persona_id": ref.persona_id,
                "profile_version": ref.profile_version,
                "effective_content_digest": ref.effective_content_digest,
            }
            if existing is not None:
                if existing == wire:
                    return ref
                raise PersonaRevisionConflict(
                    "PERSONA_REVISION_CONFLICT: binding already pins a different Persona revision"
                )
            entry["persona_revision_ref"] = wire
            self._save_store(data)
            return ref
        raise BindingRegistryError(
            RegistryFailureCode.BINDING_ID_UNKNOWN,
            f"binding_id {binding_id!r} not found in registry",
        )

    @_serialized_write
    def set_default(self, binding_id: str) -> None:
        data = self._load_store()
        found = False
        target_env = None

        for entry in data["entries"]:
            if entry.get("binding_id") == binding_id:
                found = True
                target_env = entry.get("identity", {}).get("environment")
                break

        if not found:
            raise BindingRegistryError(
                RegistryFailureCode.BINDING_ID_UNKNOWN,
                f"cannot set default: binding_id {binding_id!r} unknown",
            )

        # Atomic replacement within the same environment
        for entry in data["entries"]:
            if entry.get("identity", {}).get("environment") == target_env:
                entry["is_default"] = entry.get("binding_id") == binding_id

        self._save_store(data)

    @_serialized_write
    def clear_default(self, environment: RuntimeEnvironment) -> None:
        data = self._load_store()
        for entry in data["entries"]:
            if entry.get("identity", {}).get("environment") == environment.value:
                entry["is_default"] = False
        self._save_store(data)


def build_binding_registry(store_dir: Path | str) -> BindingRegistry:
    """Production factory for Upstream BindingRegistry."""
    return BindingRegistry(store_dir)
