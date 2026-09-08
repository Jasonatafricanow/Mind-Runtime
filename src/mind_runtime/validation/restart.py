"""D11S.6 fresh-composition restart certification for the durable Product Slice."""

from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import dataclass
from pathlib import Path

from mind_runtime.contracts import (
    ActionReceipt,
    HistoricalContextBundle,
    Intent,
    IntentTransition,
    RuntimeState,
    StateDefinition,
    TurnCheckpoint,
)
from mind_runtime.facts.persistence import SqliteFactBackend
from mind_runtime.intents.persistence import SqliteIntentBackend
from mind_runtime.pipeline.checkpoints import (
    RecoveryDecision,
    SqliteCheckpointStore,
    recovery_decision,
)
from mind_runtime.pipeline.fake_agent import FakeAgent
from mind_runtime.pipeline.receipts import ReceiptRegistry
from mind_runtime.state.persistence import SqliteStateBackend
from mind_runtime.validation.composition import (
    CertificationRuntimeConfig,
    DurablePaths,
    _require_unambiguous_current_states,
    build_composition,
)
from mind_runtime.validation.contracts import (
    RestartFixture,
    decode_runtime_config_manifest_bytes,
    decode_runtime_manifest,
    verify_fixture_artifacts,
)
from mind_runtime.validation.digest import canonical_json_bytes, sha256_bytes
from mind_runtime.validation.schedule import SimulationClock


@dataclass(frozen=True, slots=True)
class _RestartRecords:
    facts: tuple[object, ...]
    state: tuple[object, ...]
    intents: tuple[object, ...]
    checkpoint: TurnCheckpoint
    recovery: RecoveryDecision
    current_states: tuple[RuntimeState, ...]
    intent_history: tuple[Intent, ...]
    intent_transitions: tuple[IntentTransition, ...]
    current_intent: Intent
    receipts: tuple[ActionReceipt, ...]


@dataclass(frozen=True, slots=True)
class _CanonicalRuntimeRecords:
    states: tuple[RuntimeState, ...]
    recovery: RecoveryDecision


@dataclass(frozen=True, slots=True)
class RestartCertificationResult:
    """Exact before/after evidence for a fresh SQLite-backed composition."""

    fact_digest_before: str
    fact_digest_after: str
    state_digest_before: str
    state_digest_after: str
    canonical_state_digest_before: str
    canonical_state_digest_after: str
    intent_digest_before: str
    intent_digest_after: str
    checkpoint_digest_before: str
    checkpoint_digest_after: str
    recovery_decision_before: RecoveryDecision
    recovery_decision_after: RecoveryDecision
    history_hash_before: str
    history_hash_after: str
    restored_states: tuple[RuntimeState, ...]
    canonical_states_after: tuple[RuntimeState, ...]
    intent_history: tuple[Intent, ...]
    intent_transitions: tuple[IntentTransition, ...]
    current_intent: Intent
    restored_checkpoint: TurnCheckpoint
    restored_history: HistoricalContextBundle
    receipt_count_before: int
    receipt_count_after: int

    def __post_init__(self) -> None:
        for before_name, after_name in (
            ("fact_digest_before", "fact_digest_after"),
            ("state_digest_before", "state_digest_after"),
            ("canonical_state_digest_before", "canonical_state_digest_after"),
            ("intent_digest_before", "intent_digest_after"),
            ("checkpoint_digest_before", "checkpoint_digest_after"),
            ("history_hash_before", "history_hash_after"),
        ):
            before = getattr(self, before_name)
            after = getattr(self, after_name)
            if not _is_sha256(before) or not _is_sha256(after):
                raise ValueError("restart digests must be SHA-256 values")
            if before != after:
                raise ValueError(f"{before_name} must equal {after_name}")
        if self.recovery_decision_before != self.recovery_decision_after:
            raise ValueError("restart recovery decision must remain exact")
        if self.receipt_count_before != 0 or self.receipt_count_after != 0:
            raise ValueError("D11S restart cannot claim durable ActionReceipt records")


