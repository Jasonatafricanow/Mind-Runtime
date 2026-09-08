"""OW-P1 provenance graph builder.

Walks explicit reference edges in durable state, transition, evidence,
and observation rows to build a read-only provenance tree from a given
state or evidence ID.

**Hard rule**: every edge in the returned graph corresponds to an
explicit reference field (``evidence_refs``, ``transition_refs``,
``source_ref``) on a durable row. No edge is created from timing,
naming, or inferred causation. If the referenced record is missing
from the durable stores, the edge is reported with an
``UNRESOLVED_REFERENCE`` marker on the upstream node — never silently
filled in.
"""

from mind_runtime.state.persistence import StateBackend
from mind_runtime.facts.persistence import FactBackend

from observation_window.contracts import (
    ProvenanceNode,
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNodeKind,
)


_MAX_DEPTH = 6  # safety bound on recursive upstream traversal


class ProvenanceBuilder:
    """Read-only provenance graph builder.

    Constructed with the same read-only backends as
    ``ObservationQueryService``. Holds no MR runtime references.
    """

    def __init__(
        self,
        state_backend: StateBackend,
        fact_backend: FactBackend,
    ) -> None:
        self._state = state_backend
        self._fact = fact_backend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def graph_for_state(self, state_id: str) -> ProvenanceGraph:
        """Build the provenance graph rooted at the given canonical state.

        Walks the state's ``evidence_refs`` and ``transition_refs`` to
        pull in evidence and transition nodes. Transitions are then
        expanded via their ``from_state`` (only the explicit
        ``from_state_id`` reference) to chain back through prior
        versions.
        """
        states_by_id = {s.state_id: s for s in self._state.load_states()}
        states = list(states_by_id.values())
        # load_evidence returns (Evidence, interaction_id) pairs
        evidence_by_id = {e.id: e for e, _ixn in self._fact.load_evidence()}
        observations_by_id = {o.id: o for o in self._fact.load_observations()}
        transitions = self._state.load_transitions()

        root = states_by_id.get(state_id)
        if root is None:
            # Emit an UNRESOLVED marker so the graph is never empty
            root_node = ProvenanceNode(
                node_id=f"state:{state_id}",
                provenance_kind=ProvenanceNodeKind.STATE,
                raw_id=state_id,
                label=f"UNRESOLVED_REFERENCE state:{state_id}",
                extra={"unresolved": True},
                upstream=(),
                lifecycle_note=None,
            )
            return ProvenanceGraph(
                root_id=state_id,
                root_kind=ProvenanceNodeKind.STATE,
                nodes=(root_node,),
                edges=(),
                incomplete=True,
            )

        nodes: dict[str, ProvenanceNode] = {}
        edges: list[ProvenanceEdge] = []
        incomplete = False

        # Root node
        nodes[state_id] = ProvenanceNode(
            node_id=f"state:{state_id}",
            provenance_kind=ProvenanceNodeKind.STATE,
            raw_id=state_id,
            label=f"state {root.dimension}={root.value!r} v{root.version} ({root.status})",
            extra={
                "scope": str(root.scope),
                "dimension": root.dimension,
                "value": root.value,
                "status": root.status,
                "version": root.version,
                "valid_from": root.valid_from.isoformat(),
                "valid_until": root.valid_until.isoformat() if root.valid_until else None,
                "updated_at": root.updated_at.isoformat(),
                "origin_runtime_id": root.origin_runtime_id,
            },
            upstream=tuple(f"evidence:{ref}" for ref in root.evidence_refs)
            + tuple(f"transition:{ref}" for ref in root.transition_refs),
            lifecycle_note=self._lifecycle_note(root.status),
        )

        # Evidence refs
        for ev_ref in root.evidence_refs:
            ev_node_id = f"evidence:{ev_ref}"
            ev = evidence_by_id.get(ev_ref)
            if ev is None:
                # Unresolved reference — emit a marker node
                nodes[ev_node_id] = ProvenanceNode(
                    node_id=ev_node_id,
                    provenance_kind=ProvenanceNodeKind.EVIDENCE,
                    raw_id=ev_ref,
                    label=f"UNRESOLVED_REFERENCE evidence:{ev_ref}",
                    extra={"unresolved": True},
                    upstream=(),
                    lifecycle_note=None,
                )
                incomplete = True
            else:
                nodes[ev_node_id] = ProvenanceNode(
                    node_id=ev_node_id,
                    provenance_kind=ProvenanceNodeKind.EVIDENCE,
                    raw_id=ev.id,
                    label=f"evidence {ev.source_type}={ev.source_id!r}",
                    extra={
                        "source_type": ev.source_type,
                        "source_id": ev.source_id,
                        "occurred_at": ev.occurred_at.isoformat(),
                        "payload": ev.payload,
                        "origin_runtime_id": ev.origin_runtime_id,
                    },
                    upstream=(),
                    lifecycle_note=None,
                )
                # Walk observations whose evidence_refs include this
                # evidence row's id (only durable edge we can use).
                for obs in observations_by_id.values():
                    if ev.id in obs.evidence_refs:
                        obs_node_id = f"observation:{obs.id}"
                        nodes[obs_node_id] = ProvenanceNode(
                            node_id=obs_node_id,
                            provenance_kind=ProvenanceNodeKind.OBSERVATION,
                            raw_id=obs.id,
                            label=f"observation {obs.id}",
                            extra={
                                "type": obs.type,
                                "key": obs.key,
                                "observed_at": obs.observed_at.isoformat(),
                            },
                            upstream=(),
                            lifecycle_note=None,
                        )
                        edges.append(
                            ProvenanceEdge(
                                source_id=obs_node_id,
                                target_id=ev_node_id,
                                relation="observation admitted from evidence",
                            )
                        )

            edges.append(
                ProvenanceEdge(
                    source_id=ev_node_id,
                    target_id=state_id,
                    relation="evidence → state",
                )
            )

        # Transition refs
        for tr_ref in root.transition_refs:
            tr_node_id = f"transition:{tr_ref}"
            matching = [t for t in transitions if t.transition_id == tr_ref]
            if not matching:
                nodes[tr_node_id] = ProvenanceNode(
                    node_id=tr_node_id,
                    provenance_kind=ProvenanceNodeKind.TRANSITION,
                    raw_id=tr_ref,
                    label=f"UNRESOLVED_REFERENCE transition:{tr_ref}",
                    extra={"unresolved": True},
                    upstream=(),
                    lifecycle_note=None,
                )
                incomplete = True
            else:
                t = matching[0]
                from_id = t.from_state.state_id
                to_id = t.to_state.state_id
                nodes[tr_node_id] = ProvenanceNode(
                    node_id=tr_node_id,
                    provenance_kind=ProvenanceNodeKind.TRANSITION,
                    raw_id=t.transition_id,
                    label=f"transition {from_id} → {to_id}",
                    extra={
                        "intent_id": t.intent_id,
                        "committed_at": t.committed_at.isoformat(),
                        "from_state_id": from_id,
                        "to_state_id": to_id,
                    },
                    upstream=(f"state:{from_id}",),
                    lifecycle_note=None,
                )
                edges.append(
                    ProvenanceEdge(
                        source_id=tr_node_id,
                        target_id=state_id,
                        relation="transition → state",
                    )
                )
                # Include the explicit from_state as upstream
                fs = states_by_id.get(from_id)
                if fs is None:
                    incomplete = True
                else:
                    fs_node_id = f"state:{from_id}"
                    nodes[fs_node_id] = ProvenanceNode(
                        node_id=fs_node_id,
                        provenance_kind=ProvenanceNodeKind.STATE,
                        raw_id=fs.state_id,
                        label=f"state {fs.dimension}={fs.value!r} v{fs.version} ({fs.status})",
                        extra={
                            "scope": str(fs.scope),
                            "dimension": fs.dimension,
                            "value": fs.value,
                            "status": fs.status,
                            "version": fs.version,
                            "valid_from": fs.valid_from.isoformat(),
                            "updated_at": fs.updated_at.isoformat(),
                        },
                        upstream=tuple(f"evidence:{ref}" for ref in fs.evidence_refs)
                        + tuple(f"transition:{ref}" for ref in fs.transition_refs),
                        lifecycle_note=self._lifecycle_note(fs.status),
                    )
                    edges.append(
                        ProvenanceEdge(
                            source_id=fs_node_id,
                            target_id=tr_node_id,
                            relation="from_state → transition",
                        )
                    )

        return ProvenanceGraph(
            root_id=state_id,
            root_kind=ProvenanceNodeKind.STATE,
            nodes=tuple(nodes.values()),
            edges=tuple(edges),
            incomplete=incomplete,
        )

    def graph_for_evidence(self, evidence_id: str) -> ProvenanceGraph:
        """Build the provenance graph rooted at an evidence row.

        Pulls in observations that admitted this evidence and any
        downstream state rows that explicitly reference this evidence.
        """
        evidence_by_id = {e.id: e for e, _ixn in self._fact.load_evidence()}
        observations = self._fact.load_observations()
        states = self._state.load_states()

        ev = evidence_by_id.get(evidence_id)
        nodes: dict[str, ProvenanceNode] = {}
        edges: list[ProvenanceEdge] = []
        incomplete = False

        root_node_id = f"evidence:{evidence_id}"
        if ev is None:
            nodes[root_node_id] = ProvenanceNode(
                node_id=root_node_id,
                provenance_kind=ProvenanceNodeKind.EVIDENCE,
                raw_id=evidence_id,
                label=f"UNRESOLVED_REFERENCE evidence:{evidence_id}",
                extra={"unresolved": True},
                upstream=(),
                lifecycle_note=None,
            )
            return ProvenanceGraph(
                root_id=evidence_id,
                root_kind=ProvenanceNodeKind.EVIDENCE,
                nodes=tuple(nodes.values()),
                edges=tuple(edges),
                incomplete=True,
            )

        nodes[root_node_id] = ProvenanceNode(
            node_id=root_node_id,
            provenance_kind=ProvenanceNodeKind.EVIDENCE,
            raw_id=ev.id,
            label=f"evidence {ev.source_type}={ev.source_id!r}",
            extra={
                "source_type": ev.source_type,
                "source_id": ev.source_id,
                "occurred_at": ev.occurred_at.isoformat(),
                "payload": ev.payload,
                "origin_runtime_id": ev.origin_runtime_id,
            },
            upstream=(),
            lifecycle_note=None,
        )

        # Observations that admitted this evidence (via durable
        # evidence_refs on Observation rows — the only persistent edge).
        for obs in observations:
            if ev.id in obs.evidence_refs:
                obs_node_id = f"observation:{obs.id}"
                nodes[obs_node_id] = ProvenanceNode(
                    node_id=obs_node_id,
                    provenance_kind=ProvenanceNodeKind.OBSERVATION,
                    raw_id=obs.id,
                    label=f"observation {obs.id}",
                    extra={
                        "type": obs.type,
                        "key": obs.key,
                        "observed_at": obs.observed_at.isoformat(),
                    },
                    upstream=(root_node_id,),
                    lifecycle_note=None,
                )
                edges.append(
                    ProvenanceEdge(
                        source_id=root_node_id,
                        target_id=obs_node_id,
                        relation="evidence → observation",
                    )
                )

                # State rows referencing this observation's id (explicit edge)
                for s in states:
                    if obs.id in s.evidence_refs:
                        state_node_id = f"state:{s.state_id}"
                        if state_node_id not in nodes:
                            nodes[state_node_id] = ProvenanceNode(
                                node_id=state_node_id,
                                provenance_kind=ProvenanceNodeKind.STATE,
                                raw_id=s.state_id,
                                label=f"state {s.dimension}={s.value!r} v{s.version} ({s.status})",
                                extra={
                                    "scope": str(s.scope),
                                    "dimension": s.dimension,
                                    "value": s.value,
                                    "status": s.status,
                                    "version": s.version,
                                },
                                upstream=(f"observation:{obs.id}",),
                                lifecycle_note=self._lifecycle_note(s.status),
                            )
                        edges.append(
                            ProvenanceEdge(
                                source_id=obs_node_id,
                                target_id=state_node_id,
                                relation="observation → state",
                            )
                        )

        return ProvenanceGraph(
            root_id=evidence_id,
            root_kind=ProvenanceNodeKind.EVIDENCE,
            nodes=tuple(nodes.values()),
            edges=tuple(edges),
            incomplete=incomplete,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lifecycle_note(status: str) -> str | None:
        from mind_runtime.state.lifecycle import (
            _coerce,
            CURRENT_LIKE_LIFECYCLES,
            TERMINAL_LIFECYCLES,
        )

        coerced = _coerce(status)
        if coerced is None:
            return "unknown"
        if coerced in CURRENT_LIKE_LIFECYCLES:
            return "current_like"
        if coerced in TERMINAL_LIFECYCLES:
            return "terminal"
        return "validity_outcome"