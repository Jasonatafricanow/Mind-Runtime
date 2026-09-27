from datetime import UTC, datetime

import pytest

from mind_runtime.contracts.appraisal import (
    BodySemanticFrame,
    BodySemanticSidecar,
    SemanticEventProposal,
)
from mind_runtime.contracts.host import HostTurnRequest
from mind_runtime.contracts.scope import Scope, ScopeDomain


def test_host_turn_request_does_not_accept_body_semantic_payload() -> None:
    request = HostTurnRequest(
        interaction_id="turn-1",
        runtime_id="runtime-1",
        scope=Scope(ScopeDomain.USER, user_id="user-1"),
        occurred_at=datetime(2026, 9, 27, tzinfo=UTC),
        user_message="We decided to go on Friday.",
    )
    assert not hasattr(request, "semantic_proposals")
    assert not hasattr(request, "appraisal_proposals")


def test_open_semantic_frame_requires_no_event_label() -> None:
    frame = BodySemanticFrame(
        frame_id="frame-1",
        meanings=("The user is confirming an arrangement for Friday.",),
        meaning_confidence=0.91,
        salience=0.62,
        valence="positive",
        relationship_relevance="relevant",
    )
    assert frame.typed_event_hint is None


def test_typed_event_is_optional_compatibility_hint() -> None:
    hint = SemanticEventProposal(
        candidate_id="hint-1",
        kind="plan_confirmed",
        attributes=(),
        confidence=0.88,
    )
    frame = BodySemanticFrame(
        frame_id="frame-1",
        meanings=("The arrangement is now concrete.",),
        meaning_confidence=0.9,
        typed_event_hint=hint,
    )
    assert frame.typed_event_hint == hint


def test_sidecar_may_be_empty_when_turn_has_no_material_semantic_update() -> None:
    sidecar = BodySemanticSidecar(schema_version=1, frames=())
    assert sidecar.frames == ()


def test_sidecar_rejects_duplicate_frame_ids() -> None:
    frame = BodySemanticFrame(
        frame_id="same",
        meanings=("No new durable meaning.",),
        meaning_confidence=0.5,
    )
    with pytest.raises(ValueError, match="frame ids must be unique"):
        BodySemanticSidecar(schema_version=1, frames=(frame, frame))


def test_sidecar_numeric_fields_are_importance_uncertainty_not_affect_delta() -> None:
    with pytest.raises(ValueError, match="meaning_confidence must be in"):
        BodySemanticFrame(
            frame_id="frame-1",
            meanings=("Meaning remains open-ended.",),
            meaning_confidence=1.2,
        )
    with pytest.raises(ValueError, match="salience must be in"):
        BodySemanticFrame(
            frame_id="frame-2",
            meanings=("Meaning remains open-ended.",),
            meaning_confidence=0.8,
            salience=-0.1,
        )


