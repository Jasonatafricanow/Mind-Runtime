"""D3.2 Authority + Ownership validator tests."""

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    Evidence,
    Scope,
    ScopeDomain,
    SyncFields,
)
from mind_runtime.facts.validators import (
    AuthorityError,
    AuthorityValidator,
    OwnershipError,
    OwnershipValidator,
)
from mind_runtime.providers.clock import Clock
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 20, 19, 30, tzinfo=UTC)


def make_clock() -> Clock:
    return FakeClock(NOW)


def make_sync(scope: Scope, evidence_id: str, runtime_id: str) -> SyncFields:
    return SyncFields(scope, runtime_id, evidence_id, 1, f"idem-{evidence_id}")


def make_user_evidence(
    *,
    source_type: str = "user_message",
    level: AuthorityLevel = AuthorityLevel.ASSERTED,
    scope: Scope | None = None,
    evidence_id: str = "evidence-1",
    origin_runtime_id: str = "runtime-1",
) -> Evidence:
    factual_scope = scope or Scope(domain=ScopeDomain.USER, user_id="user-1")
    return Evidence(
        id=evidence_id,
        scope=factual_scope,
        origin_runtime_id=origin_runtime_id,
        source_type=source_type,
        source_id=f"source-{evidence_id}",
        authority_level=level,
        authority=Authority(factual_scope, level, f"source-{evidence_id}"),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(factual_scope, evidence_id, origin_runtime_id),
    )


def make_assistant_evidence() -> Evidence:
    scope = Scope(domain=ScopeDomain.USER, user_id="user-1")
    return Evidence(
        id="evidence-assistant",
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="assistant_message",
        source_id="assistant-1",
        authority_level=AuthorityLevel.NONE,
        authority=Authority(scope, AuthorityLevel.NONE, None),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "感觉你有点累。"},
        sync=make_sync(scope, "evidence-assistant", "runtime-1"),
    )


def make_kayla_agent_scope() -> Scope:
    return Scope(domain=ScopeDomain.AGENT, agent_id="kayla", persona_id="persona-kayla")


def scope_for_domain(domain: ScopeDomain) -> Scope:
    if domain is ScopeDomain.USER:
        return Scope(domain=domain, user_id="user-1")
    if domain is ScopeDomain.WORLD:
        return Scope(domain=domain, world_id="world-1")
    if domain is ScopeDomain.INTERACTION:
        return Scope(domain=domain, interaction_id="interaction-1")
    raise AssertionError(f"unsupported test domain: {domain}")


# --- AuthorityValidator ---


def test_authority_accepts_user_message_asserted() -> None:
    validator = AuthorityValidator(clock=make_clock())
    evidence = make_user_evidence()
    assert validator.is_user_fact(evidence) is True
    validator.require_user_fact(evidence)  # no raise


@pytest.mark.parametrize("source_type", ("user_message", "user_profile", "typed_event"))
def test_authority_accepts_registered_external_source_types(source_type: str) -> None:
    validator = AuthorityValidator(clock=make_clock())
    evidence = make_user_evidence(source_type=source_type)
    assert validator.is_user_fact(evidence) is True
    validator.require_user_fact(evidence)


def test_authority_rejects_assistant_message_as_user_fact() -> None:
    validator = AuthorityValidator(clock=make_clock())
    evidence = make_assistant_evidence()
    assert validator.is_user_fact(evidence) is False
    with pytest.raises(AuthorityError, match="assistant"):
        validator.require_user_fact(evidence)


@pytest.mark.parametrize(
    "source_type",
    (
        "assistant",
        "assistant_message",
        "assistant_output",
        "assistant_expression",
        "model_output",
        "derived_context",
        "internal_projection",
    ),
)
@pytest.mark.parametrize(
    "level",
    (
        AuthorityLevel.ASSERTED,
        AuthorityLevel.OBSERVED,
        AuthorityLevel.VERIFIED,
        AuthorityLevel.SYSTEM,
    ),
)
def test_authority_rejects_every_internal_source_at_every_non_none_level(
    source_type: str, level: AuthorityLevel
) -> None:
    validator = AuthorityValidator(clock=make_clock())
    evidence = make_user_evidence(source_type=source_type, level=level)
    assert validator.is_user_fact(evidence) is False
    with pytest.raises(AuthorityError, match="source type"):
        validator.require_user_fact(evidence)


