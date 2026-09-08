"""D1.2 Evidence / Observation / State / Transition contract tests."""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Observation,
    RuntimeState,
    Scope,
    ScopeDomain,
    StateDefinition,
    StateDomain,
    StateTransition,
    StateValueType,
    Syncable,
    SyncFields,
    TransitionIntent,
)
from mind_runtime.contracts.common import freeze_mapping

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def make_scope() -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id="user-1")


def make_sync(scope: Scope, object_id: str, *, version: int = 1) -> SyncFields:
    return SyncFields(scope, "runtime-1", object_id, version, f"idem-{object_id}")


def as_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def make_evidence(*, scope: Scope | None = None, payload: object | None = None) -> Evidence:
    factual_scope = scope or make_scope()
    factual_payload = {"text": "I am hungry", "labels": ["food"]} if payload is None else payload
    return Evidence(
        id="evidence-1",
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id="message-1",
        authority_level=AuthorityLevel.ASSERTED,
        authority=Authority(factual_scope, AuthorityLevel.ASSERTED, "message-1"),
        occurred_at=NOW,
        received_at=NOW,
        payload=factual_payload,
        sync=make_sync(factual_scope, "evidence-1"),
    )


def make_observation(*, scope: Scope | None = None, value: object | None = None) -> Observation:
    factual_scope = scope or make_scope()
    observation_value = {"status": "hungry", "sources": ["evidence-1"]} if value is None else value
    return Observation(
        id="observation-1",
        interaction_id="interaction-1",
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.hunger",
        value=observation_value,
        confidence=0.8,
        observed_at=NOW,
        evidence_refs=("evidence-1",),
        sync=make_sync(factual_scope, "observation-1"),
    )


def make_state(
    *,
    scope: Scope | None = None,
    state_id: str = "state-1",
    dimension: str = "user.hunger",
    value: object | None = None,
) -> RuntimeState:
    factual_scope = scope or make_scope()
    state_value = {"status": "hungry", "history": ["observed"]} if value is None else value
    return RuntimeState(
        state_id=state_id,
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        dimension=dimension,
        value=state_value,
        status="current",
        valid_from=NOW,
        valid_until=None,
        relevant_until=None,
        last_observed_at=NOW,
        evidence_refs=("evidence-1",),
        transition_refs=(),
        version=1,
        updated_at=NOW,
        sync=make_sync(factual_scope, state_id),
    )


def make_intent(*, scope: Scope | None = None) -> TransitionIntent:
    factual_scope = scope or make_scope()
    return TransitionIntent(
        intent_id="intent-1",
        interaction_id="interaction-1",
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        target_dimension="user.hunger",
        before=make_state(scope=factual_scope, state_id="state-before"),
        proposed_after=make_state(scope=factual_scope, state_id="state-after"),
        cause_refs=("evidence-1",),
        policy="reconciler",
        confidence=0.8,
        commit_phase="ingest",
    )


def make_transition(*, scope: Scope | None = None) -> StateTransition:
    factual_scope = scope or make_scope()
    return StateTransition(
        transition_id="transition-1",
        scope=factual_scope,
        origin_runtime_id="runtime-1",
        intent_id="intent-1",
        from_state=make_state(scope=factual_scope, state_id="state-before"),
        to_state=make_state(scope=factual_scope, state_id="state-after"),
        committed_at=NOW,
        sync=make_sync(factual_scope, "transition-1"),
    )


