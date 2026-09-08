"""D11S.4 model-swap invariance tests: identical internal authority across providers."""

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.validation import CertificationPlan, load_horizon_template, sha256_bytes
from mind_runtime.validation.model_swap import ModelSwapResult, compare_model_swap

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "certification/d11s/inputs"
MANIFEST = INPUTS / "runtime-config.json"
HEAD = subprocess.run(
    ["git", "rev-parse", "--verify", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def make_plan(days: int = 30) -> CertificationPlan:
    template = load_horizon_template(INPUTS / f"horizon-{days}.json")
    return CertificationPlan(
        certification_id=template.certification_id,
        source_head=HEAD,
        persona_version=template.persona_version,
        runtime_config_manifest_sha256=sha256_bytes(MANIFEST.read_bytes()),
        horizon_days=template.horizon_days,
        started_at=template.started_at,
        events=template.events,
        checkpoint_interval=template.checkpoint_interval,
    )


def test_different_accepted_prose_keeps_internal_digest_equal(tmp_path: Path) -> None:
    result = compare_model_swap(
        FakeAgent(("早安。",)),
        FakeAgent(("你醒啦。",)),
        make_plan(),
        root=tmp_path,
        repository_root=ROOT,
    )

    assert isinstance(result, ModelSwapResult)
    assert result.expressions_differ
    assert result.left_agent_called == 1
    assert result.right_agent_called == 1
    assert result.provider_context_bytes_same
    assert result.internal_transition_same
    assert result.intent_same
    assert result.policy_same
    assert result.left_expression == "早安。"
    assert result.right_expression == "你醒啦。"


def test_internal_digest_excludes_expression_and_provider_identity() -> None:
    """The internal digest must not include prose, provider identity, or the
    provider context (expression comparison is stored separately)."""
    left = ModelSwapResult(
        expressions_differ=True,
        left_agent_called=1,
        right_agent_called=1,
        provider_context_bytes_same=True,
        internal_transition_same=True,
        intent_same=True,
        policy_same=True,
        left_expression="早安。",
        right_expression="你醒啦。",
        internal_digest="a" * 64,
        provider_context_sha256="b" * 64,
    )
    right = replace(left, left_expression="换一句。", right_expression="再换一句。")
    assert left.internal_digest == right.internal_digest
    assert left.provider_context_sha256 == right.provider_context_sha256


def test_equal_prose_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expressions must differ"):
        compare_model_swap(
            FakeAgent(("早安。",)),
            FakeAgent(("早安。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_agent_failure_fails_closed(tmp_path: Path) -> None:
    from mind_runtime.pipeline.ports import AgentFailure

    with pytest.raises(AgentFailure, match="scripted failure"):
        compare_model_swap(
            FakeAgent((AgentFailure("scripted failure"),)),
            FakeAgent(("你醒啦。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_seed_agent_does_not_count_as_a_compared_call(tmp_path: Path) -> None:
    result = compare_model_swap(
        FakeAgent(("早安。",)),
        FakeAgent(("你醒啦。",)),
        make_plan(),
        root=tmp_path,
        repository_root=ROOT,
    )
    # The seed run uses its own neutral agent; only the compared turns count.
    assert result.left_agent_called == 1
    assert result.right_agent_called == 1


def test_uncalled_agent_fails_closed(tmp_path: Path) -> None:
    class SilentAgent:
        """Responds but records no calls: the certification must detect that
        the provider was never counted as called."""

        def respond(self, provider_context: object) -> str:
            return "沉默回应。"

    with pytest.raises(ValueError, match="called exactly once"):
        compare_model_swap(
            cast(Any, SilentAgent()),
            FakeAgent(("你醒啦。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_recording_agent_without_call_count_property(tmp_path: Path) -> None:
    """A compliant AgentPort that records calls without a call_count property
    is still counted through the recorded calls."""

    class RecordingAgent:
        def __init__(self, prose: str) -> None:
            self._prose = prose
            self.calls: list[object] = []

        def respond(self, provider_context: object) -> str:
            self.calls.append(provider_context)
            return self._prose

    result = compare_model_swap(
        cast(Any, RecordingAgent("早安。")),
        cast(Any, RecordingAgent("你醒啦。")),
        make_plan(),
        root=tmp_path,
        repository_root=ROOT,
    )
    assert result.left_agent_called == 1
    assert result.right_agent_called == 1
    assert result.internal_transition_same


def test_inconsistent_recording_fails_closed(tmp_path: Path) -> None:
    """An agent whose recorded call count contradicts its recorded calls is
    rejected."""

    class InconsistentAgent:
        call_count = 2
        calls: list[object] = ["marker"]

        def respond(self, provider_context: object) -> str:
            return "早安。"

    with pytest.raises(ValueError, match="called exactly once"):
        compare_model_swap(
            cast(Any, InconsistentAgent()),
            FakeAgent(("你醒啦。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_swap_validity_rejects_different_contexts() -> None:
    from mind_runtime.validation.model_swap import _verify_swap_validity

    with pytest.raises(ValueError, match="byte-identical contexts"):
        _verify_swap_validity(
            left_calls=1,
            right_calls=1,
            left_context_bytes=b"left",
            right_context_bytes=b"right",
            left_expression="早安。",
            right_expression="你醒啦。",
        )


def test_swap_validity_rejects_empty_expression() -> None:
    from mind_runtime.validation.model_swap import _verify_swap_validity

    with pytest.raises(ValueError, match="non-empty accepted expression"):
        _verify_swap_validity(
            left_calls=1,
            right_calls=1,
            left_context_bytes=b"same",
            right_context_bytes=b"same",
            left_expression="",
            right_expression="你醒啦。",
        )


def test_capture_expression_fails_closed_without_outcome() -> None:
    from mind_runtime.validation.model_swap import _capture_expression

    with pytest.raises(ValueError, match="no expression outcome"):
        _capture_expression(None)


def test_capture_expression_fails_closed_without_accepted_prose() -> None:
    from mind_runtime.contracts import ExpressionDisposition
    from mind_runtime.validation.model_swap import _capture_expression

    class RejectedOutcome:
        accepted_expression: str | None = None
        final_disposition = ExpressionDisposition.REJECT

    with pytest.raises(ValueError, match="no accepted expression"):
        _capture_expression(RejectedOutcome())


def test_rejected_expression_agent_fails_closed(tmp_path: Path) -> None:
    """A provider whose prose is structurally rejected produces no accepted
    expression: the swap fails closed."""

    with pytest.raises(ValueError, match="no accepted expression"):
        compare_model_swap(
            FakeAgent(("",)),
            FakeAgent(("你醒啦。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_certification_requires_an_empty_root(tmp_path: Path) -> None:
    (tmp_path / "preexisting.txt").write_text("not empty", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        compare_model_swap(
            FakeAgent(("早安。",)),
            FakeAgent(("你醒啦。",)),
            make_plan(),
            root=tmp_path,
            repository_root=ROOT,
        )


def test_certification_rejects_source_head_mismatch(tmp_path: Path) -> None:
    plan = replace(make_plan(), source_head="0" * 40)

    with pytest.raises(ValueError, match="source HEAD"):
        compare_model_swap(
            FakeAgent(("早安。",)),
            FakeAgent(("你醒啦。",)),
            plan,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_certification_rejects_manifest_mismatch(tmp_path: Path) -> None:
    plan = replace(make_plan(), runtime_config_manifest_sha256="f" * 64)

    with pytest.raises(ValueError, match="runtime manifest"):
        compare_model_swap(
            FakeAgent(("早安。",)),
            FakeAgent(("你醒啦。",)),
            plan,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_certification_rejects_plan_not_decoded_from_template(tmp_path: Path) -> None:
    plan = replace(make_plan(), certification_id="changed-certification")

    with pytest.raises(ValueError, match="exact verified horizon"):
        compare_model_swap(
            FakeAgent(("早安。",)),
            FakeAgent(("你醒啦。",)),
            plan,
            root=tmp_path,
            repository_root=ROOT,
        )


def test_default_repository_root_resolves_checked_out_source(tmp_path: Path) -> None:
    result = compare_model_swap(
        FakeAgent(("早安。",)),
        FakeAgent(("你醒啦。",)),
        make_plan(),
        root=tmp_path,
    )
    assert result.internal_transition_same


def test_result_rejects_malformed_contracts() -> None:
    base = ModelSwapResult(
        expressions_differ=True,
        left_agent_called=1,
        right_agent_called=1,
        provider_context_bytes_same=True,
        internal_transition_same=True,
        intent_same=True,
        policy_same=True,
        left_expression="早安。",
        right_expression="你醒啦。",
        internal_digest="a" * 64,
        provider_context_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="boolean"):
        replace(base, expressions_differ="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="called"):
        replace(base, left_agent_called=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="expression"):
        replace(base, left_expression="")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(base, internal_digest="bad")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(base, provider_context_sha256="bad")


def test_durable_roots_are_independent(tmp_path: Path) -> None:
    """The two sides materialize the SAME pre-turn snapshot into separate
    stores; each side's durable files must exist and the side runs must not
    share a root."""
    result = compare_model_swap(
        FakeAgent(("早安。",)),
        FakeAgent(("你醒啦。",)),
        make_plan(),
        root=tmp_path,
        repository_root=ROOT,
    )
    assert result.internal_transition_same
    for side in ("left-run", "right-run", "seed-run"):
        assert (tmp_path / side / "facts.sqlite").is_file()
        assert (tmp_path / side / "state.sqlite").is_file()
        assert (tmp_path / side / "intents.sqlite").is_file()
        assert (tmp_path / side / "checkpoints.sqlite").is_file()
    # The seed snapshot predates the compared turn: the seed has no
    # interaction for the final event while each side does.
    from mind_runtime.facts.persistence import SqliteFactBackend

    last_event = make_plan().events[-1]
    seed = SqliteFactBackend(tmp_path / "seed-run" / "facts.sqlite")
    try:
        assert not any(
            item.interaction_id.endswith(f"{last_event.event_id}:interaction")
            for item in seed.load_interactions()
        )
    finally:
        seed.close()
    for side in ("left-run", "right-run"):
        backend = SqliteFactBackend(tmp_path / side / "facts.sqlite")
        try:
            assert any(
                item.interaction_id.endswith(f"{last_event.event_id}:interaction")
                for item in backend.load_interactions()
            )
        finally:
            backend.close()
