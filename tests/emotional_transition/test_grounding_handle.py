"""C-6 grounding handle protocol tests (5 invariants).

These exercise the LLM-facing surface of the bounded handle protocol:
handles are turn-local, opaque tokens; canonical Observation ids never
leave the host; the resolver fails closed on every smuggling attempt.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mind_runtime.contracts import Observation, Scope, ScopeDomain, SyncFields
from mind_runtime.emotional_transition.provider import (
    SchemaInvalidError,
    _grounding_handles,
    _is_valid_handle,
    _resolve_handle_refs,
)

SCOPE = Scope(domain=ScopeDomain.USER, user_id="u1")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_observation(obs_id: str, text: str = "hello") -> Observation:
    return Observation(
        id=obs_id, interaction_id="i1", scope=SCOPE,
        origin_runtime_id="xiyue", type="factual",
        key="user_message.observed", value={"text": text},
        confidence=1.0, observed_at=NOW, evidence_refs=(obs_id,),
        sync=SyncFields(SCOPE, "xiyue", obs_id, 1, f"idem-{obs_id}"))


def test_1_single_handle_resolves_to_canonical_id() -> None:
    """Single handle "o0" → one canonical id in the produced candidate."""
    obs = (make_observation("observation-F-001"),)
    handle_to_id, handles = _grounding_handles(obs)
    assert handles == ("o0",)
    assert handle_to_id == {"o0": "observation-F-001"}
    candidate = _resolve_handle_refs(
        {"kind": "distress_sharing", "confidence": 0.9,
         "evidence_refs": ["o0"], "attributes": {}},
        handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")
    assert candidate.evidence_refs == ("observation-F-001",)


def test_2_multi_handle_resolves_each_to_canonical() -> None:
    """Multiple handles each resolve; dedup is enforced; candidate carries
    exactly the canonical ids the model selected (no expansion)."""
    obs = (make_observation("observation-F-001"),
           make_observation("observation-F-002"),
           make_observation("observation-F-003"))
    handle_to_id, handles = _grounding_handles(obs)
    assert handles == ("o0", "o1", "o2")
    candidate = _resolve_handle_refs(
        {"kind": "plan_cancellation", "confidence": 0.7,
         "evidence_refs": ["o0", "o2"], "attributes": {}},
        handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")
    assert candidate.evidence_refs == ("observation-F-001", "observation-F-003")
    # duplicate handle collapsed
    candidate2 = _resolve_handle_refs(
        {"kind": "plan_cancellation", "confidence": 0.7,
         "evidence_refs": ["o0", "o0"], "attributes": {}},
        handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")
    assert candidate2.evidence_refs == ("observation-F-001",)
    # and rejected if it exceeds the handle set (length gate prevents
    # the LLM from sneaking in unbounded citations).
    with pytest.raises(SchemaInvalidError, match="longer than the handle set"):
        _resolve_handle_refs(
            {"kind": "plan_cancellation", "confidence": 0.7,
             "evidence_refs": ["o0", "o1", "o2", "o3", "o4"],
             "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")


def test_3_unknown_handle_fails_closed() -> None:
    """A handle that is well-formed but not in this turn's set is
    rejected as SchemaInvalidError — no silent fall-through to ANY
    canonical id (which would be the canonical-id smuggling attack)."""
    obs = (make_observation("observation-F-001"),)
    handle_to_id, _ = _grounding_handles(obs)
    with pytest.raises(SchemaInvalidError, match="not in this turn's grounding set"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.8,
             "evidence_refs": ["o99"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")


def test_4_cross_turn_handle_rejected() -> None:
    """Handles are turn-local. The canonical id from turn A must be
    UNREACHABLE through any well-formed handle in turn B (the resolver
    has no channel back to turn A's mapping; the handle "o0" in turn B
    maps to a different observation, and no handle in turn B can
    produce turn A's canonical id)."""
    turn_a_obs = (make_observation("observation-T-A"),)
    turn_a_handles, _ = _grounding_handles(turn_a_obs)
    assert "o0" in turn_a_handles
    turn_a_canonical = turn_a_handles["o0"]
    assert turn_a_canonical == "observation-T-A"

    turn_b_obs = (make_observation("observation-T-B"),
                  make_observation("observation-T-B2"))
    turn_b_handles, _ = _grounding_handles(turn_b_obs)
    # In turn B, "o0" maps to a different observation; turn A's
    # canonical id is NOT in this turn's handle set at all.
    assert turn_b_handles["o0"] == "observation-T-B"
    assert turn_a_canonical not in turn_b_handles.values()
    # No well-formed handle in turn B can resolve to turn A's id.
    for handle in turn_b_handles:
        resolved = _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": [handle], "attributes": {}},
            turn_b_handles, scope=SCOPE, origin_runtime_id="xiyue")
        assert turn_a_canonical not in resolved.evidence_refs, (
            f"turn A canonical id leaked through handle {handle!r}")
    # A handle that was valid in turn A but not in turn B must fail closed.
    for fake_turn_a_handle in ("o0", "o1", "o99"):
        # In turn B's mapping only "o0" and "o1" exist; "o99" never exists.
        if fake_turn_a_handle in turn_b_handles:
            continue  # can't construct this case (well-formed in both turns)
        with pytest.raises(SchemaInvalidError, match="not in this turn"):
            _resolve_handle_refs(
                {"kind": "gratitude", "confidence": 0.5,
                 "evidence_refs": [fake_turn_a_handle], "attributes": {}},
                turn_b_handles, scope=SCOPE, origin_runtime_id="xiyue")
    # Final invariant: a request to resolve turn A's CANONICAL id
    # directly must fail closed (raw canonical ids are never accepted).
    with pytest.raises(SchemaInvalidError):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": [turn_a_canonical], "attributes": {}},
            turn_b_handles, scope=SCOPE, origin_runtime_id="xiyue")