def test_d1_2_schemas_preserve_frozen_baseline_fields() -> None:
    assert [field.name for field in fields(Evidence)] == [
        "id",
        "source_type",
        "source_id",
        "authority_level",
        "occurred_at",
        "received_at",
        "payload",
        "scope",
        "origin_runtime_id",
        "authority",
        "sync",
    ]
    assert [field.name for field in fields(Observation)] == [
        "id",
        "interaction_id",
        "scope",
        "type",
        "key",
        "value",
        "confidence",
        "observed_at",
        "evidence_refs",
        "origin_runtime_id",
        "sync",
    ]
    assert [field.name for field in fields(StateDefinition)] == [
        "key",
        "domain",
        "value_type",
        "dynamics_policy",
        "default_validity_policy",
        "bounds",
    ]
    assert [field.name for field in fields(RuntimeState)] == [
        "state_id",
        "scope",
        "dimension",
        "value",
        "status",
        "valid_from",
        "valid_until",
        "relevant_until",
        "last_observed_at",
        "evidence_refs",
        "transition_refs",
        "updated_at",
        "origin_runtime_id",
        "version",
        "sync",
    ]
    assert [field.name for field in fields(TransitionIntent)] == [
        "intent_id",
        "interaction_id",
        "scope",
        "origin_runtime_id",
        "target_dimension",
        "before",
        "proposed_after",
        "cause_refs",
        "policy",
        "confidence",
        "commit_phase",
    ]
    assert [field.name for field in fields(StateTransition)] == [
        "transition_id",
        "scope",
        "origin_runtime_id",
        "intent_id",
        "from_state",
        "to_state",
        "committed_at",
        "sync",
    ]


def test_evidence_and_observation_have_no_expiring_lifecycle_schema() -> None:
    forbidden = {"valid_from", "valid_until", "relevant_until", "status", "expires_at"}
    assert forbidden.isdisjoint(field.name for field in fields(Evidence))
    assert forbidden.isdisjoint(field.name for field in fields(Observation))


def test_all_d1_2_contract_dataclasses_are_frozen_and_slotted() -> None:
    instances: dict[type[Any], Any] = {
        Evidence: make_evidence(),
        Observation: make_observation(),
        StateDefinition: StateDefinition(
            "user.hunger",
            StateDomain.USER,
            StateValueType.CATEGORICAL,
            "declared",
            None,
            None,
        ),
        RuntimeState: make_state(),
        TransitionIntent: make_intent(),
        StateTransition: make_transition(),
    }
    for dataclass_type, instance in instances.items():
        assert is_dataclass(dataclass_type)
        assert "__slots__" in dataclass_type.__dict__
        assert not hasattr(instance, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(instance, next(field.name for field in fields(instance)), "changed")


def test_factual_payloads_and_values_are_deeply_immutable_and_hashable() -> None:
    evidence = make_evidence()
    observation = make_observation()
    state = make_state()
    for mapping in (evidence.payload, observation.value, state.value):
        assert hash(mapping) == hash(mapping)
    assert as_mapping(evidence.payload)["labels"] == ("food",)
    assert as_mapping(observation.value)["sources"] == ("evidence-1",)
    assert as_mapping(state.value)["history"] == ("observed",)


def test_nested_mapping_and_set_values_are_deeply_immutable_and_hashable() -> None:
    observation = Observation(
        id="observation-1",
        interaction_id="interaction-1",
        scope=make_scope(),
        origin_runtime_id="runtime-1",
        type="factual",
        key="user.hunger",
        value={"nested": {"labels": {"food"}}},
        confidence=0.8,
        observed_at=NOW,
        evidence_refs=(),
        sync=make_sync(make_scope(), "observation-1"),
    )
    nested = as_mapping(observation.value)["nested"]
    assert as_mapping(nested)["labels"] == frozenset({"food"})
    assert hash(nested) == hash(nested)


def test_syncability_is_limited_to_facts_and_committed_transitions() -> None:
    assert isinstance(make_evidence(), Syncable)
    assert isinstance(make_observation(), Syncable)
    assert isinstance(make_state(), Syncable)
    assert isinstance(make_transition(), Syncable)
    assert not isinstance(make_intent(), Syncable)


def test_sync_identity_matches_each_synchronizable_contract() -> None:
    for instance, object_id in (
        (make_evidence(), "evidence-1"),
        (make_observation(), "observation-1"),
        (make_state(), "state-1"),
        (make_transition(), "transition-1"),
    ):
        sync = instance.sync_fields()
        assert sync.scope == instance.scope
        assert sync.origin_runtime_id == instance.origin_runtime_id
        assert sync.object_id == object_id
        assert sync.version >= 1


def test_evidence_authority_and_state_transition_scopes_fail_closed() -> None:
    user_scope = make_scope()
    world_scope = Scope(domain=ScopeDomain.WORLD, world_id="world-1")
    with pytest.raises(ValueError, match="authority.scope must match"):
        Evidence(
            id="evidence-1",
            scope=user_scope,
            origin_runtime_id="runtime-1",
            source_type="user_message",
            source_id="message-1",
            authority_level=AuthorityLevel.SYSTEM,
            authority=Authority(world_scope, AuthorityLevel.SYSTEM, "system-1"),
            occurred_at=NOW,
            received_at=NOW,
            payload={},
            sync=make_sync(user_scope, "evidence-1"),
        )
    with pytest.raises(ValueError, match="scope must match"):
        StateTransition(
            transition_id="transition-1",
            scope=user_scope,
            origin_runtime_id="runtime-1",
            intent_id="intent-1",
            from_state=make_state(scope=user_scope),
            to_state=make_state(
                scope=Scope(
                    domain=ScopeDomain.RELATIONSHIP,
                    relationship_id="relationship-1",
                    persona_id="kayla",
                ),
                state_id="state-relationship",
                dimension="relationship.trust",
            ),
            committed_at=NOW,
            sync=make_sync(user_scope, "transition-1"),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "error"),
    [
        ("payload", bytearray(b"mutable"), "payload contains unsupported value type"),
        ("payload", {1: "invalid"}, "payload keys must be strings"),
        ("sync", object(), "sync must be SyncFields"),
    ],
)
def test_evidence_rejects_invalid_mutable_payload_or_sync(
    field_name: str, value: object, error: str
) -> None:
    evidence = make_evidence()
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs[field_name] = value
    with pytest.raises(ValueError, match=error):
        Evidence(**kwargs)


