from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, sha256_document, strict_json_loads
from .transition import (
    TRANSITION_SCHEMA_VERSION,
    canonical_raw_export,
    compute_chain_hash,
    compute_transition_hash,
    recompute_document_hash,
)
from .replay_checkpoint import (
    build_replay_checkpoint,
    recompute_replay_checkpoint_hash,
)


class ReplayVerificationFailure(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReplayVerificationFailure(f"expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise ReplayVerificationFailure(f"blank JSONL row: {path}:{line_number}")
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise ReplayVerificationFailure(f"expected JSON object: {path}:{line_number}")
        rows.append(value)
    if not rows:
        raise ReplayVerificationFailure(f"empty JSONL artifact: {path}")
    return rows


def _environment_fingerprint(environment: dict[str, Any]) -> str:
    basis = dict(environment)
    recorded = basis.pop("environment_fingerprint_id", None)
    calculated = sha256_document(basis)
    if recorded != calculated:
        raise ReplayVerificationFailure("environment fingerprint is invalid")
    return calculated


def verify_offline_replay(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    environment = _object(run_dir / "environment.json")
    environment_id = _environment_fingerprint(environment)
    raw_rows = _rows(run_dir / "raw-states.jsonl")
    transitions = _rows(run_dir / "transitions.jsonl")

    raw_by_seq: dict[int, dict[str, Any]] = {}
    for expected_state_seq, row in enumerate(raw_rows, start=1):
        state_seq = row.get("state_seq")
        if not isinstance(state_seq, int) or state_seq < 1:
            raise ReplayVerificationFailure("raw state has an invalid state_seq")
        if state_seq != expected_state_seq:
            raise ReplayVerificationFailure(
                f"raw state sequence mismatch: expected {expected_state_seq}, got {state_seq}"
            )
        if state_seq in raw_by_seq:
            raise ReplayVerificationFailure(f"duplicate raw state_seq: {state_seq}")
        raw = row.get("raw")
        if not isinstance(raw, dict):
            raise ReplayVerificationFailure(f"raw state {state_seq} has no raw object")
        calculated = sha256_document(canonical_raw_export(raw))
        if row.get("raw_export_hash") != calculated:
            raise ReplayVerificationFailure(f"raw export hash mismatch at state {state_seq}")
        raw_by_seq[state_seq] = row

    episode_id: str | None = None
    prior_hashes: dict[str, str] | None = None
    prior_chain: str | None = None
    transition_hashes: set[str] = set()
    prior_state_seq = 0
    for expected_index, transition in enumerate(transitions):
        if transition.get("schema_version") != TRANSITION_SCHEMA_VERSION:
            raise ReplayVerificationFailure(f"transition {expected_index} has wrong schema")
        if transition.get("transition_index") != expected_index:
            raise ReplayVerificationFailure(
                f"transition index mismatch: expected {expected_index}, got {transition.get('transition_index')}"
            )
        current_episode = transition.get("episode_id")
        if not isinstance(current_episode, str) or not current_episode:
            raise ReplayVerificationFailure(f"transition {expected_index} has no episode_id")
        if episode_id is None:
            episode_id = current_episode
        elif current_episode != episode_id:
            raise ReplayVerificationFailure(f"episode changed at transition {expected_index}")
        if transition.get("environment_fingerprint_id") != environment_id:
            raise ReplayVerificationFailure(
                f"environment fingerprint mismatch at transition {expected_index}"
            )
        if transition.get("pre_hashes") != prior_hashes:
            raise ReplayVerificationFailure(f"pre-state continuity mismatch at transition {expected_index}")

        observation = transition.get("observation")
        legal_actions = transition.get("legal_actions")
        replay_checkpoint = transition.get("replay_checkpoint")
        hashes = transition.get("hashes")
        if not isinstance(observation, dict) or not isinstance(legal_actions, dict) or not isinstance(hashes, dict):
            raise ReplayVerificationFailure(f"transition {expected_index} is structurally incomplete")
        observation_hash = recompute_document_hash(observation, "observation_hash")
        legal_hash = recompute_document_hash(legal_actions, "legal_actions_hash")
        if observation.get("observation_hash") != observation_hash:
            raise ReplayVerificationFailure(f"observation hash mismatch at transition {expected_index}")
        if legal_actions.get("legal_actions_hash") != legal_hash:
            raise ReplayVerificationFailure(f"legal-actions hash mismatch at transition {expected_index}")
        if legal_actions.get("observation_hash") != observation_hash:
            raise ReplayVerificationFailure(
                f"legal actions point at another observation at transition {expected_index}"
            )
        if replay_checkpoint is not None:
            if not isinstance(replay_checkpoint, dict):
                raise ReplayVerificationFailure(
                    f"replay checkpoint is invalid at transition {expected_index}"
                )
            rebuilt_checkpoint = build_replay_checkpoint(observation, legal_actions)
            if replay_checkpoint != rebuilt_checkpoint:
                raise ReplayVerificationFailure(
                    f"replay checkpoint mismatch at transition {expected_index}"
                )
            checkpoint_hash = recompute_replay_checkpoint_hash(replay_checkpoint)
            if (
                replay_checkpoint.get("replay_checkpoint_hash") != checkpoint_hash
                or hashes.get("replay_checkpoint_hash") != checkpoint_hash
            ):
                raise ReplayVerificationFailure(
                    f"replay checkpoint hash mismatch at transition {expected_index}"
                )

        state_seq = transition.get("state_seq")
        if not isinstance(state_seq, int) or state_seq <= prior_state_seq:
            raise ReplayVerificationFailure(
                f"transition state sequence is not increasing at transition {expected_index}"
            )
        raw_row = raw_by_seq.get(state_seq) if isinstance(state_seq, int) else None
        if raw_row is None:
            raise ReplayVerificationFailure(f"transition {expected_index} has no matching raw state")
        post_hashes = {
            "raw_export_hash": raw_row["raw_export_hash"],
            "observation_hash": observation_hash,
            "legal_actions_hash": legal_hash,
        }
        for key, value in post_hashes.items():
            if hashes.get(key) != value:
                raise ReplayVerificationFailure(f"{key} mismatch at transition {expected_index}")

        if hashes.get("previous_chain_hash") != prior_chain:
            raise ReplayVerificationFailure(f"chain predecessor mismatch at transition {expected_index}")
        transition_hash = compute_transition_hash(transition)
        if transition_hash in transition_hashes:
            raise ReplayVerificationFailure(f"duplicate transition hash at transition {expected_index}")
        transition_hashes.add(transition_hash)
        if hashes.get("transition_hash") != transition_hash:
            raise ReplayVerificationFailure(f"transition hash mismatch at transition {expected_index}")
        chain_hash = compute_chain_hash(prior_chain, transition_hash)
        if hashes.get("chain_hash") != chain_hash:
            raise ReplayVerificationFailure(f"chain hash mismatch at transition {expected_index}")
        prior_hashes = post_hashes
        prior_chain = chain_hash
        prior_state_seq = state_seq

    return {
        "schema_version": "sts-offline-replay-verification.v1",
        "status": "REPLAY_VALID",
        "valid": True,
        "episode_id": episode_id,
        "environment_fingerprint_id": environment_id,
        "raw_state_count": len(raw_rows),
        "transition_count": len(transitions),
        "final_chain_hash": prior_chain,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify an H1 transition trace")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or (args.run_dir / "replay.json")
    try:
        result = verify_offline_replay(args.run_dir)
        exit_code = 0
    except Exception as exc:
        result = {
            "schema_version": "sts-offline-replay-verification.v1",
            "status": "REPLAY_INVALID",
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        exit_code = 2
    atomic_write_json(output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
