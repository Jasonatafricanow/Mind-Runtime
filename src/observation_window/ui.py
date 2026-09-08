"""OW-P1 terminal UI.

A read-only terminal interface for inspecting MR canonical state, recent
changes, and provenance. Designed for developers and operators during
debugging and exploration.

Phase 1 scope:
- State browser with scope / dimension / lifecycle filters
- State detail view (selected state + evidence + transition refs)
- Recent changes view (before/after when available)
- Provenance graph expansion (tree, not canvas)
- Empty / error state handling

No write operations. No state mutation. No runtime command construction.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from mind_runtime.contracts.scope import Scope

from observation_window.contracts import (
    ObservedStateRow,
    ObservedStateChange,
    ProvenanceNode,
    ProvenanceEdge,
    ProvenanceGraph,
    ObservedEvidenceRef,
    ObservedLifecycleStatus,
)
from observation_window.query_service import ObservationQueryService
from observation_window.provenance import ProvenanceBuilder


# ---------------------------------------------------------------------------
# Terminal rendering primitives
# ---------------------------------------------------------------------------

_PANEL_WIDTH = 80


def _rule(char: str = "─", width: int = _PANEL_WIDTH) -> str:
    return char * width


def _pad(text: str, width: int = _PANEL_WIDTH) -> str:
    """Truncate or pad text to width."""
    if len(text) > width:
        return text[: width - 3] + "..."
    return text.ljust(width)


@dataclass
class TerminalUI:
    """Read-only terminal UI for the Observation Window.

    Does NOT hold any write-capable backend references.
    """

    _svc: ObservationQueryService
    _prov: ProvenanceBuilder

    # Navigation state
    _selected_state_id: str | None = None
    _active_view: str = "states"  # "states" | "changes" | "evidence"

    def run(self) -> None:
        """Enter the interactive terminal UI loop.

        Each cycle: render → prompt → respond → repeat.
        Ctrl+C exits.
        """
        try:
            self._render()
            while True:
                try:
                    cmd = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not cmd:
                    continue
                self._handle(cmd)
                self._render()
        except KeyboardInterrupt:
            pass
        print("\n[exited]")

    def _handle(self, cmd: str) -> None:
        parts = cmd.split()
        action = parts[0].lower()
        args = parts[1:]

        if action in ("q", "quit", "exit"):
            raise KeyboardInterrupt()

        elif action in ("h", "help", "?"):
            self._print_help()

        elif action in ("s", "states", "st"):
            self._active_view = "states"
            # Apply optional dimension filter
            if args:
                dim = args[0]
                self._dim_filter = dim

        elif action in ("c", "changes", "ch"):
            self._active_view = "changes"

        elif action in ("e", "evidence", "ev"):
            self._active_view = "evidence"

        elif action in ("d", "detail", "sd"):
            if args:
                self._selected_state_id = args[0]
            self._active_view = "detail"

        elif action in ("p", "prov", "provenance"):
            if args:
                self._selected_state_id = args[0]
            self._active_view = "provenance"

        elif action == "ls":
            self._active_view = "states"

        elif action == "refresh":
            self._render()  # Just re-render — all data is read fresh

    def _print_help(self) -> None:
        print()
        print("Commands:")
        print("  states / s          — list current states")
        print("  changes / c         — list recent changes")
        print("  evidence / e        — list evidence rows")
        print("  detail / d [id]     — show state detail")
        print("  prov / p [id]       — show provenance graph for state")
        print("  refresh             — re-render current view")
        print("  help / h            — show this message")
        print("  quit / q            — exit")
        print()

    def _render(self) -> None:
        print(f"\n\033[1m{'─' * _PANEL_WIDTH}\033[0m")
        print(f"\033[1m MR Observation Window ─ READ ONLY\033[0m")
        print(f"\033[1m{'─' * _PANEL_WIDTH}\033[0m")
        print()

        if self._active_view == "states":
            self._render_states()
        elif self._active_view == "changes":
            self._render_changes()
        elif self._active_view == "evidence":
            self._render_evidence()
        elif self._active_view == "detail":
            self._render_detail()
        elif self._active_view == "provenance":
            self._render_provenance()

    def _render_states(self) -> None:
        rows = self._svc.list_current_states(status_filter="current_like")
        print(f"\033[1mCurrent Canonical States ({len(rows)} rows)\033[0m")
        print(_rule())

        if not rows:
            print("  (no current state rows — backend may be empty)")
            return

        print(f"  {'Dimension':<35} {'Value':<15} {'Status':<12} {'Version':<8} {'Updated':<25}")
        print(f"  {'─' * 35} {'─' * 15} {'─' * 12} {'─' * 8} {'─' * 25}")

        for s in sorted(rows, key=lambda r: r.dimension):
            value_str = self._format_value(s.value)
            print(
                f"  {s.dimension:<35} "
                f"{_pad(value_str, 15):<15} "
                f"{s.status:<12} "
                f"v{s.version:<8} "
                f"{s.updated_at.strftime('%Y-%m-%d %H:%M:%S'):<25}"
            )

        # Also show terminal states count
        all_rows = self._svc.list_current_states()
        terminal = [r for r in all_rows if r.lifecycle_class == "terminal"]
        if terminal:
            print(f"\n  + {len(terminal)} terminal state rows (run 'changes' for transition history)")

    def _render_changes(self) -> None:
        changes = self._svc.list_recent_changes(limit=30)
        print(f"\033[1mRecent State Changes ({len(changes)} transitions)\033[0m")
        print(_rule())

        if not changes:
            print("  (no transitions recorded in state_transitions table)")
            return

        print(f"  {'When':<26} {'Dimension':<30} {'Before → After'}")
        print(f"  {'─' * 26} {'─' * 30} {'─' * 20}")

        for c in changes:
            when = c.committed_at.strftime("%Y-%m-%d %H:%M:%S")
            dim = _pad(c.dimension, 30)

            if c.diff_available:
                before_str = self._format_value(c.before_value)
                after_str = self._format_value(c.after_value)
                change = f"{before_str} → {after_str}"
            else:
                change = f"(no prior state) → {self._format_value(c.after_value)} [DIFF NOT AVAILABLE]"

            print(f"  {when:<26} {dim:<30} {change}")

    def _render_evidence(self) -> None:
        rows = self._svc.list_evidence()
        print(f"\033[1mEvidence Rows ({len(rows)} rows)\033[0m")
        print(_rule())

        if not rows:
            print("  (no evidence rows in fact_backend)")
            return

        print(f"  {'Evidence ID':<40} {'Kind':<20} {'Occurred At'}")
        print(f"  {'─' * 40} {'─' * 20} {'─' * 20}")

        for e in sorted(rows, key=lambda r: r.occurred_at, reverse=True)[:50]:
            occurred = e.occurred_at.strftime("%Y-%m-%d %H:%M")
            kind_str = f"{e.source_kind.value} ({e.source_type})" if e.source_kind.value == "unknown" else e.source_kind.value
            print(f"  {e.evidence_id:<40} {kind_str:<20} {occurred}")

    def _render_detail(self) -> None:
        state_id = self._selected_state_id
        if state_id is None:
            print("  No state selected. Use 'd <state_id>' to select a state.")
            return

        row = self._svc.get_state(state_id)
        if row is None:
            print(f"  State {state_id!r} not found in backend.")
            return

        print(f"\033[1mState Detail: {state_id}\033[0m")
        print(_rule())

        print(f"  Dimension:        {row.dimension}")
        print(f"  Scope:            {row.scope}")
        print(f"  Value:            {self._format_value(row.value)}")
        print(f"  Status:           {row.status}  (lifecycle: {row.lifecycle_class})")
        print(f"  Version:          {row.version}")
        print(f"  Valid from:       {row.valid_from.isoformat()}")
        if row.valid_until:
            print(f"  Valid until:      {row.valid_until.isoformat()}")
        if row.relevant_until:
            print(f"  Relevant until:   {row.relevant_until.isoformat()}")
        print(f"  Last observed:    {row.last_observed_at.isoformat()}")
        print(f"  Updated at:       {row.updated_at.isoformat()}")
        print(f"  Origin runtime:   {row.origin_runtime_id}")
        print()

        print(f"  Evidence refs ({len(row.evidence_refs)}):")
        if row.evidence_refs:
            for ref in row.evidence_refs:
                ev = self._svc.get_evidence(ref)
                if ev:
                    print(f"    - {ref} [{ev.source_kind.value}] {ev.source_type}")
                else:
                    print(f"    - {ref} [UNRESOLVED_REFERENCE]")
        else:
            print("    (none)")

        print(f"\n  Transition refs ({len(row.transition_refs)}):")
        if row.transition_refs:
            for ref in row.transition_refs:
                print(f"    - {ref}")
        else:
            print("    (none)")

        print(f"\n  Provenance: type 'prov {state_id}' for full upstream trace")

    def _render_provenance(self) -> None:
        state_id = self._selected_state_id
        if state_id is None:
            print("  No state selected. Use 'prov <state_id>' to view provenance.")
            return

        print(f"\033[1mProvenance Graph for {state_id}\033[0m")
        print(_rule())

        graph = self._prov.graph_for_state(state_id)

        if not graph.nodes:
            print("  No nodes found for this state ID.")
            return

        if graph.incomplete:
            print("  ⚠ INCOMPLETE: some upstream references could not be resolved.")
            print()

        # Render as a simple tree
        self._render_graph_tree(graph)

    def _render_graph_tree(self, graph: ProvenanceGraph) -> None:
        """Render the provenance graph as a rooted tree."""

        def render_node(node: ProvenanceNode, indent: int = 0, prefix: str = "") -> None:
            marker = "●" if node.extra.get("unresolved") else "●"
            kind_label = f"[{node.provenance_kind.value}]"
            lifecycle = f" ({node.lifecycle_note})" if node.lifecycle_note else ""
            print(f"{'  ' * indent}{prefix}{marker} {kind_label} {node.label}{lifecycle}")

        # Build adjacency: target_id -> list of (source_id, relation)
        children: dict[str, list[tuple[str, str]]] = {}
        for edge in graph.edges:
            children.setdefault(edge.target_id, []).append((edge.source_id, edge.relation))

        # Render from root
        root_node_id = f"state:{graph.root_id}"
        if root_node_id not in {n.node_id for n in graph.nodes}:
            # Try direct match
            matches = [n for n in graph.nodes if n.raw_id == graph.root_id]
            if matches:
                root_node_id = matches[0].node_id

        def render_tree(node_id: str, indent: int = 0, prefix: str = "", is_last: bool = True) -> None:
            node_map = {n.node_id: n for n in graph.nodes}
            node = node_map.get(node_id)
            if node is None:
                return

            connector = "└── " if is_last else "├── "
            render_node(node, indent, connector)

            child_edges = children.get(node_id, [])
            for i, (child_id, relation) in enumerate(child_edges):
                child_is_last = i == len(child_edges) - 1
                child_connector = "└── " if child_is_last else "├── "
                rel_prefix = f"({relation}) "
                render_tree(child_id, indent + 1, child_connector + rel_prefix, child_is_last)

        print(f"  Root: {root_node_id}")
        print()
        render_tree(root_node_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_value(value: object) -> str:
        if value is None:
            return "(none)"
        if isinstance(value, str):
            return repr(value[:50]) if len(value) > 50 else repr(value)
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            return f"dict({len(value)} keys)"
        if isinstance(value, (list, tuple)):
            return f"{type(value).__name__}({len(value)} items)"
        return repr(value)

    # ------------------------------------------------------------------
    # Non-interactive render (for tests)
    # ------------------------------------------------------------------

    def render_states_text(self) -> str:
        """Render the states view to a string (for test inspection)."""
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            self._active_view = "states"
            self._render()
        return f.getvalue()

    def render_changes_text(self) -> str:
        """Render the changes view to a string."""
        import io, contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            self._active_view = "changes"
            self._render()
        return f.getvalue()


# ---------------------------------------------------------------------------
# Non-interactive render helpers (for tests and scripts)
# ---------------------------------------------------------------------------

def render_state_list(
    svc: ObservationQueryService,
    lifecycle_filter: str | None = None,
) -> list[dict[str, object]]:
    """Return a list of state rows as plain dicts for programmatic access."""
    rows = svc.list_current_states(status_filter=lifecycle_filter)
    return [
        {
            "state_id": str(r.state_id),
            "dimension": r.dimension,
            "scope": str(r.scope),
            "value": r.value,
            "status": r.status,
            "lifecycle_class": r.lifecycle_class,
            "version": r.version,
            "updated_at": r.updated_at.isoformat(),
            "valid_from": r.valid_from.isoformat(),
            "evidence_refs": list(r.evidence_refs),
            "transition_refs": list(r.transition_refs),
            "origin_runtime_id": r.origin_runtime_id,
        }
        for r in rows
    ]


def render_changes_list(
    svc: ObservationQueryService,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Return recent changes as plain dicts for programmatic access."""
    changes = svc.list_recent_changes(limit=limit)
    return [
        {
            "transition_id": str(c.transition_id),
            "dimension": c.dimension,
            "scope": str(c.scope),
            "before_value": c.before_value,
            "after_value": c.after_value,
            "status_before": c.status_before,
            "status_after": c.status_after,
            "committed_at": c.committed_at.isoformat(),
            "intent_id": c.intent_id,
            "diff_available": c.diff_available,
        }
        for c in changes
    ]


def render_provenance_tree(graph: ProvenanceGraph) -> list[str]:
    """Render a provenance graph as lines of text (for test inspection)."""
    lines: list[str] = []
    if graph.incomplete:
        lines.append("⚠ INCOMPLETE")
    lines.append(f"Root: {graph.root_id} [{graph.root_kind.value}]")
    lines.append(f"Nodes: {len(graph.nodes)}")
    lines.append(f"Edges: {len(graph.edges)}")
    for node in sorted(graph.nodes, key=lambda n: n.node_id):
        unresolved = " [UNRESOLVED]" if node.extra.get("unresolved") else ""
        lines.append(f"  {node.node_id} {node.label}{unresolved}")
    for edge in sorted(graph.edges, key=lambda e: e.source_id):
        lines.append(f"  {edge.source_id} --{edge.relation}--> {edge.target_id}")
    return lines
