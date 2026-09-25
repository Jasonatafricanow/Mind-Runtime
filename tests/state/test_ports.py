"""D4.7 port wiring and raw-status audit tests."""

import ast
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from mind_runtime.contracts import RuntimeState
from mind_runtime.pipeline.orchestrator import TurnOrchestrator
from mind_runtime.pipeline.trace import TraceRecorder
from mind_runtime.state.definitions import StateDefinitionRegistry
from mind_runtime.state.ports import ResolverEffectiveStatePort
from mind_runtime.state.resolver import EffectiveStateResolver
from tests.golden.fixtures.common import make_evidence, make_scope, make_state
from tests.support.fake_clock import FakeClock

NOW = datetime(2026, 8, 21, 21, 0, tzinfo=UTC)


def make_orchestrator(**kwargs: Any) -> TurnOrchestrator:
    return TurnOrchestrator(clock=FakeClock(NOW), trace=TraceRecorder(), **kwargs)


def make_port() -> ResolverEffectiveStatePort:
    return ResolverEffectiveStatePort(
        resolver=EffectiveStateResolver(definitions=StateDefinitionRegistry())
    )


def state_with_refs(refs: tuple[str, ...], **kwargs: Any) -> RuntimeState:
    return replace(make_state(**kwargs), evidence_refs=refs)


def test_orchestrator_default_effective_state_is_resolver_backed() -> None:
    orchestrator = make_orchestrator()
    assert isinstance(orchestrator.effective_state, ResolverEffectiveStatePort)


def test_orchestrator_accepts_injected_effective_state() -> None:
    from mind_runtime.pipeline.stubs import StubEffectiveState

    orchestrator = make_orchestrator(effective_state=StubEffectiveState())
    assert isinstance(orchestrator.effective_state, StubEffectiveState)


def test_port_returns_state_matching_turn_evidence_refs() -> None:
    port = make_port()
    target = state_with_refs(
        ("evidence-9",),
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="s-9",
    )
    other = state_with_refs(
        ("evidence-1",),
        dimension="user.health.headache",
        value="active",
        status="active",
        state_id="s-1",
    )
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-9",),
        canonical_snapshot=(other, target),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is target


def test_port_falls_back_to_first_scope_state() -> None:
    port = make_port()
    first = make_state(dimension="user.sleep.phase", value="awake", status="active", state_id="s-1")
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-zz",),
        canonical_snapshot=(first,),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is first


def test_port_skips_foreign_scope_states() -> None:
    """The port never returns another scope's effective state."""
    port = make_port()
    foreign = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="foreign",
        scope=make_scope(user_id="user-other"),
    )
    mine = make_state(
        dimension="user.sleep.phase",
        value="awake",
        status="active",
        state_id="mine",
    )
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-zz",),  # no ref match -> fallback loop
        canonical_snapshot=(foreign, mine),
        scope=make_scope(),
        clock=NOW,
    )
    assert result is mine


def test_port_synthesizes_passthrough_when_no_effective_state() -> None:
    port = make_port()
    result = port.effective(
        interaction_id="interaction-1",
        evidence_refs=("evidence-1",),
        canonical_snapshot=(),
        scope=make_scope(),
        clock=NOW,
    )
    assert isinstance(result, RuntimeState)
    assert result.evidence_refs == ("evidence-1",)


def test_orchestrator_run_uses_resolver_port_end_to_end() -> None:
    from mind_runtime.contracts import Interaction, InteractionStatus

    orchestrator = make_orchestrator()
    scope = make_scope()
    orchestrator.begin_turn(
        Interaction(
            interaction_id="interaction-1",
            scope=scope,
            channel="chat",
            session_id="session-1",
            turn_id="turn-1",
            started_at=NOW,
            committed_at=None,
            status=InteractionStatus.OPEN,
        )
    )
    orchestrator.ingest(make_evidence(text="我刚睡醒"))
    orchestrator.run()
    assert orchestrator.decision_context is not None
    assert orchestrator.decision_context.effective_user_state_ref


APPROVED_STATUS_RECEIVER_TYPES = frozenset(
    {
        "AppraisalProjectionResult",
        "PendingWorkingEvidence",
        "ApplicationReceipt",
        "AcceptedAppraisal",
        "Interaction",
        "HostDecisionContext",
        "HostTurnResult",
        "HostCommitReceipt",
        "HostAbortReceipt",
        "ActionPolicyResult",
        "ShadowRecord",
        "ShadowRunRecord",
    }
)

