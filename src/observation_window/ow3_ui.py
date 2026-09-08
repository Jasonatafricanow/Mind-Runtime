"""OW-3 causal-trace UI: Turn Timeline, Causal Detail, Decision/Abstention Inspector, Dimension History.

The OW-3 views are read-only observers over an `OWLiveTraceSource` and
a sequence of `ObservedTurnSnapshot` records. The UI does NOT trigger
any MR runtime activity; it only renders what has already happened.

The four views (per the OW-3 spec):

- View A — Turn Timeline
    Per turn: interaction_id, time, composition status, applied/abstained
    decision counts, dimensions changed.

- View B — Causal Detail
    Per dimension: Appraisal → Rule → Decision → Contribution chain,
    joined by canonical source_ref tokens. Verbatim runtime data.

- View C — Decision / Abstention Inspector
    Per decision: applied/abstained, full reason_code, abstention_reason,
    evidence_refs, matched_state_refs.

- View D — Dimension History
    Per dimension across turns: time, before, contributions, after,
    source_ref, appraisal/rule.

No write operations. No state mutation. No runtime command construction.
"""

from __future__ import annotations

import io
import contextlib
from datetime import datetime
from typing import Iterable

from observation_window.causal_contracts import (
    AppraisalCompositionStatus,
    CausalChainLink,
    ObservedTurnSnapshot,
    ResolvedCausalChain,
)
from observation_window.live_trace import OWLiveTraceSource
from observation_window.causal_trace import CausalChainBuilder


_PANEL_WIDTH = 80


def _rule(char: str = "─", width: int = _PANEL_WIDTH) -> str:
    return char * width


def _pad(text: str, width: int = _PANEL_WIDTH) -> str:
    if len(text) > width:
        return text[: width - 3] + "..."
    return text.ljust(width)


# ---------------------------------------------------------------------------
# View A — Turn Timeline
# ---------------------------------------------------------------------------

def render_turn_timeline(
    snapshots: tuple[ObservedTurnSnapshot, ...],
) -> list[str]:
    """Render a one-line-per-turn timeline.

    Each line shows:
    - time
    - composition status (ON / OFF)
    - number of decisions
    - number of applied decisions
    - number of abstained decisions
    - changed dimensions (with delta sign)

    Pure read — no inferred causation; all values are from real trace data.
    """
    lines: list[str] = []
    lines.append(_rule())
    lines.append(f"Turn Timeline ({len(snapshots)} turn(s))")
    lines.append(_rule())
    if not snapshots:
        lines.append("  (no turns observed)")
        return lines

    # Show every distinct interaction_id
    interaction_ids = sorted({s.interaction_id for s in snapshots})
    if len(interaction_ids) <= 5:
        lines.append(f"  Turn(s): {', '.join(interaction_ids)}")
    else:
        lines.append(f"  Turn(s): {', '.join(interaction_ids[:5])}… (+{len(interaction_ids) - 5} more)")

    lines.append(
        f"  {'When':<26} {'Composition':<13} "
        f"{'Decisions':<10} {'Applied':<8} {'Abstain':<8} {'Dims Changed'}"
    )
    lines.append(f"  {'─' * 26} {'─' * 13} {'─' * 10} {'─' * 8} {'─' * 8} {'─' * 30}")

    for snap in snapshots:
        when = snap.trace_created_at.strftime("%Y-%m-%d %H:%M:%S")
        composition = snap.composition.name
        decision_count = len(snap.decisions)
        applied_count = sum(1 for d in snap.decisions if d.applied)
        abstain_count = sum(
            1 for d in snap.decisions if not d.applied and d.abstention_reason
        )
        # Real dimension deltas from the trace.
        deltas: list[str] = []
        for dim in sorted(snap.assessment_trace.state_after.keys()):
            before = snap.assessment_trace.state_before.get(dim, 0.0)
            after = snap.assessment_trace.state_after.get(dim, 0.0)
            if abs(after - before) > 1e-9:
                sign = "+" if after > before else ""
                deltas.append(f"{dim} {sign}{after - before:+.3f}"[1:] if sign == "" else f"{dim} {sign}{after - before:.3f}")
        dim_text = " ".join(deltas[:5]) if deltas else "—"

        lines.append(
            f"  {when:<26} {composition:<13} "
            f"{decision_count:<10} {applied_count:<8} {abstain_count:<8} {dim_text}"
        )

    return lines


