"""Create-once Persona config publication; runtime resolution is read-only."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

from mind_runtime.persona_config import LoadedPersona, PersonaProfileError, load_persona_profile

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PersonaPublicationError(PersonaProfileError):
    """A published Persona revision cannot be admitted."""


class PersonaRevisionConflict(PersonaPublicationError):
    """An occupied Persona revision has another content digest."""


class ReplayUnavailable(PersonaPublicationError):
    """An exact historical Persona artifact cannot be resolved."""


@dataclass(frozen=True, slots=True)
class PersonaRevisionRef:
    persona_id: str
    profile_version: int
    effective_content_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.persona_id, str) or not self.persona_id.strip():
            raise ValueError("persona_id must be non-empty")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be a positive integer")
        if not isinstance(self.effective_content_digest, str) or not _DIGEST.fullmatch(
            self.effective_content_digest
        ):
            raise ValueError("effective_content_digest must be lowercase SHA-256")

    @classmethod
    def of(cls, loaded: LoadedPersona) -> PersonaRevisionRef:
        return cls(loaded.persona_id, loaded.profile_version, loaded.effective_content_digest)


class PersonaConfigPublicationRepository:
    """One create-once artifact slot per `(persona_id, profile_version)`.

    The admin author calls ``publish``. Runtime receives only a resolver and
    calls ``resolve`` against an exact binding reference. The final path omits
    digest deliberately, so competing processes cannot create two revisions
    with the same ID/version and different content.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def artifact_path(self, ref: PersonaRevisionRef) -> Path:
        if not isinstance(ref, PersonaRevisionRef):
            raise TypeError("ref must be PersonaRevisionRef")
        identity_dir = hashlib.sha256(ref.persona_id.encode("utf-8")).hexdigest()
        return self.root / identity_dir / f"revision-{ref.profile_version}.json"

    def resolve(self, ref: PersonaRevisionRef) -> LoadedPersona:
        """No writes, alias lookup, registry fallback, or implicit publication."""
        path = self.artifact_path(ref)
        if path.is_symlink():
            raise PersonaPublicationError("PERSONA_ARTIFACT_INVALID: symbolic link is mutable")
        if not path.is_file():
            raise ReplayUnavailable(
                f"REPLAY_UNAVAILABLE: missing {ref.persona_id!r}:{ref.profile_version}"
            )
        try:
            loaded = load_persona_profile(path, registry=None)
        except PersonaProfileError as exc:
            raise PersonaPublicationError(f"PERSONA_ARTIFACT_INVALID: {path}: {exc}") from exc
        if not loaded.is_surface_eligible:
            raise PersonaPublicationError("PERSONA_ARTIFACT_INVALID: schema-2 disposition required")
        if PersonaRevisionRef.of(loaded) != ref:
            raise PersonaRevisionConflict(
                "PERSONA_REVISION_CONFLICT: published content differs from bound reference"
            )
        return loaded

    def publish(self, source_path: str | Path) -> PersonaRevisionRef:
        """Admin-only atomic create-once publication of a reviewed config file."""
        # Snapshot the author-supplied bytes once. Loading the source and then
        # reading it a second time would allow a concurrent edit to publish B
        # under A's identity between those operations.
        payload = Path(source_path).read_bytes()
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".persona-publish-", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            loaded = load_persona_profile(temporary, registry=None)
            if not loaded.is_surface_eligible:
                raise PersonaPublicationError("PERSONA_PUBLICATION_INELIGIBLE: schema 2 required")
            ref = PersonaRevisionRef.of(loaded)
            target = self.artifact_path(ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                os.link(temporary, target)
                created = True
            except FileExistsError:
                try:
                    self.resolve(ref)
                except PersonaRevisionConflict as exc:
                    raise PersonaRevisionConflict(
                        "PERSONA_REVISION_CONFLICT: occupied revision differs"
                    ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        if created:
            target.chmod(stat.S_IREAD)
        return ref
