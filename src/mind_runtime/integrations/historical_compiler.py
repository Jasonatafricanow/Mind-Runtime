"""One-pass, source-bound semantic cleaning with append-only recovery receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mr_mem import (
    CommittedMemory,
    MemoryCore,
    Scope,
    SemanticAdmissionService,
    SemanticMemoryCandidate,
    SourceRefReader,
)
from mr_mem.contracts.common import require_non_empty
from mr_mem.memory.store import scope_json

from mind_runtime.integrations.native_history import (
    NativeRecord,
    SourceFragment,
    source_fragments,
    structural_drop,
)

SCHEMA_VERSION = "native-cleaner-v1"
REQUIRED_ATTRIBUTES = {"subject", "holder", "polarity", "modality", "temporal_scope", "kind"}
ALLOWED_ATTRIBUTES = REQUIRED_ATTRIBUTES | {
    "thread_action", "thread_question", "thread_summary", "thread_mature",
}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class FragmentDecision:
    fragment_id: str
    disposition: str
    reason: str
    content: str
    attributes: tuple[tuple[str, str], ...]

    def payload(self) -> dict[str, object]:
        return {
            "fragment_id": self.fragment_id, "disposition": self.disposition,
            "reason": self.reason, "content": self.content, "attributes": dict(self.attributes),
        }


class SemanticCleaner(Protocol):
    """Host semantic authority; no model is constructed inside the pipeline."""

    def compile(
        self, fragments: tuple[SourceFragment, ...], *, context: tuple[SourceFragment, ...],
    ) -> object: ...


class SemanticConsumer(Protocol):
    """Must be idempotent by canonical memory ID; receipt follows successful consumption."""

    def consume(self, memories: tuple[CommittedMemory, ...]) -> None: ...


def validate_proposal(
    raw: object, fragments: tuple[SourceFragment, ...],
) -> tuple[FragmentDecision, ...]:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "fragments"}:
        raise ValueError("unknown proposal fields; quotes/offsets are not accepted")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ValueError("compiler schema mismatch")
    items = raw["fragments"]
    if not isinstance(items, list) or len(items) != len(fragments):
        raise ValueError("complete fragment coverage required")
    by_id = {f.fragment_id: f for f in fragments}
    decisions: dict[str, FragmentDecision] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "fragment_id", "disposition", "reason", "content", "attributes",
        }:
            raise ValueError("invalid fragment fields; no quote/range repair is permitted")
        fid = item["fragment_id"]
        if not isinstance(fid, str) or fid not in by_id or fid in decisions:
            raise ValueError("unknown or duplicate host fragment ID")
        disposition, reason, content = item["disposition"], item["reason"], item["content"]
        if disposition not in ("DROP", "KEEP", "DEFER"):
            raise ValueError("expected DROP/KEEP/DEFER")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            raise ValueError("bounded disposition reason required")
        if not isinstance(content, str) or len(content.encode()) > 16384:
            raise ValueError("invalid semantic content")
        attrs = item["attributes"]
        if not isinstance(attrs, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(v) > 2048
            for k, v in attrs.items()
        ):
            raise ValueError("bounded string semantic attributes required")
        if disposition == "KEEP":
            if not content.strip() or not REQUIRED_ATTRIBUTES <= set(attrs) <= ALLOWED_ATTRIBUTES:
                raise ValueError("KEEP requires complete local semantics")
            if by_id[fid].role != "user" or attrs["holder"] != "user":
                raise ValueError("assistant/context text cannot establish user semantics")
            if attrs["polarity"] not in {"positive", "negative", "unknown"}:
                raise ValueError("invalid polarity")
            if attrs["modality"] not in {"asserted", "planned", "hypothetical", "uncertain"}:
                raise ValueError("invalid modality")
        elif content or attrs:
            raise ValueError("DROP/DEFER must not carry admitted semantics")
        decisions[fid] = FragmentDecision(
            fid, disposition, reason, content, tuple(sorted(attrs.items()))
        )
    # The model may reorder results; canonical application retains stable host order.
    return tuple(decisions[f.fragment_id] for f in fragments)


class HistoricalSemanticPipeline:
    """Freeze understanding once, then resume only missing downstream stages."""

    def __init__(
        self, *, path: Path, core: MemoryCore, admission: SemanticAdmissionService,
        scope: Scope, cleaner: SemanticCleaner, compiler_version: str,
        sources: SourceRefReader,
        consumers: Mapping[str, SemanticConsumer] | None = None,
    ) -> None:
        require_non_empty(compiler_version, "compiler_version")
        self._core, self._admission, self._scope = core, admission, scope
        self._sources = sources
        self._cleaner, self._version = cleaner, compiler_version
        self._consumers = dict(consumers or {})
        if any(not name.strip() for name in self._consumers):
            raise ValueError("consumer stage names must be nonempty")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30)
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS source_receipts (
                job_id TEXT PRIMARY KEY, source_key TEXT NOT NULL, version_key TEXT NOT NULL,
                compiler_version TEXT NOT NULL, cursor TEXT NOT NULL, hard_drop TEXT,
                accepted_proposal INTEGER, memory_ids TEXT, stages TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS proposal_history (
                proposal_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                payload TEXT NOT NULL, validation_error TEXT);
            CREATE TABLE IF NOT EXISTS consumption_receipts (
                stage TEXT NOT NULL, memory_id TEXT NOT NULL, PRIMARY KEY(stage,memory_id));
            CREATE TRIGGER IF NOT EXISTS immutable_proposal_update
                BEFORE UPDATE ON proposal_history BEGIN
                    SELECT RAISE(ABORT,'proposal history is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_proposal_delete
                BEFORE DELETE ON proposal_history BEGIN
                    SELECT RAISE(ABORT,'proposal history is append-only'); END;
        """)

    def close(self) -> None:
        self._db.close()

    def process(
        self, record: NativeRecord, *, context: tuple[SourceFragment, ...] = (),
    ) -> tuple[CommittedMemory, ...]:
        if len(context) > 8 or sum(len(f.text) for f in context) > 4096:
            raise ValueError("DEFER context exceeds bounded window")
        for ref in (record.ref, *(f.ref for f in context)):
            if self._sources.current_ref(self._scope, ref) != ref:
                raise ValueError("native source/context is missing, stale, or out of scope")
        identity = [
            SCHEMA_VERSION, scope_json(self._scope), record.ref.version_key, self._version,
            [f.fragment_id for f in context],
        ]
        job_id = hashlib.sha256(_json(identity).encode()).hexdigest()
        hard_drop = structural_drop(record)
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO source_receipts "
                "(job_id,source_key,version_key,compiler_version,cursor,hard_drop) "
                "VALUES(?,?,?,?,?,?)",
                (job_id, record.ref.source_key, record.ref.version_key, self._version,
                 _json(record.ordering_key), hard_drop),
            )
        if hard_drop is not None:
            return ()
        row = self._db.execute(
            "SELECT accepted_proposal,memory_ids,stages FROM source_receipts WHERE job_id=?",
            (job_id,),
        ).fetchone()
        fragments = source_fragments(record)
        if len(fragments) > 64 or len(record.text.encode()) > 65536:
            raise ValueError("source window too large; bounded native paging required")
        if row[0] is None:
            raw: object
            try:
                previous = self._db.execute(
                    "SELECT p.payload FROM source_receipts s JOIN proposal_history p "
                    "ON p.proposal_id=s.accepted_proposal "
                    "WHERE s.source_key=? AND s.version_key=? AND s.compiler_version=? "
                    "AND s.job_id!=? ORDER BY s.rowid DESC LIMIT 1",
                    (record.ref.source_key, record.ref.version_key, self._version, job_id),
                ).fetchone()
                reusable = () if previous is None else validate_proposal(
                    json.loads(previous[0]), fragments
                )
                deferred_ids = {d.fragment_id for d in reusable if d.disposition == "DEFER"}
                pending = tuple(f for f in fragments if f.fragment_id in deferred_ids)
                if reusable:
                    resolved = () if not pending else validate_proposal(
                        self._cleaner.compile(pending, context=context), pending
                    )
                    replacements = {d.fragment_id: d for d in resolved}
                    raw = {
                        "schema_version": SCHEMA_VERSION, "fragments": [
                            replacements.get(d.fragment_id, d).payload() for d in reusable
                        ],
                    }
                else:
                    raw = self._cleaner.compile(fragments, context=context)
            except Exception as exc:
                with self._db:
                    self._db.execute(
                        "INSERT INTO proposal_history(job_id,payload,validation_error) "
                        "VALUES(?,?,?)",
                        (job_id, "null", f"producer failed: {type(exc).__name__}"),
                    )
                raise
            decisions = self.accept_proposal(job_id, raw, fragments)
        else:
            payload = self._db.execute(
                "SELECT payload FROM proposal_history WHERE proposal_id=?", (row[0],)
            ).fetchone()[0]
            decisions = validate_proposal(json.loads(payload), fragments)
        memories = []
        for decision in decisions:
            if decision.disposition == "KEEP":
                memories.append(self._admission.admit(SemanticMemoryCandidate(
                    semantic_id=decision.fragment_id,
                    scope=self._scope, content=decision.content, source_refs=(record.ref,),
                    compiler_version=self._version, attributes=decision.attributes,
                )))
        ids = tuple(m.memory_id for m in memories)
        accepted = self._core.select(ids, scope=self._scope, active_only=True) if ids else ()
        with self._db:
            self._db.execute(
                "UPDATE source_receipts SET memory_ids=? WHERE job_id=?",
                (_json([m.memory_id for m in accepted]), job_id),
            )
        stages = json.loads(row[2])
        for name, consumer in self._consumers.items():
            pending_memories = tuple(
                m for m in accepted if self._db.execute(
                    "SELECT 1 FROM consumption_receipts WHERE stage=? AND memory_id=?",
                    (name, m.memory_id),
                ).fetchone() is None
            )
            if pending_memories:
                consumer.consume(pending_memories)
            stages[name] = [m.memory_id for m in accepted]
            with self._db:
                self._db.executemany(
                    "INSERT OR IGNORE INTO consumption_receipts VALUES(?,?)",
                    [(name, m.memory_id) for m in pending_memories],
                )
                self._db.execute(
                    "UPDATE source_receipts SET stages=? WHERE job_id=?", (_json(stages), job_id)
                )
        return accepted

    def accept_proposal(
        self, job_id: str, raw: object, fragments: tuple[SourceFragment, ...],
    ) -> tuple[FragmentDecision, ...]:
        """Every attempt appends; rejected proposals never replace earlier attempts."""
        payload = _json(raw)
        error = None
        decisions: tuple[FragmentDecision, ...] = ()
        try:
            if len(payload.encode()) > 131072:
                raise ValueError("proposal exceeds bounded output")
            decisions = validate_proposal(raw, fragments)
            normalized = _json({
                "schema_version": SCHEMA_VERSION, "fragments": [d.payload() for d in decisions],
            })
            payload = normalized
        except ValueError as exc:
            error = str(exc)
        self._db.execute("BEGIN IMMEDIATE")
        with self._db:
            receipt = self._db.execute(
                "SELECT version_key,accepted_proposal FROM source_receipts WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if receipt is None or any(f.ref.version_key != receipt[0] for f in fragments):
                error = "proposal exceeds its registered native source"
            elif error is None and receipt[1] is not None:
                frozen = self._db.execute(
                    "SELECT payload FROM proposal_history WHERE proposal_id=?", (receipt[1],)
                ).fetchone()[0]
                if frozen != payload:
                    error = "conflicting frozen semantic proposal"
            cursor = self._db.execute(
                "INSERT INTO proposal_history(job_id,payload,validation_error) VALUES(?,?,?)",
                (job_id, payload, error),
            )
            if error is None:
                self._db.execute(
                    "UPDATE source_receipts SET accepted_proposal=coalesce(accepted_proposal,?) "
                    "WHERE job_id=?", (cursor.lastrowid, job_id),
                )
        if error is not None:
            raise ValueError(error)
        return decisions

    def funnel(self) -> dict[str, int]:
        result = {
            "raw_records": 0, "structural_drop": 0, "DROP": 0, "KEEP": 0, "DEFER": 0,
            "semantic_memories": 0, "proposal_attempts": 0,
        }
        for hard, accepted, memory_ids in self._db.execute(
            "SELECT hard_drop,accepted_proposal,memory_ids FROM source_receipts "
            "WHERE rowid IN (SELECT max(rowid) FROM source_receipts GROUP BY source_key)"
        ):
            result["raw_records"] += 1
            if hard is not None:
                result["structural_drop"] += 1
            elif accepted is not None:
                payload = json.loads(self._db.execute(
                    "SELECT payload FROM proposal_history WHERE proposal_id=?", (accepted,)
                ).fetchone()[0])
                for fragment in payload["fragments"]:
                    result[fragment["disposition"]] += 1
                result["semantic_memories"] += len(json.loads(memory_ids or "[]"))
        result["proposal_attempts"] = self._db.execute(
            "SELECT count(*) FROM proposal_history"
        ).fetchone()[0]
        return result
