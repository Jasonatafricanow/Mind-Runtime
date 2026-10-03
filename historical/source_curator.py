"""Deterministic source eligibility; not Memory lifecycle or factual truth."""

from enum import StrEnum


class SourceDisposition(StrEnum):
    COMPILE = "COMPILE"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    IGNORE = "IGNORE"


OPERATIONAL_TYPES = frozenset(
    {
        "agent_progress",
        "agent_execution",
        "tool_call",
        "shell_command",
        "stdout",
        "stderr",
        "ci_output",
        "git_operation",
        "patch_progress",
        "test_progress",
        "polling",
        "retry",
        "http_transient",
        "token_accounting",
        "latency",
        "trace",
        "background_task",
        "file_operation",
        "temporary_plan",
        "session_meta",
    }
)


class HistoricalSourceCurator:
    def classify(self, source, *, necessary_context=False):
        if source.role == "agent" or source.record_type in OPERATIONAL_TYPES:
            return SourceDisposition.IGNORE
        if source.role == "user" and isinstance(source.content, str) and source.content.strip():
            # A, 对, 继续, 不是 may all establish a commitment. No length threshold.
            return SourceDisposition.COMPILE
        if source.role == "tool":
            return SourceDisposition.CONTEXT_ONLY if necessary_context else SourceDisposition.IGNORE
        # Unknown provenance cannot become canonical cognition.
        return SourceDisposition.CONTEXT_ONLY
