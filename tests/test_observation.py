from __future__ import annotations

from copy import deepcopy

from sts_harness.observation import StateNormalizer


def raw_combat_state() -> dict:
    strike = {
        "id": "Strike_R",
        "name": "打击",
        "uuid": "raw-strike",
        "cost": 1,
        "upgrades": 0,
        "type": "ATTACK",
        "rarity": "BASIC",
        "is_playable": True,
        "has_target": True,
        "exhausts": False,
        "ethereal": False,
    }
    defend = {
        "id": "Defend_R",
        "name": "防御",
        "uuid": "raw-defend",
        "cost": 1,
        "upgrades": 0,
        "type": "SKILL",
        "rarity": "BASIC",
        "is_playable": True,
        "has_target": False,
        "exhausts": False,
        "ethereal": False,
    }
    return {
        "bridge_version": "1.2.1-sts-harness.1",
        "protocol_version": "communicationmod-harness.v1",
        "available_commands": ["play", "end", "key", "click", "wait", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "seed": 123456789,
            "screen_name": "NONE",
            "screen_type": "NONE",
            "screen_state": {},
            "is_screen_up": False,
            "room_phase": "COMBAT",
            "room_type": "MonsterRoom",
            "class": "IRONCLAD",
            "ascension_level": 0,
            "act": 1,
            "floor": 1,
            "current_hp": 80,
            "max_hp": 80,
            "gold": 99,
            "act_boss": "The Guardian",
            "keys": {"ruby": False, "emerald": False, "sapphire": False},
            "deck": [strike, defend],
            "relics": [{"id": "Burning Blood", "name": "燃烧之血", "counter": -1}],
            "potions": [
                {
                    "id": "Potion Slot",
                    "name": "药水栏位",
                    "can_use": False,
                    "can_discard": False,
                    "requires_target": False,
                }
            ],
            "map": [
                {
                    "x": 0,
                    "y": 0,
                    "symbol": "M",
                    "parents": [],
                    "children": [{"x": 1, "y": 1}],
                }
            ],
            "combat_state": {
                "turn": 1,
                "cards_discarded_this_turn": 0,
                "times_damaged": 0,
                "hand": [strike, defend],
                "draw_pile": [defend, strike],
                "discard_pile": [],
                "exhaust_pile": [],
                "limbo": [],
                "player": {
                    "current_hp": 80,
                    "max_hp": 80,
                    "block": 0,
                    "energy": 3,
                    "powers": [],
                    "orbs": [],
                },
                "monsters": [
                    {
                        "id": "JawWorm",
                        "name": "大颚虫",
                        "current_hp": 40,
                        "max_hp": 40,
                        "block": 0,
                        "intent": "ATTACK",
                        "move_base_damage": 11,
                        "move_adjusted_damage": 11,
                        "move_hits": 1,
                        "last_move_id": 7,
                        "second_last_move_id": 6,
                        "half_dead": False,
                        "is_gone": False,
                        "powers": [],
                    }
                ],
            },
        },
    }


def test_player_visible_projection_hides_seed_uuid_draw_order_and_move_history() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    observation = normalizer.normalize(raw_combat_state(), 1)
    serialized = repr(observation)
    assert "123456789" not in serialized
    assert "raw-strike" not in serialized
    assert "last_move_id" not in serialized
    assert observation["combat"]["draw_pile"] == {
        "count": 2,
        "cards": [
            {
                "card_id": "Defend_R",
                "name": "防御",
                "upgrades": 0,
                "cost": 1,
                "type": "SKILL",
                "rarity": "BASIC",
                "exhausts": False,
                "ethereal": False,
                "count": 1,
            },
            {
                "card_id": "Strike_R",
                "name": "打击",
                "upgrades": 0,
                "cost": 1,
                "type": "ATTACK",
                "rarity": "BASIC",
                "exhausts": False,
                "ethereal": False,
                "count": 1,
            },
        ],
        "order_hidden": True,
    }


def test_card_and_monster_handles_are_stable_across_states() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    first = normalizer.normalize(raw_combat_state(), 1)
    changed = deepcopy(raw_combat_state())
    changed["game_state"]["combat_state"]["player"]["energy"] = 2
    second = normalizer.normalize(changed, 2)
    assert first["combat"]["hand"][0]["card_instance_id"] == second["combat"]["hand"][0]["card_instance_id"]
    assert first["combat"]["monsters"][0]["target_id"] == second["combat"]["monsters"][0]["target_id"]


def test_draw_pile_hash_does_not_change_when_only_hidden_order_changes() -> None:
    first_raw = raw_combat_state()
    second_raw = deepcopy(first_raw)
    second_raw["game_state"]["combat_state"]["draw_pile"].reverse()
    first = StateNormalizer("ep_test", "native_test").normalize(first_raw, 1)
    second = StateNormalizer("ep_test", "native_test").normalize(second_raw, 1)
    assert first["combat"]["draw_pile"] == second["combat"]["draw_pile"]
    assert first["observation_hash"] == second["observation_hash"]


def test_observation_contains_no_raw_available_commands() -> None:
    observation = StateNormalizer("ep_test", "native_test").normalize(raw_combat_state(), 1)
    assert "available_commands" not in observation
    assert observation["decision_kind"] == "combat"
    assert observation["ready_for_action"] is True

