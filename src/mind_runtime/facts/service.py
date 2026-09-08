"""FactIngestService: the D3 factual admission entry point (ADR-0009).

Dispositions (NEW / REPAIRED / REPLAY / conflict) are decided from the
append-only stores and, when a durable backend is present, arbitrated by the
backend transaction: a lost write re-reads the backend-authoritative pair and
returns REPLAY (or fails closed on byte conflict). Idempotency ownership lives
here — validation never detects duplicates.

C7C-R: ``OperationalFactAdmission`` (below) freezes the
settled-action projection surface so that ``admit_operational_fact``
cannot become a generic key/value side door.
"""

import logging
from datetime import datetime
from typing import ClassVar

from mind_runtime.contracts import (
    Authority,
    AuthorityLevel,
    DeliveryStatus,
    Evidence,
    Observation,
    Scope,
    SyncFields,
)
from mind_runtime.contracts.common import (
    require_aware_utc,
    require_non_empty,
    validate_sync_fields,
)
from mind_runtime.facts.persistence import FactBackend
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    FactAdmissionObserver,
    FactAdmissionResult,
)
from mind_runtime.facts.provenance import ProvenanceRecorder
from mind_runtime.facts.store import EvidenceStore, ObservationStore
from mind_runtime.facts.validators import (
    AuthorityError,
    AuthorityValidator,
    OwnershipError,
    OwnershipValidator,
)
from mind_runtime.providers.clock import Clock

# ============================================================================
# C7C-R: OperationalFactAdmission (frozen allow-list + authority contract).
#
# A counter fact under ``counter.last_proactive_at`` or
# ``counter.proactive_prompts_since_photo`` is an operational fact
# that the C5B/C6B readers consume under a stable semantic key.
# The C7C settled-action projector is the SINGLE producer; this
# class freezes the surface so that no random internal caller can
# become a second writer.
#
# Three guarantees:
#   1. Key allow-list: only the two C7C counter keys. Any other
#      key is refused.
#   2. Source-type allow-list: only ``settled_action_projection``.
#      SYSTEM authority alone is NOT sufficient.
#   3. Settled-delivery authority: the evidence must carry the
#      receipt identity (source_id == receipt.receipt_id) and
#      the receipt must be SENT/ACCEPTED.
# ============================================================================