def test_authority_rejects_unknown_source_type_fail_closed() -> None:
    validator = AuthorityValidator(clock=make_clock())
    evidence = make_user_evidence(source_type="assistant_claim_v2")
    assert validator.is_user_fact(evidence) is False
    with pytest.raises(AuthorityError, match="unregistered"):
        validator.require_user_fact(evidence)


def test_authority_rejects_none_authority_as_user_fact() -> None:
    validator = AuthorityValidator(clock=make_clock())
    scope = Scope(domain=ScopeDomain.USER, user_id="user-1")
    evidence = Evidence(
        id="evidence-none",
        scope=scope,
        origin_runtime_id="runtime-1",
        source_type="user_message",
        source_id="source-none",
        authority_level=AuthorityLevel.NONE,
        authority=Authority(scope, AuthorityLevel.NONE, None),
        occurred_at=NOW,
        received_at=NOW,
        payload={"text": "hello"},
        sync=make_sync(scope, "evidence-none", "runtime-1"),
    )
    with pytest.raises(AuthorityError, match="authority"):
        validator.require_user_fact(evidence)


def test_authority_accepts_observed_and_verified() -> None:
    validator = AuthorityValidator(clock=make_clock())
    for level in (AuthorityLevel.OBSERVED, AuthorityLevel.VERIFIED, AuthorityLevel.SYSTEM):
        assert validator.is_user_fact(make_user_evidence(level=level)) is True


# --- OwnershipValidator ---


def test_agent_owner_requires_matching_runtime_and_persona() -> None:
    validator = OwnershipValidator(clock=make_clock())
    kayla_scope = make_kayla_agent_scope()
    evidence = make_user_evidence(
        scope=kayla_scope,
        origin_runtime_id="runtime-kayla",
        evidence_id="evidence-kayla",
    )
    validator.require_owner(
        evidence,
        writing_runtime="kayla",
        writing_persona_id="persona-kayla",
    )


@pytest.mark.parametrize("writing_persona_id", (None, "persona-lara"))
def test_agent_owner_rejects_missing_or_foreign_persona(
    writing_persona_id: str | None,
) -> None:
    validator = OwnershipValidator(clock=make_clock())
    evidence = make_user_evidence(scope=make_kayla_agent_scope())
    with pytest.raises(OwnershipError, match="persona"):
        validator.require_owner(
            evidence,
            writing_runtime="kayla",
            writing_persona_id=writing_persona_id,
        )


def test_ownership_rejects_cross_persona_write() -> None:
    validator = OwnershipValidator(clock=make_clock())
    kayla_scope = make_kayla_agent_scope()
    evidence = make_user_evidence(
        scope=kayla_scope,
        origin_runtime_id="runtime-lara",
        evidence_id="evidence-lara",
    )
    with pytest.raises(OwnershipError, match="cannot write"):
        validator.require_owner(
            evidence,
            writing_runtime="lara",
            writing_persona_id="persona-kayla",
        )


def test_relationship_owner_requires_matching_persona() -> None:
    validator = OwnershipValidator(clock=make_clock())
    scope = Scope(
        domain=ScopeDomain.RELATIONSHIP,
        relationship_id="relationship-user-kayla",
        persona_id="persona-kayla",
    )
    evidence = make_user_evidence(scope=scope)
    validator.require_owner(
        evidence,
        writing_runtime="runtime-any",
        writing_persona_id="persona-kayla",
    )
    with pytest.raises(OwnershipError, match="persona"):
        validator.require_owner(
            evidence,
            writing_runtime="runtime-any",
            writing_persona_id="persona-lara",
        )


@pytest.mark.parametrize(
    "domain",
    (ScopeDomain.USER, ScopeDomain.WORLD, ScopeDomain.INTERACTION),
)
def test_non_persona_owned_domains_accept_none_persona(domain: ScopeDomain) -> None:
    validator = OwnershipValidator(clock=make_clock())
    evidence = make_user_evidence(scope=scope_for_domain(domain))
    validator.require_owner(
        evidence,
        writing_runtime="runtime-any",
        writing_persona_id=None,
    )


@pytest.mark.parametrize(
    "domain",
    (ScopeDomain.USER, ScopeDomain.WORLD, ScopeDomain.INTERACTION),
)
def test_non_persona_owned_domains_reject_persona_token(domain: ScopeDomain) -> None:
    validator = OwnershipValidator(clock=make_clock())
    evidence = make_user_evidence(scope=scope_for_domain(domain))
    with pytest.raises(OwnershipError, match="forbids writing persona"):
        validator.require_owner(
            evidence,
            writing_runtime="runtime-any",
            writing_persona_id="persona-kayla",
        )