def certify_restart(
    plan: RestartFixture,
    paths: DurablePaths,
    *,
    repository_root: Path | None = None,
) -> RestartCertificationResult:
    """Seed, close, release, reopen, and compare every existing durable plane."""
    if not isinstance(plan, RestartFixture):
        raise ValueError("plan must be a RestartFixture")
    if not isinstance(paths, DurablePaths):
        raise ValueError("paths must be DurablePaths")
    _require_fresh_paths(paths)
    _require_unambiguous_current_states(plan.states)
    repository = Path(__file__).resolve().parents[3]
    if repository_root is not None:
        repository = repository_root.resolve()
    state_definitions = _complete_state_definitions(plan, repository)

    stores = _open_stores(paths)
    try:
        _seed_fixture(stores, plan, state_definitions=state_definitions)
        seeded_before = _capture_records(stores, plan)
    finally:
        stores.close()
    del stores

    canonical_before = _capture_canonical_runtime(plan, paths, repository)
    reopened_before = _capture_reopened_records(plan, paths)
    canonical_after = _capture_canonical_runtime(plan, paths, repository)
    reopened_after = _capture_reopened_records(plan, paths)
    history_before = sha256_bytes(canonical_json_bytes(plan.historical_context))
    history_after = sha256_bytes(canonical_json_bytes(plan.historical_context))

    digests = {
        "fact": (_digest(seeded_before.facts), _digest(reopened_after.facts)),
        "state": (_digest(seeded_before.state), _digest(reopened_after.state)),
        "canonical_state": (_digest(canonical_before.states), _digest(canonical_after.states)),
        "intent": (_digest(seeded_before.intents), _digest(reopened_after.intents)),
        "checkpoint": (_digest(seeded_before.checkpoint), _digest(reopened_after.checkpoint)),
    }
    first_reopen_digests = {
        "fact": (_digest(seeded_before.facts), _digest(reopened_before.facts)),
        "state": (_digest(seeded_before.state), _digest(reopened_before.state)),
        "intent": (_digest(seeded_before.intents), _digest(reopened_before.intents)),
        "checkpoint": (_digest(seeded_before.checkpoint), _digest(reopened_before.checkpoint)),
    }
    repeat_digests = {
        "fact": (_digest(reopened_before.facts), _digest(reopened_after.facts)),
        "state": (_digest(reopened_before.state), _digest(reopened_after.state)),
        "intent": (_digest(reopened_before.intents), _digest(reopened_after.intents)),
        "checkpoint": (_digest(reopened_before.checkpoint), _digest(reopened_after.checkpoint)),
    }
    for comparison in (first_reopen_digests, repeat_digests, digests):
        for plane, (before_digest, after_digest) in comparison.items():
            if before_digest != after_digest:
                raise ValueError(f"{plane} durable plane changed across restart")
    if not (seeded_before.recovery == reopened_before.recovery == reopened_after.recovery):
        raise ValueError("checkpoint recovery decision changed across restart")
    if canonical_before.recovery != canonical_after.recovery:
        raise ValueError("canonical recovery decision changed across restart")
    if canonical_before.recovery != reopened_before.recovery:
        raise ValueError("canonical recovery must equal the durable checkpoint decision")
    if history_before != history_after:
        raise ValueError("read-only history changed across restart")

    return RestartCertificationResult(
        fact_digest_before=digests["fact"][0],
        fact_digest_after=digests["fact"][1],
        state_digest_before=digests["state"][0],
        state_digest_after=digests["state"][1],
        canonical_state_digest_before=digests["canonical_state"][0],
        canonical_state_digest_after=digests["canonical_state"][1],
        intent_digest_before=digests["intent"][0],
        intent_digest_after=digests["intent"][1],
        checkpoint_digest_before=digests["checkpoint"][0],
        checkpoint_digest_after=digests["checkpoint"][1],
        recovery_decision_before=seeded_before.recovery,
        recovery_decision_after=reopened_after.recovery,
        history_hash_before=history_before,
        history_hash_after=history_after,
        restored_states=reopened_after.current_states,
        canonical_states_after=canonical_after.states,
        intent_history=reopened_after.intent_history,
        intent_transitions=reopened_after.intent_transitions,
        current_intent=reopened_after.current_intent,
        restored_checkpoint=reopened_after.checkpoint,
        restored_history=plan.historical_context,
        receipt_count_before=len(seeded_before.receipts),
        receipt_count_after=len(reopened_after.receipts),
    )


