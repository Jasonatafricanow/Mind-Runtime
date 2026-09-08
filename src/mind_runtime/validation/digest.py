"""Closed canonical value algebra for D11S evidence hashes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite

from mind_runtime.validation.contracts import ArtifactManifest


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 identity of the exact supplied bytes."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """Encode only the frozen D11S value algebra as canonical UTF-8 JSON."""
    normalized = _normalize(value)
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def artifact_manifest(logical_path: str, data: bytes) -> ArtifactManifest:
    """Bind an artifact to its actual bytes, rather than an in-memory value."""
    return ArtifactManifest(logical_path, len(data), sha256_bytes(data))


def _normalize(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("float values must be finite")
        return value
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
            raise ValueError("datetime values must be aware UTC")
        return {"$datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, timedelta):
        return {"$timedelta_us": _timedelta_microseconds(value)}
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("mappings require string keys")
            if key in normalized:
                raise ValueError("duplicate normalized mapping key")
            normalized[key] = _normalize(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize({field.name: getattr(value, field.name) for field in fields(value)})
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized_items = [_normalize(item) for item in value]
        return sorted(normalized_items, key=canonical_json_bytes)
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _timedelta_microseconds(value: timedelta) -> int:
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds
