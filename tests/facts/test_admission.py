"""D3.4 Observation admission tests: validators gate immutable admission."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Observation,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.ports import FactAdmissionDisposition
from mind_runtime.facts.service import FactIngestService
from mind_runtime.facts.validators import AuthorityError, OwnershipError
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 20, 30, tzinfo=UTC)


def make_scope(user_id: str = "user-1") -> Scope:
    return Scope(domain=ScopeDomain.USER, user_id=user_id)


def make_sync(scope: Scope, object_id: str, runtime_id: str = "runtime-1") -> SyncFields:
    return SyncFields(scope, runtime_id, object_id, 1, f"idem-{object_id}")


def make_evidence(
    *,
    evidence_id: str = "evidence-1",
    source_type: str = "user_message",
    level: AuthorityLevel = AuthorityLevel.ASSERTED,
    scope: Scope | None = None,
    runtime_id: str = "runtime-1",
) -> Evidence:
    factual_scope = scope or make_scope()
    authority_source = None if level is AuthorityLevel.NONE else f"source-{evidence_id}"
    return Evidence(
        id=evidence_id,
        scope=factual_scope,
        origin_runtime_id=runtime_id,
        source_type=source_type,
        source_id=f"source-{evidence_id}",
        authority_level=level,
        authority=Authority(factual_scope, level, authority_source),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(factual_scope, evidence_id, runtime_id),
    )


def make_service() -> FactIngestService:
    return FactIngestService(clock=FakeClock(NOW))


def test_admit_user_evidence_produces_observation() -> None:
    service = make_service()
    evidence = make_evidence()
    result = service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert result.disposition is FactAdmissionDisposition.NEW
    observation = result.observation
    assert isinstance(observation, Observation)
    assert observation.evidence_refs == (evidence.id,)
    assert service.observations.count() == 1
    assert service.evidence.count() == 1
    # Provenance recorded with occurred/received kept distinct.
    assert service.provenance.all() != ()
    entry = service.provenance.all()[0]
    assert entry.evidence_id == evidence.id
    assert entry.occurred_at == entry.received_at  # same instant, distinct fields


def test_admit_assistant_evidence_rejected_no_observation() -> None:
    service = make_service()
    evidence = make_evidence(source_type="assistant_message", level=AuthorityLevel.NONE)
    with pytest.raises(AuthorityError, match="assistant"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    assert service.observations.count() == 0
    # Evidence itself is still stored (auditable) but never admitted.
    assert service.evidence.count() == 1
    # Provenance is recorded even on rejected admission (D3.5 review D4).
    assert service.provenance.all() != ()
    assert service.provenance.all()[0].evidence_id == evidence.id


@pytest.mark.parametrize(
    "source_type",
    ("assistant_expression", "model_output", "internal_projection", "unknown_internal_v2"),
)
def test_internal_or_unknown_source_is_retained_but_never_observed(source_type: str) -> None:
    service = make_service()
    evidence = make_evidence(source_type=source_type, level=AuthorityLevel.SYSTEM)
    with pytest.raises(AuthorityError):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    assert service.evidence.all() == (evidence,)
    assert service.provenance.all()[0].evidence_id == evidence.id
    assert service.observations.count() == 0


def test_admit_none_authority_rejected() -> None:
    service = make_service()
    evidence = make_evidence(level=AuthorityLevel.NONE)
    with pytest.raises(AuthorityError, match="authority"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id=None,
        )
    assert service.observations.count() == 0


def test_admit_cross_persona_write_fails_closed() -> None:
    service = make_service()
    kayla_scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    evidence = make_evidence(scope=kayla_scope, runtime_id="runtime-lara")
    with pytest.raises(OwnershipError, match="cannot write"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="lara",
            writing_persona_id="persona-kayla",
        )
    assert service.observations.count() == 0


@pytest.mark.parametrize("writing_persona_id", (None, "persona-lara"))
def test_admit_agent_scope_rejects_missing_or_mismatched_persona(
    writing_persona_id: str | None,
) -> None:
    service = make_service()
    scope = Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")
    evidence = make_evidence(scope=scope, runtime_id="kayla")
    with pytest.raises(OwnershipError, match="persona"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="kayla",
            writing_persona_id=writing_persona_id,
        )
    assert service.evidence.all() == (evidence,)
    assert service.observations.count() == 0


def test_admit_relationship_scope_requires_matching_persona() -> None:
    service = make_service()
    scope = Scope(
        domain=ScopeDomain.RELATIONSHIP,
        relationship_id="relationship-user-kayla",
        persona_id="persona-kayla",
    )
    evidence = make_evidence(scope=scope)
    accepted = service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id="persona-kayla",
    )
    assert accepted.disposition is FactAdmissionDisposition.NEW


def test_admit_user_scope_rejects_unowned_persona_token() -> None:
    service = make_service()
    evidence = make_evidence()
    with pytest.raises(OwnershipError, match="forbids writing persona"):
        service.admit(
            evidence,
            interaction_id="interaction-1",
            writing_runtime="runtime-1",
            writing_persona_id="persona-kayla",
        )
    assert service.observations.count() == 0


def test_replay_same_evidence_no_duplicate_observation() -> None:
    service = make_service()
    evidence = make_evidence()
    first = service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert first.disposition is FactAdmissionDisposition.NEW
    # Replaying the identical evidence must not duplicate and must return the
    # original authoritative Observation (ADR-0009).
    second = service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    assert second.disposition is FactAdmissionDisposition.REPLAY
    assert second.observation == first.observation
    assert service.observations.count() == 1


def test_observation_id_is_evidence_derived_and_immutable() -> None:
    service = make_service()
    evidence = make_evidence()
    result = service.admit(
        evidence,
        interaction_id="interaction-1",
        writing_runtime="runtime-1",
        writing_persona_id=None,
    )
    observation = result.observation
    assert observation.id == f"observation-{evidence.id}"
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        observation.key = "other"  # type: ignore[misc]
