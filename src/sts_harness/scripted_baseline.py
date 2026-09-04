from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import append_jsonl, atomic_write_json, sha256_document
from .client import H1Client
from .legal_actions import submission_from_public_action
from .scripted_policy import (
    POLICY_DECISION_SCHEMA_VERSION,
    PolicyChoice,
    ScriptedPolicyFailure,
    create_policy,
)


POLICY_DECISION_HASH_SCHEMA_VERSION = "sts-scripted-policy-decision-hash.v1"
POLICY_DECISION_CHAIN_SCHEMA_VERSION = "sts-scripted-policy-decision-chain.v1"


class ScriptedBaselineFailure(RuntimeError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def policy_decision_hash_basis(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("schema_version") != POLICY_DECISION_SCHEMA_VERSION:
        raise ScriptedBaselineFailure("unexpected policy-decision schema")
    content = deepcopy(record)
    hashes = content.pop("hashes", None)
    if not isinstance(hashes, dict):
        raise ScriptedBaselineFailure("policy-decision hashes are missing")
    content["hash_schema_version"] = POLICY_DECISION_HASH_SCHEMA_VERSION
    return content


def compute_policy_decision_hash(record: dict[str, Any]) -> str:
    return sha256_document(policy_decision_hash_basis(record))


def compute_policy_decision_chain_hash(
    previous_chain_hash: str | None,
    decision_hash: str,
) -> str:
    return sha256_document(
        {
            "schema_version": POLICY_DECISION_CHAIN_SCHEMA_VERSION,
            "previous_chain_hash": previous_chain_hash,
            "decision_hash": decision_hash,
        }
    )


def build_policy_decision_record(
    *,
    policy_id: str,
    policy_version: str,
    policy_decision_index: int,
    transition: dict[str, Any],
    choice: PolicyChoice,
    previous_chain_hash: str | None,
) -> dict[str, Any]:
    observation = _dict(transition.get("observation"))
    legal_actions = _dict(transition.get("legal_actions"))
    replay_checkpoint = _dict(transition.get("replay_checkpoint"))
    record = {
        "schema_version": POLICY_DECISION_SCHEMA_VERSION,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "policy_decision_index": policy_decision_index,
        "pre_transition_index": transition.get("transition_index"),
        "decision_kind": observation.get("decision_kind"),
        "observation_hash": observation.get("observation_hash"),
        "legal_actions_hash": legal_actions.get("legal_actions_hash"),
        "replay_checkpoint_hash": replay_checkpoint.get("replay_checkpoint_hash"),
        "candidate_count": choice.candidate_count,
        "candidate_set_hash": choice.candidate_set_hash,
        "selected_action": deepcopy(choice.semantic_action),
        "selection_evidence": deepcopy(choice.selection_evidence),
        "policy_state_before": deepcopy(choice.state_before),
        "policy_state_after": deepcopy(choice.state_after),
        "policy_state_before_hash": sha256_document(choice.state_before),
        "policy_state_after_hash": sha256_document(choice.state_after),
        "hashes": {
            "previous_chain_hash": previous_chain_hash,
            "decision_hash": None,
            "chain_hash": None,
        },
    }
    decision_hash = compute_policy_decision_hash(record)
    record["hashes"]["decision_hash"] = decision_hash
    record["hashes"]["chain_hash"] = compute_policy_decision_chain_hash(
        previous_chain_hash,
        decision_hash,
    )
    return record


def _step_params(
    transition: dict[str, Any],
    action: dict[str, Any],
    request_index: int,
) -> dict[str, Any]:
    observation = transition["observation"]
    legal_actions = transition["legal_actions"]
    return {
        "request_id": f"baseline_req_{request_index:06d}",
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation["run_id"],
        "expected_decision_id": observation["decision_id"],
        "expected_observation_hash": observation["observation_hash"],
        "expected_legal_actions_hash": legal_actions["legal_actions_hash"],
        "stop_on_failure": True,
        "actions": [submission_from_public_action(action)],
    }


def run_scripted_baseline_episode(
    *,
    descriptor: Path,
    output: Path,
    seed: str,
    policy_id: str,
    policy_seed: str | None,
    max_decisions: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while not descriptor.is_file():
        if time.monotonic() >= deadline:
            raise ScriptedBaselineFailure("timed out waiting for sidecar descriptor")
        time.sleep(0.05)

    policy = create_policy(policy_id, policy_seed)
    policy_descriptor = policy.descriptor()
    decisions_path = output.parent / "policy-decisions.jsonl"
    client = H1Client.from_descriptor(
        descriptor,
        timeout_seconds=min(60.0, timeout_seconds),
    )
    transition: dict[str, Any] | None = None
    policy_decision_count = 0
    terminal_reached = False
    truncated = False
    outcome: str | None = None
    error: str | None = None
    close_result: dict[str, Any] | None = None
    final_policy_chain_hash: str | None = None
    decision_kinds: set[str] = set()
    action_types: set[str] = set()

    try:
        capabilities = client.invoke("capabilities")
        if capabilities.get("raw_command_submission") is not False:
            raise ScriptedBaselineFailure("sidecar unexpectedly exposes raw command submission")
        if capabilities.get("fairness_profiles") != ["player_visible.v1"]:
            raise ScriptedBaselineFailure("sidecar fairness profile is not the accepted baseline profile")
        transition = client.invoke(
            "env.reset",
            {
                "character_id": "IRONCLAD",
                "ascension": 0,
                "seed": seed,
                "fairness_profile": "player_visible.v1",
                "policy_mode": policy_id,
                "max_episode_decisions": max_decisions,
                "max_episode_seconds": int(timeout_seconds),
            },
            mutating=True,
        )
        while True:
            observation = _dict(transition.get("observation"))
            kind = str(observation.get("decision_kind"))
            decision_kinds.add(kind)
            if transition.get("terminal") is True or kind in {"game_over", "victory"}:
                terminal_reached = True
                outcome = transition.get("outcome")
                break
            if transition.get("truncated") is True:
                truncated = True
                outcome = str(transition.get("outcome") or "FAILED_UNSUPPORTED_SCREEN")
                break
            if policy_decision_count >= max_decisions:
                truncated = True
                outcome = "TRUNCATED_DECISION_LIMIT"
                break
            if time.monotonic() >= deadline:
                truncated = True
                outcome = "TRUNCATED_TIME_LIMIT"
                break

            try:
                choice = policy.choose(
                    observation=deepcopy(observation),
                    legal_actions=deepcopy(_dict(transition.get("legal_actions"))),
                    decision_index=policy_decision_count,
                )
            except ScriptedPolicyFailure:
                raise
            record = build_policy_decision_record(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_decision_index=policy_decision_count,
                transition=transition,
                choice=choice,
                previous_chain_hash=final_policy_chain_hash,
            )
            append_jsonl(decisions_path, record)
            final_policy_chain_hash = record["hashes"]["chain_hash"]
            action_types.add(str(choice.action.get("type")))
            transition = client.invoke(
                "env.step",
                _step_params(transition, choice.action, policy_decision_count + 1),
                mutating=True,
            )
            policy_decision_count += 1
            results = _rows(transition.get("action_results"))
            if (
                len(results) != 1
                or results[0].get("status") != "accepted"
                or results[0].get("verified") is not True
            ):
                raise ScriptedBaselineFailure(
                    f"policy action was not independently verified: {results}"
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        outcome = outcome or "FAILED_POLICY"
    finally:
        try:
            if transition is not None:
                observation = _dict(transition.get("observation"))
                close_result = client.invoke(
                    "env.close",
                    {
                        "episode_id": observation["episode_id"],
                        "native_session_id": observation["native_session_id"],
                        "run_id": observation["run_id"],
                    },
                    mutating=True,
                )
            else:
                close_result = client.invoke("quit", {}, mutating=True)
        except Exception as close_exc:
            if error is None:
                error = f"close failed: {type(close_exc).__name__}: {close_exc}"
                outcome = "FAILED_POLICY"

    observation = _dict(transition.get("observation")) if isinstance(transition, dict) else {}
    run = _dict(observation.get("run"))
    if terminal_reached:
        episode_status = "terminal"
    elif truncated and error is None:
        episode_status = "truncated"
    else:
        episode_status = "failed"
    result = {
        "schema_version": "sts-scripted-baseline-driver.v1",
        "status": "passed" if episode_status in {"terminal", "truncated"} and error is None else "failed",
        "episode_status": episode_status,
        "policy": policy_descriptor,
        "seed": seed,
        "terminal_reached": terminal_reached,
        "truncated": truncated,
        "outcome": outcome,
        "policy_decision_count": policy_decision_count,
        "final_transition_index": transition.get("transition_index") if isinstance(transition, dict) else None,
        "final_decision_kind": observation.get("decision_kind"),
        "final_act": run.get("act"),
        "final_floor": run.get("floor"),
        "final_hp": run.get("current_hp"),
        "decision_kinds": sorted(decision_kinds),
        "action_types": sorted(action_types),
        "final_chain_hash": _dict(transition.get("hashes")).get("chain_hash") if isinstance(transition, dict) else None,
        "final_replay_checkpoint_hash": _dict(transition.get("replay_checkpoint")).get("replay_checkpoint_hash") if isinstance(transition, dict) else None,
        "final_policy_decision_chain_hash": final_policy_chain_hash,
        "policy_decisions": str(decisions_path),
        "close_result": close_result,
        "error": error,
    }
    atomic_write_json(output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one H1-C scripted baseline episode")
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--policy-id", required=True, choices=("scripted_random_legal", "scripted_greedy"))
    parser.add_argument("--policy-seed")
    parser.add_argument("--max-decisions", type=int, default=2000)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_scripted_baseline_episode(
            descriptor=args.descriptor.resolve(),
            output=args.output.resolve(),
            seed=args.seed,
            policy_id=args.policy_id,
            policy_seed=args.policy_seed,
            max_decisions=args.max_decisions,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "schema_version": "sts-scripted-baseline-driver.v1",
            "status": "failed",
            "episode_status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        atomic_write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
