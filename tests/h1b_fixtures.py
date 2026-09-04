from __future__ import annotations

from copy import deepcopy
from typing import Any


def card(
    card_id: str,
    uuid: str,
    *,
    card_type: str = "ATTACK",
    target: bool = True,
    price: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": card_id,
        "name": card_id,
        "uuid": uuid,
        "misc": 0,
        "cost": 1,
        "base_cost": 1,
        "cost_for_turn": 1,
        "damage": 6 if card_type == "ATTACK" else 0,
        "block": 5 if card_type == "SKILL" else 0,
        "magic_number": 0,
        "upgrades": 0,
        "type": card_type,
        "rarity": "COMMON",
        "is_playable": True,
        "has_target": target,
        "exhausts": False,
        "ethereal": False,
        "retain": False,
        "self_retain": False,
        "free_to_play_once": False,
        "purge_on_use": False,
        "description": f"Visible description for {card_id}",
    }
    if price is not None:
        result["price"] = price
    return result


def potion(potion_id: str = "Potion Slot", *, price: int | None = None) -> dict[str, Any]:
    empty = potion_id == "Potion Slot"
    result: dict[str, Any] = {
        "id": potion_id,
        "name": potion_id,
        "can_use": not empty,
        "can_discard": not empty,
        "requires_target": potion_id == "Fire Potion",
        "description": "Visible potion description",
    }
    if price is not None:
        result["price"] = price
    return result


def relic(relic_id: str, *, price: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": relic_id,
        "name": relic_id,
        "counter": -1,
        "description": "Visible relic description",
    }
    if price is not None:
        result["price"] = price
    return result


def raw_state(
    screen_type: str,
    *,
    screen_state: dict[str, Any] | None = None,
    choices: list[str] | None = None,
    commands: list[str] | None = None,
    room_type: str = "MonsterRoom",
    room_phase: str = "COMPLETE",
) -> dict[str, Any]:
    strike = card("Strike_R", "deck-strike")
    defend = card("Defend_R", "deck-defend", card_type="SKILL", target=False)
    return {
        "bridge_version": "1.2.1-sts-harness.2",
        "protocol_version": "communicationmod-harness.v2",
        "available_commands": commands or ["choose", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "seed": 123456,
            "screen_name": screen_type,
            "screen_type": screen_type,
            "screen_state": screen_state or {},
            "choice_list": choices or [],
            "is_screen_up": screen_type not in {"NONE", "COMPLETE", "SHOP_ROOM", "REST", "CHEST"},
            "room_phase": room_phase,
            "room_type": room_type,
            "class": "IRONCLAD",
            "ascension_level": 0,
            "act": 1,
            "floor": 5,
            "current_hp": 55,
            "max_hp": 80,
            "gold": 99,
            "act_boss": "Slime Boss",
            "keys": {"ruby": False, "emerald": False, "sapphire": False},
            "deck": [strike, defend],
            "relics": [relic("Burning Blood")],
            "potions": [potion(), potion(), potion()],
            "map": [
                {
                    "x": 1,
                    "y": 4,
                    "symbol": "M",
                    "parents": [{"x": 0, "y": 3}],
                    "children": [{"x": 2, "y": 5}],
                }
            ],
        },
    }


def selection_card() -> dict[str, Any]:
    return card("Strike_R", "selection-strike")


def with_full_potions(raw: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(raw)
    result["game_state"]["potions"] = [
        potion("Fire Potion"),
        potion("Strength Potion"),
        potion("Block Potion"),
    ]
    return result