def test_5_fake_canonical_id_in_response_fails_closed() -> None:
    """An LLM that returns a raw canonical id (or any non-handle token) in
    evidence_refs is treated as schema-invalid. Canonical Observation ids
    are NEVER in the response — the resolver only accepts the bounded
    handle format, so even a perfect forgery of an existing id is refused."""
    obs = (make_observation("observation-F-001"),
           make_observation("observation-F-002"))
    handle_to_id, _ = _grounding_handles(obs)
    for fake in [
        "observation-F-001",      # looks like a real canonical id
        "fictional-canonical-id",  # any string
        "o",                       # prefix only, not a handle
        "o-1",                     # bad format
        "",                        # empty
        "o0 ",                     # trailing space
        0,                         # wrong type
        None,                      # missing
    ]:
        with pytest.raises(SchemaInvalidError):
            _resolve_handle_refs(
                {"kind": "gratitude", "confidence": 0.5,
                 "evidence_refs": [fake], "attributes": {}},
                handle_to_id, scope=SCOPE, origin_runtime_id="xiyue")


def test_handle_validation_smoke() -> None:
    """_is_valid_handle enforces the bounded handle format (o + digits,
    0..999) so the resolver never receives ambiguous tokens."""
    for valid in ("o0", "o1", "o42", "o999"):
        assert _is_valid_handle(valid), f"expected valid: {valid!r}"
    for invalid in ("o", "o1000", "o-1", " o0", "o0 ", "x0", "0", "", "o01a"):
        assert not _is_valid_handle(invalid), f"expected invalid: {invalid!r}"


def test_grinding_handles_rejects_oversized_payload() -> None:
    """_grounding_handles refuses > 999 observations (defense in depth)."""
    from mind_runtime.emotional_transition.provider import _grounding_handles
    from tests.emotional_transition.test_grounding_handle import make_observation

    huge = tuple(make_observation(f"obs-{i}") for i in range(1000))
    with pytest.raises(SchemaInvalidError, match="too many observations"):
        _grounding_handles(huge)


def test_resolve_handle_refs_rejects_non_dict_item() -> None:
    """Non-dict candidate is a schema violation."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="must be a JSON object"):
        _resolve_handle_refs(
            "not a dict",
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_unknown_kind() -> None:
    """An LLM-emitted kind not in the allow-list is refused."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="unsupported semantic category"):
        _resolve_handle_refs(
            {"kind": "made_up_kind", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_non_numeric_confidence() -> None:
    """A non-numeric confidence is refused (no silent coercion)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="confidence must be a number"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": "0.5",
             "evidence_refs": ["o0"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_empty_evidence_refs() -> None:
    """Empty evidence_refs is refused (a candidate with no handle is unsafe)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="non-empty list of handles"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": [], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_oversized_evidence_refs() -> None:
    """More evidence_refs than handles in the set is refused (impossible resolution)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="longer than the handle set"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0", "o0"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_malformed_handle_token() -> None:
    """A handle that doesn't match the bounded format is refused."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="turn-local handles"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["bad-token"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_handle_not_in_set() -> None:
    """A syntactically valid handle not in this turn's grounding set is refused."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="not in this turn's grounding set"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o1"], "attributes": {}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_non_dict_attributes() -> None:
    """attributes must be an object (mapping), not a scalar or list."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="attributes must be an object"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": "not-a-dict"},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_numeric_attribute_value() -> None:
    """A bare numeric attribute value is refused (numeric authority write attempt)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="bare numeric value"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": {"mood": "42"}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_out_of_bounds_confidence() -> None:
    """A confidence outside [0, 1] is refused (no silent clamping)."""
    handle_to_id = {"o0": "obs-1"}
    for bad_conf in (-0.1, 1.1, 2.0, 100.0):
        with pytest.raises(SchemaInvalidError, match="confidence out of bounds"):
            _resolve_handle_refs(
                {"kind": "gratitude", "confidence": bad_conf,
                 "evidence_refs": ["o0"], "attributes": {}},
                handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
            )


def test_resolve_handle_refs_rejects_reserved_attribute_marker() -> None:
    """An attribute key carrying an affect/state marker is refused."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="affect/state authority write"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": {"mood_affect": "happy"}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_non_string_attribute_key_or_value() -> None:
    """attributes must be a string→string mapping (no numeric keys/values)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="attributes must map strings to strings"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": {42: "value"}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )
    with pytest.raises(SchemaInvalidError, match="attributes must map strings to strings"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": {"key": 42}},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )


def test_resolve_handle_refs_rejects_non_object_attributes() -> None:
    """attributes must be an object (not a list/scalar)."""
    handle_to_id = {"o0": "obs-1"}
    with pytest.raises(SchemaInvalidError, match="attributes must be an object"):
        _resolve_handle_refs(
            {"kind": "gratitude", "confidence": 0.5,
             "evidence_refs": ["o0"], "attributes": ["not-a-mapping"]},
            handle_to_id, scope=SCOPE, origin_runtime_id="xiyue",
        )
