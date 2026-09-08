"""D1.1 Interaction / Scope / Authority / Ownership contract tests."""

from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Interaction,
    InteractionStatus,
    Ownership,
    Scope,
    ScopeDomain,
    Syncable,
    SyncFields,
    WritePolicy,
)


def make_user_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_agent_scope() -> Scope:
    return Scope(domain=ScopeDomain.AGENT, agent_id="agent-1", persona_id="kayla")


def make_interaction(
    *,
    status: InteractionStatus | None = None,
    committed_at: datetime | None = None,
) -> Interaction:
    if status is None:
        status = InteractionStatus("open")
    return Interaction(
        interaction_id="interaction-1",
        scope=Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1"),
        channel="telegram",
        session_id="session-1",
        turn_id="turn-1",
        started_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        committed_at=committed_at,
        status=status,
    )


def test_all_d1_1_enums_are_string_enums_with_approved_values() -> None:
    expected = {
        ScopeDomain: {"user", "agent", "relationship", "interaction", "world"},
        AuthorityLevel: {"none", "asserted", "observed", "verified", "system"},
        WritePolicy: {"read_only", "single_writer", "authorized_writer"},
        InteractionStatus: {"open", "committed", "aborted"},
    }

    for enum_type, values in expected.items():
        assert issubclass(enum_type, StrEnum)
        assert {member.value for member in enum_type} == values
        assert all(isinstance(member, str) for member in enum_type)


@pytest.mark.parametrize(
    ("domain_value", "identity", "expected"),
    [
        ("user", {"user_id": "user-1"}, {"user_id": "user-1"}),
        (
            "agent",
            {"agent_id": "agent-1", "persona_id": "kayla"},
            {"agent_id": "agent-1", "persona_id": "kayla"},
        ),
        (
            "relationship",
            {"relationship_id": "relationship-1", "persona_id": "kayla"},
            {"relationship_id": "relationship-1", "persona_id": "kayla"},
        ),
        (
            "interaction",
            {"interaction_id": "interaction-1"},
            {"interaction_id": "interaction-1"},
        ),
        ("world", {"world_id": "world-1"}, {"world_id": "world-1"}),
    ],
)
def test_scope_domain_carries_only_its_structured_identity(
    domain_value: str,
    identity: dict[str, str],
    expected: dict[str, str],
) -> None:
    scope = Scope(domain=ScopeDomain(domain_value), **identity)
    assert scope.domain.value in {"user", "agent", "relationship", "interaction", "world"}
    actual = {
        name: getattr(scope, name)
        for name in (
            "user_id",
            "agent_id",
            "persona_id",
            "relationship_id",
            "world_id",
            "interaction_id",
        )
        if getattr(scope, name) is not None
    }
    assert actual == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"domain": "user"},
        {"domain": "agent", "persona_id": "kayla"},
        {"domain": "agent", "agent_id": "agent-1"},
        {"domain": "relationship", "persona_id": "kayla"},
        {"domain": "relationship", "relationship_id": "relationship-1"},
        {"domain": "interaction"},
        {"domain": "world"},
        {"domain": "user", "user_id": ""},
        {"domain": "agent", "agent_id": "agent-1", "persona_id": "   "},
    ],
)
def test_scope_rejects_missing_or_empty_required_identity(kwargs: dict[str, object]) -> None:
    kwargs = {**kwargs, "domain": ScopeDomain(str(kwargs["domain"]))}
    with pytest.raises(ValueError, match="requires non-empty"):
        Scope(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"domain": "user", "user_id": "user-1", "agent_id": "agent-1"},
        {
            "domain": "agent",
            "agent_id": "agent-1",
            "persona_id": "kayla",
            "user_id": "user-1",
        },
        {
            "domain": "relationship",
            "relationship_id": "relationship-1",
            "persona_id": "kayla",
            "world_id": "world-1",
        },
        {
            "domain": "interaction",
            "interaction_id": "interaction-1",
            "user_id": "user-1",
        },
        {"domain": "world", "world_id": "world-1", "persona_id": "kayla"},
    ],
)
def test_scope_rejects_every_identity_forbidden_by_its_domain(
    kwargs: dict[str, object],
) -> None:
    kwargs = {**kwargs, "domain": ScopeDomain(str(kwargs["domain"]))}
    with pytest.raises(ValueError, match="forbids"):
        Scope(**kwargs)  # type: ignore[arg-type]


