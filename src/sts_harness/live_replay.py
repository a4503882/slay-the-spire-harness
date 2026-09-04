from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, strict_json_loads
from .client import H1Client
from .legal_actions import submission_from_public_action
from .replay_checkpoint import (
    ReplayCheckpointFailure,
    bounded_structural_diff,
    resolve_action_selector,
)
from .replay_verify import verify_offline_replay


class LiveReplayFailure(RuntimeError):
    def __init__(self, status: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.data = data or {}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _json(path: Path) -> dict[str, Any]:
    value = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LiveReplayFailure("REPLAY_INVALID", f"expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise LiveReplayFailure(
                "REPLAY_INVALID", f"expected JSON object: {path}:{line_number}"
            )
        rows.append(value)
    if not rows:
        raise LiveReplayFailure("REPLAY_INVALID", "source transition trace is empty")
    return rows


def _step_params(transition: dict[str, Any], action: dict[str, Any], request_index: int) -> dict[str, Any]:
    observation = transition["observation"]
    legal = transition["legal_actions"]
    return {
        "request_id": f"replay_req_{request_index:06d}",
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation["run_id"],
        "expected_decision_id": observation["decision_id"],
        "expected_observation_hash": observation["observation_hash"],
        "expected_legal_actions_hash": legal["legal_actions_hash"],
        "stop_on_failure": True,
        "actions": [submission_from_public_action(action)],
    }


def _divergence_context(
    source: dict[str, Any],
    replayed: dict[str, Any],
    transition_index: int,
) -> dict[str, Any]:
    source_observation = _dict(source.get("observation"))
    replay_observation = _dict(replayed.get("observation"))
    combat = _dict(source_observation.get("combat"))
    return {
        "first_divergent_transition_index": transition_index,
        "room_id": source_observation.get("room_id"),
        "combat_id": source_observation.get("combat_id"),
        "turn": combat.get("turn"),
        "decision_kind": source_observation.get("decision_kind"),
        "recorded_checkpoint_hash": _dict(source.get("replay_checkpoint")).get(
            "replay_checkpoint_hash"
        ),
        "replayed_checkpoint_hash": _dict(replayed.get("replay_checkpoint")).get(
            "replay_checkpoint_hash"
        ),
        "recorded_observation_hash": source_observation.get("observation_hash"),
        "replayed_observation_hash": replay_observation.get("observation_hash"),
        "structural_diff": bounded_structural_diff(
            source.get("replay_checkpoint"), replayed.get("replay_checkpoint"), limit=256
        ),
    }


def run_live_replay(
    *,
    source_run: Path,
    descriptor: Path,
    output: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    source_run = source_run.resolve()
    offline = verify_offline_replay(source_run)
    if offline.get("status") != "REPLAY_VALID":
        raise LiveReplayFailure("REPLAY_INVALID", "source trace failed offline verification")
    config = _json(source_run / "config.json")
    source_environment = _json(source_run / "environment.json")
    transitions = _jsonl(source_run / "transitions.jsonl")
    seed = config.get("seed")
    if not isinstance(seed, str):
        raise LiveReplayFailure("REPLAY_INVALID", "source config has no seed")

    deadline = time.monotonic() + timeout_seconds
    while not descriptor.is_file():
        if time.monotonic() >= deadline:
            raise LiveReplayFailure("REPLAY_DIVERGED", "timed out waiting for replay sidecar")
        time.sleep(0.05)
    client = H1Client.from_descriptor(descriptor, timeout_seconds=min(60.0, timeout_seconds))
    current: dict[str, Any] | None = None
    close_result: dict[str, Any] | None = None
    compared = 0
    replayed_actions = 0
    result: dict[str, Any]
    try:
        current = client.invoke(
            "env.reset",
            {
                "character_id": config.get("character_id", "IRONCLAD"),
                "ascension": config.get("ascension", 0),
                "seed": seed,
                "fairness_profile": config.get("fairness_profile", "player_visible.v1"),
                "policy_mode": "scripted_replay",
                "max_episode_decisions": config.get("max_episode_decisions", 10_000),
                "max_episode_seconds": int(timeout_seconds),
            },
            mutating=True,
        )
        expected_environment = source_environment.get("environment_fingerprint_id")
        if current.get("environment_fingerprint_id") != expected_environment:
            raise LiveReplayFailure(
                "REPLAY_ENVIRONMENT_MISMATCH",
                "source and replay environment fingerprints differ",
                {
                    "recorded_environment_fingerprint_id": expected_environment,
                    "replayed_environment_fingerprint_id": current.get(
                        "environment_fingerprint_id"
                    ),
                },
            )
        first_checkpoint = transitions[0].get("replay_checkpoint")
        if current.get("replay_checkpoint") != first_checkpoint:
            raise LiveReplayFailure(
                "REPLAY_DIVERGED",
                "initial replay checkpoint diverged",
                _divergence_context(transitions[0], current, 0),
            )
        compared = 1

        for transition_index, source_transition in enumerate(transitions[1:], start=1):
            source_results = _rows(source_transition.get("action_results"))
            accepted = [result for result in source_results if result.get("status") == "accepted"]
            if len(accepted) != len(source_results):
                raise LiveReplayFailure(
                    "REPLAY_INVALID",
                    f"source transition {transition_index} contains non-accepted actions",
                )
            for source_result in accepted:
                selector = source_result.get("selector")
                if not isinstance(selector, dict):
                    raise LiveReplayFailure(
                        "REPLAY_INVALID",
                        f"source action at transition {transition_index} has no selector",
                    )
                try:
                    action = resolve_action_selector(selector, _dict(current.get("legal_actions")))
                except ReplayCheckpointFailure as exc:
                    raise LiveReplayFailure(
                        "REPLAY_ACTION_UNRESOLVABLE",
                        str(exc),
                        {
                            "first_divergent_transition_index": transition_index,
                            "recorded_action_selector": selector,
                            "current_legal_selectors": [
                                row.get("selector")
                                for row in _rows(_dict(current.get("legal_actions")).get("actions"))
                            ][:64],
                        },
                    ) from exc
                current = client.invoke(
                    "env.step",
                    _step_params(current, action, replayed_actions + 1),
                    mutating=True,
                )
                replayed_actions += 1
                replay_results = _rows(current.get("action_results"))
                if len(replay_results) != 1 or replay_results[0].get("status") != "accepted":
                    raise LiveReplayFailure(
                        "REPLAY_DIVERGED",
                        f"replayed action failed at transition {transition_index}",
                        {"replayed_action_results": replay_results},
                    )
            if current.get("replay_checkpoint") != source_transition.get("replay_checkpoint"):
                context = _divergence_context(source_transition, current, transition_index)
                context["recorded_actions"] = [row.get("selector") for row in accepted]
                context["replayed_actions"] = [
                    row.get("selector") for row in _rows(current.get("action_results"))
                ]
                context["environment_fingerprint_id"] = expected_environment
                raise LiveReplayFailure(
                    "REPLAY_DIVERGED",
                    f"checkpoint diverged at transition {transition_index}",
                    context,
                )
            compared += 1
        result = {
            "schema_version": "sts-live-replay.v1",
            "status": "REPLAY_PARITY",
            "valid": True,
            "source_run": str(source_run),
            "source_episode_id": transitions[0].get("episode_id"),
            "replay_episode_id": _dict(current.get("observation")).get("episode_id"),
            "environment_fingerprint_id": source_environment.get("environment_fingerprint_id"),
            "source_transition_count": len(transitions),
            "compared_checkpoint_count": compared,
            "replayed_action_count": replayed_actions,
            "final_recorded_checkpoint_hash": _dict(transitions[-1].get("replay_checkpoint")).get(
                "replay_checkpoint_hash"
            ),
            "final_replayed_checkpoint_hash": _dict(current.get("replay_checkpoint")).get(
                "replay_checkpoint_hash"
            ),
            "first_divergence": None,
        }
    except LiveReplayFailure as exc:
        result = {
            "schema_version": "sts-live-replay.v1",
            "status": exc.status,
            "valid": False,
            "source_run": str(source_run),
            "source_transition_count": len(transitions),
            "compared_checkpoint_count": compared,
            "replayed_action_count": replayed_actions,
            "error": str(exc),
            "first_divergence": exc.data or None,
        }
    except Exception as exc:
        result = {
            "schema_version": "sts-live-replay.v1",
            "status": "REPLAY_DIVERGED",
            "valid": False,
            "source_run": str(source_run),
            "source_transition_count": len(transitions),
            "compared_checkpoint_count": compared,
            "replayed_action_count": replayed_actions,
            "error": f"{type(exc).__name__}: {exc}",
            "first_divergence": None,
        }
    finally:
        try:
            if current is not None:
                observation = current["observation"]
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
            result = locals().get(
                "result",
                {
                    "schema_version": "sts-live-replay.v1",
                    "status": "REPLAY_DIVERGED",
                    "valid": False,
                },
            )
            result["close_error"] = f"{type(close_exc).__name__}: {close_exc}"
            result["valid"] = False
            if result.get("status") == "REPLAY_PARITY":
                result["status"] = "REPLAY_DIVERGED"
    result["close_result"] = close_result
    atomic_write_json(output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a recorded H1-B trace in a fresh process")
    parser.add_argument("--source-run", required=True, type=Path)
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_live_replay(
            source_run=args.source_run,
            descriptor=args.descriptor.resolve(),
            output=args.output.resolve(),
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "schema_version": "sts-live-replay.v1",
            "status": getattr(exc, "status", "REPLAY_INVALID"),
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        atomic_write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "REPLAY_PARITY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
