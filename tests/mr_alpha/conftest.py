"""Shared pytest fixtures for tests/mr_alpha/."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from tests.mr_alpha.protocol import AlphaProtocol


@pytest.fixture
def alpha_protocol() -> AlphaProtocol:
    return AlphaProtocol()


@pytest.fixture
def tmp_reports_dir() -> Iterator[Path]:
    """Per-test temp directory for Alpha reports."""
    d = Path(tempfile.mkdtemp(prefix="mr_alpha_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_arm_internal() -> "ArmInternalMetrics":  # noqa: F821 — defined in scorer
    from tests.mr_alpha.scorer import ArmInternalMetrics

    return ArmInternalMetrics(
        total_turns=10,
        slow_candidates=2,
        accepted_writes=2,
        rejected_writes=0,
        consumer_invocations=5,
        meaningful_appraisals=4,
    )