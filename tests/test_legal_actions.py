from __future__ import annotations

from copy import deepcopy

import pytest

from sts_harness.legal_actions import (
    ActionValidationFailure,
    build_legal_actions,
    submission_from_public_action,
    validate_action_submission,
)
from sts_harness.observation import StateNormalizer


def _card(card_id: str, uuid: str, card_type: str, target: bool) -> dict:
    return {
        "id": card_id,
        "name": card_id,
        "uuid": uuid,
        "cost": 1,
        "upgrades": 0,
        "type": card_type,
        "rarity": "BASIC",
        "is_playable": True,
        "has_target": target,
        "exhausts": False,
        "ethereal": False,
    }


def combat_raw() -> dict:
    strike = _card("Strike_R", "strike-uuid", "ATTACK", True)
    defend = _card("Defend_R", "defend-uuid", "SKILL", False)
    return {
        "bridge_version": "1.2.1-sts-harness.1",
        "protocol_version": "communicationmod-harness.v1",
        "available_commands": ["play", "end", "key", "click", "wait", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "screen_type": "NONE",
            "screen_name": "NONE",
            "screen_state": {},
            "room_phase": "COMBAT",
            "room_type": "MonsterRoom",
            "class": "IRONCLAD",
            "ascension_level": 0,
            "act": 1,
            "floor": 1,
            "current_hp": 80,
            "max_hp": 80,
            "gold": 99,
            "keys": {},
            "deck": [strike, defend],
            "map": [],
            "relics": [],
            "potions": [],
            "combat_state": {
                "turn": 1,
                "hand": [strike, defend],
                "draw_pile": [],
                "discard_pile": [],
                "exhaust_pile": [],
                "limbo": [],
                "player": {"energy": 3, "powers": [], "orbs": []},
                "monsters": [
                    {
                        "id": "JawWorm",
                        "name": "Jaw Worm",
                        "current_hp": 40,
                        "max_hp": 40,
                        "block": 0,
                        "is_gone": False,
                        "powers": [],
                    }
                ],
            },
        },
    }


def test_combat_legal_actions_are_typed_and_omit_raw_controls() -> None:
    raw = combat_raw()
    observation = StateNormalizer("ep_test", "native_test").normalize(raw, 1)
    snapshot = build_legal_actions(raw, observation)
    types = [action["type"] for action in snapshot.document["actions"]]
    assert types == ["play_card", "play_card", "end_turn"]
    commands = [native.command for native in snapshot.native_actions.values()]
    assert commands == ["play 1 0", "play 2", "end"]
    assert not any(command.startswith(("key ", "click ", "wait ")) for command in commands)


def test_current_public_action_round_trips_through_independent_validator() -> None:
    raw = combat_raw()
    observation = StateNormalizer("ep_test", "native_test").normalize(raw, 1)
    snapshot = build_legal_actions(raw, observation)
    public = snapshot.document["actions"][0]
    native = validate_action_submission(submission_from_public_action(public), snapshot)
    assert native.command == "play 1 0"


def test_validator_rejects_forged_payload_even_with_current_action_id() -> None:
    raw = combat_raw()
    observation = StateNormalizer("ep_test", "native_test").normalize(raw, 1)
    snapshot = build_legal_actions(raw, observation)
    submission = submission_from_public_action(snapshot.document["actions"][0])
    submission["payload"] = {"card_instance_id": "card_forged", "target_id": "target_forged"}
    with pytest.raises(ActionValidationFailure, match="does not match"):
        validate_action_submission(submission, snapshot)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda submission: submission.update({"unexpected": True}),
        lambda submission: submission.pop("payload"),
        lambda submission: submission.update({"type": 7}),
        lambda submission: submission.update({"payload": []}),
    ],
)
def test_validator_rejects_non_exact_action_schema(mutate) -> None:
    raw = combat_raw()
    observation = StateNormalizer("ep_test", "native_test").normalize(raw, 1)
    snapshot = build_legal_actions(raw, observation)
    submission = submission_from_public_action(snapshot.document["actions"][0])
    mutate(submission)
    with pytest.raises(ActionValidationFailure):
        validate_action_submission(submission, snapshot)


def test_validator_rejects_action_from_previous_decision() -> None:
    raw = combat_raw()
    normalizer = StateNormalizer("ep_test", "native_test")
    first_observation = normalizer.normalize(raw, 1)
    first = build_legal_actions(raw, first_observation)
    changed = deepcopy(raw)
    changed["game_state"]["combat_state"]["player"]["energy"] = 2
    second_observation = normalizer.normalize(changed, 2)
    second = build_legal_actions(changed, second_observation)
    submission = submission_from_public_action(first.document["actions"][0])
    with pytest.raises(ActionValidationFailure, match="not legal"):
        validate_action_submission(submission, second)


def test_map_choices_use_stable_node_ids() -> None:
    raw = {
        "bridge_version": "1.2.1-sts-harness.1",
        "protocol_version": "communicationmod-harness.v1",
        "available_commands": ["choose", "return", "key", "click", "wait", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "screen_type": "MAP",
            "screen_name": "MAP",
            "screen_state": {
                "current_node": {"x": 0, "y": -1},
                "next_nodes": [
                    {"x": 0, "y": 0, "symbol": "M"},
                    {"x": 2, "y": 0, "symbol": "M"},
                ],
                "first_node_chosen": False,
                "boss_available": False,
            },
            "choice_list": ["x=0", "x=2"],
            "room_phase": "COMPLETE",
            "room_type": "NeowRoom",
            "class": "IRONCLAD",
            "ascension_level": 0,
            "act": 1,
            "floor": 0,
            "current_hp": 80,
            "max_hp": 80,
            "gold": 99,
            "keys": {},
            "deck": [],
            "map": [],
            "relics": [],
            "potions": [],
        },
    }
    observation = StateNormalizer("ep_test", "native_test").normalize(raw, 1)
    snapshot = build_legal_actions(raw, observation)
    map_actions = [action for action in snapshot.document["actions"] if action["type"] == "choose_map_node"]
    assert [action["payload"] for action in map_actions] == [
        {"map_node_id": "node_0_0"},
        {"map_node_id": "node_2_0"},
    ]
    assert snapshot.native_actions[map_actions[1]["action_id"]].command == "choose 1"
