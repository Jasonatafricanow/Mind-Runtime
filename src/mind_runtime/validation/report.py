"""Canonical D11S certification artifacts and truthful status summaries."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from mind_runtime.validation.contracts import ArtifactManifest, CertificationReport
from mind_runtime.validation.digest import artifact_manifest, canonical_json_bytes, sha256_bytes


def write_certification_report(
    report: CertificationReport,
    path: Path,
    *,
    replace: bool = False,
) -> ArtifactManifest:
    """Validate and atomically publish one canonical UTF-8 report artifact."""
    if not isinstance(report, CertificationReport):
        raise TypeError("report must be a CertificationReport")
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not isinstance(replace, bool):
        raise TypeError("replace must be a bool")
    if _certification_semantic_hash(report) != report.certification_sha256:
        raise ValueError("certification_sha256 does not match report semantics")
    if path.exists() and not replace:
        raise FileExistsError(path)

    data = canonical_json_bytes(report)
    _require_canonical_utf8_json(data)
    temporary = _write_fsynced_sibling(path, data)
    backup: Path | None = None
    try:
        if temporary.read_bytes() != data:
            raise ValueError("temporary report bytes changed before publication")
        published_identity = temporary.stat()
        if replace:
            backup = _backup_existing_target(path)
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        try:
            final_data = path.read_bytes()
            if final_data != data:
                raise ValueError("final report bytes changed during publication")
        except BaseException as publication_error:
            try:
                _rollback_own_publication(path, published_identity, backup)
            except BaseException as rollback_error:
                recovery_path = backup
                backup = None
                if recovery_path is not None:
                    raise RuntimeError(
                        "report publication rollback failed; authoritative backup "
                        f"retained at {recovery_path}"
                    ) from rollback_error
                raise RuntimeError(
                    "report publication rollback failed with no prior authoritative "
                    f"backup; publication error was {publication_error!r}"
                ) from rollback_error
            raise
    finally:
        temporary.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)

    return artifact_manifest(path.name, final_data)


def render_certification_summary(
    report: CertificationReport,
    paired_report: CertificationReport | None = None,
) -> str:
    """Render the exact D11S/D11L boundary without production overclaiming."""
    if not isinstance(report, CertificationReport):
        raise TypeError("report must be a CertificationReport")
    if paired_report is not None and not isinstance(paired_report, CertificationReport):
        raise TypeError("paired_report must be a CertificationReport")
    reports = (report,) if paired_report is None else (report, paired_report)
    passed = (
        len(reports) == 2
        and {item.virtual_horizon_days for item in reports} == {30, 90}
        and len({item.source_head for item in reports}) == 1
        and len({item.runtime_config_manifest_sha256 for item in reports}) == 1
        and all(_report_passes(item) for item in reports)
    )
    return "\n".join(
        (
            f"D11S: {'COMPLETE' if passed else 'FAILED'}",
            f"FIXED-CLOCK 30/90-DAY CERTIFICATION: {'PASS' if passed else 'FAIL'}",
            "LIVE SHADOW VALIDATION: NOT PERFORMED",
            "D11: INCOMPLETE",
            f"READY FOR D11L: {'YES' if passed else 'NO'}",
            "READY FOR D11P: NO",
        )
    )


def _report_passes(report: CertificationReport) -> bool:
    return _certification_semantic_hash(report) == report.certification_sha256 and all(
        item.passed for item in report.invariants
    )


def _certification_semantic_hash(report: CertificationReport) -> str:
    semantic_fields = (
        report.source_head,
        report.input_sha256,
        report.runtime_config_manifest_sha256,
        report.virtual_horizon_days,
        report.first_run_daily_digests,
        report.replay_daily_digests,
        report.invariants,
    )
    return sha256_bytes(canonical_json_bytes(semantic_fields))


def _require_canonical_utf8_json(data: bytes) -> None:
    try:
        decoded_text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("report bytes must be valid UTF-8") from error
    try:
        decoded = json.loads(decoded_text)
    except json.JSONDecodeError as error:
        raise ValueError("report bytes must be canonical JSON") from error
    if canonical_json_bytes(decoded) != data:
        raise ValueError("report bytes must use canonical JSON encoding")


def _write_fsynced_sibling(path: Path, data: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _backup_existing_target(path: Path) -> Path | None:
    if not path.exists():
        return None
    descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".backup",
        dir=path.parent,
    )
    os.close(descriptor)
    backup = Path(backup_name)
    backup.unlink()
    try:
        os.link(path, backup)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _rollback_own_publication(
    path: Path,
    published_identity: os.stat_result,
    backup: Path | None,
) -> None:
    try:
        current_identity = path.stat()
    except FileNotFoundError:
        return
    if not os.path.samestat(current_identity, published_identity):
        return
    if backup is None:
        path.unlink()
    else:
        os.replace(backup, path)