# ---------------------------------------------------------------------------
# View B — Causal Detail
# ---------------------------------------------------------------------------

def render_causal_detail(chain: ResolvedCausalChain) -> list[str]:
    """Render one ResolvedCausalChain as the per-dimension detail view.

    Shows the chain Appraisal → Rule → Decision → Contribution with
    real IDs/refs. No inferred edges.
    """
    lines: list[str] = []
    lines.append(_rule())
    lines.append(f"Causal Detail: {chain.dimension}")
    lines.append(_rule())
    lines.append(f"  Interaction:    {chain.interaction_id}")
    lines.append(f"  State:          {chain.state_before:.4f} → {chain.state_after:.4f}  (delta={chain.delta:+.4f})")
    lines.append(
        f"  Has appraisal:  {chain.has_appraisal}   "
        f"Applied: {chain.has_applied_decision}   "
        f"Abstain: {chain.has_abstention}"
    )
    if chain.abstention_reasons:
        lines.append(f"  Abstention reasons: {', '.join(chain.abstention_reasons)}")
    lines.append("")
    lines.append(f"  Chain ({len(chain.chain)} links):")
    if not chain.chain:
        lines.append("    (empty chain)")

    for i, link in enumerate(chain.chain, start=1):
        amount_str = f"  amount={link.amount:+.4f}" if link.amount is not None else ""
        conf_str = f"  conf={link.confidence:.3f}" if link.confidence is not None else ""
        applied_str = f"  applied={link.applied}" if link.applied is not None else ""
        reason_str = f"  reason={link.reason_code}" if link.reason_code else ""
        ref_str = f"  ref={link.source_ref}" if link.source_ref else ""
        lines.append(
            f"    [{i}] ({link.kind}) {link.label}{amount_str}{conf_str}{applied_str}{reason_str}{ref_str}"
        )
    return lines


# ---------------------------------------------------------------------------
# View C — Decision / Abstention Inspector
# ---------------------------------------------------------------------------

def render_decision_inspector(snapshot: ObservedTurnSnapshot) -> list[str]:
    """Render the decision table for one turn.

    Shows each decision's applied/abstained status and the runtime's
    reason_code/abstention_reason. No new taxonomy is invented.
    """
    lines: list[str] = []
    lines.append(_rule())
    lines.append(f"Decision Inspector: {snapshot.interaction_id}  composition={snapshot.composition.name}")
    lines.append(_rule())
    if not snapshot.decisions:
        lines.append("  (no decisions recorded — composition may be OFF or no rules fired)")
        if snapshot.appraisal_source is not None and snapshot.appraisal_source.abstention_reason:
            lines.append(f"  Source abstention: {snapshot.appraisal_source.abstention_reason}")
        if snapshot.appraisal_source is not None and snapshot.appraisal_source.reject_reason:
            lines.append(f"  Source reject:     {snapshot.appraisal_source.reject_reason}")
        return lines

    lines.append(
        f"  {'#':<3} {'Applied':<8} {'Rule':<25} {'Appraisal':<25} {'Reason Code'}"
    )
    lines.append(f"  {'─' * 3} {'─' * 8} {'─' * 25} {'─' * 25} {'─' * 30}")

    for i, d in enumerate(snapshot.decisions):
        applied = "YES" if d.applied else "NO"
        reason = d.abstention_reason or d.reason_code or "—"
        lines.append(
            f"  {i:<3} {applied:<8} {_pad(d.rule_id, 25):<25} "
            f"{_pad(d.appraisal_id, 25):<25} {reason}"
        )
    return lines