def _capture_canonical_runtime(
    plan: RestartFixture,
    paths: DurablePaths,
    repository: Path,
) -> _CanonicalRuntimeRecords:
    manifest_path = repository / "certification/d11s/inputs/runtime-config.json"
    manifest_bytes = manifest_path.read_bytes()
    composition = build_composition(
        CertificationRuntimeConfig(
            repository_root=repository,
            manifest_path=manifest_path,
            manifest_sha256=sha256_bytes(manifest_bytes),
            durable_paths=paths,
            clock=SimulationClock(plan.checkpoint.checkpointed_at),
            certification_id="g12-composite-restart",
            agent=FakeAgent(("重启认证。",)),
        )
    )
    try:
        states = _highest_states(composition.orchestrator.canonical)
        expected = _highest_states(plan.states)
        if states != expected:
            raise ValueError("canonical runtime must restore exact highest-version State records")
        recovery = composition.orchestrator.recover(plan.checkpoint.interaction_id)
        return _CanonicalRuntimeRecords(states=states, recovery=recovery)
    finally:
        composition.close()


class _RestartStores:
    def __init__(self, paths: DurablePaths) -> None:
        stack = ExitStack()
        self.facts = stack.enter_context(closing(SqliteFactBackend(paths.facts_db)))
        self.state = stack.enter_context(closing(SqliteStateBackend(paths.state_db)))
        self.intents = stack.enter_context(closing(SqliteIntentBackend(paths.intents_db)))
        self.checkpoints = stack.enter_context(closing(SqliteCheckpointStore(paths.checkpoints_db)))
        self._stack = stack.pop_all()
        self.receipts = ReceiptRegistry()

    def close(self) -> None:
        self._stack.close()


