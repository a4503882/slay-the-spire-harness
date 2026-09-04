from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .canonical import sha256_document


BRIDGE_VERSION = "1.2.1-sts-harness.2"
BRIDGE_PROTOCOL_VERSION = "communicationmod-harness.v2"
SUPPORTED_BRIDGE_PROTOCOLS = {
    ("1.2.1-sts-harness.1", "communicationmod-harness.v1"),
    (BRIDGE_VERSION, BRIDGE_PROTOCOL_VERSION),
}
OBSERVATION_SCHEMA_VERSION = "sts-observation.v1"
FAIRNESS_PROFILE = "player_visible.v1"


class NormalizationFailure(ValueError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in _list(value) if isinstance(row, dict)]


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _clean_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return cleaned[:48] or "unknown"


@dataclass
class IdentityRegistry:
    episode_id: str
    native_session_id: str
    run_id: str | None = None
    room_id: str | None = None
    combat_id: str | None = None
    room_key: tuple[Any, ...] | None = None
    card_ids: dict[str, str] = field(default_factory=dict)
    monster_ids: dict[tuple[str, int], str] = field(default_factory=dict)
    next_card: int = 1
    next_room: int = 1
    next_combat: int = 1

    def update(self, raw: dict[str, Any]) -> None:
        if raw.get("in_game") is not True:
            return
        game = _dict(raw.get("game_state"))
        if self.run_id is None:
            self.run_id = f"run_{self.episode_id.removeprefix('ep_')}"
        key = (
            _integer(game.get("act")),
            _integer(game.get("floor")),
            _string(game.get("room_type")),
        )
        if key != self.room_key:
            self.room_key = key
            self.room_id = f"room_{self.next_room:04d}"
            self.next_room += 1
            self.combat_id = None
            self.monster_ids.clear()
        combat = _dict(game.get("combat_state"))
        if combat and self.combat_id is None:
            self.combat_id = f"combat_{self.next_combat:04d}"
            self.next_combat += 1

    def card_id(self, raw_uuid: Any) -> str:
        if not isinstance(raw_uuid, str) or not raw_uuid:
            raise NormalizationFailure("card instance has no raw UUID")
        existing = self.card_ids.get(raw_uuid)
        if existing is not None:
            return existing
        value = f"card_{self.next_card:05d}"
        self.next_card += 1
        self.card_ids[raw_uuid] = value
        return value

    def monster_id(self, native_id: str, index: int) -> str:
        if self.combat_id is None:
            raise NormalizationFailure("monster observed outside a combat identity")
        key = (native_id, index)
        existing = self.monster_ids.get(key)
        if existing is not None:
            return existing
        value = f"{self.combat_id}_monster_{index:02d}_{_slug(native_id)}"
        self.monster_ids[key] = value
        return value


