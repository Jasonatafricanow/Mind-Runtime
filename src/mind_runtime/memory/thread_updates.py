"""Durable automatic maintenance for bounded MR Threads.

Thread maintenance is derived product state over canonical Memory. It cannot
create or rewrite canonical Memory, and the default deterministic policy does
not manufacture longitudinal interpretation or LCE maturity.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from mind_runtime.contracts.common import require_non_empty
from mind_runtime.memory.contracts import CommittedMemory, MemoryLifecycle
from mind_runtime.memory.product import (
    MAX_THREAD_CURRENT_SUPPORT,
    MemoryProductStore,
    MemoryThread,
)
from mind_runtime.memory.providers.bm25 import lexical_tokens
from mind_runtime.memory.store import _decode, scope_json


@dataclass(frozen=True, slots=True)
class ThreadUpdateIntent:
    memory_id: str
    status: str
    attempts: int
    thread_ref: str | None
    last_error: str | None


class ThreadUpdateQueue:
    """Crash-retry queue written atomically with canonical Memory admission."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.__conn = connection

    @property
    def database_path(self) -> Path | None:
        for _, name, path in self.__conn.execute("PRAGMA database_list"):
            if name == "main" and path:
                return Path(path).resolve()
        return None

    def pending(self, limit: int = 32) -> tuple[ThreadUpdateIntent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        rows = self.__conn.execute(
            "SELECT memory_id,status,attempts,thread_ref,last_error "
            "FROM thread_update_intents WHERE status != 'succeeded' "
            "ORDER BY registered_at,rowid LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(ThreadUpdateIntent(*row) for row in rows)

    def get(self, memory_id: str) -> CommittedMemory | None:
        row = self.__conn.execute(
            "SELECT payload FROM canonical_memory WHERE memory_id=?", (memory_id,)
        ).fetchone()
        return None if row is None else _decode(row[0])

    def begin_attempt(self, memory_id: str) -> None:
        with self.__conn:
            self.__conn.execute(
                "UPDATE thread_update_intents SET attempts=attempts+1 WHERE memory_id=?",
                (memory_id,),
            )

    def succeed(self, memory_id: str, thread_ref: str) -> None:
        require_non_empty(thread_ref, "thread_ref")
        with self.__conn:
            self.__conn.execute(
                "UPDATE thread_update_intents SET status='succeeded',"
                "thread_ref=?,last_error=NULL WHERE memory_id=?",
                (thread_ref, memory_id),
            )

    def fail(self, memory_id: str, error: str) -> None:
        with self.__conn:
            self.__conn.execute(
                "UPDATE thread_update_intents SET status='failed_retryable',"
                "last_error=? WHERE memory_id=?",
                (error[:1024], memory_id),
            )

    def rebuild(self, memories: Iterable[CommittedMemory]) -> int:
        """Explicit-only backfill helper; production composition never calls it."""
        before = self.__conn.total_changes
        with self.__conn:
            for memory in memories:
                self.__conn.execute(
                    "INSERT OR IGNORE INTO thread_update_intents(memory_id,registered_at) "
                    "VALUES(?,?)",
                    (memory.memory_id, memory.committed_at.isoformat()),
                )
        return self.__conn.total_changes - before


class ThreadUpdateAction(StrEnum):
    NOOP = "noop"
    OPEN = "open"
    UPDATE = "update"
    RESOLVE = "resolve"


@dataclass(frozen=True, slots=True)
class ThreadUpdateDecision:
    action: ThreadUpdateAction
    thread_id: str | None = None
    open_question: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ThreadUpdateAction):
            raise ValueError("action must be ThreadUpdateAction")
        if self.action is ThreadUpdateAction.NOOP:
            if self.thread_id is not None or self.open_question is not None:
                raise ValueError("NOOP decision cannot carry Thread fields")
            return
        require_non_empty(self.thread_id or "", "thread_id")
        if self.action is ThreadUpdateAction.OPEN:
            require_non_empty(self.open_question or "", "open_question")
        elif self.open_question is not None:
            raise ValueError("only OPEN decision may carry open_question")


class ThreadUpdatePolicy(Protocol):
    def decide(
        self,
        memory: CommittedMemory,
        open_threads: tuple[MemoryThread, ...],
        product: MemoryProductStore,
    ) -> ThreadUpdateDecision: ...


_OPEN_PATTERNS = (
    re.compile(
        r"\b(?:want to|plan to|planning to|considering|thinking about|trying to|"
        r"waiting for|undecided|deciding whether|not yet|have not decided|"
        r"haven't decided|still want|still need)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:一直想|想换|想买|想做|想弄|打算|计划|准备|考虑|纠结|"
        r"还没(?:决定|买|做|弄|处理)|尚未(?:决定|完成)|决定要不要|要不要|"
        r"等.{0,20}(?:回复|结果|消息))"
    ),
    re.compile(
        r"\b(?:quero|pretendo|planejo|considerando|pensando em|ainda não|"
        r"esperando por)\b",
        re.IGNORECASE,
    ),
)

_RESOLVE_PATTERNS = (
    re.compile(
        r"\b(?:decided not to|cancelled|canceled|gave up|finished|completed|"
        r"resolved|already bought|bought it|no longer need)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:不打算了|不买了|算了|取消了|已经买了|买完了|完成了|搞定了|"
        r"解决了|决定不|不用了|结束了)"
    ),
    re.compile(
        r"\b(?:desisti|cancelei|já comprei|resolvido|resolvida|concluído|"
        r"concluída|não preciso mais)\b",
        re.IGNORECASE,
    ),
)

_SHORT_TERM_PATTERNS = (
    re.compile(r"(?:马上|等会|一会儿|今晚|今天|现在就|去睡觉|吃饭|洗澡)"),
    re.compile(
        r"\b(?:right now|today|tonight|in an hour|go to sleep|eat dinner)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:agora|hoje|esta noite)\b", re.IGNORECASE),
)

_CONTINUITY_MARKERS = (
    "又",
    "还是",
    "后来",
    "最近",
    "继续",
    "again",
    "still",
    "later",
    "recently",
    "novamente",
    "ainda",
)

_STOP_TOKENS = frozenset(
    {
        "the",
        "and",
        "but",
        "still",
        "really",
        "want",
        "plan",
        "think",
        "thinking",
        "about",
        "need",
        "now",
        "today",
        "later",
        "maybe",
        "again",
        "just",
        "have",
        "has",
        "with",
        "for",
        "this",
        "that",
        "my",
        "your",
        "to",
        "现在",
        "最近",
        "还是",
        "已经",
        "一个",
        "这个",
        "那个",
        "但是",
        "然后",
        "感觉",
        "觉得",
        "想要",
        "打算",
        "准备",
        "考虑",
        "计划",
        "还没",
        "一直",
        "今天",
        "今晚",
        "quero",
        "ainda",
        "agora",
        "hoje",
        "pensando",
        "considerando",
    }
)


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _is_cjk_token(token: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in token)


def _topic_tokens(text: str) -> frozenset[str]:
    values: set[str] = set()
    for token in lexical_tokens(text):
        if token in _STOP_TOKENS:
            continue
        if _is_cjk_token(token):
            # The BM25 tokenizer emits a whole CJK run plus bigrams. Long
            # sentence-runs are poor topic identities; bounded n-grams are
            # stable enough for conservative explicit-line matching.
            if 2 <= len(token) <= 8:
                values.add(token)
        elif len(token) >= 3 or token.isdigit():
            values.add(token)
    return frozenset(values)


def _overlap_score(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _thread_text(thread: MemoryThread, product: MemoryProductStore) -> str:
    parts = [thread.open_question]
    if thread.working_summary is not None:
        parts.append(thread.working_summary)
    canonical = product.canonical_reader
    for memory_id in thread.current_support_ids:
        memory = canonical.get(memory_id)
        if memory is not None and memory.lifecycle is MemoryLifecycle.ACTIVE:
            parts.append(memory.content)
    return "\n".join(parts)


def _auto_thread_id(memory: CommittedMemory) -> str:
    digest = hashlib.sha256(
        json.dumps(
            ["mr-thread-auto-v1", json.loads(scope_json(memory.scope)), memory.memory_id],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"thread-auto-{digest}"


def _question_from(memory: CommittedMemory) -> str:
    compact = " ".join(memory.content.split())
    return compact[:512]


class DeterministicThreadUpdatePolicy:
    """Conservative no-model policy for explicit unfinished lines.

    It opens only explicit unresolved statements, updates one unambiguous
    lexical continuation, and resolves only an already-matched open Thread.
    It never creates a working_summary or marks a Thread mature; interpretation
    remains upstream/LCE work rather than being invented by string heuristics.
    """

    def __init__(self, *, match_threshold: float = 0.2, ambiguity_margin: float = 0.08) -> None:
        if not 0.0 <= match_threshold <= 1.0:
            raise ValueError("match_threshold must be in [0, 1]")
        if not 0.0 <= ambiguity_margin <= 1.0:
            raise ValueError("ambiguity_margin must be in [0, 1]")
        self._threshold = match_threshold
        self._margin = ambiguity_margin

    def decide(
        self,
        memory: CommittedMemory,
        open_threads: tuple[MemoryThread, ...],
        product: MemoryProductStore,
    ) -> ThreadUpdateDecision:
        if memory.lifecycle is not MemoryLifecycle.ACTIVE:
            return ThreadUpdateDecision(ThreadUpdateAction.NOOP)

        for thread in open_threads:
            if memory.memory_id in thread.handoff_memory_ids:
                return ThreadUpdateDecision(ThreadUpdateAction.NOOP)

        memory_tokens = _topic_tokens(memory.content)
        ranked: list[tuple[float, str, MemoryThread]] = []
        for thread in open_threads:
            if thread.scope != memory.scope:
                continue
            score = _overlap_score(memory_tokens, _topic_tokens(_thread_text(thread, product)))
            ranked.append((score, thread.thread_id, thread))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        matched: MemoryThread | None = None
        if ranked and ranked[0][0] >= self._threshold:
            if len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= self._margin:
                matched = ranked[0][2]

        is_resolution = _matches(_RESOLVE_PATTERNS, memory.content)
        if matched is None and is_resolution and len(open_threads) == 1:
            # An explicit close statement such as "算了，不买了" often omits the
            # noun. Only permit this fallback when there is exactly one open
            # line in the authorized Scope.
            matched = open_threads[0]

        if matched is not None:
            action = (
                ThreadUpdateAction.RESOLVE
                if is_resolution
                else ThreadUpdateAction.UPDATE
            )
            return ThreadUpdateDecision(action, thread_id=matched.thread_id)

        explicit_open = _matches(_OPEN_PATTERNS, memory.content)
        short_term = _matches(_SHORT_TERM_PATTERNS, memory.content)
        unresolved_marker = any(
            marker in memory.content.casefold() for marker in _CONTINUITY_MARKERS
        )
        if explicit_open and (not short_term or unresolved_marker) and memory_tokens:
            return ThreadUpdateDecision(
                ThreadUpdateAction.OPEN,
                thread_id=_auto_thread_id(memory),
                open_question=_question_from(memory),
            )
        return ThreadUpdateDecision(ThreadUpdateAction.NOOP)


class DeterministicThreadUpdater:
    def __init__(
        self,
        *,
        product: MemoryProductStore,
        policy: ThreadUpdatePolicy | None = None,
    ) -> None:
        self._product = product
        self._policy = policy or DeterministicThreadUpdatePolicy()

    def apply(self, memory: CommittedMemory, *, intent: ThreadUpdateIntent) -> str:
        if intent.memory_id != memory.memory_id:
            raise ValueError("Thread update intent does not match canonical Memory")

        open_threads = self._product.surface_threads(
            memory.scope,
            now=memory.committed_at,
            limit=100,
            decay_lambda=0.0,
        )
        decision = self._policy.decide(memory, open_threads, self._product)

        if decision.action is ThreadUpdateAction.NOOP:
            return f"thread-v1:noop:{memory.memory_id}"

        assert decision.thread_id is not None
        if decision.action is ThreadUpdateAction.OPEN:
            assert decision.open_question is not None
            thread = self._product.open_thread(
                thread_id=decision.thread_id,
                scope=memory.scope,
                open_question=decision.open_question,
                supporting_memory_ids=(memory.memory_id,),
                at=memory.committed_at,
            )
            return f"thread-v1:open:{thread.thread_id}"

        thread = self._product.get_thread(decision.thread_id)
        if thread is None:
            raise ValueError("selected Thread disappeared before update")
        if memory.memory_id in thread.handoff_memory_ids:
            return f"thread-v1:already:{thread.thread_id}"

        support = tuple(
            dict.fromkeys((*thread.current_support_ids, memory.memory_id))
        )[-MAX_THREAD_CURRENT_SUPPORT:]
        if decision.action is ThreadUpdateAction.RESOLVE:
            resolved = self._product.resolve_thread(
                thread.thread_id,
                memory_id=memory.memory_id,
                at=memory.committed_at,
            )
            return f"thread-v1:resolve:{resolved.thread_id}"

        updated = self._product.update_thread(
            thread.thread_id,
            supporting_memory_ids=support,
            at=memory.committed_at,
        )
        return f"thread-v1:update:{updated.thread_id}"


class ThreadUpdateWorker:
    def __init__(self, queue: ThreadUpdateQueue, updater: DeterministicThreadUpdater) -> None:
        self._queue = queue
        self._updater = updater

    def run_once(self, *, limit: int = 32) -> tuple[int, int]:
        succeeded = failed = 0
        for intent in self._queue.pending(limit):
            self._queue.begin_attempt(intent.memory_id)
            memory = self._queue.get(intent.memory_id)
            if memory is None:
                self._queue.fail(intent.memory_id, "canonical Memory missing")
                failed += 1
                continue
            try:
                ref = self._updater.apply(memory, intent=intent)
                self._queue.succeed(intent.memory_id, ref)
            except Exception as exc:
                self._queue.fail(intent.memory_id, f"{type(exc).__name__}: {exc}")
                failed += 1
            else:
                succeeded += 1
        return succeeded, failed
