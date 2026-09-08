"""Mind Runtime factual ingestion (D3)."""

from mind_runtime.facts.coordinator import InteractionCoordinator
from mind_runtime.facts.persistence import FactBackend, SqliteFactBackend
from mind_runtime.facts.ports import (
    FactAdmissionDisposition,
    FactAdmissionResult,
    FactIngestPort,
)
from mind_runtime.facts.service import (
    FactAdmissionConflictError,
    FactIngestService,
)
from mind_runtime.facts.store import EvidenceStore, ObservationStore
from mind_runtime.facts.validators import (
    AuthorityError,
    AuthorityValidator,
    OwnershipError,
    OwnershipValidator,
)

__all__ = [
    "AuthorityError",
    "AuthorityValidator",
    "EvidenceStore",
    "FactAdmissionConflictError",
    "FactAdmissionDisposition",
    "FactAdmissionResult",
    "FactBackend",
    "FactIngestPort",
    "FactIngestService",
    "InteractionCoordinator",
    "ObservationStore",
    "OwnershipError",
    "OwnershipValidator",
    "SqliteFactBackend",
]