class StateNormalizer:
    def __init__(self, episode_id: str, native_session_id: str) -> None:
        self.identities = IdentityRegistry(episode_id, native_session_id)

    @property
    def episode_id(self) -> str:
        return self.identities.episode_id

    @property
    def native_session_id(self) -> str:
        return self.identities.native_session_id

    def _card(self, value: Any, *, include_instance: bool = True) -> dict[str, Any]:
        row = _dict(value)
        result = _clean_none(
            {
                "card_id": _string(row.get("id")),
                "name": _string(row.get("name")),
                "upgrades": _integer(row.get("upgrades")),
                "misc": _integer(row.get("misc")),
                "cost": _integer(row.get("cost")),
                "base_cost": _integer(row.get("base_cost")),
                "cost_for_turn": _integer(row.get("cost_for_turn")),
                "damage": _integer(row.get("damage")),
                "block": _integer(row.get("block")),
                "magic_number": _integer(row.get("magic_number")),
                "type": _string(row.get("type")),
                "rarity": _string(row.get("rarity")),
                "is_playable": _boolean(row.get("is_playable")),
                "requires_target": _boolean(row.get("has_target")),
                "exhausts": _boolean(row.get("exhausts")),
                "ethereal": _boolean(row.get("ethereal")),
                "retain": _boolean(row.get("retain")),
                "self_retain": _boolean(row.get("self_retain")),
                "free_to_play_once": _boolean(row.get("free_to_play_once")),
                "purge_on_use": _boolean(row.get("purge_on_use")),
                "description": _string(row.get("description")),
                "price": _integer(row.get("price")),
            }
        )
        if include_instance:
            result["card_instance_id"] = self.identities.card_id(row.get("uuid"))
        return result

    def _power(self, value: Any) -> dict[str, Any]:
        row = _dict(value)
        result = _clean_none(
            {
                "power_id": _string(row.get("id")),
                "name": _string(row.get("name")),
                "amount": _integer(row.get("amount")),
                "damage": _integer(row.get("damage")),
                "misc": _integer(row.get("misc")),
                "just_applied": _boolean(row.get("just_applied")),
            }
        )
        if isinstance(row.get("card"), dict):
            result["card"] = self._card(row["card"])
        return result

    def _relic(self, value: Any) -> dict[str, Any]:
        row = _dict(value)
        return _clean_none(
            {
                "relic_id": _string(row.get("id")),
                "name": _string(row.get("name")),
                "counter": _integer(row.get("counter")),
                "description": _string(row.get("description")),
                "price": _integer(row.get("price")),
            }
        )

    def _potion(self, value: Any, index: int) -> dict[str, Any]:
        row = _dict(value)
        return _clean_none(
            {
                "potion_slot_id": f"potion_slot_{index}",
                "potion_id": _string(row.get("id")),
                "name": _string(row.get("name")),
                "can_use": _boolean(row.get("can_use")),
                "can_discard": _boolean(row.get("can_discard")),
                "requires_target": _boolean(row.get("requires_target")),
                "description": _string(row.get("description")),
                "price": _integer(row.get("price")),
            }
        )

    def _node(self, value: Any) -> dict[str, Any]:
        row = _dict(value)
        x = _integer(row.get("x"))
        y = _integer(row.get("y"))
        if x is None or y is None:
            raise NormalizationFailure("map node has no integer coordinates")
        result: dict[str, Any] = {
            "map_node_id": f"node_{x}_{y}",
            "x": x,
            "y": y,
        }
        if isinstance(row.get("symbol"), str):
            result["symbol"] = row["symbol"]
        for edge_name in ("parents", "children"):
            if isinstance(row.get(edge_name), list):
                edges = [self._node(edge) for edge in _rows(row[edge_name])]
                result[edge_name] = sorted(edges, key=lambda edge: (edge["y"], edge["x"]))
        return result

    def _draw_pile(self, value: Any) -> dict[str, Any]:
        normalized = [self._card(card, include_instance=False) for card in _rows(value)]
        counts: Counter[tuple[Any, ...]] = Counter()
        samples: dict[tuple[Any, ...], dict[str, Any]] = {}
        fields = (
            "card_id",
            "name",
            "upgrades",
            "misc",
            "cost",
            "base_cost",
            "cost_for_turn",
            "damage",
            "block",
            "magic_number",
            "type",
            "rarity",
            "exhausts",
            "ethereal",
            "retain",
            "self_retain",
            "free_to_play_once",
            "purge_on_use",
        )
        for card in normalized:
            key = tuple(card.get(field) for field in fields)
            counts[key] += 1
            samples[key] = {field: card[field] for field in fields if field in card}
        rows = []
        for key in sorted(counts, key=lambda item: tuple("" if part is None else str(part) for part in item)):
            row = dict(samples[key])
            row["count"] = counts[key]
            rows.append(row)
        return {"count": len(normalized), "cards": rows, "order_hidden": True}

    def _monster(self, value: Any, index: int) -> dict[str, Any]:
        row = _dict(value)
        native_id = _string(row.get("id")) or "unknown"
        result = _clean_none(
            {
                "target_id": self.identities.monster_id(native_id, index),
                "monster_id": native_id,
                "name": _string(row.get("name")),
                "current_hp": _integer(row.get("current_hp")),
                "max_hp": _integer(row.get("max_hp")),
                "block": _integer(row.get("block")),
                "intent": _string(row.get("intent")),
                "move_base_damage": _integer(row.get("move_base_damage")),
                "move_adjusted_damage": _integer(row.get("move_adjusted_damage")),
                "move_hits": _integer(row.get("move_hits")),
                "half_dead": _boolean(row.get("half_dead")),
                "is_gone": _boolean(row.get("is_gone")),
            }
        )
        result["powers"] = [self._power(power) for power in _rows(row.get("powers"))]
        return result

    def _player(self, value: Any) -> dict[str, Any]:
        row = _dict(value)
        result = _clean_none(
            {
                "current_hp": _integer(row.get("current_hp")),
                "max_hp": _integer(row.get("max_hp")),
                "block": _integer(row.get("block")),
                "energy": _integer(row.get("energy")),
            }
        )
        result["powers"] = [self._power(power) for power in _rows(row.get("powers"))]
        result["orbs"] = [
            _clean_none(
                {
                    "orb_id": _string(orb.get("id")),
                    "name": _string(orb.get("name")),
                    "evoke_amount": _integer(orb.get("evoke_amount")),
                    "passive_amount": _integer(orb.get("passive_amount")),
                }
            )
            for orb in _rows(row.get("orbs"))
        ]
        return result

    @staticmethod
    def _decision_kind(raw: dict[str, Any], game: dict[str, Any]) -> str:
        if raw.get("in_game") is not True:
            return "main_menu"
        screen_type = str(game.get("screen_type", "NONE")).upper()
        screen_state = _dict(game.get("screen_state"))
        mapping = {
            "CHEST": "treasure",
            "SHOP_ROOM": "shop",
            "REST": "rest",
            "CARD_REWARD": "card_reward",
            "COMBAT_REWARD": "combat_reward",
            "MAP": "map",
            "BOSS_REWARD": "boss_reward",
            "SHOP_SCREEN": "shop",
            "GRID": "grid_select",
            "HAND_SELECT": "hand_select",
            "GAME_OVER": "victory" if screen_state.get("victory") is True else "game_over",
            "COMPLETE": "room_complete",
        }
        if screen_type == "EVENT":
            return "neow" if screen_state.get("event_id") == "Neow Event" else "event"
        if screen_type in mapping:
            return mapping[screen_type]
        if screen_type == "NONE" and str(game.get("room_phase", "")).upper() == "COMBAT":
            return "combat"
        if screen_type == "NONE" and str(game.get("room_phase", "")).upper() == "COMPLETE":
            return "combat_reward"
        return "unsupported"

    def _screen(
        self,
        game: dict[str, Any],
        decision_id: str,
        decision_kind: str,
    ) -> dict[str, Any]:
        screen_state = _dict(game.get("screen_state"))
        result: dict[str, Any] = _clean_none(
            {
                "decision_kind": decision_kind,
                "native_screen_type": _string(game.get("screen_type")),
                "native_screen_name": _string(game.get("screen_name")),
                "is_screen_up": _boolean(game.get("is_screen_up")),
                "room_phase": _string(game.get("room_phase")),
                "room_type": _string(game.get("room_type")),
            }
        )
        choice_list = [choice for choice in _list(game.get("choice_list")) if isinstance(choice, str)]
        result["choices"] = [
            {
                "choice_id": f"{decision_id}_choice_{index:02d}",
                "choice_index": index,
                "label": choice,
            }
            for index, choice in enumerate(choice_list)
        ]
        if decision_kind in {"neow", "event"}:
            result["event"] = {
                "event_id": _string(screen_state.get("event_id")),
                "event_name": _string(screen_state.get("event_name")),
                "body_text": _string(screen_state.get("body_text")) or "",
                "options": [
                    _clean_none(
                        {
                            "choice_id": (
                                f"{decision_id}_choice_{option['choice_index']:02d}"
                                if isinstance(option.get("choice_index"), int)
                                else None
                            ),
                            "choice_index": _integer(option.get("choice_index")),
                            "label": _string(option.get("label")),
                            "text": _string(option.get("text")),
                            "disabled": _boolean(option.get("disabled")),
                        }
                    )
                    for option in _rows(screen_state.get("options"))
                ],
            }
        elif decision_kind == "map":
            next_nodes = [self._node(node) for node in _rows(screen_state.get("next_nodes"))]
            result["map_choice"] = {
                "current_node": (
                    self._node(screen_state["current_node"])
                    if isinstance(screen_state.get("current_node"), dict)
                    else None
                ),
                "next_nodes": next_nodes,
                "first_node_chosen": _boolean(screen_state.get("first_node_chosen")),
                "boss_available": _boolean(screen_state.get("boss_available")),
            }
        elif decision_kind == "card_reward":
            cards = [self._card(card) for card in _rows(screen_state.get("cards"))]
            result["card_reward"] = {
                "cards": [
                    {**card, "choice_id": f"{decision_id}_choice_{index:02d}"}
                    for index, card in enumerate(cards)
                ],
                "skip_available": _boolean(screen_state.get("skip_available")),
                "bowl_available": _boolean(screen_state.get("bowl_available")),
            }
        elif decision_kind == "combat_reward":
            rewards: list[dict[str, Any]] = []
            for index, raw_reward in enumerate(_rows(screen_state.get("rewards"))):
                reward = _clean_none(
                    {
                        "reward_id": f"{decision_id}_reward_{index:02d}",
                        "choice_id": f"{decision_id}_choice_{index:02d}",
                        "reward_type": _string(raw_reward.get("reward_type")),
                        "gold": _integer(raw_reward.get("gold")),
                    }
                )
                if isinstance(raw_reward.get("relic"), dict):
                    reward["relic"] = self._relic(raw_reward["relic"])
                if isinstance(raw_reward.get("potion"), dict):
                    reward["potion"] = self._potion(raw_reward["potion"], index)
                if isinstance(raw_reward.get("link"), dict):
                    reward["linked_relic"] = self._relic(raw_reward["link"])
                rewards.append(reward)
            result["combat_reward"] = {"rewards": rewards}
        elif decision_kind == "boss_reward":
            result["boss_reward"] = {
                "relics": [
                    {
                        **self._relic(relic),
                        "choice_id": f"{decision_id}_choice_{index:02d}",
                    }
                    for index, relic in enumerate(_rows(screen_state.get("relics")))
                ]
            }
        elif decision_kind == "shop":
            phase = "inventory" if str(game.get("screen_type", "")).upper() == "SHOP_SCREEN" else "entrance"
            shop: dict[str, Any] = {"phase": phase}
            if phase == "inventory":
                shop.update(
                    {
                        "cards": [
                            {
                                **self._card(card),
                                "shop_item_id": f"{decision_id}_shop_card_{index:02d}",
                            }
                            for index, card in enumerate(_rows(screen_state.get("cards")))
                        ],
                        "relics": [
                            {
                                **self._relic(relic),
                                "shop_item_id": f"{decision_id}_shop_relic_{index:02d}",
                            }
                            for index, relic in enumerate(_rows(screen_state.get("relics")))
                        ],
                        "potions": [
                            {
                                **self._potion(potion, index),
                                "shop_item_id": f"{decision_id}_shop_potion_{index:02d}",
                            }
                            for index, potion in enumerate(_rows(screen_state.get("potions")))
                        ],
                        "purge_available": _boolean(screen_state.get("purge_available")),
                        "purge_cost": _integer(screen_state.get("purge_cost")),
                    }
                )
            result["shop"] = shop
        elif decision_kind == "rest":
            result["rest"] = {
                "has_rested": _boolean(screen_state.get("has_rested")),
                "actions": [
                    {
                        "rest_action_id": f"rest_{_slug(name)}",
                        "native_index": index,
                        "name": name,
                    }
                    for index, name in enumerate(
                        item for item in _list(screen_state.get("rest_options")) if isinstance(item, str)
                    )
                ],
            }
        elif decision_kind == "treasure":
            result["treasure"] = _clean_none(
                {
                    "chest_type": _string(screen_state.get("chest_type")),
                    "chest_open": _boolean(screen_state.get("chest_open")),
                }
            )
        elif decision_kind in {"grid_select", "hand_select"}:
            if decision_kind == "grid_select":
                cards = [self._card(card) for card in _rows(screen_state.get("cards"))]
                selected = [self._card(card) for card in _rows(screen_state.get("selected_cards"))]
                maximum = _integer(screen_state.get("num_cards"))
                any_number = _boolean(screen_state.get("any_number")) is True
                minimum = 0 if any_number else maximum
                mode = (
                    "upgrade"
                    if screen_state.get("for_upgrade") is True
                    else "transform"
                    if screen_state.get("for_transform") is True
                    else "remove"
                    if screen_state.get("for_purge") is True
                    else "select"
                )
                confirm_up = _boolean(screen_state.get("confirm_up"))
            else:
                cards = [self._card(card) for card in _rows(screen_state.get("hand"))]
                selected = [self._card(card) for card in _rows(screen_state.get("selected"))]
                maximum = _integer(screen_state.get("max_cards"))
                minimum = 0 if screen_state.get("can_pick_zero") is True else maximum
                any_number = screen_state.get("can_pick_zero") is True
                mode = "hand_select"
                confirm_up = False
            result["selection"] = {
                "selection_template_id": f"{decision_id}_selection",
                "mode": mode,
                "minimum": minimum,
                "maximum": maximum,
                "any_number": any_number,
                "confirm_up": confirm_up,
                "cards": cards,
                "selected_cards": selected,
            }
        elif decision_kind in {"game_over", "victory"}:
            result["terminal"] = {
                "victory": _boolean(screen_state.get("victory")),
                "score": _integer(screen_state.get("score")),
            }
        return result

    def normalize(self, raw: dict[str, Any], state_seq: int) -> dict[str, Any]:
        bridge_contract = (raw.get("bridge_version"), raw.get("protocol_version"))
        if bridge_contract not in SUPPORTED_BRIDGE_PROTOCOLS:
            raise NormalizationFailure("unexpected bridge/protocol version pair")
        if raw.get("ready_for_command") is not True:
            raise NormalizationFailure("bridge state is not ready for a command")
        if not isinstance(state_seq, int) or state_seq < 1:
            raise NormalizationFailure("state_seq must be a positive integer")

        self.identities.update(raw)
        game = _dict(raw.get("game_state"))
        decision_kind = self._decision_kind(raw, game)
        decision_id = f"decision_{state_seq:06d}"
        observation: dict[str, Any] = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "fairness_profile": FAIRNESS_PROFILE,
            "episode_id": self.episode_id,
            "native_session_id": self.native_session_id,
            "run_id": self.identities.run_id,
            "act_id": (
                f"act_{game['act']:02d}"
                if isinstance(game.get("act"), int) and not isinstance(game.get("act"), bool)
                else None
            ),
            "room_id": self.identities.room_id,
            "combat_id": self.identities.combat_id,
            "state_seq": state_seq,
            "decision_id": decision_id,
            "ready_for_action": decision_kind not in {"unsupported", "game_over", "victory"},
            "decision_kind": decision_kind,
            "bridge": {
                "version": raw["bridge_version"],
                "protocol_version": raw["protocol_version"],
            },
            "run": None,
            "map": None,
            "combat": None,
            "screen": self._screen(game, decision_id, decision_kind),
            "catalog_delta": {},
        }

        if raw.get("in_game") is True:
            observation["run"] = _clean_none(
                {
                    "character_id": _string(game.get("class")),
                    "ascension": _integer(game.get("ascension_level")),
                    "act": _integer(game.get("act")),
                    "floor": _integer(game.get("floor")),
                    "current_hp": _integer(game.get("current_hp")),
                    "max_hp": _integer(game.get("max_hp")),
                    "gold": _integer(game.get("gold")),
                    "room_type": _string(game.get("room_type")),
                    "native_score": (
                        _integer(_dict(game.get("screen_state")).get("score"))
                        if decision_kind in {"game_over", "victory"}
                        else None
                    ),
                    "terminal": decision_kind in {"game_over", "victory"},
                    "outcome": (
                        "VICTORY_ACT3"
                        if decision_kind == "victory" and _integer(game.get("act")) == 3
                        else "VICTORY_ACT4"
                        if decision_kind == "victory" and _integer(game.get("act")) == 4
                        else "DEFEAT_COMBAT"
                        if decision_kind == "game_over"
                        else None
                    ),
                    "visible_act_boss": _string(game.get("act_boss")),
                    "keys": {
                        key: bool(value)
                        for key, value in _dict(game.get("keys")).items()
                        if key in {"ruby", "emerald", "sapphire"} and isinstance(value, bool)
                    },
                    "deck": [self._card(card) for card in _rows(game.get("deck"))],
                    "relics": [self._relic(relic) for relic in _rows(game.get("relics"))],
                    "potions": [
                        self._potion(potion, index)
                        for index, potion in enumerate(_rows(game.get("potions")))
                    ],
                }
            )
            nodes = [self._node(node) for node in _rows(game.get("map"))]
            observation["map"] = {
                "nodes": sorted(nodes, key=lambda node: (node["y"], node["x"])),
            }

        combat = _dict(game.get("combat_state"))
        if combat:
            hand = [self._card(card) for card in _rows(combat.get("hand"))]
            discard = [self._card(card) for card in _rows(combat.get("discard_pile"))]
            exhaust = [self._card(card) for card in _rows(combat.get("exhaust_pile"))]
            limbo = [self._card(card) for card in _rows(combat.get("limbo"))]
            observation["combat"] = _clean_none(
                {
                    "turn": _integer(combat.get("turn")),
                    "cards_discarded_this_turn": _integer(
                        combat.get("cards_discarded_this_turn")
                    ),
                    "times_damaged": _integer(combat.get("times_damaged")),
                    "player": self._player(combat.get("player")),
                    "hand": hand,
                    "draw_pile": self._draw_pile(combat.get("draw_pile")),
                    "discard_pile": sorted(
                        discard, key=lambda card: card["card_instance_id"]
                    ),
                    "exhaust_pile": sorted(
                        exhaust, key=lambda card: card["card_instance_id"]
                    ),
                    "limbo": sorted(limbo, key=lambda card: card["card_instance_id"]),
                    "card_in_play": (
                        self._card(combat["card_in_play"])
                        if isinstance(combat.get("card_in_play"), dict)
                        else None
                    ),
                    "monsters": [
                        self._monster(monster, index)
                        for index, monster in enumerate(_rows(combat.get("monsters")))
                    ],
                }
            )

        observation["observation_hash"] = sha256_document(observation)
        return observation
