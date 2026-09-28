from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import BodySemanticFrame, Scope, ScopeDomain
from mind_runtime.contracts.appraisal import AppraisalModelProposal, SemanticEventProposal
from mind_runtime.contracts.host import HostTurnRequest
from mind_runtime.host.runtime_adapter import (
    _body_semantics_from_request,
    _evidence_from_request,
)


def _frame(
    frame_id: str = "body-1",
    *,
    event_hint: str | None = None,
    refs: tuple[str, ...] = (),
) -> BodySemanticFrame:
    return BodySemanticFrame(
        frame_id=frame_id,
        meanings=("the expected meeting will not happen",),
        confidence=0.9,
        valence="negative",
        salience=0.8,
        appraisal_confidence=0.85,
        factors=(
            ("separation", 0.8),
            ("relationship_relevance", 0.9),
            ("uncertainty", 0.4),
        ),
        supporting_evidence_refs=refs,
        event_hint=event_hint,
    )


def _request(
    *,
    frames: tuple[BodySemanticFrame, ...] = (),
    semantic_proposals: tuple[SemanticEventProposal, ...] = (),
    appraisal_proposals: tuple[tuple[str, AppraisalModelProposal], ...] = (),
) -> HostTurnRequest:
    return HostTurnRequest(
        interaction_id="turn-1",
        runtime_id="runtime-1",
        scope=Scope(ScopeDomain.USER, user_id="user-1"),
        occurred_at=datetime(2026, 9, 27, tzinfo=UTC),
        user_message="We cannot meet tonight after all.",
        body_semantic_frames=frames,
        semantic_proposals=semantic_proposals,
        appraisal_proposals=appraisal_proposals,
    )


def test_open_body_frame_binds_system_authority_without_event_taxonomy() -> None:
    request = _request(frames=(_frame(),))
    evidence = _evidence_from_request(request)
    candidates, appraisals = _body_semantics_from_request(request, evidence)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.scope == request.scope
    assert candidate.origin_runtime_id == request.runtime_id
    assert candidate.evidence_refs == (evidence.id,)
    assert candidate.kind == "__body_semantic__"

    proposal = appraisals[0][1]
    assert proposal.meanings == _frame().meanings
    assert dict(proposal.factors)["separation"] == 0.8
    assert proposal.supporting_evidence_refs == (evidence.id,)


def test_event_hint_is_legacy_metadata_not_candidate_kind() -> None:
    request = _request(frames=(_frame(event_hint="plan_cancelled"),))
    evidence = _evidence_from_request(request)
    candidates, _ = _body_semantics_from_request(request, evidence)

    assert candidates[0].kind == "__body_semantic__"
    assert dict(candidates[0].attributes)["__event_hint__"] == "plan_cancelled"


def test_multiple_open_meanings_are_supported_without_event_requirement() -> None:
    request = _request(frames=(_frame("body-1"), _frame("body-2")))
    evidence = _evidence_from_request(request)
    candidates, proposals = _body_semantics_from_request(request, evidence)

    assert tuple(c.candidate_id for c in candidates) == ("body-1", "body-2")
    assert tuple(candidate_id for candidate_id, _ in proposals) == ("body-1", "body-2")


def test_duplicate_body_frame_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="frame ids must be unique"):
        _request(frames=(_frame("same"), _frame("same")))


def test_body_frames_cannot_mix_with_legacy_event_protocol() -> None:
    legacy = SemanticEventProposal(
        candidate_id="legacy",
        kind="plan_confirmed",
        attributes=(),
        confidence=0.9,
    )
    with pytest.raises(ValueError, match="cannot be mixed"):
        _request(frames=(_frame(),), semantic_proposals=(legacy,))


def test_body_cannot_encode_out_of_range_factor() -> None:
    with pytest.raises(ValueError, match="factor values must be in"):
        BodySemanticFrame(
            frame_id="bad",
            meanings=("meaning",),
            confidence=0.9,
            valence="negative",
            salience=0.8,
            appraisal_confidence=0.9,
            factors=(("threat", 1.5),),
        )


def test_explicit_body_evidence_selector_is_preserved_for_mr_validation() -> None:
    request = _request(frames=(_frame(refs=("history-ref-1",)),))
    evidence = _evidence_from_request(request)
    _, appraisals = _body_semantics_from_request(request, evidence)

    assert appraisals[0][1].supporting_evidence_refs == ("history-ref-1",)


def test_legacy_event_protocol_still_requires_matching_appraisal_ids() -> None:
    semantic = SemanticEventProposal(
        candidate_id="legacy",
        kind="plan_confirmed",
        attributes=(),
        confidence=0.9,
    )
    proposal = AppraisalModelProposal(
        meanings=("legacy meaning",),
        valence="positive",
        relationship_relevance="legacy",
        salience=0.8,
        appraisal_confidence=0.85,
        supporting_evidence_refs=(),
    )
    with pytest.raises(ValueError, match="exactly cover"):
        _request(
            semantic_proposals=(semantic,),
            appraisal_proposals=(("other", proposal),),
        )