def _open_stores(paths: DurablePaths) -> _RestartStores:
    for path in _paths(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
    return _RestartStores(paths)


def _seed_fixture(
    stores: _RestartStores,
    plan: RestartFixture,
    *,
    state_definitions: tuple[StateDefinition, ...],
) -> None:
    for interaction in plan.interactions:
        stores.facts.save_interaction(interaction)
    for evidence in plan.evidence:
        interaction_id = plan.expected_observation.interaction_id
        if not stores.facts.save_admission(
            evidence,
            interaction_id=interaction_id,
            observation=plan.expected_observation,
        ):
            raise ValueError("restart fact admission must be unique")

    for definition in state_definitions:
        stores.state.save_definition(definition)
    for state in plan.states:
        if not stores.state.save_state(state):
            raise ValueError("restart State must be uniquely durable")
    for state_transition in plan.state_transitions:
        stores.state.save_transition(state_transition)

    histories = _intent_groups(plan.intent_history)
    transitions = {item.intent_id: item for item in plan.intent_transitions}
    for history in histories:
        stores.intents.append_initial(history[0])
        before = history[0]
        for after in history[1:]:
            intent_transition = transitions.get(after.intent_id)
            if intent_transition is None or intent_transition.version != after.sync.version:
                raise ValueError("restart Intent version must have an exact transition")
            stores.intents.apply_transition(before, after, intent_transition)
            before = after
    stores.checkpoints.save(plan.checkpoint)


def _complete_state_definitions(
    plan: RestartFixture,
    repository: Path,
) -> tuple[StateDefinition, ...]:
    manifest_path = repository / "certification/d11s/inputs/runtime-config.json"
    manifest = decode_runtime_config_manifest_bytes(manifest_path.read_bytes())
    verify_fixture_artifacts(manifest, repository)
    decoded = decode_runtime_manifest(manifest)
    definitions = {definition.key: definition for definition in decoded.state_definitions.all()}
    for definition in plan.state_definitions:
        existing = definitions.get(definition.key)
        if existing is not None and existing != definition:
            raise ValueError("restart StateDefinition conflicts with the verified runtime manifest")
        definitions[definition.key] = definition
    return tuple(definitions[key] for key in sorted(definitions))


def _capture_reopened_records(plan: RestartFixture, paths: DurablePaths) -> _RestartRecords:
    """Load existing databases without allowing SQLite to create a missing plane."""
    missing = tuple(path for path in _paths(paths) if not path.is_file())
    if missing:
        raise ValueError("missing durable database: " + ", ".join(path.name for path in missing))
    stores = _open_stores(paths)
    try:
        return _capture_records(stores, plan)
    finally:
        stores.close()


def _capture_records(stores: _RestartStores, plan: RestartFixture) -> _RestartRecords:
    states = stores.state.load_states()
    _require_unambiguous_current_states(states)
    current_states = _highest_states(states)
    checkpoint = stores.checkpoints.load(plan.checkpoint.interaction_id)
    if checkpoint is None:
        raise ValueError("restart checkpoint must remain durable")

    intent_ids = tuple(dict.fromkeys(item.intent_id for item in plan.intent_history))
    if len(intent_ids) != 1:
        raise ValueError("G12 restart fixture must contain exactly one Intent")
    intent_id = intent_ids[0]
    scope = plan.intent_history[0].scope
    history = stores.intents.history(scope, intent_id)
    transitions = stores.intents.transitions(scope, intent_id)
    current = tuple(item for item in stores.intents.current(scope) if item.intent_id == intent_id)

    facts: tuple[object, ...] = (
        stores.facts.load_interactions(),
        stores.facts.load_evidence(),
        stores.facts.load_observations(),
    )
    state: tuple[object, ...] = (
        stores.state.load_definitions(),
        states,
        stores.state.load_transitions(),
        current_states,
    )
    intents: tuple[object, ...] = (current, history, transitions)
    return _RestartRecords(
        facts=facts,
        state=state,
        intents=intents,
        checkpoint=checkpoint,
        recovery=recovery_decision(checkpoint),
        current_states=current_states,
        intent_history=history,
        intent_transitions=transitions,
        current_intent=current[0],
        receipts=stores.receipts.all(),
    )


def _highest_states(states: tuple[RuntimeState, ...]) -> tuple[RuntimeState, ...]:
    current: dict[tuple[object, str], RuntimeState] = {}
    for state in states:
        key = (state.scope, state.dimension)
        previous = current.get(key)
        if previous is None or state.version > previous.version:
            current[key] = state
    return tuple(
        sorted(
            current.values(), key=lambda item: (item.dimension, canonical_json_bytes(item.scope))
        )
    )


def _intent_groups(history: tuple[Intent, ...]) -> tuple[tuple[Intent, ...], ...]:
    grouped: dict[tuple[object, str], list[Intent]] = {}
    for intent in history:
        grouped.setdefault((intent.scope, intent.intent_id), []).append(intent)
    return tuple(
        tuple(sorted(items, key=lambda item: item.sync.version))
        for _key, items in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _require_fresh_paths(paths: DurablePaths) -> None:
    existing = tuple(path for path in _paths(paths) if path.exists())
    if existing:
        raise ValueError("restart certification requires fresh durable paths")
    forbidden = tuple(
        parent / name
        for parent in {path.parent for path in _paths(paths)}
        for name in ("receipts.sqlite", "memory.sqlite")
        if (parent / name).exists()
    )
    if forbidden:
        raise ValueError(
            "unauthorized durable plane: " + ", ".join(path.name for path in forbidden)
        )


def _paths(paths: DurablePaths) -> tuple[Path, ...]:
    return (paths.facts_db, paths.state_db, paths.intents_db, paths.checkpoints_db)


def _digest(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )
