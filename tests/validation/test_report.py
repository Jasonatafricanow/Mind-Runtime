"""D11S.7 canonical certification report and truthful status tests."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

import mind_runtime.validation.report as report_subject
from mind_runtime.validation import CertificationReport, DailyDecisionDigest, InvariantResult
from mind_runtime.validation.digest import canonical_json_bytes as actual_canonical_json_bytes
from mind_runtime.validation.report import render_certification_summary, write_certification_report

SHA_A = "a" * 64
SHA_B = "b" * 64
SOURCE_HEAD = "0ccd5b2a20f7b576166e0231aad217024e0f6bd6"


def _digest(day: int) -> DailyDecisionDigest:
    return DailyDecisionDigest(day, SHA_A, SHA_A, SHA_A, SHA_A, SHA_A)


def _invariant(*, passed: bool = True) -> InvariantResult:
    return InvariantResult(
        code="replay.equal",
        passed=passed,
        observed="byte-identical" if passed else "different",
        expected="byte-identical",
        evidence_refs=("daily-digest-0",),
    )


def _semantic_hash(report: CertificationReport) -> str:
    semantic_fields = (
        report.source_head,
        report.input_sha256,
        report.runtime_config_manifest_sha256,
        report.virtual_horizon_days,
        report.first_run_daily_digests,
        report.replay_daily_digests,
        report.invariants,
    )
    return hashlib.sha256(actual_canonical_json_bytes(semantic_fields)).hexdigest()


def make_report(
    *,
    days: int = 30,
    wall_seconds: float = 1.25,
    passed: bool = True,
    source_head: str = SOURCE_HEAD,
    manifest_sha256: str = SHA_B,
) -> CertificationReport:
    report = CertificationReport(
        certification_id=f"d11s-{days}-day",
        source_head=source_head,
        input_sha256=SHA_A,
        runtime_config_manifest_sha256=manifest_sha256,
        virtual_horizon_days=days,
        wall_clock_execution_seconds=wall_seconds,
        first_run_daily_digests=tuple(_digest(day) for day in range(days)),
        replay_daily_digests=tuple(_digest(day) for day in range(days)),
        invariants=(_invariant(passed=passed),),
        certification_sha256="0" * 64,
    )
    return replace(report, certification_sha256=_semantic_hash(report))


def test_writer_hashes_actual_utf8_bytes_and_is_semantically_replayable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "certification.json"
    report = make_report(wall_seconds=1.25)

    manifest = write_certification_report(report, path)
    data = path.read_bytes()

    assert data == actual_canonical_json_bytes(report)
    assert manifest.logical_path == "certification.json"
    assert manifest.byte_length == len(data)
    assert manifest.bytes_sha256 == hashlib.sha256(data).hexdigest()
    decoded = json.loads(data.decode("utf-8"))
    assert decoded["virtual_horizon_days"] == 30
    assert decoded["certification_sha256"] == report.certification_sha256


def test_wall_clock_changes_artifact_not_certification_hash(tmp_path: Path) -> None:
    left = make_report(wall_seconds=1.0)
    right = replace(left, wall_clock_execution_seconds=2.0)

    left_manifest = write_certification_report(left, tmp_path / "left.json")
    right_manifest = write_certification_report(right, tmp_path / "right.json")

    assert left.certification_sha256 == right.certification_sha256
    assert left_manifest.bytes_sha256 != right_manifest.bytes_sha256


def test_unicode_filename_round_trips_without_changing_report_bytes(tmp_path: Path) -> None:
    report = make_report()
    path = tmp_path / "证据-кайла.json"

    manifest = write_certification_report(report, path)

    assert manifest.logical_path == "证据-кайла.json"
    assert path.read_bytes() == actual_canonical_json_bytes(report)


def test_existing_report_is_not_overwritten_by_default(tmp_path: Path) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"existing-evidence")

    with pytest.raises(FileExistsError):
        write_certification_report(make_report(), path)

    assert path.read_bytes() == b"existing-evidence"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_concurrent_target_creation_is_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    actual_link = os.link

    def create_competing_target_then_link(source: Path, target: Path) -> None:
        Path(target).write_bytes(b"concurrent-authoritative-report")
        actual_link(source, target)

    monkeypatch.setattr(
        "mind_runtime.validation.report.os.link",
        create_competing_target_then_link,
    )

    with pytest.raises(FileExistsError):
        write_certification_report(make_report(), path)

    assert path.read_bytes() == b"concurrent-authoritative-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_explicit_replace_atomically_replaces_existing_report(tmp_path: Path) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"old")
    report = make_report()

    manifest = write_certification_report(report, path, replace=True)

    assert path.read_bytes() == actual_canonical_json_bytes(report)
    assert manifest.bytes_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert tuple(tmp_path.iterdir()) == (path,)


def test_explicit_replace_can_publish_when_target_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "certification.json"
    report = make_report()

    write_certification_report(report, path, replace=True)

    assert path.read_bytes() == actual_canonical_json_bytes(report)
    assert tuple(tmp_path.iterdir()) == (path,)


def test_replace_backup_failure_preserves_existing_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"old-authoritative-report")

    def fail_link(_source: Path, _target: Path) -> None:
        raise OSError("backup link failed")

    monkeypatch.setattr("mind_runtime.validation.report.os.link", fail_link)

    with pytest.raises(OSError, match="backup link failed"):
        write_certification_report(make_report(), path, replace=True)

    assert path.read_bytes() == b"old-authoritative-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_fsync_failure_leaves_no_partial_new_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"

    def fail_fsync(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr("mind_runtime.validation.report.os.fsync", fail_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        write_certification_report(make_report(), path)

    assert not path.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_fsync_failure_preserves_existing_report_during_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"old-authoritative-report")

    def fail_fsync(_fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr("mind_runtime.validation.report.os.fsync", fail_fsync)

    with pytest.raises(OSError, match="fsync failed"):
        write_certification_report(make_report(), path, replace=True)

    assert path.read_bytes() == b"old-authoritative-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_writer_rejects_final_bytes_changed_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    actual_link = os.link

    def link_then_tamper(source: Path, target: Path) -> None:
        actual_link(source, target)
        Path(target).write_bytes(b"tampered-after-publication")

    monkeypatch.setattr("mind_runtime.validation.report.os.link", link_then_tamper)

    with pytest.raises(ValueError, match="final report bytes changed"):
        write_certification_report(make_report(), path)

    assert not path.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_partial_temporary_bytes_are_never_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"

    def partial_sibling(target: Path, data: bytes) -> Path:
        temporary = target.parent / ".partial.tmp"
        temporary.write_bytes(data[:17])
        return temporary

    monkeypatch.setattr(report_subject, "_write_fsynced_sibling", partial_sibling)

    with pytest.raises(ValueError, match="temporary report bytes changed"):
        write_certification_report(make_report(), path)

    assert not path.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_concurrent_replacement_after_publication_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    actual_link = os.link

    def link_then_replace(source: Path, target: Path) -> None:
        actual_link(source, target)
        competing = Path(target).with_suffix(".competing")
        competing.write_bytes(b"concurrent-authoritative-report")
        os.replace(competing, target)

    monkeypatch.setattr("mind_runtime.validation.report.os.link", link_then_replace)

    with pytest.raises(ValueError, match="final report bytes changed"):
        write_certification_report(make_report(), path)

    assert path.read_bytes() == b"concurrent-authoritative-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_target_disappearance_during_verification_leaves_no_partial_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    actual_read_bytes = Path.read_bytes

    def disappear_before_read(candidate: Path) -> bytes:
        if candidate == path:
            candidate.unlink()
            raise FileNotFoundError(candidate)
        return actual_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", disappear_before_read)

    with pytest.raises(FileNotFoundError):
        write_certification_report(make_report(), path)

    assert not path.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_failed_explicit_replace_restores_previous_authoritative_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"previous-authoritative-report")
    actual_replace = os.replace
    calls = 0

    def replace_then_tamper(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        actual_replace(source, target)
        if calls == 1:
            Path(target).write_bytes(b"tampered-new-report")

    monkeypatch.setattr("mind_runtime.validation.report.os.replace", replace_then_tamper)

    with pytest.raises(ValueError, match="final report bytes changed"):
        write_certification_report(make_report(), path, replace=True)

    assert path.read_bytes() == b"previous-authoritative-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_failed_replace_rollback_retains_recoverable_authoritative_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    path.write_bytes(b"previous-authoritative-report")
    actual_replace = os.replace
    calls = 0

    def replace_tamper_then_fail_rollback(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            actual_replace(source, target)
            Path(target).write_bytes(b"tampered-new-report")
            return
        raise OSError("rollback replace failed")

    monkeypatch.setattr(
        "mind_runtime.validation.report.os.replace",
        replace_tamper_then_fail_rollback,
    )

    with pytest.raises(RuntimeError, match="authoritative backup retained at"):
        write_certification_report(make_report(), path, replace=True)

    backups = tuple(tmp_path.glob("*.backup"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"previous-authoritative-report"
    assert path.read_bytes() == b"tampered-new-report"


def test_failed_new_report_rollback_reports_absence_of_prior_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "certification.json"
    actual_link = os.link
    actual_unlink = Path.unlink

    def link_then_tamper(source: Path, target: Path) -> None:
        actual_link(source, target)
        Path(target).write_bytes(b"tampered-new-report")

    def fail_target_unlink(candidate: Path, missing_ok: bool = False) -> None:
        if candidate == path:
            raise OSError("rollback unlink failed")
        actual_unlink(candidate, missing_ok=missing_ok)

    monkeypatch.setattr("mind_runtime.validation.report.os.link", link_then_tamper)
    monkeypatch.setattr(Path, "unlink", fail_target_unlink)

    with pytest.raises(RuntimeError, match="no prior authoritative backup"):
        write_certification_report(make_report(), path)

    assert path.read_bytes() == b"tampered-new-report"
    assert tuple(tmp_path.iterdir()) == (path,)


def test_writer_rejects_valid_utf8_that_is_not_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def non_json_report_bytes(value: object) -> bytes:
        if isinstance(value, CertificationReport):
            return b"not-json"
        return actual_canonical_json_bytes(value)

    monkeypatch.setattr(report_subject, "canonical_json_bytes", non_json_report_bytes)

    with pytest.raises(ValueError, match="canonical JSON"):
        write_certification_report(make_report(), tmp_path / "certification.json")


def _change_manifest_hash(report: CertificationReport) -> CertificationReport:
    return replace(report, runtime_config_manifest_sha256=SHA_A)


def _change_input_hash(report: CertificationReport) -> CertificationReport:
    return replace(report, input_sha256=SHA_B)


def _change_source_head(report: CertificationReport) -> CertificationReport:
    return replace(report, source_head="1" * 40)


def _change_daily_digest(report: CertificationReport) -> CertificationReport:
    changed = replace(report.first_run_daily_digests[0], canonical_state_hash=SHA_B)
    return replace(
        report,
        first_run_daily_digests=(changed, *report.first_run_daily_digests[1:]),
    )


def _change_invariant(report: CertificationReport) -> CertificationReport:
    return replace(report, invariants=(replace(report.invariants[0], observed="changed"),))


@pytest.mark.parametrize(
    "change",
    [
        _change_manifest_hash,
        _change_input_hash,
        _change_source_head,
        _change_daily_digest,
        _change_invariant,
    ],
)
def test_writer_rejects_semantic_or_manifest_hash_mismatch(
    change: Callable[[CertificationReport], CertificationReport],
    tmp_path: Path,
) -> None:
    report = change(make_report())
    path = tmp_path / "certification.json"

    with pytest.raises(ValueError, match="certification_sha256"):
        write_certification_report(report, path)

    assert not path.exists()


def test_writer_rejects_invalid_utf8_encoder_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_report_bytes(value: object) -> bytes:
        if isinstance(value, CertificationReport):
            return b"\xff"
        return actual_canonical_json_bytes(value)

    monkeypatch.setattr(report_subject, "canonical_json_bytes", invalid_report_bytes)

    with pytest.raises(ValueError, match="UTF-8"):
        write_certification_report(make_report(), tmp_path / "certification.json")


def test_writer_rejects_noncanonical_json_encoder_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def noncanonical_report_bytes(value: object) -> bytes:
        encoded = actual_canonical_json_bytes(value)
        if isinstance(value, CertificationReport):
            return json.dumps(json.loads(encoded), ensure_ascii=False, indent=2).encode("utf-8")
        return encoded

    monkeypatch.setattr(report_subject, "canonical_json_bytes", noncanonical_report_bytes)

    with pytest.raises(ValueError, match="canonical JSON"):
        write_certification_report(make_report(), tmp_path / "certification.json")


@pytest.mark.parametrize(
    ("report", "path", "replace_value", "message"),
    [
        (object(), Path("report.json"), False, "CertificationReport"),
        (make_report(), "report.json", False, "Path"),
        (make_report(), Path("report.json"), 1, "replace"),
    ],
)
def test_writer_rejects_invalid_argument_types(
    report: object,
    path: object,
    replace_value: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        write_certification_report(report, path, replace=replace_value)  # type: ignore[arg-type]


@pytest.mark.parametrize("days", [30, 90])
def test_single_horizon_cannot_close_combined_certification(days: int) -> None:
    summary = render_certification_summary(make_report(days=days))

    assert summary == "\n".join(
        (
            "D11S: FAILED",
            "FIXED-CLOCK 30/90-DAY CERTIFICATION: FAIL",
            "LIVE SHADOW VALIDATION: NOT PERFORMED",
            "D11: INCOMPLETE",
            "READY FOR D11L: NO",
            "READY FOR D11P: NO",
        )
    )


def test_paired_30_and_90_day_reports_render_exact_completion_vocabulary() -> None:
    summary = render_certification_summary(make_report(days=30), make_report(days=90))

    assert summary == "\n".join(
        (
            "D11S: COMPLETE",
            "FIXED-CLOCK 30/90-DAY CERTIFICATION: PASS",
            "LIVE SHADOW VALIDATION: NOT PERFORMED",
            "D11: INCOMPLETE",
            "READY FOR D11L: YES",
            "READY FOR D11P: NO",
        )
    )
    assert "D11 COMPLETE" not in summary
    assert "production proven" not in summary.lower()
    assert "shadow validated" not in summary.lower()


@pytest.mark.parametrize(
    "paired",
    [
        make_report(days=30),
        make_report(days=90, source_head="1" * 40),
        make_report(days=90, manifest_sha256=SHA_A),
    ],
)
def test_paired_summary_requires_distinct_horizons_and_shared_runtime_identity(
    paired: CertificationReport,
) -> None:
    summary = render_certification_summary(make_report(days=30), paired)

    assert "D11S: FAILED" in summary
    assert "READY FOR D11L: NO" in summary


def test_summary_fails_closed_for_semantic_hash_mismatch() -> None:
    report = replace(make_report(), runtime_config_manifest_sha256=SHA_A)

    summary = render_certification_summary(report)

    assert summary == "\n".join(
        (
            "D11S: FAILED",
            "FIXED-CLOCK 30/90-DAY CERTIFICATION: FAIL",
            "LIVE SHADOW VALIDATION: NOT PERFORMED",
            "D11: INCOMPLETE",
            "READY FOR D11L: NO",
            "READY FOR D11P: NO",
        )
    )


def test_failed_invariant_report_is_writable_and_keeps_failure_evidence(tmp_path: Path) -> None:
    report = make_report(passed=False)
    path = tmp_path / "failed-certification.json"

    write_certification_report(report, path)

    decoded = json.loads(path.read_bytes())
    assert decoded["invariants"][0]["passed"] is False
    assert render_certification_summary(report, make_report(days=90)) == "\n".join(
        (
            "D11S: FAILED",
            "FIXED-CLOCK 30/90-DAY CERTIFICATION: FAIL",
            "LIVE SHADOW VALIDATION: NOT PERFORMED",
            "D11: INCOMPLETE",
            "READY FOR D11L: NO",
            "READY FOR D11P: NO",
        )
    )


def test_summary_rejects_wrong_type() -> None:
    with pytest.raises(TypeError, match="CertificationReport"):
        render_certification_summary(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="CertificationReport"):
        render_certification_summary(make_report(), object())  # type: ignore[arg-type]
