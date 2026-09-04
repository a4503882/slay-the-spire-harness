from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path

import pytest

from sts_harness.legal_actions import submission_from_public_action
from sts_harness.rpc_protocol import RpcFailure
from sts_harness.runtime import H1Runtime, _combat_completed_between

from test_legal_actions import combat_raw
from h1b_fixtures import card, raw_state, relic


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


def test_combat_modal_is_not_counted_as_combat_completion() -> None:
    before = {"decision_kind": "combat", "combat": {"turn": 1}}
    modal = {"decision_kind": "card_reward", "combat": {"turn": 1}}
    terminal = {"decision_kind": "game_over", "combat": {"turn": 8}}
    reward = {"decision_kind": "combat_reward", "combat": None}

    assert _combat_completed_between(before, modal) is False
    assert _combat_completed_between(before, terminal) is True
    assert _combat_completed_between(before, reward) is True


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

    public_trace = (tmp_path / "transitions.jsonl").read_text(encoding="utf-8")
    assert '"controller_nonce"' not in public_trace
    assert '"available_commands"' not in public_trace
    assert '"uuid"' not in public_trace
    assert '"native_command":' not in public_trace
    raw_trace = (tmp_path / "raw-states.jsonl").read_text(encoding="utf-8")
    assert '"non_benchmark":true' in raw_trace
    assert '"available_commands"' in raw_trace

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


def test_authenticated_quit_closes_worker_before_reset(tmp_path: Path) -> None:
    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_abort",
        native_session_id="native_abort",
        environment_fingerprint_id="sha256:environment",
        controller_nonce="secret",
        command_sink=lambda _: None,
        state_timeout_seconds=1,
    )
    result = runtime.dispatch("quit", {"controller_nonce": "secret"})
    assert result == {
        "episode_id": "ep_abort",
        "close_requested": True,
        "idempotent": False,
        "aborted": True,
    }
    assert runtime.close_requested is True
    assert runtime.abort_requested is True


def _batch_runtime(tmp_path: Path):
    commands: list[str] = []
    holder: dict[str, H1Runtime] = {}
    first_post = deepcopy(combat_raw())
    first_post["game_state"]["combat_state"]["hand"] = first_post["game_state"]["combat_state"]["hand"][1:]
    first_post["game_state"]["combat_state"]["player"]["energy"] = 2
    second_post = deepcopy(first_post)
    second_post["game_state"]["combat_state"]["hand"] = []
    second_post["game_state"]["combat_state"]["player"]["energy"] = 1
    play_count = 0

    def sink(command: str) -> None:
        nonlocal play_count
        commands.append(command)
        if command.startswith("start "):
            holder["runtime"].ingest_bridge_document(combat_raw())
        elif command.startswith("play "):
            play_count += 1
            holder["runtime"].ingest_bridge_document(first_post if play_count == 1 else second_post)

    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_batch",
        native_session_id="native_batch",
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
    return runtime, reset, commands


def test_batch_re_resolves_card_indices_after_each_stable_state(tmp_path: Path) -> None:
    runtime, reset, commands = _batch_runtime(tmp_path)
    play_actions = [
        action for action in reset["legal_actions"]["actions"] if action["type"] == "play_card"
    ]
    params = _step_params(reset, play_actions[0])
    params["actions"] = [
        submission_from_public_action(play_actions[0]),
        submission_from_public_action(play_actions[1]),
    ]
    params["stop_on_failure"] = True
    stepped = runtime.dispatch("env.step", params)
    assert [result["status"] for result in stepped["action_results"]] == [
        "accepted",
        "accepted",
    ]
    assert commands == [
        "start ironclad 0 AMIYA20260904",
        "play 1 0",
        "play 1",
    ]
    assert stepped["action_results"][1]["requested_action_id"] != stepped["action_results"][1]["resolved_action_id"]


def test_batch_records_partial_success_and_skips_trailing_actions(tmp_path: Path) -> None:
    runtime, reset, commands = _batch_runtime(tmp_path)
    play_actions = [
        action for action in reset["legal_actions"]["actions"] if action["type"] == "play_card"
    ]
    params = _step_params(reset, play_actions[0])
    params["actions"] = [
        submission_from_public_action(play_actions[0]),
        submission_from_public_action(play_actions[0]),
        submission_from_public_action(play_actions[1]),
    ]
    stepped = runtime.dispatch("env.step", params)
    assert [result["status"] for result in stepped["action_results"]] == [
        "accepted",
        "rejected",
        "skipped",
    ]
    assert stepped["action_results"][2]["reason"] == "ACTION_NOT_LEGAL"
    assert any(event["type"] == "ACTION_PARTIAL_SUCCESS" for event in stepped["events"])
    assert commands == ["start ironclad 0 AMIYA20260904", "play 1 0"]


def test_batch_limit_and_stop_on_failure_are_strict(tmp_path: Path) -> None:
    runtime, reset, _ = _batch_runtime(tmp_path)
    action = reset["legal_actions"]["actions"][0]
    params = _step_params(reset, action)
    params["actions"] = [submission_from_public_action(action)] * 13
    with pytest.raises(RpcFailure, match="batch size"):
        runtime.dispatch("env.step", params)
    params["actions"] = [submission_from_public_action(action)]
    params["stop_on_failure"] = False
    with pytest.raises(RpcFailure, match="stop_on_failure"):
        runtime.dispatch("env.step", params)