def test_reference_collections_reject_string_and_non_iterable_values() -> None:
    observation = make_observation()
    kwargs = {field.name: getattr(observation, field.name) for field in fields(observation)}
    kwargs["evidence_refs"] = "evidence-1"
    with pytest.raises(ValueError, match="evidence_refs must not be a string"):
        Observation(**kwargs)

    state = make_state()
    kwargs = {field.name: getattr(state, field.name) for field in fields(state)}
    kwargs["transition_refs"] = object()
    with pytest.raises(ValueError, match="transition_refs must be iterable"):
        RuntimeState(**kwargs)


@pytest.mark.parametrize(
    ("sync", "error"),
    [
        (SyncFields(make_scope(), "runtime-1", "wrong", 1, "idem"), "object id"),
        (SyncFields(make_scope(), "other-runtime", "evidence-1", 1, "idem"), "origin_runtime_id"),
        (
            SyncFields(
                Scope(domain=ScopeDomain.WORLD, world_id="world-1"),
                "runtime-1",
                "evidence-1",
                1,
                "idem",
            ),
            "sync.scope",
        ),
        (SyncFields(make_scope(), "runtime-1", "evidence-1", 0, "idem"), "at least 1"),
        (SyncFields(make_scope(), "runtime-1", "evidence-1", 1, "   "), "idempotency_key"),
    ],
)
def test_sync_fields_reject_mismatched_or_invalid_identity(sync: SyncFields, error: str) -> None:
    evidence = make_evidence()
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["sync"] = sync
    with pytest.raises(ValueError, match=error):
        Evidence(**kwargs)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence must be in \\[0, 1\\]"):
        Observation(
            id="observation-1",
            interaction_id="interaction-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            type="factual",
            key="user.hunger",
            value={},
            confidence=confidence,
            observed_at=NOW,
            evidence_refs=(),
            sync=make_sync(make_scope(), "observation-1"),
        )
    with pytest.raises(ValueError, match="confidence must be in \\[0, 1\\]"):
        TransitionIntent(
            intent_id="intent-1",
            interaction_id="interaction-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            target_dimension="user.hunger",
            before=make_state(),
            proposed_after=make_state(state_id="state-after"),
            cause_refs=(),
            policy="reconciler",
            confidence=confidence,
            commit_phase="ingest",
        )


