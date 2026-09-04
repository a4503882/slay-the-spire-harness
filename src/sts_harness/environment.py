from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, sha256_document, strict_json_loads


class EnvironmentFailure(ValueError):
    pass


def seal_environment(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EnvironmentFailure("environment document must be an object")
    if "environment_fingerprint_id" in document:
        raise EnvironmentFailure("environment document is already sealed")
    result = dict(document)
    result["environment_fingerprint_id"] = sha256_document(document)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seal an H1 environment fingerprint document")
    parser.add_argument("--path", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = args.path.resolve()
    document = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise EnvironmentFailure("environment document must be an object")
    sealed = seal_environment(document)
    atomic_write_json(path, sealed)
    print(sealed["environment_fingerprint_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

