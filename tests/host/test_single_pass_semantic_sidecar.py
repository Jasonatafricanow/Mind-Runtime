from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEAM = REPO / "xiyue" / "mr_seam.py"


def _load_seam():
    spec = importlib.util.spec_from_file_location("mr_seam_single_pass_test", str(SEAM))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_single_pass_sidecar_is_stripped_from_user_visible_reply() -> None:
    seam = _load_seam()
    payload = {
        "schema_version": 1,
        "frames": [
            {
                "frame_id": "frame-1",
                "meanings": ["the expected meeting will not happen"],
                "confidence": 0.9,
                "valence": "negative",
                "salience": 0.8,
                "appraisal_confidence": 0.85,
                "factors": {
                    "separation": 0.8,
                    "relationship_relevance": 0.9,
                },
            }
        ],
    }
    result = {
        "final_response": (
            "I understand.\n"
            "<MR_SEMANTIC_SIDECAR>\n"
            + json.dumps(payload)
            + "\n</MR_SEMANTIC_SIDECAR>"
        )
    }

    visible, frames = seam.extract_single_pass_semantics(result)

    assert visible == "I understand."
    assert len(frames) == 1
    assert frames[0].event_hint is None
    assert dict(frames[0].factors)["separation"] == 0.8


def test_provider_native_sidecar_metadata_needs_no_text_wrapper() -> None:
    seam = _load_seam()
    result = {
        "final_response": "Normal reply.",
        "mr_semantic_frames": [
            {
                "frame_id": "frame-1",
                "meanings": ["ordinary meaning"],
                "confidence": 0.8,
                "valence": "neutral",
                "salience": None,
                "appraisal_confidence": 0.8,
                "factors": {},
            }
        ],
    }

    visible, frames = seam.extract_single_pass_semantics(result)

    assert visible == "Normal reply."
    assert len(frames) == 1
    assert frames[0].factors == ()


def test_missing_or_invalid_sidecar_fails_soft_without_extra_processing() -> None:
    seam = _load_seam()

    visible, frames = seam.extract_single_pass_semantics(
        {"final_response": "Plain response with no sidecar."}
    )
    assert visible == "Plain response with no sidecar."
    assert frames == ()

    broken = {
        "final_response": (
            "Plain response.\n"
            "<MR_SEMANTIC_SIDECAR>{bad json}</MR_SEMANTIC_SIDECAR>"
        )
    }
    visible, frames = seam.extract_single_pass_semantics(broken)
    assert visible == broken["final_response"]
    assert frames == ()


def test_sidecar_instruction_forbids_affect_deltas_and_second_semantic_call() -> None:
    seam = _load_seam()
    instruction = seam.single_pass_semantic_instruction()

    assert "Never output affect deltas" in instruction
    assert "not an event category" in instruction
    assert "chain-of-thought" in instruction
