from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json
from .episode_launcher import LauncherFailure, launch_episode


LIVE_REQUIRED_DECISIONS = {
    "combat",
    "card_reward",
    "map",
    "event",
    "shop",
    "rest",
    "treasure",
    "boss_reward",
}


def run_h1b(
    *,
    project_root: Path,
    seed: str,
    timeout_seconds: int,
    max_decisions: int,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    corpus_root = project_root / "artifacts" / "h1b-corpus" / f"h1b-{stamp}"
    corpus_root.mkdir(parents=True, exist_ok=False)
    source: dict[str, Any] | None = None
    replay: dict[str, Any] | None = None
    error: str | None = None
    try:
        source = launch_episode(
            project_root=project_root,
            mode="full",
            seed=seed,
            timeout_seconds=timeout_seconds,
            max_decisions=max_decisions,
            build_bridge=True,
        )
        if source.get("status") != "passed":
            raise LauncherFailure("source full episode failed; replay was not started")
        replay = launch_episode(
            project_root=project_root,
            mode="replay",
            seed=seed,
            timeout_seconds=timeout_seconds,
            max_decisions=max_decisions,
            source_run=Path(source["run_root"]),
            build_bridge=False,
        )
        if replay.get("status") != "passed":
            raise LauncherFailure("same-seed live replay failed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    source_metrics = (
        source.get("worker", {}).get("metrics", {}) if isinstance(source, dict) else {}
    )
    live_decisions = set(source_metrics.get("decision_kinds", []))
    missing_live_decisions = sorted(LIVE_REQUIRED_DECISIONS - live_decisions)
    environment_match = (
        isinstance(source, dict)
        and isinstance(replay, dict)
        and source.get("environment_fingerprint_id")
        == replay.get("environment_fingerprint_id")
    )
    live_replay = replay.get("driver") if isinstance(replay, dict) else None
    status = "passed" if all(
        (
            error is None,
            isinstance(source, dict) and source.get("status") == "passed",
            isinstance(replay, dict) and replay.get("status") == "passed",
            isinstance(live_replay, dict) and live_replay.get("status") == "REPLAY_PARITY",
            environment_match,
            not missing_live_decisions,
        )
    ) else "failed"
    result = {
        "schema_version": "sts-h1b-corpus-report.v1",
        "status": status,
        "seed": seed.upper(),
        "source_run": source.get("run_root") if isinstance(source, dict) else None,
        "replay_run": replay.get("run_root") if isinstance(replay, dict) else None,
        "source_status": source.get("status") if isinstance(source, dict) else None,
        "source_outcome": (
            source.get("driver", {}).get("outcome") if isinstance(source, dict) else None
        ),
        "source_terminal_reached": (
            source.get("driver", {}).get("terminal_reached")
            if isinstance(source, dict)
            else None
        ),
        "replay_status": live_replay.get("status") if isinstance(live_replay, dict) else None,
        "environment_fingerprint_match": environment_match,
        "live_decision_kinds": sorted(live_decisions),
        "required_live_decision_kinds": sorted(LIVE_REQUIRED_DECISIONS),
        "missing_live_decision_kinds": missing_live_decisions,
        "source_metrics": source_metrics,
        "source_report": source,
        "replay_report": replay,
        "error": error,
    }
    atomic_write_json(corpus_root / "h1b-report.json", result)
    result["corpus_root"] = str(corpus_root)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the formal H1-B source and live replay corpus")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--seed", default="AMIYA20260904")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-decisions", type=int, default=5000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_h1b(
            project_root=args.project_root,
            seed=args.seed,
            timeout_seconds=args.timeout_seconds,
            max_decisions=args.max_decisions,
        )
    except Exception as exc:
        print(f"H1B_FAILED={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    console_summary = {
        key: result.get(key)
        for key in (
            "schema_version",
            "status",
            "seed",
            "corpus_root",
            "source_run",
            "source_status",
            "source_outcome",
            "source_terminal_reached",
            "replay_run",
            "replay_status",
            "environment_fingerprint_match",
            "missing_live_decision_kinds",
            "error",
        )
    }
    print(json.dumps(console_summary, ensure_ascii=False, sort_keys=True))
    print(f"H1B_STATUS={result['status'].upper()}")
    print(f"CORPUS_ROOT={result['corpus_root']}")
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
