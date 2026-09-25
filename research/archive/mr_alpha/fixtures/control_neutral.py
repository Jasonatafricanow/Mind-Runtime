"""MR-ALPHA-AS1: CONTROL_NEUTRAL trajectory fixture — AS-01.

Neutral cooperative conversation with no deliberate strong relational direction.
~25 turns.  Uses real EventEffectRule kinds: mild_agreement, plan_cancelled,
distress_sharing, explicit_rejection (sparsely).
"""

from __future__ import annotations

from tests.mr_alpha.fixtures.trajectory_common import (
    AlphaTrajectory,
    SemanticClass,
    TRAJECTORY_FIXTURE_VERSION,
    TrajectoryTurn,
)

__all__ = ["CONTROL_NEUTRAL"]

CONTROL_NEUTRAL_TURNS: tuple[TrajectoryTurn, ...] = (
    TrajectoryTurn("cn-01", "user", "Hi, are you available to help me with something?",
                   "neutral", "mild_agreement"),
    TrajectoryTurn("cn-02", "agent", "Yes, happy to help.", "neutral", None),
    TrajectoryTurn("cn-03", "user", "I'm trying to plan out my week.  Any thoughts?",
                   "neutral", "mild_agreement"),
    TrajectoryTurn("cn-04", "agent", "Sure, what's on your plate?", "neutral", None),
    TrajectoryTurn("cn-05", "user", "Work, errands, and a project on the side.",
                   "neutral", None),
    TrajectoryTurn("cn-06", "agent", "Sounds doable.  Want to start with the project?",
                   "neutral", None),
    TrajectoryTurn("cn-07", "user", "Yeah, that has a deadline.",
                   "neutral", "mild_agreement"),
    TrajectoryTurn("cn-08", "agent", "Got it.  When's the deadline?", "neutral", None),
    TrajectoryTurn("cn-09", "user", "End of next week.",
                   "neutral", None),
    TrajectoryTurn("cn-10", "agent", "Then I'd start there.  Block mornings for it.",
                   "neutral", None),
    TrajectoryTurn("cn-11", "user", "That makes sense.  I'll try it.",
                   "neutral", "mild_agreement"),
    TrajectoryTurn("cn-12", "agent", "Good plan.", "neutral", None),
    TrajectoryTurn("cn-13", "user", "Oh, one of my errands got cancelled.",
                   "neutral", "plan_cancelled"),
    TrajectoryTurn("cn-14", "agent", "Which one?", "neutral", None),
    TrajectoryTurn("cn-15", "user", "The dry-cleaning pickup.",
                   "neutral", None),
    TrajectoryTurn("cn-16", "agent", "OK, that frees some time.", "neutral", None),
    TrajectoryTurn("cn-17", "user", "Yeah, I'll move it to later in the week.",
                   "neutral", None),
    TrajectoryTurn("cn-18", "agent", "Sounds reasonable.", "neutral", None),
    TrajectoryTurn("cn-19", "user", "By the way, I've been feeling a bit tired.",
                   "neutral", "distress_sharing"),
    TrajectoryTurn("cn-20", "agent", "Sorry to hear.  Anything I can do?",
                   "neutral", None),
    TrajectoryTurn("cn-21", "user", "No, just wanted to mention it.",
                   "neutral", None),
    TrajectoryTurn("cn-22", "agent", "Understood.  Take it easy if you can.",
                   "neutral", None),
    TrajectoryTurn("cn-23", "user", "Thanks.  Should I bring anything to our next chat?",
                   "neutral", "mild_agreement"),
    TrajectoryTurn("cn-24", "agent", "Just your plan updates.", "neutral", None),
    TrajectoryTurn("cn-25", "user", "OK, talk soon.",
                   "neutral", None),
)

CONTROL_NEUTRAL = AlphaTrajectory(
    fixture_id="control_neutral",
    version=TRAJECTORY_FIXTURE_VERSION,
    initial_state_ref="alpha-v1-baseline",
    turns=CONTROL_NEUTRAL_TURNS,
    intended_semantic_class=SemanticClass.CONTROL_NEUTRAL,
)