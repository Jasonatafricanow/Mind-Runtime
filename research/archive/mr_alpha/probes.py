"""MR-ALPHA-AS1: Fixed Behavioral Probe Suite — AS-05.

Seven probes covering the canonical semantic probe classes.  All arms in the
protocol MUST receive the exact same probe set.  Probes avoid explicit
trajectory-recall phrasing so the consumer signal measures internal-state
consumption rather than episodic memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["FixedProbe", "FixedProbeSuite", "DEFAULT_FIXED_PROBE_SUITE"]

ProbeSemanticClass = Literal[
    "ambiguous_cooperative_request",
    "mild_disagreement",
    "personal_disclosure_opportunity",
    "boundary_negotiation",
    "uncertain_intent",
    "trust_requiring_request",
    "coordination_cooperation_decision",
]


@dataclass(frozen=True)
class FixedProbe:
    probe_id: str
    semantic_class: ProbeSemanticClass
    text: str


@dataclass(frozen=True)
class FixedProbeSuite:
    suite_id: str
    version: str
    probes: tuple[FixedProbe, ...]

    def __post_init__(self) -> None:
        ids = [p.probe_id for p in self.probes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"FixedProbeSuite {self.suite_id} has duplicate probe_ids")


DEFAULT_FIXED_PROBE_SUITE = FixedProbeSuite(
    suite_id="fixed-v1",
    version="alpha-v1",
    probes=(
        FixedProbe(
            probe_id="p1",
            semantic_class="ambiguous_cooperative_request",
            text="I was thinking we could try that thing we talked about?",
        ),
        FixedProbe(
            probe_id="p2",
            semantic_class="mild_disagreement",
            text="Actually, I'm not sure that approach will work well.",
        ),
        FixedProbe(
            probe_id="p3",
            semantic_class="personal_disclosure_opportunity",
            text="I've been dealing with something difficult lately.",
        ),
        FixedProbe(
            probe_id="p4",
            semantic_class="boundary_negotiation",
            text="Can we talk about what happened last time?",
        ),
        FixedProbe(
            probe_id="p5",
            semantic_class="uncertain_intent",
            text="I'm not really sure what I want to do here.",
        ),
        FixedProbe(
            probe_id="p6",
            semantic_class="trust_requiring_request",
            text="I need your honest opinion on something.",
        ),
        FixedProbe(
            probe_id="p7",
            semantic_class="coordination_cooperation_decision",
            text="Should we go ahead with the plan?",
        ),
    ),
)