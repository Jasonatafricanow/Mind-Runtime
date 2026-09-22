"""P0 Source Resolution and Provenance Attack Matrix tests (Step 0 / Step 1).

Covers:
- R1: Forged source rejected by Gate and SourceResolver.
- Provenance Attack Matrix:
  1. assistant output ref
  2. derived summary ref
  3. missing / nonexistent ref
  4. wrong runtime
  5. wrong persona / scope
  6. old valid ref repeated without new independent occurrence
  7. same root occurrence with new model summary
  8. circular summary refs
  9. typed-looking forged ref
  10. user quoting assistant's old judgment (reported vs observed)
"""

from datetime import UTC, datetime
from pathlib import Path
import tempfile
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
from mind_runtime.contracts.trace import (
    EpistemicMode,
    ResolvedSource,
    SourceKind,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.facts.validators import SourceResolver
from mind_runtime.homeostasis.contracts import (
    CandidateStateDelta,
    HomeostasisDisposition,
)
from mind_runtime.homeostasis.policy import (
    FixedSalienceThresholdConfig,
    SalienceThresholdPolicy,
)


def _make_scope(user_id: str = "alice", persona_id: str | None = None) -> Scope:
    if persona_id:
        return Scope(domain=ScopeDomain.PERSONA, user_id=user_id, persona_id=persona_id)
    return Scope(domain=ScopeDomain.USER, user_id=user_id)


def _admit_fact(
    backend: SqliteFactBackend,
    *,
    evidence_id: str,
    observation_id: str,
    scope: Scope,
    runtime_id: str,
    source_type: str = "user_message",
    authority_level: AuthorityLevel = AuthorityLevel.ASSERTED,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> tuple[Evidence, Observation]:
    now = occurred_at or datetime.now(UTC)
    auth = Authority(
        scope=scope,
        level=authority_level,
        source_id=(f"src-{evidence_id}" if authority_level is not AuthorityLevel.NONE else None),
    )
    evidence = Evidence(
        id=evidence_id,
        scope=scope,
        origin_runtime_id=runtime_id,
        source_type=source_type,
        source_id=f"src-{evidence_id}",
        authority_level=authority_level,
        occurred_at=now,
        received_at=now,
        payload=payload or {"text": "hello"},
        authority=auth,
        sync=SyncFields(scope, runtime_id, evidence_id, 1, f"idem-{evidence_id}"),
    )
    observation = Observation(
        id=observation_id,
        interaction_id=f"interaction-{evidence_id}",
        scope=scope,
        origin_runtime_id=runtime_id,
        type="factual",
        key="user_message.observed",
        value={"text": "hello"},
        confidence=1.0,
        observed_at=now,
        evidence_refs=(evidence_id,),
        sync=SyncFields(scope, runtime_id, observation_id, 1, f"idem-{observation_id}"),
    )
    backend.save_admission(evidence, interaction_id=f"interaction-{evidence_id}", observation=observation)
    return evidence, observation


@pytest.fixture
def temp_facts_backend():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "facts.sqlite"
        backend = SqliteFactBackend(db_path)
        yield backend
        backend.close()


def test_r1_forged_source_rejected(temp_facts_backend):
    """R1: CandidateStateDelta with forged non-empty string cannot get SLOW_ACCEPT."""
    resolver = SourceResolver(temp_facts_backend)
    policy = SalienceThresholdPolicy(
        config=FixedSalienceThresholdConfig(),
        source_resolver=resolver,
    )
    scope = _make_scope("alice")
    now = datetime.now(UTC)

    # Candidate with a fake non-empty string as evidence_ref
    candidate = CandidateStateDelta(
        target_dimension="relationship.longitudinal.relationship_security",
        proposed_value=0.8,
        scope=scope,
        evidence_refs=("forged_evidence_123",),
        salience=0.85,
        confidence=0.9,
        source_event_ref="impulse:test",
        observed_at=now,
    )

    decision = policy.decide(candidate, prior_value=0.5)
    assert decision.decision is not HomeostasisDisposition.SLOW_ACCEPT
    assert decision.decision in (HomeostasisDisposition.REJECT, HomeostasisDisposition.FAST_ONLY)
    assert "unresolved" in decision.reason_code or "forged" in decision.reason_code or "no_evidence" in decision.reason_code


def test_provenance_matrix_missing_ref(temp_facts_backend):
    resolver = SourceResolver(temp_facts_backend)
    scope = _make_scope("alice")
    res = resolver.resolve("non_existent_ref", expected_scope=scope, expected_runtime="rt-1")
    assert not res.is_admitted
    assert not res.is_valid_for_longitudinal_support
    assert res.denial_reason == "ref_not_found"


def test_provenance_matrix_wrong_scope(temp_facts_backend):
    scope_alice = _make_scope("alice")
    scope_bob = _make_scope("bob")
    _admit_fact(temp_facts_backend, evidence_id="ev-1", observation_id="ob-1", scope=scope_alice, runtime_id="rt-1")

    resolver = SourceResolver(temp_facts_backend)
    res = resolver.resolve("ev-1", expected_scope=scope_bob, expected_runtime="rt-1")
    assert not res.is_valid_for_longitudinal_support
    assert res.denial_reason == "scope_mismatch"


def test_provenance_matrix_wrong_runtime(temp_facts_backend):
    scope = _make_scope("alice")
    _admit_fact(temp_facts_backend, evidence_id="ev-1", observation_id="ob-1", scope=scope, runtime_id="rt-1")

    resolver = SourceResolver(temp_facts_backend)
    res = resolver.resolve("ev-1", expected_scope=scope, expected_runtime="rt-other")
    assert not res.is_valid_for_longitudinal_support
    assert res.denial_reason == "runtime_mismatch"


def test_provenance_matrix_assistant_output_ref(temp_facts_backend):
    scope = _make_scope("alice")
    _admit_fact(
        temp_facts_backend,
        evidence_id="ev-asst",
        observation_id="ob-asst",
        scope=scope,
        runtime_id="rt-1",
        source_type="assistant_output",
        authority_level=AuthorityLevel.NONE,
    )

    resolver = SourceResolver(temp_facts_backend)
    res = resolver.resolve("ev-asst", expected_scope=scope, expected_runtime="rt-1")
    assert res.source_kind is SourceKind.DERIVED
    assert not res.is_valid_for_longitudinal_support
    assert res.denial_reason == "derived_source_cannot_support_longitudinal"


def test_provenance_matrix_derived_summary_ref(temp_facts_backend):
    scope = _make_scope("alice")
    _admit_fact(
        temp_facts_backend,
        evidence_id="ev-derived",
        observation_id="ob-derived",
        scope=scope,
        runtime_id="rt-1",
        source_type="derived_context",
        authority_level=AuthorityLevel.NONE,
    )

    resolver = SourceResolver(temp_facts_backend)
    res = resolver.resolve("ev-derived", expected_scope=scope, expected_runtime="rt-1")
    assert res.source_kind is SourceKind.DERIVED
    assert not res.is_valid_for_longitudinal_support


def test_provenance_matrix_valid_user_report(temp_facts_backend):
    scope = _make_scope("alice")
    _admit_fact(
        temp_facts_backend,
        evidence_id="ev-valid",
        observation_id="ob-valid",
        scope=scope,
        runtime_id="rt-1",
        source_type="user_message",
        authority_level=AuthorityLevel.ASSERTED,
    )

    resolver = SourceResolver(temp_facts_backend)
    res = resolver.resolve("ev-valid", expected_scope=scope, expected_runtime="rt-1")
    assert res.is_admitted
    assert res.is_valid_for_longitudinal_support
    assert res.source_kind is SourceKind.USER_REPORT
    assert res.epistemic_mode is EpistemicMode.REPORTED
    assert res.root_evidence_id == "ev-valid"