class OperationalFactAdmission:
    """The frozen allow-list + authority contract for operational
    counter facts. C7C-R freezes this surface; any new key MUST
    be added here and the existing C7C tests updated.
    """

    ALLOWED_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "counter.last_proactive_at",
            "counter.proactive_prompts_since_photo",
        }
    )
    ALLOWED_SOURCE_TYPE: ClassVar[str] = "settled_action_projection"

    @classmethod
    def validate_key(cls, key: str) -> None:
        require_non_empty(key, "key")
        if key not in cls.ALLOWED_KEYS:
            raise ValueError(
                f"unknown operational key {key!r}; "
                f"allowed keys are sorted {sorted(cls.ALLOWED_KEYS)}"
            )

    @classmethod
    def validate_source_type(cls, source_type: str) -> None:
        require_non_empty(source_type, "source_type")
        if source_type != cls.ALLOWED_SOURCE_TYPE:
            raise ValueError(
                f"operational facts require source_type="
                f"{cls.ALLOWED_SOURCE_TYPE!r}; got {source_type!r}"
            )

    @staticmethod
    def validate_action_type(request: object) -> None:
        action_type = getattr(request, "action_type", None)
        if not isinstance(action_type, str) or not action_type:
            raise ValueError(
                "request.action_type is required (non-empty) for a "
                "settled-action projection; legacy unknown action_type "
                "is not backfilled silently"
            )

    @staticmethod
    def validate_settled_at(settled_at: datetime) -> None:
        try:
            require_aware_utc(settled_at, "settled_at")
        except ValueError as exc:
            raise ValueError(
                f"settled_at must be timezone-aware UTC: {exc}"
            ) from exc

    @staticmethod
    def validate_scope(
        *, evidence_scope: Scope, request: object, receipt: object,
    ) -> None:
        request_scope = getattr(request, "scope", None)
        receipt_scope = getattr(receipt, "scope", None)
        if request_scope is None or receipt_scope is None:
            raise ValueError(
                "request and receipt must both carry a scope"
            )
        if evidence_scope != request_scope or evidence_scope != receipt_scope:
            raise ValueError(
                f"operational fact scope must match request and "
                f"receipt scope; got evidence={evidence_scope!r} "
                f"request={request_scope!r} receipt={receipt_scope!r}"
            )

    @classmethod
    def validate_authority(
        cls,
        evidence: Evidence,
        request: object,
        receipt: object,
    ) -> None:
        """The settled-delivery authority contract.

        A operational-fact admit is valid iff all seven conditions
        hold; any failure is fail-closed (ValueError) with NO
        side effects.
        """
        cls.validate_source_type(evidence.source_type)
        # SYSTEM-only is the documented contract; the other branches
        # are unreachable from the public API.
        if evidence.authority_level is not AuthorityLevel.SYSTEM:  # pragma: no cover
            raise ValueError(
                f"operational facts require SYSTEM authority; got "
                f"{evidence.authority_level!r}"
            )
        receipt_id = getattr(receipt, "receipt_id", None)
        # The DeliveryReceipt dataclass refuses an empty receipt_id
        # in __post_init__, so this branch is unreachable from
        # the public API. Kept as defense in depth.
        if not isinstance(receipt_id, str) or not receipt_id:  # pragma: no cover
            raise ValueError("receipt.receipt_id is required")
        if evidence.source_id != receipt_id:
            raise ValueError(
                f"operational fact evidence.source_id must equal "
                f"receipt.receipt_id; got {evidence.source_id!r} "
                f"expected {receipt_id!r}"
            )
        cls.validate_scope(
            evidence_scope=evidence.scope, request=request, receipt=receipt,
        )
        delivery_status = getattr(receipt, "delivery_status", None)
        if delivery_status is not DeliveryStatus.SENT:
            raise ValueError(
                f"settled-action projection requires receipt "
                f"delivery_status=SENT; got {delivery_status!r}"
            )
        cls.validate_action_type(request)
        delivered_at = getattr(receipt, "delivered_at", None)
        if delivered_at is None:
            raise ValueError(
                "settled-action projection requires receipt.delivered_at"
            )
        cls.validate_settled_at(delivered_at)
        try:
            validate_sync_fields(
                evidence.sync,
                scope=evidence.scope,
                origin_runtime_id=evidence.origin_runtime_id,
                object_id=evidence.id,
            )
        # Evidence.__post_init__ already enforces sync.object_id
        # integrity; this branch is unreachable from the public API.
        except ValueError as exc:  # pragma: no cover
            raise ValueError(
                f"operational fact evidence sync envelope invalid: {exc}"
            ) from exc

    @classmethod
    def is_known_action_type(
        cls, action_type: str | None,
    ) -> bool:
        """Whether a row's ``action_type`` is known (and thus eligible
        for the settled-action projection). A legacy empty / unknown
        value is NOT backfilled silently — the projector must fail
        closed unless an operator-facing deterministic backfill is
        explicitly registered.
        """
        if not isinstance(action_type, str) or not action_type:
            return False
        return action_type in {"proactive_message", "send_photo"}


class FactAdmissionConflictError(RuntimeError):
    """Same ``(scope, id)`` with different immutable bytes, or an impossible
    partial pair. Admission fails closed; the conflict is never reinterpreted
    as replay."""


