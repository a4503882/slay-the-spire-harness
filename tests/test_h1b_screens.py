from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_checkpoint import RUN_LOCAL_KEYS

from h1b_fixtures import card, potion, raw_state, relic, selection_card, with_full_potions


PROVENANCE = Path(__file__).parent / "fixtures" / "h1b" / "provenance.json"


def normalize(raw: dict):
    observation = StateNormalizer("ep_h1b", "native_h1b").normalize(raw, 1)
    legal = build_legal_actions(raw, observation)
    return observation, legal


def contains_run_local_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(key in RUN_LOCAL_KEYS or contains_run_local_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_run_local_key(item) for item in value)
    return False


def test_h1b_fixture_provenance_forbids_model_prompt_use() -> None:
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == "sts-fixture-provenance.v1"
    assert provenance["fairness_profile"] == "player_visible.v1"
    assert provenance["contains_raw_hidden_state"] is True
    assert "model prompts" in provenance["forbidden_uses"]
    assert provenance["contains_credentials"] is False


def test_main_menu_publishes_only_the_bounded_ironclad_a0_start_template() -> None:
    raw = {
        "bridge_version": "1.2.1-sts-harness.2",
        "protocol_version": "communicationmod-harness.v2",
        "available_commands": ["start", "state"],
        "ready_for_command": True,
        "in_game": False,
    }
    observation, legal = normalize(raw)

    assert observation["decision_kind"] == "main_menu"
    assert legal.document["actions"] == []
    assert legal.document["templates"] == [
        {
            "type": "start_run",
            "allowed_character_ids": ["IRONCLAD"],
            "minimum_ascension": 0,
            "maximum_ascension": 0,
            "seed_pattern": "^[A-Za-z0-9]+$",
        }
    ]


@pytest.mark.parametrize(
    ("raw", "kind", "action_types"),
    [
        (
            raw_state(
                "EVENT",
                screen_state={
                    "event_id": "Neow Event",
                    "event_name": "Neow",
                    "body_text": "Welcome",
                    "options": [{"text": "Talk", "label": "Talk", "disabled": False, "choice_index": 0}],
                },
                choices=["talk"],
            ),
            "neow",
            {"choose_option"},
        ),
        (
            raw_state(
                "EVENT",
                screen_state={
                    "event_id": "Big Fish",
                    "event_name": "Big Fish",
                    "body_text": "Choose",
                    "options": [{"text": "Banana", "label": "Banana", "disabled": False, "choice_index": 0}],
                },
                choices=["banana"],
                room_type="EventRoom",
                room_phase="EVENT",
            ),
            "event",
            {"choose_option"},
        ),
        (
            raw_state(
                "CARD_REWARD",
                screen_state={
                    "cards": [card("Inflame", "reward-inflame", card_type="POWER", target=False)],
                    "skip_available": True,
                    "bowl_available": False,
                },
                choices=["inflame"],
                commands=["choose", "skip", "state"],
            ),
            "card_reward",
            {"choose_option", "return_or_skip"},
        ),
        (
            raw_state(
                "COMBAT_REWARD",
                screen_state={"rewards": [{"reward_type": "GOLD", "gold": 15}, {"reward_type": "CARD"}]},
                choices=["gold", "card"],
                commands=["choose", "proceed", "state"],
            ),
            "combat_reward",
            {"choose_option", "proceed"},
        ),
        (
            raw_state(
                "MAP",
                screen_state={
                    "current_node": {"x": 1, "y": 4, "symbol": "M"},
                    "next_nodes": [{"x": 2, "y": 5, "symbol": "R"}],
                    "first_node_chosen": True,
                    "boss_available": False,
                },
                choices=["x=2"],
                commands=["choose", "return", "state"],
            ),
            "map",
            {"choose_map_node", "return_or_skip"},
        ),
        (
            raw_state("SHOP_ROOM", choices=["shop"], commands=["choose", "proceed", "state"], room_type="ShopRoom"),
            "shop",
            {"choose_option", "proceed"},
        ),
        (
            raw_state(
                "REST",
                screen_state={"has_rested": False, "rest_options": ["rest", "smith"]},
                choices=["rest", "smith"],
                commands=["choose", "state"],
                room_type="RestRoom",
            ),
            "rest",
            {"rest_site_action"},
        ),
        (
            raw_state(
                "CHEST",
                screen_state={"chest_type": "SmallChest", "chest_open": False},
                choices=["open"],
                commands=["choose", "proceed", "state"],
                room_type="TreasureRoom",
            ),
            "treasure",
            {"choose_option", "proceed"},
        ),
        (
            raw_state(
                "BOSS_REWARD",
                screen_state={"relics": [relic("Black Blood"), relic("Snecko Eye")]},
                choices=["black blood", "snecko eye"],
                commands=["choose", "skip", "state"],
            ),
            "boss_reward",
            {"choose_option", "return_or_skip"},
        ),
        (
            raw_state("COMPLETE", commands=["proceed", "state"]),
            "room_complete",
            {"proceed"},
        ),
    ],
)
def test_screen_kinds_publish_typed_actions(raw: dict, kind: str, action_types: set[str]) -> None:
    observation, legal = normalize(raw)
    assert observation["decision_kind"] == kind
    assert {action["type"] for action in legal.document["actions"]} == action_types
    assert all(not contains_run_local_key(action["selector"]) for action in legal.document["actions"])


