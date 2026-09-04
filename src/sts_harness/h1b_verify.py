from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .action_verify import verify_action_effect
from .canonical import atomic_write_json, sha256_document, strict_json_loads
from .h1b_run import LIVE_REQUIRED_DECISIONS
from .legal_actions import (
    ActionValidationFailure,
    LegalActionSnapshot,
    build_legal_actions,
    resolve_planned_action,
    validate_action_submission,
)
from .observation import StateNormalizer
from .replay_checkpoint import build_replay_checkpoint
from .replay_verify import verify_offline_replay
from .transition import StateSnapshot, make_snapshot


class H1BVerificationFailure(RuntimeError):
    pass


SETTLE_PROOF_FIELDS = {
    "verification_attempts",
    "initial_post_state_seq",
    "settled_post_state_seq",
}
FORBIDDEN_PUBLIC_KEYS = {
    "seed",
    "uuid",
    "available_commands",
    "last_move_id",
    "second_last_move_id",
    "native_command",
    "controller_nonce",
}


def _object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise H1BVerificationFailure(f"missing JSON artifact: {path}")
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise H1BVerificationFailure(f"expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise H1BVerificationFailure(f"missing JSONL artifact: {path}")
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise H1BVerificationFailure(f"blank JSONL row: {path}:{line_number}")
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise H1BVerificationFailure(f"expected JSON object: {path}:{line_number}")
        result.append(value)
    if not result:
        raise H1BVerificationFailure(f"empty JSONL artifact: {path}")
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in forbidden or _contains_key(item, forbidden) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _rebuild_snapshots(
    raw_rows: list[dict[str, Any]],
    episode_id: str,
    native_session_id: str,
) -> tuple[dict[int, StateSnapshot], dict[int, LegalActionSnapshot]]:
    normalizer = StateNormalizer(episode_id, native_session_id)
    snapshots: dict[int, StateSnapshot] = {}
    legal_snapshots: dict[int, LegalActionSnapshot] = {}
    for row in raw_rows:
        state_seq = row.get("state_seq")
        raw = row.get("raw")
        if not isinstance(state_seq, int) or isinstance(state_seq, bool) or not isinstance(raw, dict):
            raise H1BVerificationFailure("raw state record is incomplete")
        if state_seq in snapshots:
            raise H1BVerificationFailure(f"duplicate raw state sequence: {state_seq}")
        observation = normalizer.normalize(raw, state_seq)
        legal = build_legal_actions(raw, observation)
        snapshots[state_seq] = make_snapshot(
            state_seq=state_seq,
            raw=raw,
            observation=observation,
            legal_actions=legal.document,
        )
        legal_snapshots[state_seq] = legal
    return snapshots, legal_snapshots


def _proof_matches(
    *,
    native: Any,
    before: StateSnapshot,
    after: StateSnapshot,
    recorded_proof: Any,
    snapshots: dict[int, StateSnapshot],
) -> bool:
    if not isinstance(recorded_proof, dict):
        return False
    recorded = deepcopy(recorded_proof)
    settle = {key: recorded.pop(key) for key in list(recorded) if key in SETTLE_PROOF_FIELDS}
    verified, rebuilt = verify_action_effect(native, before, after)
    if not verified or recorded != rebuilt:
        return False
    if not settle:
        return True
    if set(settle) != SETTLE_PROOF_FIELDS:
        return False
    attempts = settle["verification_attempts"]
    initial_seq = settle["initial_post_state_seq"]
    settled_seq = settle["settled_post_state_seq"]
    if (
        not isinstance(attempts, int)
        or isinstance(attempts, bool)
        or attempts < 2
        or not isinstance(initial_seq, int)
        or isinstance(initial_seq, bool)
        or not isinstance(settled_seq, int)
        or isinstance(settled_seq, bool)
        or not before.state_seq < initial_seq <= settled_seq
        or settled_seq != after.state_seq
    ):
        return False
    initial = snapshots.get(initial_seq)
    if initial is None:
        return False
    initially_verified, _ = verify_action_effect(native, before, initial)
    return not initially_verified


def _verify_episode(run_dir: Path, expected_mode: str) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    report = _object(run_dir / "episode-report.json")
    worker = _object(run_dir / "worker-summary.json")
    driver_name = "driver-summary.json" if expected_mode == "full" else "live-replay.json"
    driver = _object(run_dir / driver_name)
    guard = _object(run_dir / "normal-guard-result.json")
    stored_replay = _object(run_dir / "replay.json")
    metrics = _object(run_dir / "metrics.json")
    environment = _object(run_dir / "environment.json")
    raw_rows = _rows(run_dir / "raw-states.jsonl")
    transitions = _rows(run_dir / "transitions.jsonl")
    audits = _rows(run_dir / "actions.jsonl")
    replay = verify_offline_replay(run_dir)

    episode_id = worker.get("episode_id")
    native_session_id = worker.get("native_session_id")
    if not isinstance(episode_id, str) or not isinstance(native_session_id, str):
        raise H1BVerificationFailure("worker identities are missing")
    snapshots, legal_snapshots = _rebuild_snapshots(raw_rows, episode_id, native_session_id)

    normalized_trace_matches = True
    public_documents: list[Any] = []
    transition_results: list[dict[str, Any]] = []
    decision_kinds: set[str] = set()
    for transition in transitions:
        state_seq = transition.get("state_seq")
        rebuilt = snapshots.get(state_seq) if isinstance(state_seq, int) else None
        observation = transition.get("observation")
        legal_actions = transition.get("legal_actions")
        public_documents.extend((observation, legal_actions))
        if (
            rebuilt is None
            or rebuilt.observation != observation
            or rebuilt.legal_actions != legal_actions
            or build_replay_checkpoint(rebuilt.observation, rebuilt.legal_actions)
            != transition.get("replay_checkpoint")
        ):
            normalized_trace_matches = False
        kind = _dict(observation).get("decision_kind")
        if isinstance(kind, str):
            decision_kinds.add(kind)
        for result in transition.get("action_results", []):
            if isinstance(result, dict):
                transition_results.append(result)
            else:
                normalized_trace_matches = False

    action_resolution_matches = True
    action_proofs_recompute = True
    audit_results_match_transitions = len(audits) == len(transition_results)
    forbidden_native_commands: list[str] = []
    for index, audit in enumerate(audits):
        try:
            pre_seq = audit.get("state_seq")
            post_seq = audit.get("post_state_seq")
            if not isinstance(pre_seq, int) or not isinstance(post_seq, int):
                raise H1BVerificationFailure("action audit is missing state sequence")
            legal = legal_snapshots[pre_seq]
            submission = audit.get("submission")
            try:
                native = validate_action_submission(submission, legal)
            except ActionValidationFailure:
                native = resolve_planned_action(submission, legal)
            command = audit.get("native_command")
            if not isinstance(command, str):
                raise H1BVerificationFailure("action audit has no native command")
            if command.lower().startswith(("key ", "click ", "wait ")):
                forbidden_native_commands.append(command)
            result = audit.get("result")
            expected_command_hash = sha256_document(
                {"schema_version": "sts-native-command-hash.v1", "command": native.command}
            )
            if (
                native.command != command
                or native.action_id != audit.get("resolved_action_id")
                or not isinstance(result, dict)
                or result.get("resolved_action_id") != native.action_id
                or result.get("selector") != native.selector
                or result.get("native_command_hash") != expected_command_hash
            ):
                action_resolution_matches = False
            if not _proof_matches(
                native=native,
                before=snapshots[pre_seq],
                after=snapshots[post_seq],
                recorded_proof=_dict(result).get("proof"),
                snapshots=snapshots,
            ):
                action_proofs_recompute = False
            if index >= len(transition_results) or result != transition_results[index]:
                audit_results_match_transitions = False
        except Exception:
            action_resolution_matches = False
            action_proofs_recompute = False
            audit_results_match_transitions = False

    bridge = _dict(environment.get("bridge"))
    model_metrics_unavailable = all(
        value is None for key, value in metrics.items() if key.startswith("model_")
    )
    common_checks = {
        "report_passed": report.get("status") == "passed",
        "mode_matches": report.get("mode") == expected_mode,
        "worker_passed": worker.get("status") == "passed",
        "worker_not_aborted": worker.get("abort_requested") is False,
        "driver_passed": (
            driver.get("status") == "passed"
            if expected_mode == "full"
            else driver.get("status") == "REPLAY_PARITY" and driver.get("valid") is True
        ),
        "offline_replay_valid": replay.get("status") == "REPLAY_VALID"
        and stored_replay == replay,
        "normalized_trace_matches_raw": normalized_trace_matches,
        "all_action_results_verified": bool(transition_results)
        and all(
            result.get("status") == "accepted"
            and result.get("verified") is True
            and result.get("code") == "ACTION_VERIFIED"
            for result in transition_results
        ),
        "native_action_resolution_matches": action_resolution_matches,
        "semantic_action_proofs_recompute": action_proofs_recompute,
        "audit_results_match_transitions": audit_results_match_transitions,
        "action_counts_match": worker.get("actions_attempted") == len(transition_results)
        and worker.get("actions_accepted") == len(transition_results)
        and worker.get("actions_rejected") == 0
        and worker.get("actions_skipped") == 0
        and worker.get("actions_unverified") == 0,
        "no_forbidden_native_control": not forbidden_native_commands,
        "no_player_visible_hidden_key": not any(
            _contains_key(document, FORBIDDEN_PUBLIC_KEYS) for document in public_documents
        ),
        "normal_guard_unchanged": guard.get("unchanged") is True and not guard.get("changes"),
        "normal_guard_documents_identical": (run_dir / "normal-guard-before.json").read_bytes()
        == (run_dir / "normal-guard-after.json").read_bytes(),
        "owned_java_stopped": report.get("owned_java_stopped") is True,
        "owned_worker_stopped": report.get("owned_worker_stopped") is True,
        "sidecar_descriptor_removed": report.get("sidecar_descriptor_removed") is True,
        "no_residual_related_process": report.get("residual_related_processes") == [],
        "descriptor_acl_restricted": report.get("descriptor_acl_restricted") is True,
        "not_timed_out": report.get("timed_out") is False,
        "no_launch_error": report.get("launch_error") is None,
        "bridge_artifact_matches_environment": report.get("bridge_sha256") == bridge.get("sha256"),
        "environment_matches_trace": report.get("environment_fingerprint_id")
        == replay.get("environment_fingerprint_id"),
        "metrics_match_worker": worker.get("metrics") == metrics,
        "combat_metrics_coherent": isinstance(metrics.get("combats_entered"), int)
        and isinstance(metrics.get("combats_completed"), int)
        and 0 <= metrics["combats_completed"] <= metrics["combats_entered"],
        "model_metrics_explicitly_unavailable": model_metrics_unavailable,
        "terminal_native_state": transitions[-1].get("terminal") is True
        and _dict(transitions[-1].get("observation")).get("decision_kind")
        in {"game_over", "victory"},
    }
    if expected_mode == "full":
        common_checks.update(
            {
                "full_driver_terminal": driver.get("terminal_reached") is True
                and driver.get("outcome") in {"DEFEAT_COMBAT", "VICTORY"},
                "post_coverage_strategy_audited": driver.get(
                    "post_coverage_terminal_strategy"
                )
                == "act2_end_turn_until_native_defeat"
                and driver.get("post_coverage_terminal_strategy_activated") is True,
                "required_live_decisions": not (LIVE_REQUIRED_DECISIONS - decision_kinds),
            }
        )
    else:
        common_checks.update(
            {
                "live_replay_compared_every_checkpoint": driver.get(
                    "compared_checkpoint_count"
                )
                == len(transitions),
                "live_replay_replayed_every_action": driver.get("replayed_action_count")
                == len(transition_results),
                "live_replay_no_divergence": driver.get("first_divergence") is None,
            }
        )
    failures = [name for name, passed in common_checks.items() if not passed]
    return {
        "valid": not failures,
        "checks": common_checks,
        "failures": failures,
        "report": report,
        "driver": driver,
        "metrics": metrics,
        "environment": environment,
        "transitions": transitions,
        "decision_kinds": sorted(decision_kinds),
        "action_count": len(transition_results),
        "forbidden_native_commands": forbidden_native_commands,
        "final_chain_hash": replay.get("final_chain_hash"),
    }


def _selectors(transitions: list[dict[str, Any]]) -> list[Any]:
    return [
        result.get("selector")
        for transition in transitions
        for result in transition.get("action_results", [])
        if isinstance(result, dict)
    ]


def verify_h1b_corpus(corpus_dir: Path) -> dict[str, Any]:
    corpus_dir = corpus_dir.resolve()
    report = _object(corpus_dir / "h1b-report.json")
    source_path = report.get("source_run")
    replay_path = report.get("replay_run")
    if not isinstance(source_path, str) or not isinstance(replay_path, str):
        raise H1BVerificationFailure("corpus report has no source/replay run paths")
    source = _verify_episode(Path(source_path), "full")
    replay = _verify_episode(Path(replay_path), "replay")
    source_transitions = source["transitions"]
    replay_transitions = replay["transitions"]
    same_length = len(source_transitions) == len(replay_transitions)
    checkpoints_match = same_length and all(
        left.get("replay_checkpoint") == right.get("replay_checkpoint")
        for left, right in zip(source_transitions, replay_transitions)
    )
    selectors_match = _selectors(source_transitions) == _selectors(replay_transitions)
    differing_observation_hashes = sum(
        _dict(left.get("observation")).get("observation_hash")
        != _dict(right.get("observation")).get("observation_hash")
        for left, right in zip(source_transitions, replay_transitions)
    )
    source_report = source["report"]
    replay_report = replay["report"]
    live = replay["driver"]
    source_kinds = set(source["decision_kinds"])
    checks = {
        "corpus_report_passed": report.get("status") == "passed",
        "source_independently_valid": source["valid"] is True,
        "replay_independently_valid": replay["valid"] is True,
        "source_report_embedded_exactly": report.get("source_report") == source_report,
        "replay_report_embedded_exactly": report.get("replay_report") == replay_report,
        "source_metrics_embedded_exactly": report.get("source_metrics") == source.get("metrics"),
        "environment_fingerprint_match": report.get("environment_fingerprint_match") is True
        and source_report.get("environment_fingerprint_id")
        == replay_report.get("environment_fingerprint_id"),
        "required_live_decisions_complete": not (LIVE_REQUIRED_DECISIONS - source_kinds)
        and report.get("missing_live_decision_kinds") == [],
        "live_replay_status_parity": report.get("replay_status") == "REPLAY_PARITY"
        and live.get("status") == "REPLAY_PARITY"
        and live.get("valid") is True,
        "checkpoint_count_matches": live.get("compared_checkpoint_count")
        == len(source_transitions)
        == len(replay_transitions),
        "every_checkpoint_matches": checkpoints_match,
        "every_action_selector_matches": selectors_match,
        "final_checkpoint_hash_matches": live.get("final_recorded_checkpoint_hash")
        == live.get("final_replayed_checkpoint_hash")
        == _dict(source_transitions[-1].get("replay_checkpoint")).get(
            "replay_checkpoint_hash"
        ),
        "run_local_observation_hashes_not_used_for_parity": differing_observation_hashes > 0,
        "no_corpus_error": report.get("error") is None,
    }
    failures = [name for name, passed in checks.items() if not passed]
    failures.extend(f"source:{name}" for name in source["failures"])
    failures.extend(f"replay:{name}" for name in replay["failures"])
    return {
        "schema_version": "sts-h1b-independent-verification.v1",
        "valid": not failures,
        "corpus_root": str(corpus_dir),
        "source_run": source_path,
        "replay_run": replay_path,
        "checks": checks,
        "source_checks": source["checks"],
        "replay_checks": replay["checks"],
        "failures": failures,
        "source_transition_count": len(source_transitions),
        "replay_transition_count": len(replay_transitions),
        "source_action_count": source["action_count"],
        "replay_action_count": replay["action_count"],
        "differing_run_local_observation_hash_count": differing_observation_hashes,
        "decision_kinds": source["decision_kinds"],
        "final_replay_checkpoint_hash": live.get("final_replayed_checkpoint_hash"),
        "source_final_chain_hash": source["final_chain_hash"],
        "replay_final_chain_hash": replay["final_chain_hash"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify an H1-B source/replay corpus")
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_h1b_corpus(args.corpus_dir)
        exit_code = 0 if result["valid"] else 2
    except Exception as exc:
        result = {
            "schema_version": "sts-h1b-independent-verification.v1",
            "valid": False,
            "failures": [f"{type(exc).__name__}: {exc}"],
        }
        exit_code = 2
    output = args.output or (args.corpus_dir / "h1b-independent-verification.json")
    atomic_write_json(output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