@pytest.mark.parametrize(
    "invalid_time",
    [
        datetime(2026, 8, 20, 9, 0),
        datetime(2026, 8, 20, 11, 0, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_contract_datetimes_must_be_aware_utc(invalid_time: datetime) -> None:
    with pytest.raises(ValueError, match="occurred_at must be aware UTC"):
        Evidence(
            id="evidence-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            source_type="user_message",
            source_id="message-1",
            authority_level=AuthorityLevel.ASSERTED,
            authority=Authority(make_scope(), AuthorityLevel.ASSERTED, "message-1"),
            occurred_at=invalid_time,
            received_at=NOW,
            payload={},
            sync=make_sync(make_scope(), "evidence-1"),
        )
    with pytest.raises(ValueError, match="updated_at must be aware UTC"):
        RuntimeState(
            state_id="state-1",
            scope=make_scope(),
            origin_runtime_id="runtime-1",
            dimension="user.hunger",
            value={},
            status="current",
            valid_from=NOW,
            valid_until=None,
            relevant_until=None,
            last_observed_at=NOW,
            evidence_refs=(),
            transition_refs=(),
            version=1,
            updated_at=invalid_time,
            sync=make_sync(make_scope(), "state-1"),
        )


def test_runtime_state_rejects_invalid_optional_time_version_and_sync_version() -> None:
    state = make_state()
    kwargs = {field.name: getattr(state, field.name) for field in fields(state)}
    kwargs["valid_until"] = datetime(2026, 8, 20, 9, 1)
    with pytest.raises(ValueError, match="valid_until must be aware UTC"):
        RuntimeState(**kwargs)

    kwargs = {field.name: getattr(state, field.name) for field in fields(state)}
    kwargs["version"] = 0
    with pytest.raises(ValueError, match="version must be at least 1"):
        RuntimeState(**kwargs)

    kwargs = {field.name: getattr(state, field.name) for field in fields(state)}
    kwargs["sync"] = make_sync(make_scope(), "state-1", version=2)
    with pytest.raises(ValueError, match="sync.version must match version"):
        RuntimeState(**kwargs)


def test_state_definition_and_transition_intent_reject_invalid_schema_values() -> None:
    with pytest.raises(ValueError, match="StateValueType"):
        StateDefinition("user.hunger", StateDomain.USER, "factual", "declared", None, None)  # type: ignore[arg-type]
    intent = make_intent()
    kwargs = {field.name: getattr(intent, field.name) for field in fields(intent)}
    kwargs["commit_phase"] = "invalid"
    with pytest.raises(ValueError, match="commit_phase must be ingest or turn_commit"):
        TransitionIntent(**kwargs)


def test_transition_intent_rejects_cross_scope_state() -> None:
    intent = make_intent()
    kwargs = {field.name: getattr(intent, field.name) for field in fields(intent)}
    kwargs["proposed_after"] = make_state(
        scope=Scope(
            domain=ScopeDomain.RELATIONSHIP,
            relationship_id="relationship-1",
            persona_id="kayla",
        ),
        state_id="state-relationship",
        dimension="relationship.trust",
    )
    with pytest.raises(ValueError, match="state scope must match"):
        TransitionIntent(**kwargs)


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (make_evidence, "id"),
        (make_observation, "id"),
        (make_state, "state_id"),
        (make_intent, "intent_id"),
        (make_transition, "transition_id"),
    ],
)
def test_opaque_contract_ids_must_be_non_empty(factory: Any, field_name: str) -> None:
    instance = factory()
    kwargs = {field.name: getattr(instance, field.name) for field in fields(instance)}
    kwargs[field_name] = "   "
    with pytest.raises(ValueError, match="non-empty"):
        type(instance)(**kwargs)


def test_original_mutable_references_cannot_mutate_frozen_contract_values() -> None:
    payload = {"nested": {"labels": ["food"]}}
    value = {"nested": {"labels": ["hungry"]}}
    evidence = make_evidence(payload=payload)
    observation = make_observation(value=value)
    state = make_state(value=value)

    payload["nested"]["labels"].append("changed")
    value["nested"]["labels"].append("changed")

    assert as_mapping(as_mapping(evidence.payload)["nested"])["labels"] == ("food",)
    assert as_mapping(as_mapping(observation.value)["nested"])["labels"] == ("hungry",)
    assert as_mapping(as_mapping(state.value)["nested"])["labels"] == ("hungry",)


@pytest.mark.parametrize("value", [False, 7, 0.5, "hungry", b"evidence"])
def test_observation_and_runtime_state_allow_immutable_scalar_values(value: object) -> None:
    observation = make_observation(value=value)
    state = make_state(value=value)

    assert observation.value == value
    assert state.value == value
    assert hash(observation.value) == hash(observation.value)
    assert hash(state.value) == hash(state.value)


@pytest.mark.parametrize("value", [bytearray(b"mutable"), object()])
def test_contract_values_reject_unsupported_mutable_or_unknown_leaves(value: object) -> None:
    with pytest.raises(ValueError, match="unsupported value type"):
        make_evidence(payload=value)
    with pytest.raises(ValueError, match="unsupported value type"):
        make_observation(value=value)
    with pytest.raises(ValueError, match="unsupported value type"):
        make_state(value=value)


def test_contracts_and_structured_values_have_stable_hashes() -> None:
    evidence = make_evidence()
    observation = make_observation()
    state = make_state()
    transition = make_transition()

    for value in (evidence, observation, state, transition, evidence.payload, observation.value):
        assert hash(value) == hash(value)


def test_frozen_mapping_rejects_non_mapping_and_has_mapping_behavior() -> None:
    mapping = as_mapping(make_evidence().payload)
    assert len(mapping) == 2
    with pytest.raises(KeyError):
        mapping["missing"]
    with pytest.raises(ValueError, match="value must be a mapping"):
        freeze_mapping([], "value")


def test_evidence_authority_level_source_and_scope_must_match_provenance() -> None:
    evidence = make_evidence()
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority"] = Authority(make_scope(), AuthorityLevel.OBSERVED, "message-1")
    with pytest.raises(ValueError, match="authority.level must match authority_level"):
        Evidence(**kwargs)

    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority"] = Authority(make_scope(), AuthorityLevel.ASSERTED, "other-message")
    with pytest.raises(ValueError, match="authority.source_id must match source_id"):
        Evidence(**kwargs)

    world_scope = Scope(domain=ScopeDomain.WORLD, world_id="world-1")
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority"] = Authority(world_scope, AuthorityLevel.ASSERTED, "message-1")
    with pytest.raises(ValueError, match="authority.scope must match scope"):
        Evidence(**kwargs)

    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority_level"] = "asserted"
    with pytest.raises(ValueError, match="authority_level must be an AuthorityLevel"):
        Evidence(**kwargs)

    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority"] = object()
    with pytest.raises(ValueError, match="authority must be an Authority"):
        Evidence(**kwargs)


def test_state_definition_is_declarative_and_has_only_approved_value_types() -> None:
    definition = StateDefinition(
        key="user.hunger",
        domain=StateDomain.USER,
        value_type=StateValueType.STRUCTURED,
        dynamics_policy="declared",
        default_validity_policy="declared",
        bounds={"minimum": 0, "maximum": 1},
    )
    assert as_mapping(definition.bounds)["minimum"] == 0
    assert hash(definition) == hash(definition)
    assert {member.value for member in StateValueType} == {
        "categorical",
        "boolean",
        "scalar",
        "structured",
    }
    with pytest.raises(ValueError, match="domain must be a StateDomain"):
        StateDefinition(
            key="user.hunger",
            domain="user",  # type: ignore[arg-type]
            value_type=StateValueType.STRUCTURED,
            dynamics_policy="declared",
            default_validity_policy=None,
            bounds=None,
        )


def test_transition_intent_state_dimensions_must_equal_target_dimension() -> None:
    intent = make_intent()
    kwargs = {field.name: getattr(intent, field.name) for field in fields(intent)}
    kwargs["before"] = make_state(state_id="state-before", dimension="user.sleep")
    with pytest.raises(ValueError, match="before.dimension must match target_dimension"):
        TransitionIntent(**kwargs)

    kwargs = {field.name: getattr(intent, field.name) for field in fields(intent)}
    kwargs["proposed_after"] = make_state(state_id="state-after", dimension="user.sleep")
    with pytest.raises(ValueError, match="proposed_after.dimension must match target_dimension"):
        TransitionIntent(**kwargs)


def test_committed_transition_state_dimensions_must_match() -> None:
    transition = make_transition()
    kwargs = {field.name: getattr(transition, field.name) for field in fields(transition)}
    kwargs["to_state"] = make_state(state_id="state-after", dimension="user.sleep")
    with pytest.raises(ValueError, match="state dimensions must match"):
        StateTransition(**kwargs)


def test_evidence_none_authority_keeps_source_id_but_has_no_authority_source() -> None:
    scope = make_scope()
    evidence = Evidence(
        id="evidence-none",
        source_type="user_message",
        source_id="message-1",
        authority_level=AuthorityLevel.NONE,
        occurred_at=NOW,
        received_at=NOW,
        payload="untrusted assistant output",
        scope=scope,
        origin_runtime_id="runtime-1",
        authority=Authority(scope, AuthorityLevel.NONE),
        sync=make_sync(scope, "evidence-none"),
    )
    assert evidence.source_id == "message-1"
    assert evidence.authority.source_id is None


def test_evidence_none_authority_rejects_non_none_provenance_level() -> None:
    evidence = make_evidence()
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority_level"] = AuthorityLevel.NONE
    with pytest.raises(ValueError, match="authority.level must match authority_level"):
        Evidence(**kwargs)

    malformed_authority = Authority(make_scope(), AuthorityLevel.NONE)
    object.__setattr__(malformed_authority, "source_id", "forbidden")
    kwargs = {field.name: getattr(evidence, field.name) for field in fields(evidence)}
    kwargs["authority_level"] = AuthorityLevel.NONE
    kwargs["authority"] = malformed_authority
    with pytest.raises(ValueError, match="NONE authority forbids authority.source_id"):
        Evidence(**kwargs)


def test_state_domain_and_key_rules_fail_closed() -> None:
    definition = StateDefinition(
        key="relationship.trust",
        domain=StateDomain.RELATIONSHIP,
        value_type=StateValueType.SCALAR,
        dynamics_policy="declared",
        default_validity_policy=None,
        bounds=None,
    )
    assert definition.domain is StateDomain.RELATIONSHIP

    for key in ("trust", "world.temperature", "user"):
        with pytest.raises(ValueError, match="key must use approved <domain>.<name> form"):
            StateDefinition(
                key=key,
                domain=StateDomain.USER,
                value_type=StateValueType.SCALAR,
                dynamics_policy="declared",
                default_validity_policy=None,
                bounds=None,
            )

    with pytest.raises(ValueError, match="domain must be a StateDomain"):
        StateDefinition(
            key="world.temperature",
            domain=ScopeDomain.WORLD,  # type: ignore[arg-type]
            value_type=StateValueType.SCALAR,
            dynamics_policy="declared",
            default_validity_policy=None,
            bounds=None,
        )


@pytest.mark.parametrize("dimension", ["relationship.trust", "trust", "world.temperature"])
def test_runtime_state_dimension_must_match_one_of_four_state_scope_domains(dimension: str) -> None:
    with pytest.raises(ValueError, match="dimension must use approved <domain>.<name> form"):
        make_state(dimension=dimension)

    world_scope = Scope(domain=ScopeDomain.WORLD, world_id="world-1")
    with pytest.raises(ValueError, match="scope.domain must be a StateDomain"):
        make_state(scope=world_scope, state_id="state-world", dimension="world.temperature")


def test_transition_intent_target_dimension_must_match_scope_domain_format() -> None:
    intent = make_intent()
    object.__setattr__(intent.before, "dimension", "trust")
    object.__setattr__(intent.proposed_after, "dimension", "trust")
    kwargs = {field.name: getattr(intent, field.name) for field in fields(intent)}
    kwargs["target_dimension"] = "trust"
    with pytest.raises(ValueError, match="target_dimension must use approved <domain>.<name> form"):
        TransitionIntent(**kwargs)


def test_frozen_mapping_has_standard_mapping_equality_and_deterministic_hash() -> None:
    first = freeze_mapping({"b": 2, "a": 1}, "value")
    second = freeze_mapping({"a": 1, "b": 2}, "value")
    plain = {"a": 1, "b": 2}

    assert first == second
    assert first == plain
    assert plain == first
    assert hash(first) == hash(second)
    assert first != {"a": 1}
    assert first != object()