def test_shop_inventory_has_affordable_typed_items_and_suppresses_full_potion_bug() -> None:
    raw = raw_state(
        "SHOP_SCREEN",
        screen_state={
            "cards": [card("Pommel Strike", "shop-card", price=50)],
            "relics": [relic("Bag of Marbles", price=150)],
            "potions": [potion("Fire Potion", price=40)],
            "purge_available": True,
            "purge_cost": 75,
        },
        choices=["purge", "pommel strike", "fire potion"],
        commands=["choose", "leave", "state"],
        room_type="ShopRoom",
    )
    observation, legal = normalize(raw)
    assert observation["screen"]["shop"]["phase"] == "inventory"
    assert [action["type"] for action in legal.document["actions"]] == [
        "choose_option",
        "buy_item",
        "buy_item",
        "return_or_skip",
    ]
    assert [native.command for native in legal.native_actions.values()] == [
        "choose 0",
        "choose 1",
        "choose 2",
        "return",
    ]

    _, full_legal = normalize(with_full_potions(raw))
    assert all(
        action.get("selector", {}).get("item_kind") != "potion"
        for action in full_legal.document["actions"]
    )


def test_full_potion_inventory_suppresses_silent_combat_reward_take() -> None:
    raw = raw_state(
        "COMBAT_REWARD",
        screen_state={
            "rewards": [
                {"reward_type": "POTION", "potion": potion("Fire Potion")},
                {"reward_type": "CARD"},
            ]
        },
        choices=["potion", "card"],
        commands=["choose", "proceed", "state"],
    )
    _, legal = normalize(with_full_potions(raw))
    reward_actions = [
        action
        for action in legal.document["actions"]
        if action.get("selector", {}).get("semantic") == "claim_reward"
    ]
    assert [action["selector"]["reward_type"] for action in reward_actions] == ["CARD"]
    assert legal.native_actions[reward_actions[0]["action_id"]].command == "choose 1"


