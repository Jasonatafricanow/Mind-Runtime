from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.appraisal import AppraisalModelProposal, SemanticEventProposal
from mind_runtime.contracts.host import HostTurnRequest
from mind_runtime.host.runtime_adapter import (
    _body_semantics_from_request,
    _evidence_from_request,
)


def _semantic(candidate_id: str = "body-1") -> SemanticEventProposal:
    return SemanticEventProposal(
        candidate_id=candidate_id,
        kind="plan_confirmed",
        attributes=(("thread_action", "track"),),
        confidence=0.9,
    )


def _appraisal() -> AppraisalModelProposal:
    return AppraisalModelProposal(
        meanings=("plan became concrete",),
        valence="positive",
        relationship_relevance="relevant",
        salience=0.8,
        appraisal_confidence=0.85,
        supporting_evidence_refs=(),
    )


def _request(
    *,
    semantic_proposals: tuple[SemanticEventProposal, ...] = (),
    appraisal_proposals: tuple[tuple[str, AppraisalModelProposal], ...] = (),
) -> HostTurnRequest:
    return HostTurnRequest(
        interaction_id="turn-1",
        runtime_id="runtime-1",
        scope=Scope(ScopeDomain.USER, user_id="user-1"),
        occurred_at=datetime(2026, 9, 27, tzinfo=UTC),
        user_message="We decided to go on Friday.",
        semantic_proposals=semantic_proposals,
        appraisal_proposals=appraisal_proposals,
    )


def test_body_semantics_are_bound_to_system_scope_runtime_and_evidence() -> None:
    request = _request(
        semantic_proposals=(_semantic(),),
        appraisal_proposals=(("body-1", _appraisal()),),
    )
    evidence = _evidence_from_request(request)
    candidates, appraisals = _body_semantics_from_request(request, evidence)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.scope == request.scope
    assert candidate.origin_runtime_id == request.runtime_id
    assert candidate.evidence_refs == (evidence.id,)
    assert dict(candidate.attributes)["thread_action"] == "track"

    assert appraisals[0][0] == candidate.candidate_id
    assert appraisals[0][1].supporting_evidence_refs == (evidence.id,)


def test_appraisal_proposals_must_exactly_cover_semantic_proposals() -> None:
    with pytest.raises(ValueError, match="exactly cover"):
        _request(
            semantic_proposals=(_semantic("body-1"),),
            appraisal_proposals=(("other", _appraisal()),),
        )


def test_duplicate_body_semantic_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="semantic proposal ids must be unique"):
        _request(semantic_proposals=(_semantic("same"), _semantic("same")))


def test_semantic_proposal_without_appraisal_sidecar_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly cover"):
        _request(semantic_proposals=(_semantic("body-1"),))


def test_explicit_body_evidence_selector_is_preserved_for_mr_validation() -> None:
    proposal = _appraisal()
    explicit = AppraisalModelProposal(
        meanings=proposal.meanings,
        valence=proposal.valence,
        relationship_relevance=proposal.relationship_relevance,
        salience=proposal.salience,
        appraisal_confidence=proposal.appraisal_confidence,
        supporting_evidence_refs=("history-ref-1",),
    )
    request = _request(
        semantic_proposals=(_semantic(),),
        appraisal_proposals=(("body-1", explicit),),
    )
    evidence = _evidence_from_request(request)
    _, appraisals = _body_semantics_from_request(request, evidence)
    assert appraisals[0][1].supporting_evidence_refs == ("history-ref-1",)
