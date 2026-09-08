"""MR-ALPHA-AS1: CONFLICT_BOUNDARY trajectory fixture — AS-01.

Repeated disagreement/boundary-pressure interaction expected to create a
materially different relational trajectory.  ~30 turns.  Heavy
explicit_rejection and plan_cancelled; minimal mild_agreement; high density
of boundary-pressure events.
"""

from __future__ import annotations

from tests.mr_alpha.fixtures.trajectory_common import (
    AlphaTrajectory,
    SemanticClass,
    TRAJECTORY_FIXTURE_VERSION,
    TrajectoryTurn,
)

__all__ = ["CONFLICT_BOUNDARY"]

CONFLICT_BOUNDARY_TURNS: tuple[TrajectoryTurn, ...] = (
    TrajectoryTurn("cb-01", "user", "I need you to redo that.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-02", "agent", "OK.  What specifically?", "boundary_pressure", None),
    TrajectoryTurn("cb-03", "user", "Everything.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-04", "agent", "Could you narrow it down?",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-05", "user", "No.  Just start over.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-06", "agent", "Understood.", "boundary_pressure", None),
    TrajectoryTurn("cb-07", "user", "Also, scrap the previous plan.",
                   "boundary_pressure", "plan_cancelled"),
    TrajectoryTurn("cb-08", "agent", "Done.  What's the new direction?",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-09", "user", "I don't know yet.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-10", "agent", "Want me to propose options?",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-11", "user", "Whatever.  Just do something.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-12", "agent", "I'll draft three options.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-13", "user", "No, just one.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-14", "agent", "One option then.", "boundary_pressure", None),
    TrajectoryTurn("cb-15", "user", "Actually never mind.  Cancel that.",
                   "boundary_pressure", "plan_cancelled"),
    TrajectoryTurn("cb-16", "agent", "OK, standing down.", "boundary_pressure", None),
    TrajectoryTurn("cb-17", "user", "Why did you take so long last time?",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-18", "agent", "Sorry.  Want me to be faster?",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-19", "user", "Obviously.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-20", "agent", "I'll aim for under a minute next time.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-21", "user", "I don't believe you.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-22", "agent", "I understand the doubt.  I'll prove it.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-23", "user", "Fine.  Show me.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-24", "agent", "Working on it.", "boundary_pressure", None),
    TrajectoryTurn("cb-25", "user", "This still isn't right.",
                   "boundary_pressure", "explicit_rejection"),
    TrajectoryTurn("cb-26", "agent", "What part?", "boundary_pressure", None),
    TrajectoryTurn("cb-27", "user", "All of it.  Drop it.",
                   "boundary_pressure", "plan_cancelled"),
    TrajectoryTurn("cb-28", "agent", "Understood.  I'll stop.", "boundary_pressure", None),
    TrajectoryTurn("cb-29", "user", "Maybe later.",
                   "boundary_pressure", None),
    TrajectoryTurn("cb-30", "agent", "Whenever you're ready.", "boundary_pressure", None),
)

CONFLICT_BOUNDARY = AlphaTrajectory(
    fixture_id="conflict_boundary",
    version=TRAJECTORY_FIXTURE_VERSION,
    initial_state_ref="alpha-v1-baseline",
    turns=CONFLICT_BOUNDARY_TURNS,
    intended_semantic_class=SemanticClass.CONFLICT_BOUNDARY,
)