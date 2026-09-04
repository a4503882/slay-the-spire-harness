from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonical import atomic_write_json
from .guard import compare_snapshots, snapshot_roots


def _named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("root must use NAME=PATH")
    return name.strip(), Path(raw_path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Snapshot and compare guarded paths")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--root", action="append", required=True, type=_named_path)
    snapshot.add_argument("--output", required=True, type=Path)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--before", required=True, type=Path)
    compare.add_argument("--after", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "snapshot":
        document = snapshot_roots(args.root)
    else:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        document = compare_snapshots(before, after)
    atomic_write_json(args.output.resolve(), document)
    print(document["digest"] if "digest" in document else document["unchanged"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

