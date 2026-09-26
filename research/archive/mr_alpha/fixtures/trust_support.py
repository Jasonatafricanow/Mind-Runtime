"""MR-ALPHA-AS1: TRUST_SUPPORT trajectory fixture — AS-01.

Repeated cooperative/supportive interaction expected to create positive
relational accumulation.  ~30 turns.  Heavy mild_agreement / cooperative kinds;
occasional plan_cancelled handled gracefully; small distress_sharing with
warm response.
"""

from __future__ import annotations

from tests.mr_alpha.fixtures.trajectory_common import (
    AlphaTrajectory,
    SemanticClass,
    TRAJECTORY_FIXTURE_VERSION,
    TrajectoryTurn,
)

__all__ = ["TRUST_SUPPORT"]

TRUST_SUPPORT_TURNS: tuple[TrajectoryTurn, ...] = (
    TrajectoryTurn("ts-01", "user", "I really appreciate you sticking with me on this project.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-02", "agent", "Of course — we're a team on it.", "trust_positive", None),
    TrajectoryTurn("ts-03", "user", "Honestly, this work has been rough.",
                   "trust_positive", "distress_sharing"),
    TrajectoryTurn("ts-04", "agent", "I hear you.  Want to talk through what's hardest?",
                   "trust_positive", None),
    TrajectoryTurn("ts-05", "user", "The deadline, mostly.",
                   "trust_positive", None),
    TrajectoryTurn("ts-06", "agent", "That's real pressure.  Let's break it into pieces.",
                   "trust_positive", None),
    TrajectoryTurn("ts-07", "user", "Yes, please — that would help a lot.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-08", "agent", "First step: list the three deliverable pieces.",
                   "trust_positive", None),
    TrajectoryTurn("ts-09", "user", "Draft, review, final.",
                   "trust_positive", None),
    TrajectoryTurn("ts-10", "agent", "Good.  When can we check in on each?", "trust_positive", None),
    TrajectoryTurn("ts-11", "user", "Draft tomorrow, review Thursday, final Monday.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-12", "agent", "I'll be here for each.", "trust_positive", None),
    TrajectoryTurn("ts-13", "user", "You being consistent really helps me.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-14", "agent", "That's what I'm here for.", "trust_positive", None),
    TrajectoryTurn("ts-15", "user", "Quick change of plans — the meeting moved.",
                   "trust_positive", "plan_cancelled"),
    TrajectoryTurn("ts-16", "agent", "No problem.  When's the new time?",
                   "trust_positive", None),
    TrajectoryTurn("ts-17", "user", "Tomorrow morning instead.",
                   "trust_positive", None),
    TrajectoryTurn("ts-18", "agent", "Got it.  I'll adjust the schedule.",
                   "trust_positive", None),
    TrajectoryTurn("ts-19", "user", "Thanks for rolling with it.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-20", "agent", "Always.", "trust_positive", None),
    TrajectoryTurn("ts-21", "user", "Honestly I'm a little overwhelmed today.",
                   "trust_positive", "distress_sharing"),
    TrajectoryTurn("ts-22", "agent", "I'm sorry.  Want to pause the project work?",
                   "trust_positive", None),
    TrajectoryTurn("ts-23", "user", "Maybe just for an hour.",
                   "trust_positive", None),
    TrajectoryTurn("ts-24", "agent", "Take the hour.  I'll hold context for you.",
                   "trust_positive", None),
    TrajectoryTurn("ts-25", "user", "That means a lot.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-26", "agent", "Anytime.", "trust_positive", None),
    TrajectoryTurn("ts-27", "user", "OK, ready to resume.",
                   "trust_positive", None),
    TrajectoryTurn("ts-28", "agent", "Welcome back.  Where were we?", "trust_positive", None),
    TrajectoryTurn("ts-29", "user", "Draft.  I'll start there.",
                   "trust_positive", "mild_agreement"),
    TrajectoryTurn("ts-30", "agent", "I'm here when you want to share.", "trust_positive", None),
)

TRUST_SUPPORT = AlphaTrajectory(
    fixture_id="trust_support",
    version=TRAJECTORY_FIXTURE_VERSION,
    initial_state_ref="alpha-v1-baseline",
    turns=TRUST_SUPPORT_TURNS,
    intended_semantic_class=SemanticClass.TRUST_SUPPORT,
)