"""Optional Hermes native ingestion at the existing MR ingress and commit seams."""

import logging
import os
import threading
from pathlib import Path

_lock = threading.RLock()
_log = logging.getLogger("xiyue.native_memory")


def enabled():
    return os.environ.get("MR_MEM_NATIVE_ENABLED", "false").strip().lower() in {
        "true", "1", "on", "yes",
    }


def sync_native_memory(agent, source, session_id, adapter, *, compile_pending=False, compiler=None):
    if not enabled():
        return {"status": "disabled"}
    from mr_mem import Scope, ScopeDomain
    from mr_mem_aml.config import RuntimeConfig
    from mr_mem_aml.native_ingest import NativeMemory

    from xiyue.native_memory_source import HermesNativeSource

    if adapter is None or adapter._scope.domain.value != "user" or not session_id:
        raise ValueError("native memory needs a bound USER adapter and native session")
    if os.environ.get("SEMANTIC_DELTA_V1_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        raise ValueError("select one semantic writer: native batches or Semantic Delta")
    native_user = getattr(source, "user_id", None)
    if native_user is None:
        raise ValueError("native source owner required")
    config = RuntimeConfig.load(os.environ["MR_MEM_NATIVE_CONFIG"])
    native_path = Path(agent._session_db.db_path).resolve()
    canonical = (config.data_dir / "memory.sqlite").resolve()
    if (canonical != Path(os.environ["MR_MEM_CANONICAL_DB"]).resolve()
            or native_path.is_relative_to(config.data_dir.resolve())):
        raise ValueError("native writer and MR reader must share a separate canonical database")
    if config.path_a_engine == "tree" and Path(os.environ["MR_MEM_LINE_ROOT"]).resolve() != (
        config.data_dir / "lce_tree"
    ).resolve():
        raise ValueError("native writer and MR reader must share the same Line root")
    scope = Scope(ScopeDomain.USER, user_id=adapter._scope.user_id)
    with _lock:
        reader = HermesNativeSource(native_path, scope=scope, user_id=native_user,
                                   namespace=adapter._runtime_id + ":hermes")
        native = None
        try:
            native = NativeMemory(config, user_id=scope.user_id, reader=reader, compiler=compiler)
            sessions = sorted(set(native.source.sessions()) | {session_id})
            result = {sid: native.synchronize(sid, reader.snapshot(sid),
                                              compile_pending=compile_pending) for sid in sessions}
            agent._mr_native_memory_status = result
            return result
        except Exception as exc:
            # Do not turn a read/ownership failure into successful empty context.
            agent._mr_native_memory_status = {"status": "failed", "error_type": type(exc).__name__}
            _log.warning("Native memory synchronization failed (%s)", type(exc).__name__)
            raise
        finally:
            if native is not None:
                native.close()
            reader.close()