def test_scope_rejects_a_non_enum_domain() -> None:
    with pytest.raises(ValueError, match="ScopeDomain"):
        Scope(domain="user", user_id="user-1")  # type: ignore[arg-type]


def test_scope_authority_and_ownership_schemas_are_exact() -> None:
    assert [field.name for field in fields(Scope)] == [
        "domain",
        "user_id",
        "agent_id",
        "persona_id",
        "relationship_id",
        "world_id",
        "interaction_id",
    ]
    assert [field.name for field in fields(Authority)] == ["scope", "level", "source_id"]
    assert [field.name for field in fields(Ownership)] == [
        "scope",
        "write_policy",
        "owner_runtime_id",
        "owner_persona_id",
    ]


def test_authority_source_rules_are_fail_closed() -> None:
    scope = make_user_scope()
    assert Authority(scope=scope, level=AuthorityLevel.NONE).source_id is None

    for level in (
        AuthorityLevel.ASSERTED,
        AuthorityLevel.OBSERVED,
        AuthorityLevel.VERIFIED,
        AuthorityLevel.SYSTEM,
    ):
        assert Authority(scope=scope, level=level, source_id="source-1").source_id == "source-1"

    with pytest.raises(ValueError, match="NONE forbids"):
        Authority(scope=scope, level=AuthorityLevel.NONE, source_id="source-1")
    for invalid_source in (None, "", "   "):
        with pytest.raises(ValueError, match="requires non-empty"):
            Authority(scope=scope, level=AuthorityLevel.OBSERVED, source_id=invalid_source)
    with pytest.raises(ValueError, match="AuthorityLevel"):
        Authority(scope=scope, level="observed", source_id="source-1")  # type: ignore[arg-type]


def test_ownership_private_persona_must_match_scope() -> None:
    agent_scope = make_agent_scope()
    ownership = Ownership(
        scope=agent_scope,
        write_policy=WritePolicy.SINGLE_WRITER,
        owner_runtime_id="runtime-1",
        owner_persona_id="kayla",
    )
    assert ownership.owner_persona_id == agent_scope.persona_id

    relationship_scope = Scope(
        domain=ScopeDomain.RELATIONSHIP,
        relationship_id="relationship-1",
        persona_id="lara",
    )
    assert (
        Ownership(
            scope=relationship_scope,
            write_policy=WritePolicy.READ_ONLY,
            owner_persona_id="lara",
        ).owner_persona_id
        == "lara"
    )

    for invalid_owner in (None, "", "kayla"):
        with pytest.raises(ValueError, match="match scope.persona_id"):
            Ownership(
                scope=relationship_scope,
                write_policy=WritePolicy.READ_ONLY,
                owner_persona_id=invalid_owner,
            )


def test_ownership_non_private_scope_forbids_persona_owner() -> None:
    with pytest.raises(ValueError, match="forbids owner_persona_id"):
        Ownership(
            scope=make_user_scope(),
            write_policy=WritePolicy.READ_ONLY,
            owner_persona_id="kayla",
        )


@pytest.mark.parametrize("policy_value", ["single_writer", "authorized_writer"])
def test_writable_ownership_requires_runtime_owner(policy_value: str) -> None:
    policy = WritePolicy(policy_value)
    for invalid_owner in (None, "", "   "):
        with pytest.raises(ValueError, match="requires non-empty owner_runtime_id"):
            Ownership(
                scope=make_user_scope(),
                write_policy=policy,
                owner_runtime_id=invalid_owner,
            )

    assert (
        Ownership(
            scope=make_user_scope(),
            write_policy=policy,
            owner_runtime_id="runtime-1",
        ).owner_runtime_id
        == "runtime-1"
    )


def test_read_only_ownership_allows_no_runtime_owner() -> None:
    ownership = Ownership(scope=make_user_scope(), write_policy=WritePolicy.READ_ONLY)
    assert ownership.owner_runtime_id is None
    assert ownership.owner_persona_id is None
    with pytest.raises(ValueError, match="non-empty owner_runtime_id"):
        Ownership(
            scope=make_user_scope(),
            write_policy=WritePolicy.READ_ONLY,
            owner_runtime_id="   ",
        )
    with pytest.raises(ValueError, match="WritePolicy"):
        Ownership(scope=make_user_scope(), write_policy="read_only")  # type: ignore[arg-type]