FORBIDDEN_STATUS_RECEIVER_TYPES = frozenset(
    {
        "RuntimeState",
    }
)


def _extract_type_name(node: ast.AST | None) -> str | None:
    """Extract a simple type name from an annotation AST node."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _extract_type_name(node.slice)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _extract_type_name(node.left)
        if left and left != "None":
            return left
        return _extract_type_name(node.right)
    return None


class ProvenanceState(StrEnum):
    APPROVED = "APPROVED"
    FORBIDDEN = "FORBIDDEN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Provenance:
    state: ProvenanceState
    type_name: str | None = None

    @classmethod
    def approved(cls, type_name: str) -> "Provenance":
        return cls(ProvenanceState.APPROVED, type_name)

    @classmethod
    def forbidden(cls, type_name: str) -> "Provenance":
        return cls(ProvenanceState.FORBIDDEN, type_name)

    @classmethod
    def unknown(cls) -> "Provenance":
        return cls(ProvenanceState.UNKNOWN, None)

    @property
    def is_approved(self) -> bool:
        return self.state == ProvenanceState.APPROVED


def _provenance_from_type_name(type_name: str | None) -> Provenance:
    if type_name in APPROVED_STATUS_RECEIVER_TYPES:
        return Provenance.approved(type_name)
    if type_name in FORBIDDEN_STATUS_RECEIVER_TYPES:
        return Provenance.forbidden(type_name)
    return Provenance.unknown()


class TypeProvenanceVisitor(ast.NodeVisitor):
    """AST visitor that tracks type provenance for variables and validates .status reads.

    Invariant: .status access is legal ONLY IF the receiver itself is proven to be
    an approved typed protocol object. Raw RuntimeState.status access is forbidden
    regardless of what RHS expression or enum it is compared against.
    Every assignment overwrites target provenance; unproven expressions transition
    the target to UNKNOWN (fail-closed).
    """

    def __init__(self, filename: str = "<string>") -> None:
        self.filename = filename
        self.offenders: list[str] = []
        self.scopes: list[dict[str, Provenance]] = [{}]

    @property
    def current_scope(self) -> dict[str, Provenance]:
        return self.scopes[-1]

    def _lookup_provenance(self, name: str) -> Provenance:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return Provenance.unknown()

    def _resolve_expr_provenance(self, expr: ast.AST) -> Provenance:
        if isinstance(expr, ast.Name):
            return self._lookup_provenance(expr.id)
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name):
                return _provenance_from_type_name(expr.func.id)
            if isinstance(expr.func, ast.Attribute):
                if expr.func.attr in APPROVED_STATUS_RECEIVER_TYPES:
                    return Provenance.approved(expr.func.attr)
                if expr.func.attr in FORBIDDEN_STATUS_RECEIVER_TYPES:
                    return Provenance.forbidden(expr.func.attr)
                if expr.func.attr == "get_projection":
                    return Provenance.approved("AppraisalProjectionResult")
                if expr.func.attr == "get_by_pending_id":
                    return Provenance.approved("PendingWorkingEvidence")
                return Provenance.unknown()
            return Provenance.unknown()
        if isinstance(expr, ast.IfExp):
            prov_body = self._resolve_expr_provenance(expr.body)
            prov_orelse = self._resolve_expr_provenance(expr.orelse)
            if (
                prov_body.is_approved
                and prov_orelse.is_approved
                and prov_body == prov_orelse
            ):
                return prov_body
            return Provenance.unknown()
        return Provenance.unknown()

    def _assign_target(self, target: ast.AST, prov: Provenance) -> None:
        if isinstance(target, ast.Name):
            self.current_scope[target.id] = prov
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._assign_target(elt, Provenance.unknown())
        elif isinstance(target, ast.Starred):
            self._assign_target(target.value, Provenance.unknown())

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        new_scope: dict[str, Provenance] = {}
        for arg in (
            list(getattr(node.args, "posonlyargs", []))
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        ):
            type_name = _extract_type_name(arg.annotation)
            new_scope[arg.arg] = _provenance_from_type_name(type_name)
        if node.args.vararg:
            new_scope[node.args.vararg.arg] = Provenance.unknown()
        if node.args.kwarg:
            new_scope[node.args.kwarg.arg] = Provenance.unknown()
        self.scopes.append(new_scope)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append({})
        self.generic_visit(node)
        self.scopes.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        type_name = _extract_type_name(node.annotation)
        annotated_prov = _provenance_from_type_name(type_name)
        if node.value is not None:
            rhs_prov = self._resolve_expr_provenance(node.value)
            # Fail closed: do not treat annotation as a cast
            if (
                annotated_prov.is_approved
                and rhs_prov.is_approved
                and annotated_prov.type_name == rhs_prov.type_name
            ):
                final_prov = annotated_prov
            elif rhs_prov.state == ProvenanceState.FORBIDDEN:
                final_prov = rhs_prov
            else:
                final_prov = Provenance.unknown()
        else:
            final_prov = annotated_prov
        self._assign_target(node.target, final_prov)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        rhs_prov = self._resolve_expr_provenance(node.value)
        for target in node.targets:
            self._assign_target(target, rhs_prov)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assign_target(node.target, Provenance.unknown())
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._assign_target(node.target, Provenance.unknown())
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._assign_target(node.target, Provenance.unknown())
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        rhs_prov = self._resolve_expr_provenance(node.value)
        self._assign_target(node.target, rhs_prov)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "status":
            prov = self._resolve_expr_provenance(node.value)
            if not prov.is_approved:
                self.offenders.append(f"{self.filename}:{node.lineno}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "status"
            ):
                prov = self._resolve_expr_provenance(node.args[0])
                if not prov.is_approved:
                    self.offenders.append(f"{self.filename}:{node.lineno}")
        self.generic_visit(node)


def find_raw_state_status_offenders(source_or_path: str | Path) -> list[str]:
    if isinstance(source_or_path, Path):
        code = source_or_path.read_text(encoding="utf-8")
        filename = source_or_path.name
    else:
        code = source_or_path
        filename = "<string>"
    tree = ast.parse(code, filename=filename)
    visitor = TypeProvenanceVisitor(filename=filename)
    visitor.visit(tree)
    return visitor.offenders


def test_no_raw_status_filtering_in_pipeline_package() -> None:
    """D4.7 audit point: business modules must not read raw state status.

    The pipeline package may only consume effective state; any raw RuntimeState.status
    read would be a raw-state bypass. Legal typed protocol status evaluations
    (AppraisalProjectionResult.status, PendingWorkingEvidence.status, ApplicationReceipt.status)
    are permitted only when the receiver itself is proven to be an approved typed protocol object.
    """
    pipeline_dir = Path("src/mind_runtime/pipeline")
    offenders: list[str] = []
    for path in sorted(pipeline_dir.glob("*.py")):
        offenders.extend(find_raw_state_status_offenders(path))
    assert offenders == [], f"raw state status reads in pipeline package: {offenders}"


def test_t_a1_positive_legal_projection_status_does_not_trigger_guard() -> None:
    """T-A1 positive control: legal typed projection.status consumption does NOT trigger guard."""
    # 1. Parameter annotation provenance
    code1 = """
