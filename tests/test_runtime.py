from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from sts_harness.legal_actions import submission_from_public_action
from sts_harness.rpc_protocol import RpcFailure
from sts_harness.runtime import H1Runtime

from test_legal_actions import combat_raw


def _menu_raw() -> dict:
    return {
        "bridge_version": "1.2.1-sts-harness.1",
        "protocol_version": "communicationmod-harness.v1",
        "available_commands": ["start", "state"],
        "ready_for_command": True,
        "in_game": False,
    }


def _step_params(transition: dict, action: dict) -> dict:
    observation = transition["observation"]
    legal = transition["legal_actions"]
    return {
        "controller_nonce": "secret",
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation["run_id"],
        "expected_decision_id": observation["decision_id"],
        "expected_observation_hash": observation["observation_hash"],
        "expected_legal_actions_hash": legal["legal_actions_hash"],
        "actions": [submission_from_public_action(action)],
    }


def test_runtime_reset_step_observe_and_stale_guard(tmp_path: Path) -> None:
    commands: list[str] = []
    holder: dict[str, H1Runtime] = {}

    post_play = deepcopy(combat_raw())
    post_play["game_state"]["combat_state"]["hand"] = post_play["game_state"]["combat_state"]["hand"][1:]
    post_play["game_state"]["combat_state"]["player"]["energy"] = 2

    def sink(command: str) -> None:
        commands.append(command)
        if command.startswith("start "):
            holder["runtime"].ingest_bridge_document(combat_raw())
        elif command.startswith("play "):
            holder["runtime"].ingest_bridge_document(post_play)

    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_test",
        native_session_id="native_test",
        environment_fingerprint_id="sha256:environment",
        controller_nonce="secret",
        command_sink=sink,
        state_timeout_seconds=1,
    )
    holder["runtime"] = runtime
    runtime.ingest_bridge_document(_menu_raw())
    reset = runtime.dispatch(
        "env.reset",
        {
            "controller_nonce": "secret",
            "character_id": "IRONCLAD",
            "ascension": 0,
            "seed": "AMIYA20260904",
            "fairness_profile": "player_visible.v1",
            "policy_mode": "scripted",
            "max_episode_decisions": 10,
            "max_episode_seconds": 60,
        },
    )
    assert reset["transition_index"] == 0
    assert reset["observation"]["decision_kind"] == "combat"
    action = reset["legal_actions"]["actions"][0]
    stepped = runtime.dispatch("env.step", _step_params(reset, action))
    assert stepped["transition_index"] == 1
    assert stepped["action_results"][0]["status"] == "accepted"
    assert runtime.dispatch("env.observe", {}) == stepped
    assert commands == ["start ironclad 0 AMIYA20260904", "play 1 0"]

    stale = _step_params(reset, action)
    with pytest.raises(RpcFailure, match="STALE_OR_FOREIGN_DECISION"):
        runtime.dispatch("env.step", stale)


def test_runtime_rejects_wrong_controller_nonce_without_command(tmp_path: Path) -> None:
    commands: list[str] = []
    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_test",
        native_session_id="native_test",
        environment_fingerprint_id="sha256:environment",
        controller_nonce="secret",
        command_sink=commands.append,
        state_timeout_seconds=1,
    )
    runtime.ingest_bridge_document(_menu_raw())
    with pytest.raises(RpcFailure, match="CONTROLLER_AUTH_FAILED"):
        runtime.dispatch("env.reset", {"controller_nonce": "wrong"})
    assert commands == []


def test_duplicate_bridge_state_does_not_create_a_new_decision(tmp_path: Path) -> None:
    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_test",
        native_session_id="native_test",
        environment_fingerprint_id="sha256:environment",
        controller_nonce="secret",
        command_sink=lambda _: None,
        state_timeout_seconds=1,
    )
    runtime.ingest_bridge_document(_menu_raw())
    runtime.ingest_bridge_document(deepcopy(_menu_raw()))
    status = runtime.dispatch("bridge.status", {})
    assert status["state_seq"] == 1

