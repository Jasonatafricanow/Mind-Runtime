"""Checkpointable offline reconstruction into a fresh independent MR-Mem DB."""

import hashlib
import os
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from mr_mem.memory.core import MemoryCore
from mr_mem.memory.semantic_contracts import SCHEMA_VERSION
from mr_mem.memory.semantic_store import SemanticSourceBinding, binding_payload, read_binding
from mr_mem.memory.store import scope_json

from historical.agy_adapter import PROMPT_VERSION, build_prompt
from historical.checkpoint import CheckpointFile
from historical.context_assembler import HistoricalContextAssembler
from historical.source_curator import HistoricalSourceCurator, SourceDisposition


def native_digest(path):
    digest = hashlib.sha256()
    for file in (path, Path(str(path) + "-wal")):
        if file.exists():
            digest.update(file.name.encode())
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


class RebuildClock:
    def now(self):
        return datetime.now(UTC)


class HistoricalRebuild:
    def __init__(self, root, *, sources, worker, resume=False):
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise ValueError("rebuild root must not be a symlink")
        if not resume:
            self.root.mkdir(parents=True, exist_ok=False)
        self.root = self.root.resolve(strict=True)
        self.sources, self.worker = sources, worker
        self.db_path = self.root / "historical-rebuild-v1.sqlite"
        forbidden = os.environ.get("MR_MEM_CANONICAL_DB")
        if self.db_path.is_symlink() or (
            forbidden and Path(forbidden).resolve() == self.db_path.resolve()
        ):
            raise ValueError("production canonical DB is forbidden")
        self.checkpoint = CheckpointFile(self.root)
        try:
            authority = {
                "native_path": str(sources.path),
                "native_digest": native_digest(sources.path),
                "namespace": sources.namespace,
                "scope": scope_json(sources.scope),
                "schema_version": SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "canonical_path": str(self.db_path),
            }
            if resume:
                self.state = self.checkpoint.load()
                if self.state["authority"] != authority or not self.db_path.is_file():
                    raise ValueError("rebuild authority, Raw, schema or prompt changed")
                # Verify ownership read-only before reopening any canonical writer.
                with MemoryCore(self.db_path, read_only=True) as canonical:
                    if any(
                        item.origin_runtime_id != self.state["origin"]
                        or item.scope != sources.scope
                        or not item.provenance.source_refs
                        or any(
                            ref.source_namespace != sources.namespace
                            for ref in item.provenance.source_refs
                        )
                        for item in canonical.load_all()
                    ):
                        raise ValueError("DB is not owned by this fresh historical rebuild")
            else:
                if self.db_path.exists():
                    raise ValueError("fresh empty rebuild DB required")
                self.state = {
                    "authority": authority,
                    "origin": "historical-rebuild:" + uuid.uuid4().hex,
                    "last_source_ref": None,
                    "last_ordering_key": None,
                    "compile_count": 0,
                    "ignore_count": 0,
                    "context_count": 0,
                    "defer_count": 0,
                    "failure_ref": None,
                    "pending": None,
                    "prompt_version": PROMPT_VERSION,
                    "schema_version": SCHEMA_VERSION,
                }
                self.checkpoint.save(self.state)
            self.memory = MemoryCore(self.db_path)
            self.admission = self.memory.semantic_admission(
                sources=sources,
                clock=RebuildClock(),
                origin_runtime_id=self.state["origin"],
            )
            self.context = HistoricalContextAssembler(sources, self.memory)
        except BaseException:
            self.checkpoint.close()
            raise

    def run(self, *, selection=None, limit=None):
        """Selection returns explicit context_refs/activated_memory_ids for one source.

        Counts cover source dispositions; defer_count counts fully deferred sources.
        No provider call is made for CONTEXT_ONLY/IGNORE or an accepted replay.
        """
        if native_digest(self.sources.path) != self.state["authority"]["native_digest"]:
            raise ValueError("immutable native Raw changed")
        count = 0
        after = self.state["last_ordering_key"]
        for source in self.sources.iterate(after=after):
            if limit is not None and count >= limit:
                break
            disposition = HistoricalSourceCurator().classify(source)
            try:
                if disposition == SourceDisposition.COMPILE:
                    self._compile(source, selection)
                else:
                    key = (
                        "context_count"
                        if disposition == SourceDisposition.CONTEXT_ONLY
                        else "ignore_count"
                    )
                    self.state[key] += 1
                self.state["last_source_ref"] = asdict(source.source_ref)
                self.state["last_source_ref"]["occurred_at"] = (
                    source.source_ref.occurred_at.isoformat()
                )
                self.state["last_ordering_key"] = list(source.ordering_key)
                self.state["failure_ref"] = None
                self.state["pending"] = None
                self.checkpoint.save(self.state)
            except BaseException:
                self.state["failure_ref"] = source.source_ref.source_key
                self.checkpoint.save(self.state)
                raise
            count += 1
        if native_digest(self.sources.path) != self.state["authority"]["native_digest"]:
            raise ValueError("immutable native Raw changed during rebuild")
        return dict(self.state)

    def _compile(self, source, selection):
        self.sources.bind(source)
        binding = SemanticSourceBinding(
            self.sources.scope, source.interaction_id, source.source_ref
        )
        pending = self.state["pending"]
        if pending and read_binding(pending["binding"]) != binding:
            raise ValueError("pending historical source drift or ordering mismatch")
        # MR-Mem finishes its frozen transaction/receipt before any AGY retry.
        receipt = self.admission.resume_semantic_delta(binding)
        if receipt is None:
            if pending is None:
                selected = selection(source, self) if selection else {}
                context = self.context.assemble(source, **selected)
                pending = {
                    "binding": binding_payload(binding),
                    "payload": None,
                    "prompt_digest": hashlib.sha256(build_prompt(context).encode()).hexdigest(),
                    "activated_memory_ids": list(context.activated_memory_ids),
                }
                self.state["pending"] = pending
                self.checkpoint.save(self.state)
                payload = self.worker.compile(context)
                pending["payload"] = payload
                self.checkpoint.save(self.state)
            elif pending["payload"] is None:
                selected = selection(source, self) if selection else {}
                context = self.context.assemble(source, **selected)
                if list(context.activated_memory_ids) != pending["activated_memory_ids"]:
                    raise ValueError("pending activated selection changed")
                if (
                    hashlib.sha256(build_prompt(context).encode()).hexdigest()
                    != pending["prompt_digest"]
                ):
                    raise ValueError("pending historical context changed")
                pending["payload"] = self.worker.compile(context)
                self.checkpoint.save(self.state)
            receipt = self.admission.admit_semantic_delta(
                pending["payload"],
                binding=binding,
                activated_memory_ids=tuple(pending["activated_memory_ids"]),
            )
        self.state["compile_count"] += 1
        self.state["defer_count"] += receipt.status == "deferred"

    def close(self):
        self.memory.close()
        self.checkpoint.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