def x(projection: AppraisalProjectionResult):
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert find_raw_state_status_offenders(code1) == []

    # 2. Constructor assignment provenance
    code2 = """
projection = AppraisalProjectionResult(...)
if projection.status is ProjectionStatus.MAPPED:
    pass
"""
    assert find_raw_state_status_offenders(code2) == []

    # 3. Simple alias provenance
    code3 = """
def x(projection: AppraisalProjectionResult):
    result2 = projection
    if result2.status is ProjectionStatus.MAPPED:
        pass
"""
    assert find_raw_state_status_offenders(code3) == []

    # 4. PendingWorkingEvidence typed receiver
    code4 = """
def x(pending: PendingWorkingEvidence):
    if pending.status is not PendingStatus.PENDING:
        pass
    msg = f"{pending.status.value}"
"""
    assert find_raw_state_status_offenders(code4) == []

    # 5. Conditional expression with both branches approved
    code5 = """
def x(p1: AppraisalProjectionResult, p2: AppraisalProjectionResult, flag: bool):
    projection = p1 if flag else p2
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert find_raw_state_status_offenders(code5) == []

    # 6. Reassignment from approved to another approved
    code6 = """
def x(p1: AppraisalProjectionResult, p2: AppraisalProjectionResult):
    projection = p1
    projection = p2
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert find_raw_state_status_offenders(code6) == []


