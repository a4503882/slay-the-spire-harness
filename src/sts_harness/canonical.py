from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


class DuplicateJsonKey(ValueError):
    """Raised when a JSON object contains the same key more than once."""


def _object_without_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(value: str) -> Any:
    """Parse strict JSON while rejecting duplicate keys and non-finite numbers."""

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON number is not allowed: {token}")

    return json.loads(
        value,
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=reject_constant,
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode the v1 canonical JSON representation used by M-1 evidence."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_document(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8") + b"\n"
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)

