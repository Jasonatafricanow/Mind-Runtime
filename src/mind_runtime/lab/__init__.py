"""MR Lab runtime lifecycle (MR-RUNTIME-03).

One MR Core + LAB RuntimeBinding (ADR-0020) + isolated storage namespace.
Fork is DEFERRED — no authoritative snapshot primitive exists (see
docs/audits/MR_LAB_RUNTIME_LIFECYCLE_AUDIT.md).
"""

from mind_runtime.lab.runtime import (
    LAB_AGENT_ID,
    LabDestroyRefused,
    LabRuntime,
    LabRuntimeError,
    LabRuntimeInfo,
    LabRuntimeSpec,
    create_lab_runtime,
    destroy_lab_runtime,
    inspect_lab_runtime,
)

__all__ = [
    "LAB_AGENT_ID",
    "LabDestroyRefused",
    "LabRuntime",
    "LabRuntimeError",
    "LabRuntimeInfo",
    "LabRuntimeSpec",
    "create_lab_runtime",
    "destroy_lab_runtime",
    "inspect_lab_runtime",
]