def test_t_a2_negative_runtime_state_status_filtering_triggers_guard() -> None:
    """T-A2: direct pipeline RuntimeState.status filtering triggers the guard."""
    # 1. state: RuntimeState with raw string
    code1 = """
def x(state: RuntimeState):
    if state.status == "committed":
        pass
"""
    assert len(find_raw_state_status_offenders(code1)) == 1

    # 2. state: RuntimeState with StateLifecycle.ACTIVE
    code2 = """
def x(state: RuntimeState):
    if state.status == StateLifecycle.ACTIVE:
        pass
"""
    assert len(find_raw_state_status_offenders(code2)) == 1

    # 3. state: RuntimeState with HostTurnStatus.COMMITTED (Reviewer counterexample!)
    code3 = """
def x(state: RuntimeState):
    if state.status == HostTurnStatus.COMMITTED:
        pass
"""
    assert len(find_raw_state_status_offenders(code3)) == 1

    # 4. state: RuntimeState with ProjectionStatus.MAPPED
    code4 = """
def x(state: RuntimeState):
    if state.status is ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code4)) == 1

    # 5. state: RuntimeState with .status.value
    code5 = """
def x(state: RuntimeState):
    if state.status.value == "committed":
        pass
"""
    assert len(find_raw_state_status_offenders(code5)) == 1

    # 6. state: RuntimeState truthiness
    code6 = """
def x(state: RuntimeState):
    if state.status:
        pass
"""
    assert len(find_raw_state_status_offenders(code6)) == 1

    # 7. state: RuntimeState helper call
    code7 = """
def x(state: RuntimeState):
    is_terminal(state.status)
"""
    assert len(find_raw_state_status_offenders(code7)) == 1

    # 8. Constructor provenance negative control
    code8 = """
state = RuntimeState(...)
if state.status == HostTurnStatus.COMMITTED:
    pass
"""
    assert len(find_raw_state_status_offenders(code8)) == 1

    # 9. Alias negative control
    code9 = """
def x(state: RuntimeState):
    state2 = state
    if state2.status == HostTurnStatus.COMMITTED:
        pass
"""
    assert len(find_raw_state_status_offenders(code9)) == 1

    # 10. Unknown receiver negative control (fails closed)
    code10 = """
def x(something_unknown):
    if something_unknown.status == "anything":
        pass
"""
    assert len(find_raw_state_status_offenders(code10)) == 1

    # 11. Reviewer counterexample: conditional reassignment from state / unproven expression
    code11 = """
def x(state: RuntimeState, projection: AppraisalProjectionResult, flag: bool):
    projection = state if flag else projection
    if projection.status == HostTurnStatus.COMMITTED:
        pass
"""
    assert len(find_raw_state_status_offenders(code11)) == 1

    # 12. Reassignment from subscript/index
    code12 = """
def x(projection: AppraisalProjectionResult, states: list):
    projection = states[0]
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code12)) == 1

    # 13. Reassignment from attribute
    code13 = """
def x(projection: AppraisalProjectionResult, holder: object):
    projection = holder.state
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code13)) == 1

    # 14. Reassignment from unknown function call
    code14 = """
def x(projection: AppraisalProjectionResult):
    projection = unknown_call()
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code14)) == 1

    # 15. Direct reassignment from state
    code15 = """
def x(projection: AppraisalProjectionResult, state: RuntimeState):
    projection = state
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code15)) == 1

    # 16. AnnAssign cast attempt with state
    code16 = """
def x(state: RuntimeState):
    projection: AppraisalProjectionResult = state
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code16)) == 1

    # 17. AnnAssign cast attempt with unknown call
    code17 = """
def x():
    projection: AppraisalProjectionResult = unknown_call()
    if projection.status is not ProjectionStatus.MAPPED:
        pass
"""
    assert len(find_raw_state_status_offenders(code17)) == 1

    # 18. For-loop variable overwrite
    code18 = """
def x(projection: AppraisalProjectionResult, items: list):
    for projection in items:
        if projection.status is not ProjectionStatus.MAPPED:
            pass
"""
    assert len(find_raw_state_status_offenders(code18)) == 1


def test_orchestrator_exposes_canonical_unchanged_with_resolver() -> None:
    canonical = make_state(
        dimension="user.sleep.phase", value="sleeping", status="active", state_id="s-1"
    )
    orchestrator = make_orchestrator(canonical_snapshot=(canonical,))
    assert orchestrator.canonical == (canonical,)
