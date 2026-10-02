"""Hermes 0.19.0 composition factory; optional MR-Mem imports stay outside MR Core."""

import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger("xiyue.semantic_delta")


def enabled():
    return os.environ.get("SEMANTIC_DELTA_V1_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class _Clock:
    def now(self):
        return datetime.now(UTC)


def run_gateway_turn(
    agent, user_message, *, seam, handle, source, session_id, message_id, **conversation_kwargs
):
    if not enabled():
        return agent.run_conversation(user_message, **conversation_kwargs)

    # All setup is before Body. A setup failure can degrade to one normal invocation.
    core = sources = None
    try:
        from mr_mem import MemoryCore, Scope, ScopeDomain
        from mr_mem.memory.providers.bm25 import BM25RetrievalProvider
        from mr_mem.memory.retrieval import MemoryRetrievalQuery, MemoryRetrievalService

        from xiyue.semantic_delta_composition import run_one_pass
        from xiyue.semantic_delta_source import HermesDeltaSources

        adapter = seam.get_mr_adapter() if seam is not None else None
        if adapter is None or handle is None or not message_id:
            raise ValueError("system MR interaction/adapter and platform message ID required")
        # Explicit standalone MR-Mem path; never point a legacy MR reader at native memories.
        canonical_path = Path(os.environ["MR_MEM_CANONICAL_DB"])
        if not canonical_path.is_absolute():
            raise ValueError("MR_MEM_CANONICAL_DB must be an absolute path")
        scope_fields = asdict(adapter._scope)
        scope_fields["domain"] = ScopeDomain(scope_fields["domain"].value)
        scope = Scope(**scope_fields)
        native_user = getattr(source, "user_id", None)
        if native_user is None:
            raise ValueError("native session owner required")
        sources = HermesDeltaSources(
            Path(agent._session_db.db_path),
            scope=scope,
            namespace=adapter._runtime_id + ":hermes",
            session_id=session_id,
            message_id=message_id,
            user_id=str(native_user),
            interaction_id=handle.interaction_id,
            channel=handle.channel,
        )
        core = MemoryCore(canonical_path)
        # Reuse the existing bounded canonical retrieval policy, with no new reranker.
        retrieval = MemoryRetrievalService(
            store=core.canonical, provider=BM25RetrievalProvider(core.load_all())
        )
        activated = tuple(
            item.memory
            for item in retrieval.search(MemoryRetrievalQuery(scope, str(user_message)[:4096]))
        )
        admission = core.semantic_admission(
            sources=sources, clock=_Clock(), origin_runtime_id=adapter._runtime_id
        )
    except Exception:
        if core is not None:
            core.close()
        if sources is not None:
            sources.close()
        _log.warning("Semantic Delta setup degraded", exc_info=True)
        return agent.run_conversation(user_message, **conversation_kwargs)

    try:
        # Body errors propagate through the existing host lifecycle, never a second call.
        return run_one_pass(
            agent,
            user_message,
            admission=admission,
            sources=sources,
            scope=scope,
            interaction_id=handle.interaction_id,
            message_id=message_id,
            activated_memories=activated,
            guard=lambda prose: adapter.guard_turn_prose(handle, prose),
            **conversation_kwargs,
        )
    finally:
        core.close()
        sources.close()
