"""Typed AML boundary values; none of these are MR core contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AmlMessage:
    role: str
    content: str
    timestamp: float | int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("role must be nonempty")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be nonempty")
        if self.timestamp is not None and (
            isinstance(self.timestamp, bool)
            or not isinstance(self.timestamp, (int, float))
        ):
            raise TypeError("timestamp must be numeric when supplied")


@dataclass(frozen=True, slots=True)
class AmlAddRequest:
    request_id: str
    user_id: str
    session_id: str
    messages: tuple[AmlMessage, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.request_id, "request_id"),
            (self.user_id, "user_id"),
            (self.session_id, "session_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if not self.messages:
            raise ValueError("messages must be nonempty")


@dataclass(frozen=True, slots=True)
class AmlSearchRequest:
    user_id: str
    query: str
    top_k: int
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id must be nonempty")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be nonempty")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 100:
            raise ValueError("top_k must be an integer in [1, 100]")
        if any(not isinstance(item, str) for item in self.options):
            raise TypeError("options must contain strings")


@dataclass(frozen=True, slots=True)
class AmlSearchItem:
    item_id: str
    content: str
    score: float
    created_at: str
    layer: str
    covers_memory_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.item_id, "item_id"),
            (self.content, "content"),
            (self.created_at, "created_at"),
            (self.layer, "layer"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if isinstance(self.score, bool) or not isinstance(
            self.score, (int, float)
        ):
            raise TypeError("score must be numeric")
        if (
            not isinstance(self.covers_memory_ids, tuple)
            or len(set(self.covers_memory_ids))
            != len(self.covers_memory_ids)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.covers_memory_ids
            )
        ):
            raise ValueError(
                "covers_memory_ids must contain unique nonempty IDs"
            )


@dataclass(frozen=True, slots=True)
class AmlRuntimeConfig:
    result_cap: int = 30
    candidate_limit: int = 70
    max_context_characters: int = 65536
    thread_enabled: bool = True
    lce_enabled: bool = True
    lce_bootstrap_on_add: bool = True
    thread_cap: int = 4
    lce_cap: int = 8
    hyde_min_results: int = 20

    def __post_init__(self) -> None:
        for value, name, low, high in (
            (self.result_cap, "result_cap", 1, 100),
            (self.candidate_limit, "candidate_limit", 1, 100),
            (
                self.max_context_characters,
                "max_context_characters",
                1024,
                262144,
            ),
            (self.thread_cap, "thread_cap", 0, 20),
            (self.lce_cap, "lce_cap", 0, 20),
            (self.hyde_min_results, "hyde_min_results", 1, 100),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(
                    f"{name} must be an integer in [{low}, {high}]"
                )
        for value, name in (
            (self.thread_enabled, "thread_enabled"),
            (self.lce_enabled, "lce_enabled"),
            (self.lce_bootstrap_on_add, "lce_bootstrap_on_add"),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} must be bool")