def test_grid_and_hand_selection_publish_card_semantics_and_confirm() -> None:
    selectable = selection_card()
    grid = raw_state(
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
    observation, legal = normalize(grid)
    assert observation["screen"]["selection"]["mode"] == "remove"
    assert legal.document["actions"][0]["type"] == "remove_card"

    confirm_grid = deepcopy(grid)
    confirm_grid["game_state"]["screen_state"]["selected_cards"] = [selectable]
    confirm_grid["game_state"]["screen_state"]["confirm_up"] = True
    confirm_grid["game_state"]["choice_list"] = []
    confirm_grid["available_commands"] = ["confirm", "cancel", "state"]
    _, confirm_legal = normalize(confirm_grid)
    assert confirm_legal.document["actions"][0]["type"] == "select_cards"
    assert confirm_legal.document["actions"][0]["payload"]["confirm"] is True

    hand = raw_state(
        "HAND_SELECT",
        screen_state={"hand": [selectable], "selected": [], "max_cards": 1, "can_pick_zero": False},
        choices=["strike"],
        commands=["choose", "state"],
        room_phase="COMBAT",
    )
    hand_observation, hand_legal = normalize(hand)
    assert hand_observation["decision_kind"] == "hand_select"
    assert hand_legal.document["actions"][0]["type"] == "select_cards"


@pytest.mark.parametrize(("victory", "kind", "outcome"), [(False, "game_over", "DEFEAT_COMBAT"), (True, "victory", "VICTORY_ACT3")])
def test_terminal_states_publish_no_policy_action(victory: bool, kind: str, outcome: str | None) -> None:
    raw = raw_state(
        "GAME_OVER",
        screen_state={"score": 123, "victory": victory},
        commands=["proceed", "state"],
    )
    if victory:
        raw["game_state"]["act"] = 3
    observation, legal = normalize(raw)
    assert observation["decision_kind"] == kind
    assert observation["ready_for_action"] is False
    assert legal.document["actions"] == []
    assert observation["run"]["outcome"] == outcome


def test_unknown_actionable_screen_is_an_explicit_hard_stop() -> None:
    raw = raw_state("MYSTERY_SCREEN", choices=["mystery"], commands=["choose", "state"])
    observation, legal = normalize(raw)
    assert observation["decision_kind"] == "unsupported"
    assert observation["ready_for_action"] is False
    assert legal.document["actions"] == []


def test_combat_fixture_covers_multiple_monsters_card_variants_and_potions() -> None:
    whirlwind = card("Whirlwind", "hand-x", target=False)
    whirlwind.update({"cost": -1, "base_cost": -1, "cost_for_turn": -1, "damage": 5})
    unplayable = card("Clash", "hand-unplayable")
    unplayable["is_playable"] = False
    generated = card("Shiv", "hand-generated")
    generated.update({"cost": 0, "base_cost": 0, "cost_for_turn": 0, "purge_on_use": True})
    retained = card("Warcry", "hand-retained", card_type="SKILL", target=False)
    retained.update({"cost": 0, "base_cost": 0, "cost_for_turn": 0, "retain": True})
    temporary_cost = card("Bash", "hand-temporary")
    temporary_cost.update({"cost": 2, "base_cost": 2, "cost_for_turn": 0, "damage": 8})
    exhausted = card("Shockwave", "exhausted", card_type="SKILL", target=False)
    exhausted["exhausts"] = True
    raw = raw_state(
        "NONE",
        commands=["play", "potion", "end", "state"],
        room_phase="COMBAT",
    )
    raw["game_state"]["deck"] = [whirlwind, unplayable, retained, temporary_cost, exhausted]
    raw["game_state"]["potions"] = [
        potion("Fire Potion"),
        potion("Strength Potion"),
        potion(),
    ]
    raw["game_state"]["combat_state"] = {
        "turn": 3,
        "hand": [whirlwind, unplayable, generated, retained, temporary_cost],
        "draw_pile": [temporary_cost, whirlwind],
        "discard_pile": [],
        "exhaust_pile": [exhausted],
        "limbo": [],
        "player": {"current_hp": 60, "max_hp": 80, "block": 0, "energy": 3, "powers": [], "orbs": []},
        "monsters": [
            {
                "id": "Louse",
                "name": "Red Louse",
                "current_hp": 12,
                "max_hp": 12,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 7,
                "move_hits": 1,
                "powers": [],
            },
            {
                "id": "Louse",
                "name": "Green Louse",
                "current_hp": 11,
                "max_hp": 11,
                "block": 0,
                "is_gone": False,
                "intent": "BUFF",
                "move_adjusted_damage": -1,
                "move_hits": 1,
                "powers": [],
            },
        ],
    }

    observation, legal = normalize(raw)
    actions = legal.document["actions"]

    assert len(observation["combat"]["monsters"]) == 2
    assert observation["combat"]["draw_pile"]["order_hidden"] is True
    assert observation["combat"]["exhaust_pile"][0]["card_id"] == "Shockwave"
    hand = {row["card_id"]: row for row in observation["combat"]["hand"]}
    assert hand["Whirlwind"]["cost_for_turn"] == -1
    assert hand["Bash"]["base_cost"] == 2 and hand["Bash"]["cost_for_turn"] == 0
    assert hand["Warcry"]["retain"] is True
    assert hand["Shiv"]["purge_on_use"] is True
    assert not any(
        action.get("selector", {}).get("card", {}).get("card_id") == "Clash"
        for action in actions
    )
    assert sum(
        action["type"] == "play_card"
        and action.get("selector", {}).get("card", {}).get("card_id") == "Whirlwind"
        for action in actions
    ) == 1
    assert sum(
        action["type"] == "play_card"
        and action.get("selector", {}).get("card", {}).get("card_id") == "Shiv"
        for action in actions
    ) == 2
    assert sum(
        action["type"] == "use_potion"
        and action.get("selector", {}).get("potion_id") == "Fire Potion"
        for action in actions
    ) == 2
    assert sum(
        action["type"] == "use_potion"
        and action.get("selector", {}).get("potion_id") == "Strength Potion"
        for action in actions
    ) == 1
    assert sum(action["type"] == "discard_potion" for action in actions) == 2


def test_any_number_grid_exposes_selection_and_zero_card_confirm() -> None:
    selectable = selection_card()
    raw = raw_state(
        "GRID",
        screen_state={
            "cards": [selectable],
            "selected_cards": [],
            "num_cards": 3,
            "any_number": True,
            "for_upgrade": False,
            "for_transform": True,
            "for_purge": False,
            "confirm_up": False,
        },
        choices=["strike"],
        commands=["choose", "confirm", "cancel", "state"],
    )
    observation, legal = normalize(raw)

    assert observation["screen"]["selection"]["any_number"] is True
    assert observation["screen"]["selection"]["mode"] == "transform"
    assert {action["type"] for action in legal.document["actions"]} == {
        "select_cards",
        "return_or_skip",
    }
    assert any(
        action["type"] == "select_cards" and action["payload"].get("confirm") is True
        for action in legal.document["actions"]
    )
