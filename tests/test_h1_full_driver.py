from __future__ import annotations

from sts_harness.h1_full_driver import ScriptedFullRunPolicy
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer

from h1b_fixtures import card, raw_state, relic


def transition(raw: dict) -> dict:
    observation = StateNormalizer("ep_policy", "native_policy").normalize(raw, 1)
    legal = build_legal_actions(raw, observation).document
    return {"observation": observation, "legal_actions": legal}


def test_shop_room_is_entered_once_then_proceeded() -> None:
    raw = raw_state(
        "SHOP_ROOM",
        choices=["shop"],
        commands=["choose", "proceed", "state"],
        room_type="ShopRoom",
    )
    state = transition(raw)
    policy = ScriptedFullRunPolicy()
    assert policy.choose(state)["type"] == "choose_option"
    assert policy.choose(state)["type"] == "proceed"


def test_combat_reward_claims_before_proceeding() -> None:
    raw = raw_state(
        "COMBAT_REWARD",
        screen_state={"rewards": [{"reward_type": "GOLD", "gold": 15}]},
        choices=["gold"],
        commands=["choose", "proceed", "state"],
    )
    selected = ScriptedFullRunPolicy().choose(transition(raw))
    assert selected["selector"]["semantic"] == "claim_reward"
    assert selected["selector"]["reward_type"] == "GOLD"


def test_combat_policy_values_aoe_across_live_monsters() -> None:
    cleave = card("Cleave", "hand-cleave", target=False)
    cleave["damage"] = 8
    defend = card("Defend_R", "hand-defend", card_type="SKILL", target=False)
    defend["block"] = 5
    raw = raw_state(
        "NONE",
        commands=["play", "end", "state"],
        room_phase="COMBAT",
    )
    raw["game_state"]["combat_state"] = {
        "turn": 8,
        "hand": [cleave, defend],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {"current_hp": 40, "max_hp": 80, "block": 0, "energy": 1, "powers": [], "orbs": []},
        "monsters": [
            {
                "id": "SpikeSlime_M",
                "name": "Spike Slime",
                "current_hp": 9,
                "max_hp": 28,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 10,
                "move_hits": 1,
                "powers": [],
            },
            {
                "id": "AcidSlime_M",
                "name": "Acid Slime",
                "current_hp": 5,
                "max_hp": 28,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 10,
                "move_hits": 1,
                "powers": [],
            },
            {
                "id": "AcidSlime_L",
                "name": "Acid Slime",
                "current_hp": 38,
                "max_hp": 68,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 18,
                "move_hits": 1,
                "powers": [],
            },
        ],
    }

    selected = ScriptedFullRunPolicy().choose(transition(raw))

    assert selected["type"] == "play_card"
    assert selected["selector"]["card"]["card_id"] == "Cleave"


def test_card_reward_policy_takes_metallicize() -> None:
    raw = raw_state(
        "CARD_REWARD",
        screen_state={
            "cards": [
                card("Combust", "reward-combust", card_type="POWER", target=False),
                card("Brutality", "reward-brutality", card_type="POWER", target=False),
                card("Metallicize", "reward-metallicize", card_type="POWER", target=False),
            ],
            "bowl_available": False,
        },
        choices=["combust", "brutality", "metallicize"],
        commands=["choose", "skip", "state"],
    )

    selected = ScriptedFullRunPolicy().choose(transition(raw))

    assert selected["selector"]["card"]["card_id"] == "Metallicize"


def test_shop_policy_prefers_relevant_relic_over_cheapest_relic() -> None:
    raw = raw_state(
        "SHOP_SCREEN",
        screen_state={
            "cards": [card("Pommel Strike", "shop-pommel", price=54)],
            "relics": [relic("Red Skull", price=154), relic("Chemical X", price=146)],
            "potions": [],
            "purge_available": False,
            "purge_cost": 75,
        },
        choices=["pommel strike", "red skull", "chemical x"],
        commands=["choose", "leave", "state"],
        room_type="ShopRoom",
    )
    raw["game_state"]["gold"] = 250

    selected = ScriptedFullRunPolicy().choose(transition(raw))

    assert selected["type"] == "buy_item"
    assert selected["selector"]["item"]["item_id"] == "Red Skull"


def test_post_coverage_act2_combat_uses_native_end_turn_terminal_strategy() -> None:
    strike = card("Strike_R", "act2-strike", target=True)
    raw = raw_state(
        "NONE",
        commands=["play", "end", "state"],
        room_phase="COMBAT",
    )
    raw["game_state"]["act"] = 2
    raw["game_state"]["floor"] = 18
    raw["game_state"]["combat_state"] = {
        "turn": 1,
        "hand": [strike],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3, "powers": [], "orbs": []},
        "monsters": [
            {
                "id": "Shelled Parasite",
                "name": "Shelled Parasite",
                "current_hp": 51,
                "max_hp": 51,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 12,
                "move_hits": 1,
                "powers": [],
            }
        ],
    }
    policy = ScriptedFullRunPolicy()
    policy.boss_reward_taken = True

    selected = policy.choose(transition(raw))

    assert selected["type"] == "end_turn"
