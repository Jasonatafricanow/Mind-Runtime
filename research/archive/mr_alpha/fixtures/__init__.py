"""MR-ALPHA-AS1: Trajectory fixtures — AS-01.

Exposes the three canonical trajectory fixtures:
  - CONTROL_NEUTRAL    : neutral cooperative conversation
  - TRUST_SUPPORT      : positive relational accumulation
  - CONFLICT_BOUNDARY  : boundary-pressure / disagreement
"""

from __future__ import annotations

from tests.mr_alpha.fixtures.conflict_boundary import CONFLICT_BOUNDARY
from tests.mr_alpha.fixtures.control_neutral import CONTROL_NEUTRAL
from tests.mr_alpha.fixtures.trust_support import TRUST_SUPPORT

__all__ = ["CONTROL_NEUTRAL", "TRUST_SUPPORT", "CONFLICT_BOUNDARY"]