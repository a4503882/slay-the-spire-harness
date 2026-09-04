from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

from .canonical import sha256_document


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix() if path != root else "."
    if path.is_symlink():
        return {
            "path": relative,
            "kind": "symlink",
            "target": os.readlink(path),
        }
    if path.is_dir():
        return {"path": relative, "kind": "directory"}
    if path.is_file():
        stat = path.stat()
        return {
            "path": relative,
            "kind": "file",
            "bytes": stat.st_size,
            "sha256": sha256_file(path),
        }
    return {"path": relative, "kind": "other"}


def snapshot_path(name: str, raw_path: str | Path) -> dict[str, Any]:
    path = Path(raw_path).resolve()
    if not path.exists() and not path.is_symlink():
        document: dict[str, Any] = {
            "name": name,
            "root": str(path),
            "exists": False,
            "entries": [],
        }
    elif path.is_dir() and not path.is_symlink():
        children = sorted(path.rglob("*"), key=lambda child: child.relative_to(path).as_posix())
        document = {
            "name": name,
            "root": str(path),
            "exists": True,
            "entries": [_entry(path, path), *(_entry(path, child) for child in children)],
        }
    else:
        document = {
            "name": name,
            "root": str(path),
            "exists": True,
            "entries": [_entry(path.parent, path)],
        }
    document["digest"] = sha256_document(
        {
            "name": document["name"],
            "exists": document["exists"],
            "entries": document["entries"],
        }
    )
    return document


def snapshot_roots(roots: Iterable[tuple[str, str | Path]]) -> dict[str, Any]:
    rows = [snapshot_path(name, path) for name, path in roots]
    result = {
        "schema_version": "sts-path-fingerprint.v1",
        "roots": rows,
    }
    result["digest"] = sha256_document(
        {
            "schema_version": result["schema_version"],
            "roots": [{"name": row["name"], "digest": row["digest"]} for row in rows],
        }
    )
    return result


def compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_rows = {row["name"]: row for row in before.get("roots", [])}
    after_rows = {row["name"]: row for row in after.get("roots", [])}
    names = sorted(set(before_rows) | set(after_rows))
    changes = []
    for name in names:
        left = before_rows.get(name)
        right = after_rows.get(name)
        left_digest = left.get("digest") if left else None
        right_digest = right.get("digest") if right else None
        if left_digest != right_digest:
            changes.append(
                {
                    "name": name,
                    "before_digest": left_digest,
                    "after_digest": right_digest,
                }
            )
    return {
        "schema_version": "sts-path-guard-result.v1",
        "unchanged": not changes,
        "before_digest": before.get("digest"),
        "after_digest": after.get("digest"),
        "changes": changes,
    }