def test_interaction_schema_is_the_frozen_main_index_and_not_syncable() -> None:
    interaction = make_interaction()
    assert [field.name for field in fields(Interaction)] == [
        "interaction_id",
        "scope",
        "channel",
        "session_id",
        "turn_id",
        "started_at",
        "committed_at",
        "status",
    ]
    assert not isinstance(interaction, Syncable)


def test_interaction_rejects_a_non_enum_status() -> None:
    with pytest.raises(ValueError, match="InteractionStatus"):
        Interaction(
            interaction_id="interaction-1",
            scope=Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1"),
            channel="telegram",
            session_id="session-1",
            turn_id="turn-1",
            started_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            committed_at=None,
            status="open",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("status_value", ["open", "aborted"])
def test_uncommitted_interaction_statuses_forbid_committed_at(
    status_value: str,
) -> None:
    status = InteractionStatus(status_value)
    assert make_interaction(status=status).committed_at is None
    with pytest.raises(ValueError, match="forbids committed_at"):
        make_interaction(
            status=status,
            committed_at=datetime(2026, 8, 20, 9, 1, tzinfo=UTC),
        )


def test_committed_interaction_requires_ordered_commit_time() -> None:
    committed_at = datetime(2026, 8, 20, 9, 1, tzinfo=UTC)
    interaction = make_interaction(
        status=InteractionStatus.COMMITTED,
        committed_at=committed_at,
    )
    assert interaction.committed_at == committed_at

    with pytest.raises(ValueError, match="requires committed_at"):
        make_interaction(status=InteractionStatus.COMMITTED)
    with pytest.raises(ValueError, match="cannot precede"):
        make_interaction(
            status=InteractionStatus.COMMITTED,
            committed_at=datetime(2026, 8, 20, 8, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("interaction_id", ""),
        ("channel", "   "),
        ("session_id", ""),
        ("turn_id", "   "),
    ],
)
def test_interaction_identity_fields_must_be_non_empty(field_name: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "interaction_id": "interaction-1",
        "scope": Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1"),
        "channel": "telegram",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "started_at": datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        "committed_at": None,
        "status": InteractionStatus.OPEN,
    }
    kwargs[field_name] = value
    with pytest.raises(ValueError, match="non-empty"):
        Interaction(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "started_at",
    [
        datetime(2026, 8, 20, 9, 0),
        datetime(2026, 8, 20, 11, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_interaction_started_at_must_be_aware_utc(started_at: datetime) -> None:
    with pytest.raises(ValueError, match="started_at must be aware UTC"):
        Interaction(
            interaction_id="interaction-1",
            scope=Scope(domain=ScopeDomain.INTERACTION, interaction_id="interaction-1"),
            channel="telegram",
            session_id="session-1",
            turn_id="turn-1",
            started_at=started_at,
            committed_at=None,
            status=InteractionStatus.OPEN,
        )


@pytest.mark.parametrize(
    "committed_at",
    [
        datetime(2026, 8, 20, 9, 1),
        datetime(2026, 8, 20, 11, 1, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_interaction_committed_at_must_be_aware_utc(committed_at: datetime) -> None:
    with pytest.raises(ValueError, match="committed_at must be aware UTC"):
        make_interaction(status=InteractionStatus.COMMITTED, committed_at=committed_at)


@pytest.mark.parametrize("dataclass_type", [SyncFields, Scope, Authority, Ownership, Interaction])
def test_all_d1_1_dataclasses_are_frozen_and_slotted(dataclass_type: type[object]) -> None:
    assert is_dataclass(dataclass_type)
    assert "__slots__" in dataclass_type.__dict__

    scope = make_user_scope()
    instances: dict[type[Any], Any] = {
        SyncFields: SyncFields(scope, "runtime-1", "object-1", 1, "idem-1"),
        Scope: scope,
        Authority: Authority(scope, AuthorityLevel.NONE),
        Ownership: Ownership(scope, WritePolicy.READ_ONLY),
        Interaction: make_interaction(),
    }
    instance = instances[dataclass_type]
    assert not hasattr(instance, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(instance, next(field.name for field in fields(instance)), "changed")
