"""Closed canonical serialization and byte hash tests."""

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import pytest

from mind_runtime.validation.digest import artifact_manifest, canonical_json_bytes, sha256_bytes


class Mode(StrEnum):
    FIXED = "fixed"


def test_canonical_json_is_stable_across_mapping_and_set_order() -> None:
    left = {"b": frozenset({"z", "a"}), "a": (2, 1)}
    right = {"a": (2, 1), "b": frozenset({"a", "z"})}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)


def test_unknown_mutable_or_non_finite_value_fails_closed() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        canonical_json_bytes(bytearray(b"x"))
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes(float("nan"))


def test_artifact_hash_covers_actual_written_bytes() -> None:
    data = '{"line":"值"}\n'.encode()
    manifest = artifact_manifest("report.json", data)
    assert manifest.byte_length == len(data)
    assert manifest.bytes_sha256 == hashlib.sha256(data).hexdigest()


def test_canonical_algebra_represents_closed_leaves_deterministically() -> None:
    value = {
        "bytes": b"\x0f",
        "enum": Mode.FIXED,
        "at": datetime(2026, 8, 23, 12, tzinfo=UTC),
        "elapsed": timedelta(microseconds=3),
    }
    assert canonical_json_bytes(value) == (
        b'{"at":{"$datetime":"2026-08-23T12:00:00+00:00"},"bytes":{"$bytes":"0f"},'
        b'"elapsed":{"$timedelta_us":3},"enum":"fixed"}'
    )


def test_naive_datetime_and_non_string_mapping_key_fail_closed() -> None:
    with pytest.raises(ValueError, match="aware UTC"):
        canonical_json_bytes(datetime(2026, 8, 23))
    with pytest.raises(TypeError, match="string keys"):
        canonical_json_bytes({1: "one"})


def test_sha256_bytes_is_lowercase_hex() -> None:
    assert sha256_bytes(b"d11s") == hashlib.sha256(b"d11s").hexdigest()


@dataclass(frozen=True)
class FrozenValue:
    name: str
    count: int


class DuplicateKeyMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        return 1

    def __iter__(self) -> Iterator[str]:
        return iter(("key",))

    def __len__(self) -> int:
        return 1

    def items(self) -> Any:
        return iter((("key", 1), ("key", 2)))


def test_canonical_algebra_rejects_every_closed_boundary_and_encodes_dataclasses() -> None:
    assert canonical_json_bytes(FrozenValue("frozen", 2)) == b'{"count":2,"name":"frozen"}'
    with pytest.raises(TypeError, match="data"):
        sha256_bytes(bytearray(b"x"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes(float("inf"))
    with pytest.raises(ValueError, match="duplicate"):
        canonical_json_bytes(DuplicateKeyMapping())
    with pytest.raises(TypeError, match="unsupported"):
        canonical_json_bytes(object())
