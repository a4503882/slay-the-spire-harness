from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .action_verify import verify_action_effect
from .canonical import atomic_write_json, sha256_document, strict_json_loads
from .legal_actions import build_legal_actions, validate_action_submission
from .observation import StateNormalizer
from .replay_verify import verify_offline_replay
from .transition import make_snapshot


class H1EvidenceFailure(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise H1EvidenceFailure(f"expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise H1EvidenceFailure(f"expected JSON object: {path}:{line_number}")
        rows.append(value)
    return rows


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def verify_h1a_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    report = _object(run_dir / "h1-report.json")
    worker = _object(run_dir / "worker-summary.json")
    driver = _object(run_dir / "driver-summary.json")
    guard = _object(run_dir / "normal-guard-result.json")
    replay_file = _object(run_dir / "replay.json")
    transitions = _rows(run_dir / "transitions.jsonl")
    actions = _rows(run_dir / "actions.jsonl")
    raw_states = _rows(run_dir / "raw-states.jsonl")
    replay = verify_offline_replay(run_dir)

    episode_id = worker.get("episode_id")
    native_session_id = worker.get("native_session_id")
    if not isinstance(episode_id, str) or not isinstance(native_session_id, str):
        raise H1EvidenceFailure("worker identities are missing")
    normalizer = StateNormalizer(episode_id, native_session_id)
    snapshots: dict[int, Any] = {}
    legal_snapshots: dict[int, Any] = {}
    for row in raw_states:
        state_seq = row.get("state_seq")
        raw = row.get("raw")
        if not isinstance(state_seq, int) or not isinstance(raw, dict):
            raise H1EvidenceFailure("raw state record is incomplete")
        observation = normalizer.normalize(raw, state_seq)
        legal_snapshot = build_legal_actions(raw, observation)
        snapshots[state_seq] = make_snapshot(
            state_seq=state_seq,
            raw=raw,
            observation=observation,
            legal_actions=legal_snapshot.document,
        )
        legal_snapshots[state_seq] = legal_snapshot

    public_documents: list[Any] = []
    decision_kinds: set[str] = set()
    results: list[dict[str, Any]] = []
    combat_completed = False
    normalized_trace_matches = True
    verified_effects_match = True
    prior_transition_state_seq: int | None = None
    for transition in transitions:
        observation = transition.get("observation")
        legal = transition.get("legal_actions")
        public_documents.extend([observation, legal])
        state_seq = transition.get("state_seq")
        rebuilt = snapshots.get(state_seq) if isinstance(state_seq, int) else None
        if rebuilt is None or rebuilt.observation != observation or rebuilt.legal_actions != legal:
            normalized_trace_matches = False
        if isinstance(observation, dict) and isinstance(observation.get("decision_kind"), str):
            decision_kinds.add(observation["decision_kind"])
        for result in transition.get("action_results", []):
            if isinstance(result, dict):
                results.append(result)
        for event in transition.get("events", []):
            if isinstance(event, dict) and event.get("type") == "combat_completed":
                combat_completed = True
        transition_results = [
            result for result in transition.get("action_results", []) if isinstance(result, dict)
        ]
        batch = transition.get("submitted_batch")
        if transition_results:
            if (
                prior_transition_state_seq is None
                or not isinstance(batch, dict)
                or len(batch.get("actions", [])) != 1
            ):
                verified_effects_match = False
            else:
                try:
                    native = validate_action_submission(
                        batch["actions"][0],
                        legal_snapshots[prior_transition_state_seq],
                    )
                    verified, proof = verify_action_effect(
                        native,
                        snapshots[prior_transition_state_seq],
                        snapshots[state_seq],
                    )
                    result = transition_results[0]
                    command_hash = sha256_document(
                        {
                            "schema_version": "sts-native-command-hash.v1",
                            "command": native.command,
                        }
                    )
                    if (
                        not verified
                        or result.get("proof") != proof
                        or result.get("native_command_hash") != command_hash
                    ):
                        verified_effects_match = False
                except Exception:
                    verified_effects_match = False
        prior_transition_state_seq = state_seq if isinstance(state_seq, int) else None

    native_commands = [row.get("native_command") for row in actions if isinstance(row.get("native_command"), str)]
    forbidden_native = [
        command
        for command in native_commands
        if str(command).lower().startswith(("key ", "click ", "wait "))
    ]
    action_resolution_matches = True
    for row in actions:
        try:
            state_seq = row["state_seq"]
            native = validate_action_submission(row["submission"], legal_snapshots[state_seq])
            command_hash = sha256_document(
                {
                    "schema_version": "sts-native-command-hash.v1",
                    "command": native.command,
                }
            )
            if (
                native.command != row.get("native_command")
                or row.get("result", {}).get("native_command_hash") != command_hash
            ):
                action_resolution_matches = False
        except Exception:
            action_resolution_matches = False
    leaked_keys = {"seed", "uuid", "available_commands", "last_move_id", "second_last_move_id"}
    checks = {
        "report_passed": report.get("status") == "passed",
        "worker_passed": worker.get("status") == "passed",
        "driver_passed": driver.get("status") == "passed",
        "one_combat_completed": driver.get("one_combat_completed") is True and combat_completed,
        "combat_was_observed": "combat" in decision_kinds,
        "map_was_observed": "map" in decision_kinds,
        "event_was_observed": "event" in decision_kinds,
        "post_combat_state_observed": bool(decision_kinds - {"event", "map", "combat"}),
        "all_action_results_verified": bool(results)
        and all(
            result.get("status") == "accepted"
            and result.get("verified") is True
            and result.get("code") == "ACTION_VERIFIED"
            for result in results
        ),
        "action_counts_match": worker.get("actions_attempted") == len(results)
        and worker.get("actions_accepted") == len(results)
        and worker.get("actions_unverified") == 0,
        "no_forbidden_native_control": not forbidden_native,
        "normalized_trace_matches_raw": normalized_trace_matches,
        "native_action_resolution_matches": action_resolution_matches,
        "semantic_action_proofs_recompute": verified_effects_match,
        "no_player_visible_hidden_key": not any(
            _contains_key(document, leaked_keys) for document in public_documents
        ),
        "offline_replay_valid": replay.get("status") == "REPLAY_VALID"
        and replay_file.get("status") == "REPLAY_VALID",
        "chain_hash_agrees": replay.get("final_chain_hash")
        == worker.get("final_chain_hash")
        == driver.get("final_chain_hash"),
        "normal_guard_unchanged": guard.get("unchanged") is True and not guard.get("changes"),
        "normal_guard_documents_identical": (run_dir / "normal-guard-before.json").read_bytes()
        == (run_dir / "normal-guard-after.json").read_bytes(),
        "owned_java_stopped": report.get("owned_java_stopped") is True,
        "owned_driver_stopped": report.get("owned_driver_stopped") is True,
        "sidecar_descriptor_removed": report.get("sidecar_descriptor_removed") is True,
        "not_timed_out": report.get("timed_out") is False,
        "no_launch_error": report.get("launch_error") is None,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "sts-h1a-independent-verification.v1",
        "run_id": report.get("run_id"),
        "episode_id": worker.get("episode_id"),
        "valid": not failures,
        "checks": checks,
        "failures": failures,
        "transition_count": len(transitions),
        "action_count": len(actions),
        "verified_action_count": len(results),
        "decision_kinds": sorted(decision_kinds),
        "final_chain_hash": replay.get("final_chain_hash"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify an H1-A evidence directory")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_h1a_run(args.run_dir)
        exit_code = 0 if result["valid"] else 2
    except Exception as exc:
        result = {
            "schema_version": "sts-h1a-independent-verification.v1",
            "valid": False,
            "failures": [f"{type(exc).__name__}: {exc}"],
        }
        exit_code = 2
    output = args.output or (args.run_dir / "h1-independent-verification.json")
    atomic_write_json(output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