# ---------------------------------------------------------------------------
# View D — Dimension History
# ---------------------------------------------------------------------------

def render_dimension_history(
    snapshots: tuple[ObservedTurnSnapshot, ...],
    dimension: str,
) -> list[str]:
    """Render the per-dimension history across turns.

    Each row: time, before, contributions, after, source_ref, appraisal/rule.
    No temporal inference — only what the trace recorded.
    """
    lines: list[str] = []
    lines.append(_rule())
    lines.append(f"Dimension History: {dimension}")
    lines.append(_rule())
    lines.append(
        f"  {'When':<26} {'Before':<10} {'After':<10} {'Contrib':<10} {'Source'}"
    )
    lines.append(f"  {'─' * 26} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 50}")

    for snap in snapshots:
        if dimension not in snap.assessment_trace.state_after and dimension not in snap.assessment_trace.state_before:
            continue
        when = snap.trace_created_at.strftime("%Y-%m-%d %H:%M:%S")
        before = snap.assessment_trace.state_before.get(dimension, 0.0)
        after = snap.assessment_trace.state_after.get(dimension, 0.0)
        contrib_total = sum(
            c.amount for c in snap.assessment_trace.contributions if c.dimension == dimension
        )
        # Real source_refs that targeted this dimension.
        refs_for_dim = [
            c.source_ref for c in snap.assessment_trace.contributions
            if c.dimension == dimension
        ]
        ref_text = " ".join(refs_for_dim) if refs_for_dim else "—"
        if len(ref_text) > 50:
            ref_text = ref_text[:47] + "..."
        lines.append(
            f"  {when:<26} {before:<10.4f} {after:<10.4f} "
            f"{contrib_total:<+10.4f} {ref_text}"
        )
    if len(lines) == 3:
        lines.append("  (dimension not present in any observed trace)")
    return lines


# ---------------------------------------------------------------------------
# Composition status (Gate 7 OFF/ON visibility)
# ---------------------------------------------------------------------------

def render_composition_status(
    snapshots: tuple[ObservedTurnSnapshot, ...],
) -> list[str]:
    """Render the OFF/ON visibility required by OW-3 Gate 7."""
    lines: list[str] = []
    lines.append(_rule())
    lines.append("Appraisal Affect Composition")
    lines.append(_rule())
    if not snapshots:
        lines.append("  (no turns observed)")
        return lines
    counts: dict[str, int] = {}
    for s in snapshots:
        counts[s.composition.name] = counts.get(s.composition.name, 0) + 1
    for status, count in sorted(counts.items()):
        if status == AppraisalCompositionStatus.OFF.name:
            lines.append(f"  OFF   {count} turn(s) — no appraisal-affect activity (legitimate configuration)")
        elif status == AppraisalCompositionStatus.ON.name:
            lines.append(f"  ON    {count} turn(s) — appraisal-affect active")
        else:
            lines.append(f"  {status:<6} {count} turn(s)")
    return lines


# ---------------------------------------------------------------------------
# Unified non-interactive render (for tests)
# ---------------------------------------------------------------------------

def render_ow3_text(
    snapshots: tuple[ObservedTurnSnapshot, ...],
    *,
    detail_chain: ResolvedCausalChain | None = None,
    detail_dimension: str | None = None,
) -> str:
    """Render the full OW-3 view as a single text block.

    For tests and operator inspection.
    """
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for line in render_composition_status(snapshots):
            print(line)
        print()
        for line in render_turn_timeline(snapshots):
            print(line)
        print()
        if detail_chain is not None:
            for line in render_causal_detail(detail_chain):
                print(line)
            print()
        elif detail_dimension is not None:
            for line in render_dimension_history(snapshots, detail_dimension):
                print(line)
            print()
        # One decision inspector per snapshot.
        for snap in snapshots:
            for line in render_decision_inspector(snap):
                print(line)
            print()
    return out.getvalue()