def test_action_proof_can_settle_on_a_later_distinct_native_state(tmp_path: Path) -> None:
    holder: dict[str, H1Runtime] = {}
    timers: list[threading.Timer] = []
    boss = raw_state(
        "BOSS_REWARD",
        screen_state={"relics": [relic("Snecko Eye")]},
        choices=["snecko eye"],
        commands=["choose", "skip", "state"],
        room_type="TreasureRoomBoss",
    )
    early = raw_state(
        "MAP",
        screen_state={
            "current_node": {"x": -1, "y": 15},
            "next_nodes": [],
            "first_node_chosen": True,
            "boss_available": False,
        },
        choices=[],
        commands=["return", "state"],
        room_type="TreasureRoomBoss",
    )
    early["game_state"]["floor"] = 17
    settled = deepcopy(early)
    settled["game_state"]["relics"].append(relic("Snecko Eye"))

    def sink(command: str) -> None:
        if command.startswith("start "):
            holder["runtime"].ingest_bridge_document(boss)
        elif command.startswith("choose "):
            holder["runtime"].ingest_bridge_document(early)
            timer = threading.Timer(
                0.05,
                holder["runtime"].ingest_bridge_document,
                args=(settled,),
            )
            timers.append(timer)
            timer.start()

    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_settle",
        native_session_id="native_settle",
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
    action = next(
        action
        for action in reset["legal_actions"]["actions"]
        if action["selector"].get("semantic") == "take_boss_relic"
    )
    stepped = runtime.dispatch("env.step", _step_params(reset, action))
    for timer in timers:
        timer.join(timeout=1)

    result = stepped["action_results"][0]
    assert result["status"] == "accepted"
    assert result["verified"] is True
    assert result["proof"]["verification_attempts"] == 2
    assert result["proof"]["initial_post_state_seq"] == 3
    assert result["proof"]["settled_post_state_seq"] == 4
    assert stepped["observation"]["run"]["relics"][-1]["relic_id"] == "Snecko Eye"


def test_neow_reward_waits_for_visible_effect_via_read_only_state_probe(tmp_path: Path) -> None:
    commands: list[str] = []
    holder: dict[str, H1Runtime] = {}
    labels = [
        "随机获得一张稀有牌",
        "获得 3 瓶药水",
        "得到一张诅咒牌。 变化 2 张牌",
        "失去你的初始遗物， 获得一件随机boss遗物。",
    ]

    def neow_state(choice_labels: list[str]) -> dict:
        return raw_state(
            "EVENT",
            screen_state={
                "event_id": "Neow Event",
                "event_name": "Neow",
                "body_text": "Choose",
                "options": [
                    {"text": label, "label": label, "disabled": False, "choice_index": index}
                    for index, label in enumerate(choice_labels)
                ],
            },
            choices=choice_labels,
            commands=["choose", "state"],
            room_type="NeowRoom",
            room_phase="EVENT",
        )

    reward = neow_state(labels)
    early = neow_state(["离开"])
    settled = deepcopy(early)
    settled["game_state"]["deck"].append(
        card("Feed", "neow-feed", card_type="ATTACK", target=True)
    )

    def sink(command: str) -> None:
        commands.append(command)
        if command.startswith("start "):
            holder["runtime"].ingest_bridge_document(reward)
        elif command.startswith("choose "):
            holder["runtime"].ingest_bridge_document(early)
        elif command == "state":
            holder["runtime"].ingest_bridge_document(settled)

    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_neow_settle",
        native_session_id="native_neow_settle",
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
    selected = reset["legal_actions"]["actions"][0]
    stepped = runtime.dispatch("env.step", _step_params(reset, selected))

    result = stepped["action_results"][0]
    assert result["status"] == "accepted"
    assert result["proof"]["neow_reward_effect_visible"] is True
    assert result["proof"]["verification_attempts"] == 2
    assert stepped["observation"]["run"]["deck"][-1]["card_id"] == "Feed"
    assert commands[-2:] == ["choose 0", "state"]


def test_unknown_actionable_screen_resets_to_explicit_truncation(tmp_path: Path) -> None:
    commands: list[str] = []
    holder: dict[str, H1Runtime] = {}
    unknown = raw_state(
        "FUTURE_ACTION_SCREEN",
        choices=["mystery"],
        commands=["choose", "state"],
    )

    def sink(command: str) -> None:
        commands.append(command)
        if command.startswith("start "):
            holder["runtime"].ingest_bridge_document(unknown)

    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_unknown",
        native_session_id="native_unknown",
        environment_fingerprint_id="sha256:environment",
        controller_nonce="secret",
        command_sink=sink,
        state_timeout_seconds=1,
    )
    holder["runtime"] = runtime
    runtime.ingest_bridge_document(_menu_raw())
    transition = runtime.dispatch(
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

    assert transition["truncated"] is True
    assert transition["terminal"] is False
    assert transition["outcome"] == "FAILED_UNSUPPORTED_SCREEN"
    assert transition["events"][-1]["type"] == "UNSUPPORTED_SCREEN"
    assert transition["legal_actions"]["actions"] == []
    params = {
        "controller_nonce": "secret",
        "episode_id": transition["observation"]["episode_id"],
        "native_session_id": transition["observation"]["native_session_id"],
        "run_id": transition["observation"]["run_id"],
        "expected_decision_id": transition["observation"]["decision_id"],
        "expected_observation_hash": transition["observation"]["observation_hash"],
        "expected_legal_actions_hash": transition["legal_actions"]["legal_actions_hash"],
        "actions": [{"action_id": "forged", "type": "choose_option", "payload": {}}],
    }
    with pytest.raises(RpcFailure, match="UNSUPPORTED_SCREEN"):
        runtime.dispatch("env.step", params)
    assert commands == ["start ironclad 0 AMIYA20260904"]
