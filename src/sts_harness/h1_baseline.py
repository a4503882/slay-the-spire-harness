from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json
from .client import H1Client
from .legal_actions import submission_from_public_action


class BaselineFailure(RuntimeError):
    pass


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _choose_action(transition: dict[str, Any]) -> dict[str, Any]:
    observation = transition.get("observation")
    legal = transition.get("legal_actions")
    if not isinstance(observation, dict) or not isinstance(legal, dict):
        raise BaselineFailure("transition has no observation/legal-actions documents")
    actions = _rows(legal.get("actions"))
    if not actions:
        raise BaselineFailure(f"no legal action for {observation.get('decision_kind')}")
    decision_kind = observation.get("decision_kind")
    if decision_kind == "combat":
        play_actions = [action for action in actions if action.get("type") == "play_card"]

        def priority(action: dict[str, Any]) -> tuple[int, int, str]:
            presentation = action.get("presentation")
            presentation = presentation if isinstance(presentation, dict) else {}
            card_id = str(presentation.get("card_id", ""))
            card_type = str(presentation.get("type", ""))
            rank = 0 if card_id == "Bash" else 1 if card_type == "ATTACK" else 2
            cost = presentation.get("cost")
            return rank, -(cost if isinstance(cost, int) else 0), str(action.get("action_id", ""))

        if play_actions:
            return min(play_actions, key=priority)
        end_turn = next((action for action in actions if action.get("type") == "end_turn"), None)
        if end_turn is not None:
            return end_turn
    for action_type in (
        "choose_option",
        "choose_map_node",
        "proceed",
        "return_or_skip",
        "end_turn",
    ):
        candidate = next((action for action in actions if action.get("type") == action_type), None)
        if candidate is not None:
            return candidate
    raise BaselineFailure(f"no H1-A baseline action for {decision_kind}")


def _step_params(transition: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    observation = transition["observation"]
    legal = transition["legal_actions"]
    return {
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation["run_id"],
        "expected_decision_id": observation["decision_id"],
        "expected_observation_hash": observation["observation_hash"],
        "expected_legal_actions_hash": legal["legal_actions_hash"],
        "actions": [submission_from_public_action(action)],
    }


def run_baseline(
    *,
    descriptor: Path,
    output: Path,
    seed: str,
    max_decisions: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while not descriptor.is_file():
        if time.monotonic() >= deadline:
            raise BaselineFailure("timed out waiting for sidecar descriptor")
        time.sleep(0.05)
    client = H1Client.from_descriptor(descriptor, timeout_seconds=min(60.0, timeout_seconds))
    transition: dict[str, Any] | None = None
    seen_combat = False
    decision_count = 0
    combat_action_count = 0
    completed = False
    error: str | None = None
    close_result: dict[str, Any] | None = None
    try:
        capabilities = client.invoke("capabilities")
        if capabilities.get("raw_command_submission") is not False:
            raise BaselineFailure("sidecar unexpectedly exposes raw command submission")
        transition = client.invoke(
            "env.reset",
            {
                "character_id": "IRONCLAD",
                "ascension": 0,
                "seed": seed,
                "fairness_profile": "player_visible.v1",
                "policy_mode": "scripted",
                "max_episode_decisions": max_decisions,
                "max_episode_seconds": int(timeout_seconds),
            },
            mutating=True,
        )
        while decision_count < max_decisions:
            observation = transition["observation"]
            decision_kind = observation.get("decision_kind")
            if decision_kind == "combat":
                seen_combat = True
            elif seen_combat:
                events = _rows(transition.get("events"))
                if any(event.get("type") == "combat_completed" for event in events):
                    completed = True
                    break
                raise BaselineFailure(
                    f"combat ended without a verified completion event: {decision_kind}"
                )
            action = _choose_action(transition)
            if decision_kind == "combat":
                combat_action_count += 1
            transition = client.invoke(
                "env.step",
                _step_params(transition, action),
                mutating=True,
            )
            decision_count += 1
            results = _rows(transition.get("action_results"))
            if len(results) != 1 or results[0].get("status") != "accepted" or results[0].get("verified") is not True:
                raise BaselineFailure(f"action was not independently verified: {results}")
        if not completed:
            raise BaselineFailure("one-combat decision limit reached before completion")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if transition is not None:
                observation = transition["observation"]
                close_result = client.invoke(
                    "env.close",
                    {
                        "episode_id": observation["episode_id"],
                        "native_session_id": observation["native_session_id"],
                        "run_id": observation["run_id"],
                    },
                    mutating=True,
                )
        except Exception as close_exc:
            if error is None:
                error = f"close failed: {type(close_exc).__name__}: {close_exc}"

    final_observation = transition.get("observation", {}) if isinstance(transition, dict) else {}
    run = final_observation.get("run") if isinstance(final_observation.get("run"), dict) else {}
    result = {
        "schema_version": "sts-h1-baseline-summary.v1",
        "status": "passed" if completed and error is None else "failed",
        "seed": seed,
        "one_combat_completed": completed,
        "seen_combat": seen_combat,
        "decision_count": decision_count,
        "combat_action_count": combat_action_count,
        "final_transition_index": transition.get("transition_index") if isinstance(transition, dict) else None,
        "final_decision_kind": final_observation.get("decision_kind"),
        "final_floor": run.get("floor"),
        "final_hp": run.get("current_hp"),
        "final_chain_hash": (
            transition.get("hashes", {}).get("chain_hash") if isinstance(transition, dict) else None
        ),
        "close_result": close_result,
        "error": error,
    }
    atomic_write_json(output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic H1-A one-combat baseline")
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--max-decisions", type=int, default=128)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_baseline(
            descriptor=args.descriptor.resolve(),
            output=args.output.resolve(),
            seed=args.seed,
            max_decisions=args.max_decisions,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "schema_version": "sts-h1-baseline-summary.v1",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        atomic_write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

