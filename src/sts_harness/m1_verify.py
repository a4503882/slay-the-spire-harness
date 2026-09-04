from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, strict_json_loads
from .guard import sha256_file


class EvidenceFailure(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceFailure(f"expected a JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise EvidenceFailure(f"expected a JSON object at {path}:{index}")
        rows.append(value)
    return rows


def verify_m1_run(run_dir: Path, bridge_jar: Path | None = None) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    report = _json(run_dir / "m1-report.json")
    worker = _json(run_dir / "worker-summary.json")
    guard = _json(run_dir / "normal-guard-result.json")
    states = _jsonl(run_dir / "bridge-states.jsonl")
    commands = _jsonl(run_dir / "bridge-commands.jsonl")

    raw_states = [row.get("raw") for row in states]
    if not all(isinstance(raw, dict) for raw in raw_states):
        raise EvidenceFailure("every raw-state row must contain an object")
    raw_states = [raw for raw in raw_states if isinstance(raw, dict)]
    command_text = [row.get("command") for row in commands]

    checks = {
        "report_passed": report.get("status") == "passed",
        "worker_passed": worker.get("status") == "passed",
        "worker_evidence_complete": bool(worker.get("evidence"))
        and all(value is True for value in worker["evidence"].values()),
        "state_count_matches": worker.get("states_seen") == len(states) and len(states) >= 4,
        "command_count_matches": worker.get("commands_sent") == len(commands) and len(commands) >= 4,
        "guard_unchanged": guard.get("unchanged") is True and not guard.get("changes"),
        "guard_documents_identical": (run_dir / "normal-guard-before.json").read_bytes()
        == (run_dir / "normal-guard-after.json").read_bytes(),
        "bridge_protocol_consistent": all(
            raw.get("bridge_version") == "1.2.1-sts-harness.1"
            and raw.get("protocol_version") == "communicationmod-harness.v1"
            for raw in raw_states
        ),
        "main_menu_observed": raw_states[0].get("in_game") is False,
        "run_observed": any(raw.get("in_game") is True for raw in raw_states[1:]),
        "required_commands_present": any(str(value).startswith("start ironclad 0 ") for value in command_text)
        and "play 1 0" in command_text
        and "end" in command_text
        and "choose 0" in command_text,
        "forbidden_commands_absent": not any(
            str(value).lower().startswith(("key ", "click ", "wait ")) for value in command_text
        ),
        "turn_advanced": any(
            isinstance(raw.get("game_state"), dict)
            and isinstance(raw["game_state"].get("combat_state"), dict)
            and raw["game_state"]["combat_state"].get("turn") == 2
            for raw in raw_states
        ),
        "owned_process_stopped": report.get("owned_process_stopped") is True,
        "not_timed_out": report.get("timed_out") is False,
    }
    if bridge_jar is not None:
        checks["current_bridge_matches"] = (
            bridge_jar.is_file()
            and sha256_file(bridge_jar).upper() == str(report.get("bridge_sha256", "")).upper()
        )

    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "sts-m1-independent-verification.v1",
        "run_id": report.get("run_id"),
        "valid": not failures,
        "checks": checks,
        "failures": failures,
        "state_count": len(states),
        "command_count": len(commands),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify an M-1 evidence directory")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--bridge-jar", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify_m1_run(args.run_dir, args.bridge_jar)
    output = args.output or (args.run_dir / "m1-independent-verification.json")
    atomic_write_json(output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

