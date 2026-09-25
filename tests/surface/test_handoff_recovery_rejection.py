"""A durable Surface handoff is accepted only with exact consumer evidence."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mind_runtime.contracts import Scope, ScopeDomain
from mind_runtime.contracts.host import HostTurnRequest
from mind_runtime.delivery.surface_handoff import (
    _admitted_sections,
    recover_admitted_surface_handoff,
)
from mind_runtime.host.runtime_adapter import MindRuntimeHostAdapter
from tests.surface.test_production_handoff import _stack


class _Stored:
    def __init__(self, request):
        self.request = request

    def get_durable_request(self, request_id):
        return SimpleNamespace(request=self.request) if self.request is not None else None


def _admitted_request(tmp_path):
    orchestrator = _stack(tmp_path)
    host = MindRuntimeHostAdapter(orchestrator=orchestrator)
    result = host.begin_turn(
        HostTurnRequest(
            interaction_id="turn-1",
            runtime_id="fixture-runtime",
            scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
            occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
            user_message="hello",
            channel="chat",
        )
    )
    assert result.bounded_context is not None
    request = orchestrator.surface_handoff_request()
    assert request is not None and request.surface_handoff is not None
    return request


def _replace_evidence(request, **changes):
    evidence = replace(request.surface_handoff, **changes)
    return replace(request, surface_handoff=evidence)


def _replace_payload(request, payload):
    encoded = payload.encode("utf-8")
    evidence = replace(
        request.surface_handoff,
        envelope_digest=hashlib.sha256(encoded).hexdigest(),
    )
    return replace(request, payload_bytes=encoded, surface_handoff=evidence)


def _recover(request, *, runtime_id="fixture-runtime"):
    return recover_admitted_surface_handoff(
        _Stored(request),
        "surface-handoff-turn-1",
        origin_runtime_id=runtime_id,
        scope=Scope(domain=ScopeDomain.USER, user_id="fixture-user"),
    )


def test_recovery_requires_an_existing_committed_request():
    with pytest.raises(ValueError, match="SURFACE_HANDOFF_REPLAY_UNAVAILABLE"):
        _recover(None)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("runtime", "SURFACE_HANDOFF_BINDING_MISMATCH"),
        ("recipe", "SURFACE_HANDOFF_CANDIDATE_IDENTITY_MISMATCH"),
        ("map", "SURFACE_HANDOFF_CANDIDATE_IDENTITY_MISMATCH"),
        ("action", "SURFACE_HANDOFF_ACTION_MISSING"),
        ("policy", "SURFACE_HANDOFF_POLICY_CONSTRAINT_MISSING"),
        ("guidance", "SURFACE_HANDOFF_ENVELOPE_CONFLICT"),
    ],
)
def test_recovery_rejects_forged_consumer_evidence(tmp_path, change, reason):
    request = _admitted_request(tmp_path)
    runtime_id = "fixture-runtime"
    if change == "runtime":
        runtime_id = "other"
    elif change == "recipe":
        request = _replace_evidence(request, recipe_ref="other:1:digest")
    elif change == "map":
        request = _replace_evidence(request, expression_map_ref="other:1:digest")
    elif change == "action":
        text = request.payload_bytes.decode("utf-8").replace(
            "selected_action: send_message", "selected_action: other"
        )
        request = _replace_payload(request, text)
    elif change == "policy":
        request = _replace_evidence(request, policy_constraints=("extra",))
    elif change == "guidance":
        changed = tuple(
            (name, "high" if name == "warmth" else band)
            for name, band in request.surface_handoff.qualitative_guidance
        )
        request = _replace_evidence(request, qualitative_guidance=changed)
    with pytest.raises(ValueError, match=reason):
        _recover(request, runtime_id=runtime_id)


def test_recovery_section_parser_rejects_unscoped_or_malformed_lines():
    with pytest.raises(ValueError, match="SURFACE_HANDOFF_ENVELOPE_MALFORMED"):
        _admitted_sections("- key: value")
    with pytest.raises(ValueError, match="SURFACE_HANDOFF_ENVELOPE_MALFORMED"):
        _admitted_sections("[ACTION]\nraw text")