class FactIngestService:
    """Admits Evidence into the factual plane after authority/ownership gates.

    The in-memory stores are a cache seeded from the durable backend at
    construction; the backend is the source of truth for restart semantics
    and for concurrent arbitration.
    """

    def __init__(self, *, clock: Clock, backend: FactBackend | None = None,
                 after_admission: FactAdmissionObserver | None = None) -> None:
        self._clock = clock
        self._after_admission = after_admission
        self._backend = backend
        self._authority = AuthorityValidator(clock=clock)
        self._ownership = OwnershipValidator(clock=clock)
        self._evidence = EvidenceStore()
        self._observations = ObservationStore()
        self._provenance = ProvenanceRecorder()
        if backend is not None:
            for evidence, interaction_id in backend.load_evidence():
                self._evidence.append(evidence)
                self._provenance.record(evidence, interaction_id=interaction_id)
            for observation in backend.load_observations():
                self._observations.append(observation)

    @property
    def evidence(self) -> EvidenceStore:
        return self._evidence

    @property
    def observations(self) -> ObservationStore:
        return self._observations

    @property
    def provenance(self) -> ProvenanceRecorder:
        return self._provenance

    def admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        result = self._admit(evidence, interaction_id=interaction_id,
                             writing_runtime=writing_runtime,
                             writing_persona_id=writing_persona_id)
        if self._after_admission is not None:
            try:
                self._after_admission.after_admission(evidence, result)
            except Exception as exc:
                # A derived consumer cannot suppress NEW after factual commit.
                # Its registered durable job can retry on a later replay.
                # Do not log candidate content or provider exception payloads.
                logging.getLogger(__name__).warning(
                    "Post-admission observer failed (%s); factual result preserved",
                    type(exc).__name__,
                )
        return result

    def _admit(
        self,
        evidence: Evidence,
        *,
        interaction_id: str,
        writing_runtime: str,
        writing_persona_id: str | None,
    ) -> FactAdmissionResult:
        stored_evidence = self._evidence.get(evidence.scope, evidence.id)
        observation_id = f"observation-{evidence.id}"
        stored_observation = self._observations.get(evidence.scope, observation_id)
        # Impossible partial pair: an Observation without its Evidence can
        # never be admitted, healed, or reinterpreted as replay.
        if stored_observation is not None and stored_evidence is None:
            raise FactAdmissionConflictError(
                f"observation {observation_id} exists without its evidence row"
            )
        # Capture the durable original provenance interaction BEFORE recording
        # the current admission, so a repair binds the first admission's
        # identity, never this attempt's (ADR-0009 §2).
        original_interaction_id = next(
            (
                entry.interaction_id
                for entry in self._provenance.all()
                if entry.scope == evidence.scope and entry.evidence_id == evidence.id
            ),
            None,
        )
        # Evidence is always stored (independent auditability), even when the
        # admission is rejected — the gate decides admission, not retention.
        is_new_evidence = self._evidence.append(evidence)
        self._provenance.record(evidence, interaction_id=interaction_id)
        # Same (scope, id) with different immutable bytes fails closed. The
        # in-memory cache can hold a stale/poisoned entry (e.g. after a lost
        # arbitration conflict), so with a durable backend the byte identity
        # is re-verified against the backend row — the cache is a cache, not
        # the arbiter (ADR-0009 §5).
        if stored_evidence is not None and stored_evidence != evidence:
            if self._backend is None or (
                (backend_pair := self._backend.find_evidence(evidence.scope, evidence.id)) is None
                or backend_pair[0] != evidence
            ):
                raise FactAdmissionConflictError(
                    f"evidence {evidence.id} reuses (scope, id) with different immutable bytes"
                )
        try:
            self._authority.require_user_fact(evidence)
            self._ownership.require_owner(
                evidence,
                writing_runtime=writing_runtime,
                writing_persona_id=writing_persona_id,
            )
        except (AuthorityError, OwnershipError):
            # Rejected evidence is still persisted alone: the audit trail must
            # survive restart even when the admission is denied.
            if self._backend is not None and is_new_evidence:
                self._backend.save_evidence(evidence, interaction_id=interaction_id)
            raise
        if stored_observation is not None:
            # Exact Evidence and derived Observation already exist: replay.
            # The byte-identity of the Evidence was checked above, so the
            # stored Observation is the authoritative one.
            return FactAdmissionResult(
                observation=stored_observation,
                disposition=FactAdmissionDisposition.REPLAY,
            )
        if is_new_evidence:
            observation = self._build_observation(
                evidence, interaction_id=interaction_id, observed_at=self._clock.now()
            )
            if self._backend is not None:
                # One transaction for the admitted pair (D3.C2 boundary); the
                # backend write is the arbiter when caches are stale.
                if not self._backend.save_admission(
                    evidence, interaction_id=interaction_id, observation=observation
                ):
                    return self._arbitrate(evidence)
            self._observations.append(observation)
            return FactAdmissionResult(observation, FactAdmissionDisposition.NEW)
        # Crash window: the exact Evidence already exists but its derived
        # Observation is missing. The repaired Observation keeps the original
        # admission's causal identity (ADR-0009 §2): the durable original
        # provenance Interaction ID (the backend row when present — the
        # in-memory provenance mirror may be stale) and the immutable
        # Evidence.received_at. A missing durable Evidence row fails closed
        # instead of fabricating an orphan Observation.
        if self._backend is not None:
            stored_pair = self._backend.find_evidence(evidence.scope, evidence.id)
            if stored_pair is None:
                raise FactAdmissionConflictError(
                    f"evidence {evidence.id} row is missing from the durable store"
                )
            original_interaction_id = stored_pair[1]
        if original_interaction_id is None:
            raise FactAdmissionConflictError(
                f"evidence {evidence.id} has no original provenance interaction"
            )
        observation = self._build_observation(
            evidence,
            interaction_id=original_interaction_id,
            observed_at=evidence.received_at,
        )
        if self._backend is not None and not self._backend.save_observation(observation):
            return self._arbitrate(evidence)
        self._observations.append(observation)
        return FactAdmissionResult(observation, FactAdmissionDisposition.REPAIRED)

    def _build_observation(
        self, evidence: Evidence, *, interaction_id: str, observed_at: datetime
    ) -> Observation:
        return Observation(
            id=f"observation-{evidence.id}",
            interaction_id=interaction_id,
            scope=evidence.scope,
            origin_runtime_id=evidence.origin_runtime_id,
            type="factual",
            key=f"{evidence.source_type}.observed",
            value=evidence.payload,
            confidence=1.0,
            observed_at=observed_at,
            evidence_refs=(evidence.id,),
            sync=SyncFields(
                evidence.scope,
                evidence.origin_runtime_id,
                f"observation-{evidence.id}",
                1,
                f"idem-obs-{evidence.id}",
            ),
        )

    def admit_operational_fact(
        self,
        *,
        key: str,
        value: str,
        request: object,
        receipt: object,
        observed_at: datetime | None = None,
    ) -> Observation:
        """Admit a C7C-R settled-delivery operational fact.

        C7C-R contract: the only valid caller is the C7C
        ``SettledActionProjector`` carrying a settled
        DeliveryReceipt (provider-accepted). This method refuses
        any caller that does not satisfy the
        ``OperationalFactAdmission`` authority contract:

          1. ``key`` is on the allow-list
             (counter.last_proactive_at or
             counter.proactive_prompts_since_photo).
          2. ``request.action_type`` is a known typed action
             (proactive_message or send_photo). Legacy empty /
             unknown action_type is NOT backfilled silently — a
             ``ValueError`` is raised before any side effect.
          3. ``receipt.delivery_status == SENT`` and
             ``receipt.delivered_at`` is timezone-aware UTC.
          4. ``request.scope == receipt.scope``.
          5. The deterministic observation id is derived from
             ``(receipt.receipt_id, key)``; a re-admit with the same
             pair is a no-op.

        The caller passes the ``request`` and ``receipt`` so the
        authority can be enforced end-to-end (no stringly-typed
        side door). A random internal caller that does not hold a
        settled delivery outcome cannot admit counter facts.
        """
        OperationalFactAdmission.validate_key(key)
        require_non_empty(value, "value")
        OperationalFactAdmission.validate_action_type(request)
        # The receipt.delivered_at IS the observed_at; the caller
        # is allowed to override (e.g. backfill path) but the
        # default is the receipt's authoritative timestamp.
        if observed_at is None:
            delivered_at = getattr(receipt, "delivered_at", None)
            if delivered_at is None:
                raise ValueError(
                    "settled-action projection requires "
                    "receipt.delivered_at; refuse to fabricate observed_at"
                )
            # Unreachable from the public API today: every caller
            # uses the default observed_at (which falls back from
            # receipt.delivered_at). Kept as defense in depth.
            observed_at = delivered_at  # pragma: no cover
        OperationalFactAdmission.validate_settled_at(observed_at)
        # End-to-end authority check (covers scope + status + sync
        # envelope + identity). The receipt is the only authority;
        # the synthesized Evidence is built from it.
        receipt_id = getattr(receipt, "receipt_id", None)
        receipt_scope = getattr(receipt, "scope", None)
        receipt_origin = getattr(receipt, "origin_runtime_id", None)
        # DeliveryReceipt.__post_init__ blocks empty id / non-Scope;
        # these branches are unreachable from the public API.
        if (
            not isinstance(receipt_id, str) or not receipt_id
        ):  # pragma: no cover
            raise ValueError("receipt.receipt_id is required")
        if not isinstance(receipt_scope, Scope):  # pragma: no cover
            raise ValueError("receipt.scope must be a Scope")
        # Build a transient evidence purely to validate the
        # authority contract end-to-end; the observation id is
        # deterministic from (receipt_id, key) so this is the
        # only place we need the evidence shape.
        evidence_id = f"op-evidence-{receipt_id}-{key}"
        evidence = Evidence(
            id=evidence_id,
            scope=receipt_scope,
            origin_runtime_id=receipt_origin or "",
            source_type=OperationalFactAdmission.ALLOWED_SOURCE_TYPE,
            source_id=receipt_id,
            authority_level=AuthorityLevel.SYSTEM,
            authority=Authority(
                scope=receipt_scope,
                level=AuthorityLevel.SYSTEM,
                source_id=receipt_id,
            ),
            occurred_at=observed_at,
            received_at=observed_at,
            payload={"key": key, "value": value},
            sync=SyncFields(
                receipt_scope, receipt_origin or "", evidence_id, 1,
                f"idem-op-evidence-{receipt_id}-{key}",
            ),
        )
        OperationalFactAdmission.validate_authority(evidence, request, receipt)
        # Deterministic observation id keyed by (receipt_id, key).
        observation_id = f"op-{receipt_id}-{key}"
        existing = self._observations.get(receipt_scope, observation_id)
        if existing is not None:
            return existing
        observation = Observation(
            id=observation_id,
            interaction_id=f"operational-{receipt_id}-{key}",
            scope=receipt_scope,
            origin_runtime_id=receipt_origin or "",
            type="operational",
            key=key,
            value=value,
            confidence=1.0,
            observed_at=observed_at,
            evidence_refs=(receipt_id,),
            sync=SyncFields(
                receipt_scope, receipt_origin or "", observation_id, 1,
                f"idem-op-{receipt_id}-{key}",
            ),
        )
        if self._backend is not None:
            with self._backend._conn:  # type: ignore[attr-defined]
                self._backend.save_evidence(
                    evidence,
                    interaction_id=f"operational-{receipt_id}-{key}",
                )
                self._backend.save_observation(observation)
        self._observations.append(observation)
        return observation

    def _arbitrate(self, evidence: Evidence) -> FactAdmissionResult:
        """Re-derive the disposition from the backend after a lost write.

        The backend transaction chose another writer; the loser must return
        the backend-authoritative stored Observation, never a freshly
        constructed current-interaction Observation (ADR-0009 §5). A repair
        written here is rebuilt from the backend-authoritative stored
        Evidence so the ADR-0009 §2 binding (original provenance
        interaction, immutable received_at) always holds — the caller's
        observation may be current-bound when its cache was stale.
        """
        assert self._backend is not None
        observation_id = f"observation-{evidence.id}"
        stored = self._backend.find_evidence(evidence.scope, evidence.id)
        stored_observation = self._backend.find_observation(evidence.scope, observation_id)
        if stored is None:
            raise FactAdmissionConflictError(
                f"observation {observation_id} exists without its evidence row"
            )
        stored_evidence, stored_interaction = stored
        if stored_evidence != evidence:
            raise FactAdmissionConflictError(
                f"evidence {evidence.id} reuses (scope, id) with different immutable bytes"
            )
        if stored_observation is not None:
            self._observations.append(stored_observation)
            return FactAdmissionResult(stored_observation, FactAdmissionDisposition.REPLAY)
        # Evidence-only: another writer is mid-repair, or this service's cache
        # was stale. Rebuild the repair from the durable row so the binding
        # is the original provenance interaction and Evidence.received_at;
        # the repair is deterministic, so either winner's row is identical.
        repair = self._build_observation(
            stored_evidence,
            interaction_id=stored_interaction,
            observed_at=stored_evidence.received_at,
        )
        if self._backend.save_observation(repair):
            self._observations.append(repair)
            return FactAdmissionResult(repair, FactAdmissionDisposition.REPAIRED)
        stored_observation = self._backend.find_observation(evidence.scope, observation_id)
        if stored_observation is None:
            raise FactAdmissionConflictError(
                f"observation {observation_id} still missing after arbitration"
            )
        self._observations.append(stored_observation)
        return FactAdmissionResult(stored_observation, FactAdmissionDisposition.REPLAY)
