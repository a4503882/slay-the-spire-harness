from __future__ import annotations

from copy import deepcopy

from sts_harness.action_verify import verify_action_effect
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.transition import make_snapshot

from test_legal_actions import combat_raw
from h1b_fixtures import raw_state, selection_card


def _snapshot(normalizer: StateNormalizer, raw: dict, state_seq: int):
    observation = normalizer.normalize(raw, state_seq)
    legal = build_legal_actions(raw, observation)
    return (
        make_snapshot(
            state_seq=state_seq,
            raw=raw,
            observation=observation,
            legal_actions=legal.document,
        ),
        legal,
    )


def test_play_card_requires_the_selected_instance_to_leave_hand() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(iter(legal.native_actions.values()))
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["hand"] = after_raw["game_state"]["combat_state"]["hand"][1:]
    after_raw["game_state"]["combat_state"]["player"]["energy"] = 2
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["pre_location"] == "hand"
    assert proof["post_location"] != "hand"


def test_play_card_rejects_an_unrelated_state_change() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(iter(legal.native_actions.values()))
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["player"]["block"] = 1
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, _ = verify_action_effect(action, before, after)
    assert verified is False


def test_end_turn_requires_turn_advance_or_combat_end() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(value for value in legal.native_actions.values() if value.action_type == "end_turn")
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["turn"] = 2
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["post_turn"] == 2


def test_grid_selection_can_be_proven_by_entering_native_confirm_stage() -> None:
    selectable = selection_card()
    before_raw = raw_state(
        "GRID",
        screen_state={
            "cards": [selectable],
            "selected_cards": [],
            "num_cards": 1,
            "any_number": False,
            "for_upgrade": False,
            "for_transform": False,
            "for_purge": True,
            "confirm_up": False,
        },
        choices=["strike"],
        commands=["choose", "cancel", "state"],
    )
    after_raw = deepcopy(before_raw)
    after_raw["game_state"]["screen_state"]["confirm_up"] = True
    after_raw["game_state"]["choice_list"] = []
    after_raw["available_commands"] = ["confirm", "cancel", "state"]
    normalizer = StateNormalizer("ep_grid", "native_grid")
    before, legal = _snapshot(normalizer, before_raw, 1)
    after, _ = _snapshot(normalizer, after_raw, 2)
    action = next(value for value in legal.native_actions.values() if value.action_type == "remove_card")
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["entered_confirm_stage"] is True


def test_end_turn_accepts_explicit_terminal_even_with_stale_combat_export() -> None:
    normalizer = StateNormalizer("ep_terminal", "native_terminal")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(value for value in legal.native_actions.values() if value.action_type == "end_turn")
    terminal_raw = deepcopy(combat_raw())
    terminal_raw["game_state"]["screen_type"] = "GAME_OVER"
    terminal_raw["game_state"]["screen_name"] = "DEATH"
    terminal_raw["game_state"]["screen_state"] = {"score": 88, "victory": False}
    terminal_raw["game_state"]["is_screen_up"] = True
    terminal_raw["game_state"]["current_hp"] = 0
    terminal_raw["game_state"]["combat_state"]["player"]["current_hp"] = 0
    terminal_raw["available_commands"] = ["proceed", "state"]
    after, _ = _snapshot(normalizer, terminal_raw, 2)
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["combat_ended"] is True


def test_in_combat_card_reward_is_verified_in_hand_not_master_deck() -> None:
    reward_card = {
        **deepcopy(combat_raw()["game_state"]["deck"][1]),
        "id": "Inflame",
        "name": "Inflame",
        "uuid": "generated-inflame",
        "type": "POWER",
        "has_target": False,
    }
    before_raw = combat_raw()
    before_raw["game_state"]["screen_type"] = "CARD_REWARD"
    before_raw["game_state"]["screen_name"] = "CARD_REWARD"
    before_raw["game_state"]["screen_state"] = {
        "cards": [reward_card],
        "skip_available": False,
        "bowl_available": False,
    }
    before_raw["game_state"]["choice_list"] = ["inflame"]
    before_raw["available_commands"] = ["choose", "state"]
    after_raw = combat_raw()
    after_raw["game_state"]["combat_state"]["hand"].append(reward_card)
    normalizer = StateNormalizer("ep_reward", "native_reward")
    before, legal = _snapshot(normalizer, before_raw, 1)
    after, _ = _snapshot(normalizer, after_raw, 2)
    action = next(value for value in legal.native_actions.values() if value.action_type == "choose_option")
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["card_destination"] == "combat_hand"
