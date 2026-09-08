"""D4.1 validity-policy vocabulary and StateDefinitionRegistry tests."""

from datetime import timedelta

import pytest

from mind_runtime.contracts import StateDefinition, StateDomain, StateValueType
from mind_runtime.state.definitions import (
    StateDefinitionRegistry,
    ValidityKind,
    ValidityPolicy,
    parse_validity_policy,
)


def make_definition(
    key: str = "user.health.headache",
    *,
    domain: StateDomain = StateDomain.USER,
    policy: str | None = None,
) -> StateDefinition:
    return StateDefinition(
        key=key,
        domain=domain,
        value_type=StateValueType.CATEGORICAL,
        dynamics_policy="ttl_lifecycle",
        default_validity_policy=policy,
        bounds=None,
    )


# --- policy parsing ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, ValidityPolicy(kind=ValidityKind.INDEFINITE)),
        ("indefinite", ValidityPolicy(kind=ValidityKind.INDEFINITE)),
        (
            "event_only",
            ValidityPolicy(kind=ValidityKind.EVENT_ONLY, refresh_on_reaffirm=False),
        ),
        ("ttl:90s", ValidityPolicy(kind=ValidityKind.TTL, ttl=timedelta(seconds=90))),
        ("ttl:30m", ValidityPolicy(kind=ValidityKind.TTL, ttl=timedelta(minutes=30))),
        ("ttl:6h", ValidityPolicy(kind=ValidityKind.TTL, ttl=timedelta(hours=6))),
        ("ttl:2d", ValidityPolicy(kind=ValidityKind.TTL, ttl=timedelta(days=2))),
    ],
)
def test_parse_validity_policy_grammar(text: str | None, expected: ValidityPolicy) -> None:
    assert parse_validity_policy(text) == expected


@pytest.mark.parametrize("text", ["ttl:", "ttl:abc", "ttl:0s", "ttl:6x", "ttl:6", "bogus"])
def test_parse_validity_policy_fails_closed(text: str) -> None:
    with pytest.raises(ValueError, match="validity|ttl"):
        parse_validity_policy(text)


def test_validity_policy_contract() -> None:
    with pytest.raises(ValueError, match="requires a ttl"):
        ValidityPolicy(kind=ValidityKind.TTL, ttl=None)
    with pytest.raises(ValueError, match="forbids a ttl"):
        ValidityPolicy(kind=ValidityKind.INDEFINITE, ttl=timedelta(hours=1))
    with pytest.raises(ValueError, match="positive"):
        ValidityPolicy(kind=ValidityKind.TTL, ttl=timedelta(0))


# --- registry ---


def test_registry_register_and_lookup() -> None:
    definition = make_definition(policy="ttl:6h")
    registry = StateDefinitionRegistry((definition,))
    assert registry.get(definition.key) is definition
    assert registry.require(definition.key) is definition
    assert registry.all() == (definition,)


def test_registry_rejects_duplicate_definition() -> None:
    registry = StateDefinitionRegistry()
    registry.register(make_definition())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_definition())


def test_registry_require_unknown_fails_closed() -> None:
    registry = StateDefinitionRegistry()
    assert registry.get("user.unknown") is None
    with pytest.raises(ValueError, match="no state definition"):
        registry.require("user.unknown")


def test_registry_resolves_validity_policy_from_definition() -> None:
    registry = StateDefinitionRegistry(
        (
            make_definition(key="user.health.headache", policy="ttl:6h"),
            make_definition(key="user.planning.calligraphy", policy="event_only"),
            make_definition(key="user.sleep.phase"),
        )
    )
    assert registry.validity_policy("user.health.headache") == ValidityPolicy(
        kind=ValidityKind.TTL, ttl=timedelta(hours=6)
    )
    assert registry.validity_policy("user.planning.calligraphy") == ValidityPolicy(
        kind=ValidityKind.EVENT_ONLY, refresh_on_reaffirm=False
    )
    assert registry.validity_policy("user.sleep.phase") == ValidityPolicy(
        kind=ValidityKind.INDEFINITE
    )


def test_registry_unknown_dimension_defaults_to_indefinite() -> None:
    registry = StateDefinitionRegistry()
    assert registry.validity_policy("user.never.defined") == ValidityPolicy(
        kind=ValidityKind.INDEFINITE
    )


def test_registry_constructor_accepts_definitions() -> None:
    registry = StateDefinitionRegistry((make_definition(),))
    assert registry.all() == (make_definition(),)
