"""Optional durable-host hooks for the core HTTP integration."""

import os
import threading
from pathlib import Path

from mind_runtime.integrations.mr_mem_delivery import NativeMemoryDelivery

_lock = threading.RLock()


def sync_core_memory(agent, source, session_id, adapter, *, after_commit=False):
    if os.environ.get("MR_MEM_NATIVE_HTTP_ENABLED", "false").strip().lower() not in {
        "true", "1", "yes", "on",
    }:
        return {"status": "disabled"}
    if adapter is None or adapter.memory is None or source.user_id is None:
        raise ValueError("native memory requires a bound core client and source owner")
    with _lock:
        delivery = None
        try:
            delivery = NativeMemoryDelivery(
                Path(agent._session_db.db_path), Path(os.environ["MR_MEM_NATIVE_JOURNAL"]),
                adapter.memory, native_user=str(source.user_id), runtime_id=adapter._runtime_id,
                baseline=int(os.environ["MR_MEM_NATIVE_BASELINE"]),
            )
            result = delivery.synchronize(session_id, after_commit=after_commit)
            agent._mr_native_memory_status = result
            return result
        except Exception as exc:
            agent._mr_native_memory_status = {"status": "pending" if after_commit else "blocked",
                                              "error_type": type(exc).__name__}
            if not after_commit:
                raise
            # Delivery already committed. Retry on the next successful commit,
            # never rerun Body or reinterpret memory failure as failed delivery.
            return agent._mr_native_memory_status
        finally:
            if delivery is not None:
                delivery.close()
