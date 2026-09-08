"""Egress boundary for private runtime data (ADR-0011, C1).

Private canonical cognition keeps real person/name semantics INSIDE the
instance trust boundary. The moment a record leaves that boundary — support
export, publication corpus, external inspection — it must be projected
through `sanitize_record`:

    PrivateRecord -> EgressPolicy -> SanitizedProjection

Contract properties (frozen here):
  * projection, never mutation — the canonical store is only read; the
    sanitized copy is a fresh value.
  * strict mode — person names ARE coded on egress even though private mode
    keeps them plaintext (ADR-0011 boundary split).
  * fail-closed — if protected plaintext would survive the policy, the
    egress is refused with EgressLeakError instead of emitted.
  * auditable, not reversible — provenance (source id/ts/scope, policy
    version, redaction reasons) travels with the copy while no protected
    value does.

This is deliberately NOT an export subsystem: callers decide where a
projection goes. C1 freezes the seam and its tests only.
"""

from __future__ import annotations

from dataclasses import dataclass

from mind_runtime.shadow.redaction import redact_text, sensitive_labels

POLICY_VERSION = "egress-v1"

_PERSON = "person"


@dataclass(frozen=True)
class SanitizedProjection:
    """Strictly sanitized COPY of one private record.

    Provenance fields let an auditor locate the exact source record and the
    policy version that produced this copy without any protected value being
    present in this object.
    """

    record_id: str
    source_type: str
    source_ts: str | None
    scope: str
    policy_version: str
    text: str
    redactions: tuple[str, ...]


class EgressLeakError(RuntimeError):
    """Refused egress: protected plaintext would survive the policy."""

    def __init__(self, labels: tuple[str, ...]) -> None:
        super().__init__(
            f"egress refused under {POLICY_VERSION}: unsanitizable sensitive "
            f"material remains: {', '.join(labels)}"
        )
        self.labels = labels


def _present_names(text: str, known_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in known_names if name and name in text)


def sanitize_record(
    text: str,
    *,
    record_id: str,
    source_type: str,
    source_ts: str | None = None,
    scope: str = "",
    known_names: tuple[str, ...] = (),
) -> SanitizedProjection:
    """Project one private record through the egress policy (pure function).

    Raises EgressLeakError when material that the policy cannot confidently
    tokenize (e.g. PIN/OTP-like digit runs) remains after redaction, so a
    caller can never accidentally emit it.
    """
    present = sensitive_labels(text)
    coded_names = _present_names(text, known_names)
    projected_text = redact_text(text, known_names)
    residual = sensitive_labels(projected_text)
    if residual:
        raise EgressLeakError(residual)

    reasons: list[str] = []
    if coded_names:
        reasons.append(_PERSON)
    # Every detected credential class that did NOT survive the pass was
    # sanitized away; residual ones already refused above.
    reasons.extend(label for label in dict.fromkeys(present) if label not in residual)
    return SanitizedProjection(
        record_id=record_id,
        source_type=source_type,
        source_ts=source_ts,
        scope=scope,
        policy_version=POLICY_VERSION,
        text=projected_text,
        redactions=tuple(reasons),
    )
