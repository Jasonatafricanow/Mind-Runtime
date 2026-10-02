"""Sibling-output routing at the existing Hermes Body invocation, outside MR Core."""

import json
import logging

from mr_mem.memory.semantic_contracts import COMPILER_VERSION, SemanticDeltaErrorCode
from mr_mem.memory.semantic_store import SemanticSourceBinding

from xiyue.semantic_delta_protocol import PROMPT, parse_body_turn_result

_log = logging.getLogger("xiyue.semantic_delta")


def run_one_pass(
    agent,
    user_message,
    *,
    admission,
    sources,
    scope,
    interaction_id,
    message_id,
    activated_memories=(),
    guard=None,
    telemetry=None,
    **conversation_kwargs,
):
    """One normal Body invocation; canonical writes belong exclusively to admission."""
    activated_ids = tuple(memory.memory_id for memory in activated_memories)
    old_prompt = agent.ephemeral_system_prompt
    old_persist = agent._persist_session
    native_db = agent._session_db
    old_append = native_db.append_message
    old_stream = getattr(agent, "stream_delta_callback", None)
    captured = {"native_id": None, "prose": None, "submitted": False}
    processed = []
    metrics = dict(
        status="missing",
        point_count=0,
        dependency_count=0,
        deferred_count=0,
        validation_failed=False,
        commit_failed=False,
        sidecar_tokens=None,
        compiler_version=COMPILER_VERSION,
    )

    def append(*args, **kwargs):
        role = kwargs.get("role", args[1] if len(args) > 1 else None)
        session = kwargs.get("session_id", args[0] if args else None)
        if role == "user" and session == sources.session_id and captured["native_id"] is None:
            # Metadata on the host's own current-row append, never an inferred row/text match.
            kwargs["platform_message_id"] = message_id
            captured["native_id"] = old_append(*args, **kwargs)
            return captured["native_id"]
        return old_append(*args, **kwargs)

    def persist(messages, *args, **kwargs):
        if (
            messages
            and messages[-1].get("role") == "assistant"
            and not messages[-1].get("tool_calls")
            and not any(message is messages[-1] for message in processed)
        ):
            processed.append(messages[-1])
            envelope = parse_body_turn_result(messages[-1].get("content") or "")
            captured["prose"] = envelope.assistant_response
            messages[-1]["content"] = envelope.assistant_response
            if envelope.semantic_delta is not None and not captured["submitted"]:
                captured["submitted"] = True
                try:
                    ref = sources.current_user_source(scope, interaction_id)
                    if ref is None or str(captured["native_id"]) != ref.record_id:
                        raise ValueError("exact current native row receipt is unavailable")
                    binding = SemanticSourceBinding(scope, interaction_id, ref)
                    receipt = admission.resume_semantic_delta(binding)
                    if receipt is not None:
                        metrics["status"] = SemanticDeltaErrorCode.REPLAY.value
                    else:
                        receipt = admission.admit_semantic_delta(
                            envelope.semantic_delta,
                            binding=binding,
                            activated_memory_ids=activated_ids,
                        )
                        metrics["status"] = receipt.status
                    payload = envelope.semantic_delta
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    metrics["point_count"] = len(payload["points"])
                    metrics["dependency_count"] = len(payload["dependencies"])
                    metrics["deferred_count"] = sum(
                        p["status"] == "defer" or bool(p.get("unresolved_refs"))
                        for p in payload["points"]
                    )
                except Exception as exc:
                    code = getattr(exc, "code", SemanticDeltaErrorCode.INVALID_SCHEMA)
                    metrics["status"] = str(code)
                    metrics["commit_failed"] = code == SemanticDeltaErrorCode.COMMIT_FAILED
                    metrics["validation_failed"] = not metrics["commit_failed"]
                    _log.warning("Semantic Delta degraded: %s", code)
            elif envelope.semantic_delta is None:
                metrics["status"] = SemanticDeltaErrorCode.INVALID_SCHEMA.value
                metrics["validation_failed"] = True
        return old_persist(messages, *args, **kwargs)

    try:
        memory_context = [
            dict(memory_id=m.memory_id, content=m.content, lifecycle=m.lifecycle.value)
            for m in activated_memories
        ]
        agent.ephemeral_system_prompt = (
            (old_prompt or "")
            + "\n"
            + PROMPT
            + ("\nActivated canonical memories:\n" + json.dumps(memory_context, ensure_ascii=False))
        )
        # Buffer prose until sibling parsing and deterministic MR guard have run.
        agent.stream_delta_callback = None
        conversation_kwargs["stream_callback"] = None
        agent._persist_session = persist
        native_db.append_message = append
        result = agent.run_conversation(user_message, **conversation_kwargs)
        envelope = parse_body_turn_result(result.get("final_response") or "")
        prose = captured["prose"] if captured["prose"] is not None else envelope.assistant_response
        if guard is not None and prose and not guard(prose):
            prose = ""
        result["final_response"] = prose
        return result
    finally:
        agent.ephemeral_system_prompt = old_prompt
        agent.stream_delta_callback = old_stream
        agent._persist_session = old_persist
        native_db.append_message = old_append
        event = {"semantic_delta." + key: value for key, value in metrics.items()}
        _log.info("semantic_delta %s", json.dumps(event))
        if telemetry is not None:
            try:
                telemetry(event)
            except Exception:
                _log.debug("Semantic Delta telemetry sink unavailable", exc_info=True)
