"""Typed boundary values for the AML host adapter."""

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
    id: str
    content: str
    score: float
    created_at: str
    layer: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "id"),
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


@dataclass(frozen=True, slots=True)
class AmlRuntimeConfig:
    result_cap: int = 20
    candidate_limit: int = 50
    max_context_characters: int = 32768
    thread_enabled: bool = True
    lce_enabled: bool = True
    thread_cap: int = 2
    lce_cap: int = 4
    retrieval_cache_users: int = 12
    hyde_min_results: int = 20

    def __post_init__(self) -> None:
        for value, name, low, high in (
            (self.result_cap, "result_cap", 1, 100),
            (self.candidate_limit, "candidate_limit", 1, 100),
            (
                self.max_context_characters,
                "max_context_characters",
                1024,
                65536,
            ),
            (self.thread_cap, "thread_cap", 0, 20),
            (self.lce_cap, "lce_cap", 0, 20),
            (
                self.retrieval_cache_users,
                "retrieval_cache_users",
                1,
                1024,
            ),
            (self.hyde_min_results, "hyde_min_results", 1, 100),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(
                    f"{name} must be an integer in [{low}, {high}]"
                )
        if type(self.thread_enabled) is not bool or type(
            self.lce_enabled
        ) is not bool:
            raise TypeError("thread_enabled and lce_enabled must be bool")
