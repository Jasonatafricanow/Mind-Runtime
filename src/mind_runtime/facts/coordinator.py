"""InteractionCoordinator: lifecycle driver for the D1 Interaction contract."""

from mind_runtime.contracts import Interaction, InteractionStatus, Scope
from mind_runtime.facts.persistence import FactBackend
from mind_runtime.providers.clock import Clock


class InteractionCoordinator:
    """Tracks interactions through begin/processing/commit/abort.

    Interactions persist through the optional backend (V0.1.4 first-batch
    ``interactions`` table): a restarted coordinator re-loads known
    interactions so lifecycle transitions stay fail-closed after restart.
    The in-flight ``processing`` marker is runtime state, not durable.
    """

    def __init__(self, *, clock: Clock, backend: FactBackend | None = None) -> None:
        self._clock = clock
        self._backend = backend
        self._known: dict[str, Interaction] = {}
        self._processing: set[str] = set()
        if backend is not None:
            for interaction in backend.load_interactions():
                self._known[interaction.interaction_id] = interaction

    def get_interaction(self, interaction_id: str) -> Interaction | None:
        """Return the known interaction or None (restart-safe read)."""
        return self._known.get(interaction_id)

    def begin_interaction(
        self,
        *,
        interaction_id: str,
        scope: Scope,
        channel: str,
        session_id: str,
        turn_id: str,
    ) -> Interaction:
        if interaction_id in self._known:
            raise ValueError(f"interaction already exists: {interaction_id}")
        interaction = Interaction(
            interaction_id=interaction_id,
            scope=scope,
            channel=channel,
            session_id=session_id,
            turn_id=turn_id,
            started_at=self._clock.now(),
            committed_at=None,
            status=InteractionStatus.OPEN,
        )
        self._known[interaction_id] = interaction
        if self._backend is not None:
            self._backend.save_interaction(interaction)
        return interaction

    def processing(self, interaction: Interaction) -> None:
        self._require_active(interaction)
        self._processing.add(interaction.interaction_id)

    def is_processing(self, interaction_id: str) -> bool:
        return interaction_id in self._processing

    def commit_interaction(self, interaction: Interaction) -> Interaction:
        self._require_active(interaction)
        committed = Interaction(
            interaction_id=interaction.interaction_id,
            scope=interaction.scope,
            channel=interaction.channel,
            session_id=interaction.session_id,
            turn_id=interaction.turn_id,
            started_at=interaction.started_at,
            committed_at=self._clock.now(),
            status=InteractionStatus.COMMITTED,
        )
        self._known[interaction.interaction_id] = committed
        self._processing.discard(interaction.interaction_id)
        if self._backend is not None:
            self._backend.save_interaction(committed)
        return committed

    def abort_interaction(self, interaction: Interaction) -> Interaction:
        self._require_active(interaction)
        aborted = Interaction(
            interaction_id=interaction.interaction_id,
            scope=interaction.scope,
            channel=interaction.channel,
            session_id=interaction.session_id,
            turn_id=interaction.turn_id,
            started_at=interaction.started_at,
            committed_at=None,
            status=InteractionStatus.ABORTED,
        )
        self._known[interaction.interaction_id] = aborted
        self._processing.discard(interaction.interaction_id)
        if self._backend is not None:
            self._backend.save_interaction(aborted)
        return aborted

    def _require_active(self, interaction: Interaction) -> None:
        current = self._known.get(interaction.interaction_id)
        if current is None:
            raise ValueError(f"unknown interaction: {interaction.interaction_id}")
        if current.status is not InteractionStatus.OPEN:
            raise ValueError(
                f"interaction already {current.status.value}: {interaction.interaction_id}"
            )
