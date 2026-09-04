from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Any

from .canonical import sha256_document


LEGAL_ACTIONS_SCHEMA_VERSION = "sts-legal-actions.v1"


class ActionValidationFailure(ValueError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in _list(value) if isinstance(row, dict)]


def _commands(raw: dict[str, Any]) -> set[str]:
    return {
        str(command).strip().lower()
        for command in _list(raw.get("available_commands"))
        if isinstance(command, str)
    }


def _action_id(decision_id: str, action_type: str, payload: dict[str, Any]) -> str:
    digest = sha256_document(
        {
            "decision_id": decision_id,
            "type": action_type,
            "payload": payload,
        }
    ).removeprefix("sha256:")
    return "action_" + digest[:20]


@dataclass(frozen=True)
class NativeAction:
    action_id: str
    action_type: str
    payload: dict[str, Any]
    command: str
    selector: dict[str, Any]


@dataclass(frozen=True)
class LegalActionSnapshot:
    document: dict[str, Any]
    native_actions: dict[str, NativeAction]


def _public_action(
    *,
    decision_id: str,
    action_type: str,
    payload: dict[str, Any],
    label: str,
    presentation: dict[str, Any] | None = None,
    selector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action_id": _action_id(decision_id, action_type, payload),
        "type": action_type,
        "payload": payload,
        "label": label,
        "selector": selector or {"schema_version": "sts-action-selector.v1", "type": action_type},
    }
    if presentation:
        result["presentation"] = presentation
    return result


def _card_selectors(cards: list[dict[str, Any]], zone: str) -> list[dict[str, Any]]:
    fields = (
        "card_id",
        "upgrades",
        "misc",
        "base_cost",
        "cost_for_turn",
        "cost",
        "damage",
        "block",
        "magic_number",
        "free_to_play_once",
        "retain",
        "self_retain",
    )
    seen: Counter[tuple[Any, ...]] = Counter()
    result: list[dict[str, Any]] = []
    for card in cards:
        key = tuple(card.get(field) for field in fields)
        ordinal = seen[key]
        seen[key] += 1
        result.append(
            {
                "zone": zone,
                "occurrence_ordinal": ordinal,
                **{field: card[field] for field in fields if field in card},
            }
        )
    return result


def _target_selectors(monsters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    for monster in monsters:
        monster_id = str(monster.get("monster_id", "unknown"))
        ordinal = seen[monster_id]
        seen[monster_id] += 1
        result.append({"monster_id": monster_id, "spawn_ordinal": ordinal})
    return result


def build_legal_actions(raw: dict[str, Any], observation: dict[str, Any]) -> LegalActionSnapshot:
    decision_id = observation["decision_id"]
    commands = _commands(raw)
    if observation.get("ready_for_action") is not True:
        commands = set()
    game = _dict(raw.get("game_state"))
    combat_raw = _dict(game.get("combat_state"))
    combat_observation = _dict(observation.get("combat"))
    actions: list[dict[str, Any]] = []
    native: dict[str, NativeAction] = {}

    def add(
        action_type: str,
        payload: dict[str, Any],
        command: str,
        label: str,
        presentation: dict[str, Any] | None = None,
        selector: dict[str, Any] | None = None,
    ) -> None:
        public = _public_action(
            decision_id=decision_id,
            action_type=action_type,
            payload=payload,
            label=label,
            presentation=presentation,
            selector=selector,
        )
        actions.append(public)
        native[public["action_id"]] = NativeAction(
            action_id=public["action_id"],
            action_type=action_type,
            payload=payload,
            command=command,
            selector=public["selector"],
        )

    if "play" in commands and combat_raw and combat_observation:
        raw_hand = _rows(combat_raw.get("hand"))
        hand = _rows(combat_observation.get("hand"))
        raw_monsters = _rows(combat_raw.get("monsters"))
        monsters = _rows(combat_observation.get("monsters"))
        if len(raw_hand) != len(hand) or len(raw_monsters) != len(monsters):
            raise ActionValidationFailure("raw and normalized combat collections are misaligned")
        live_targets = [
            (index, monster)
            for index, (raw_monster, monster) in enumerate(zip(raw_monsters, monsters))
            if raw_monster.get("is_gone") is not True
            and isinstance(raw_monster.get("current_hp"), int)
            and raw_monster["current_hp"] > 0
        ]
        hand_selectors = _card_selectors(hand, "hand")
        target_selectors = _target_selectors(monsters)
        for hand_index, (raw_card, card) in enumerate(zip(raw_hand, hand), start=1):
            if raw_card.get("is_playable") is not True:
                continue
            instance_id = card.get("card_instance_id")
            if not isinstance(instance_id, str):
                continue
            presentation = {
                key: card[key]
                for key in (
                    "card_id",
                    "name",
                    "cost",
                    "base_cost",
                    "cost_for_turn",
                    "damage",
                    "block",
                    "magic_number",
                    "type",
                    "upgrades",
                    "description",
                )
                if key in card
            }
            if raw_card.get("has_target") is True:
                for target_index, monster in live_targets:
                    target_id = monster.get("target_id")
                    if not isinstance(target_id, str):
                        continue
                    payload = {
                        "card_instance_id": instance_id,
                        "target_id": target_id,
                    }
                    add(
                        "play_card",
                        payload,
                        f"play {hand_index} {target_index}",
                        f"Play {card.get('name', card.get('card_id', instance_id))} on {monster.get('name', target_id)}",
                        {**presentation, "target_name": monster.get("name")},
                        {
                            "schema_version": "sts-action-selector.v1",
                            "type": "play_card",
                            "card": hand_selectors[hand_index - 1],
                            "target": target_selectors[target_index],
                        },
                    )
            else:
                payload = {"card_instance_id": instance_id}
                add(
                    "play_card",
                    payload,
                    f"play {hand_index}",
                    f"Play {card.get('name', card.get('card_id', instance_id))}",
                    presentation,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "play_card",
                        "card": hand_selectors[hand_index - 1],
                    },
                )

    if "end" in commands and combat_raw:
        add(
            "end_turn",
            {},
            "end",
            "End turn",
            selector={"schema_version": "sts-action-selector.v1", "type": "end_turn"},
        )

    if "potion" in commands and observation.get("run"):
        raw_potions = _rows(game.get("potions"))
        potions = _rows(_dict(observation.get("run")).get("potions"))
        monsters = _rows(combat_observation.get("monsters"))
        raw_monsters = _rows(combat_raw.get("monsters"))
        for index, (raw_potion, potion) in enumerate(zip(raw_potions, potions)):
            slot_id = potion.get("potion_slot_id")
            if not isinstance(slot_id, str):
                continue
            if raw_potion.get("can_discard") is True:
                add(
                    "discard_potion",
                    {"potion_slot_id": slot_id},
                    f"potion discard {index}",
                    f"Discard {potion.get('name', slot_id)}",
                    {"potion_id": potion.get("potion_id"), "name": potion.get("name")},
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "discard_potion",
                        "slot_index": index,
                        "potion_id": potion.get("potion_id"),
                    },
                )
            if raw_potion.get("can_use") is not True:
                continue
            if raw_potion.get("requires_target") is True:
                for target_index, (raw_monster, monster) in enumerate(zip(raw_monsters, monsters)):
                    if raw_monster.get("is_gone") is True or raw_monster.get("current_hp", 0) <= 0:
                        continue
                    target_id = monster.get("target_id")
                    if not isinstance(target_id, str):
                        continue
                    add(
                        "use_potion",
                        {"potion_slot_id": slot_id, "target_id": target_id},
                        f"potion use {index} {target_index}",
                        f"Use {potion.get('name', slot_id)} on {monster.get('name', target_id)}",
                        selector={
                            "schema_version": "sts-action-selector.v1",
                            "type": "use_potion",
                            "slot_index": index,
                            "potion_id": potion.get("potion_id"),
                            "target": _target_selectors(monsters)[target_index],
                        },
                    )
            else:
                add(
                    "use_potion",
                    {"potion_slot_id": slot_id},
                    f"potion use {index}",
                    f"Use {potion.get('name', slot_id)}",
                    selector={
                        "schema_version": "sts-action-selector.v1",
                        "type": "use_potion",
                        "slot_index": index,
                        "potion_id": potion.get("potion_id"),
                    },
                )

    if "choose" in commands:
        choices = _rows(_dict(observation.get("screen")).get("choices"))
        decision_kind = observation.get("decision_kind")
        screen = _dict(observation.get("screen"))
        event_options = _rows(_dict(screen.get("event")).get("options"))
        map_nodes = _rows(
            _dict(screen.get("map_choice")).get("next_nodes")
        )
        if decision_kind == "map":
            boss_available = _dict(screen.get("map_choice")).get("boss_available") is True
            if boss_available and choices:
                add(
                    "choose_map_node",
                    {"map_node_id": f"boss_{observation.get('act_id', 'act_unknown')}"},
                    "choose 0",
                    "Choose act boss",
                    {"boss": _dict(observation.get("run")).get("visible_act_boss")},
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_map_node",
                        "boss": True,
                        "act": _dict(observation.get("run")).get("act"),
                    },
                )
            for index, node in enumerate(map_nodes):
                node = map_nodes[index]
                payload = {"map_node_id": node["map_node_id"]}
                add(
                    "choose_map_node",
                    payload,
                    f"choose {index}",
                    f"Choose map node ({node['x']}, {node['y']}) {node.get('symbol', '')}".strip(),
                    node,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_map_node",
                        "x": node["x"],
                        "y": node["y"],
                        "symbol": node.get("symbol"),
                    },
                )
        elif decision_kind == "rest":
            rest_actions = _rows(_dict(screen.get("rest")).get("actions"))
            for index, rest_action in enumerate(rest_actions):
                rest_id = rest_action.get("rest_action_id")
                if not isinstance(rest_id, str):
                    continue
                add(
                    "rest_site_action",
                    {"rest_action_id": rest_id},
                    f"choose {index}",
                    str(rest_action.get("name", rest_id)),
                    rest_action,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "rest_site_action",
                        "rest_action": str(rest_action.get("name", rest_id)).lower(),
                    },
                )
        elif decision_kind == "shop" and _dict(screen.get("shop")).get("phase") == "inventory":
            shop = _dict(screen.get("shop"))
            gold = _dict(observation.get("run")).get("gold")
            native_index = 0
            purge_cost = shop.get("purge_cost")
            if shop.get("purge_available") is True and isinstance(gold, int) and isinstance(purge_cost, int) and gold >= purge_cost:
                add(
                    "choose_option",
                    {"choice_id": f"{decision_id}_shop_purge"},
                    f"choose {native_index}",
                    "Open card removal",
                    {"semantic": "open_card_removal", "price": purge_cost},
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": "shop",
                        "semantic": "open_card_removal",
                        "price": purge_cost,
                    },
                )
                native_index += 1
            has_empty_potion_slot = any(
                potion.get("potion_id") == "Potion Slot"
                for potion in _rows(_dict(observation.get("run")).get("potions"))
            )
            for item_kind, rows in (
                ("card", _rows(shop.get("cards"))),
                ("relic", _rows(shop.get("relics"))),
                ("potion", _rows(shop.get("potions"))),
            ):
                selectors = _card_selectors(rows, "shop") if item_kind == "card" else []
                for item_index, item in enumerate(rows):
                    price = item.get("price")
                    if not isinstance(gold, int) or not isinstance(price, int) or price > gold:
                        continue
                    command_index = native_index
                    native_index += 1
                    if item_kind == "potion" and not has_empty_potion_slot:
                        continue
                    item_id = item.get("shop_item_id")
                    if not isinstance(item_id, str):
                        continue
                    semantic_id = item.get("card_id") or item.get("relic_id") or item.get("potion_id")
                    selector_item = (
                        selectors[item_index]
                        if item_kind == "card"
                        else {"item_id": semantic_id, "occurrence_ordinal": item_index}
                    )
                    add(
                        "buy_item",
                        {"shop_item_id": item_id},
                        f"choose {command_index}",
                        f"Buy {item.get('name', semantic_id)}",
                        item,
                        {
                            "schema_version": "sts-action-selector.v1",
                            "type": "buy_item",
                            "item_kind": item_kind,
                            "item": selector_item,
                            "price": price,
                        },
                    )
        elif decision_kind in {"grid_select", "hand_select"}:
            selection = _dict(screen.get("selection"))
            cards = _rows(selection.get("cards"))
            selectors = _card_selectors(cards, decision_kind)
            selection_id = selection.get("selection_template_id")
            mode = selection.get("mode")
            if isinstance(selection_id, str):
                selected_ids = {
                    card.get("card_instance_id")
                    for card in _rows(selection.get("selected_cards"))
                    if isinstance(card.get("card_instance_id"), str)
                }
                for index, card in enumerate(cards):
                    instance_id = card.get("card_instance_id")
                    if not isinstance(instance_id, str) or instance_id in selected_ids:
                        continue
                    action_type = "remove_card" if mode == "remove" else "select_cards"
                    payload = (
                        {"card_instance_id": instance_id}
                        if action_type == "remove_card"
                        else {
                            "selection_template_id": selection_id,
                            "card_instance_ids": [instance_id],
                            "confirm": False,
                        }
                    )
                    add(
                        action_type,
                        payload,
                        f"choose {index}",
                        f"Select {card.get('name', card.get('card_id', instance_id))}",
                        card,
                        {
                            "schema_version": "sts-action-selector.v1",
                            "type": action_type,
                            "selection_mode": mode,
                            "cards": [selectors[index]],
                            "confirm": False,
                        },
                    )
        elif decision_kind == "card_reward":
            reward_cards = _rows(_dict(screen.get("card_reward")).get("cards"))
            selectors = _card_selectors(reward_cards, "card_reward")
            for index, card in enumerate(reward_cards):
                choice_id = card.get("choice_id")
                if not isinstance(choice_id, str):
                    continue
                add(
                    "choose_option",
                    {"choice_id": choice_id},
                    f"choose {index}",
                    f"Take {card.get('name', card.get('card_id', choice_id))}",
                    card,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": "card_reward",
                        "semantic": "take_card",
                        "card": selectors[index],
                    },
                )
            if _dict(screen.get("card_reward")).get("bowl_available") is True and len(choices) > len(reward_cards):
                index = len(reward_cards)
                add(
                    "choose_option",
                    {"choice_id": choices[index]["choice_id"]},
                    f"choose {index}",
                    "Take Singing Bowl max HP",
                    selector={
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": "card_reward",
                        "semantic": "singing_bowl",
                    },
                )
        elif decision_kind == "combat_reward":
            rewards = _rows(_dict(screen.get("combat_reward")).get("rewards"))
            has_empty_potion_slot = any(
                potion.get("potion_id") == "Potion Slot"
                for potion in _rows(_dict(observation.get("run")).get("potions"))
            )
            for index, reward in enumerate(rewards):
                choice_id = reward.get("choice_id")
                if not isinstance(choice_id, str):
                    continue
                reward_type = str(reward.get("reward_type", "UNKNOWN"))
                if reward_type == "POTION" and not has_empty_potion_slot:
                    continue
                add(
                    "choose_option",
                    {"choice_id": choice_id},
                    f"choose {index}",
                    f"Claim {reward_type.lower()} reward",
                    reward,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": "combat_reward",
                        "semantic": "claim_reward",
                        "reward_type": reward_type,
                        "gold": reward.get("gold"),
                        "relic_id": _dict(reward.get("relic")).get("relic_id"),
                        "potion_id": _dict(reward.get("potion")).get("potion_id"),
                    },
                )
        elif decision_kind == "boss_reward":
            relics = _rows(_dict(screen.get("boss_reward")).get("relics"))
            for index, relic in enumerate(relics):
                choice_id = relic.get("choice_id")
                if not isinstance(choice_id, str):
                    continue
                add(
                    "choose_option",
                    {"choice_id": choice_id},
                    f"choose {index}",
                    f"Take {relic.get('name', relic.get('relic_id', choice_id))}",
                    relic,
                    {
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": "boss_reward",
                        "semantic": "take_boss_relic",
                        "relic_id": relic.get("relic_id"),
                        "occurrence_ordinal": index,
                    },
                )
        else:
            disabled_by_index = {
                option.get("choice_index"): option.get("disabled") is True
                for option in event_options
                if isinstance(option.get("choice_index"), int)
            }
            for index, choice in enumerate(choices):
                if disabled_by_index.get(index) is True:
                    continue
                choice_id = choice.get("choice_id")
                if not isinstance(choice_id, str):
                    continue
                payload = {"choice_id": choice_id}
                add(
                    "choose_option",
                    payload,
                    f"choose {index}",
                    str(choice.get("label", choice_id)),
                    selector={
                        "schema_version": "sts-action-selector.v1",
                        "type": "choose_option",
                        "decision_kind": decision_kind,
                        "choice_ordinal": index,
                        "label": choice.get("label"),
                    },
                )

    selection = _dict(_dict(observation.get("screen")).get("selection"))
    if "confirm" in commands and observation.get("decision_kind") in {"grid_select", "hand_select"}:
        selected = _rows(selection.get("selected_cards"))
        selected_ids = [card["card_instance_id"] for card in selected if isinstance(card.get("card_instance_id"), str)]
        add(
            "select_cards",
            {
                "selection_template_id": selection.get("selection_template_id"),
                "card_instance_ids": selected_ids,
                "confirm": True,
            },
            "confirm",
            "Confirm card selection",
            selector={
                "schema_version": "sts-action-selector.v1",
                "type": "select_cards",
                "selection_mode": selection.get("mode"),
                "cards": _card_selectors(selected, "selected"),
                "confirm": True,
            },
        )
    elif commands & {"proceed", "confirm", "open", "continue"} and observation.get("decision_kind") not in {"game_over", "victory"}:
        semantic = sorted(commands & {"proceed", "confirm", "open", "continue"})[0]
        add(
            "proceed",
            {},
            "proceed",
            "Proceed",
            selector={
                "schema_version": "sts-action-selector.v1",
                "type": "proceed",
                "decision_kind": observation.get("decision_kind"),
                "semantic": semantic,
            },
        )
    return_aliases = commands & {"return", "skip", "cancel", "leave"}
    if return_aliases:
        semantic = sorted(return_aliases)[0]
        add(
            "return_or_skip",
            {"semantic": semantic},
            "return",
            semantic.replace("_", " ").title(),
            selector={
                "schema_version": "sts-action-selector.v1",
                "type": "return_or_skip",
                "decision_kind": observation.get("decision_kind"),
                "semantic": semantic,
            },
        )

    templates: list[dict[str, Any]] = []
    if "start" in commands and observation.get("decision_kind") == "main_menu":
        templates.append(
            {
                "type": "start_run",
                "allowed_character_ids": ["IRONCLAD"],
                "minimum_ascension": 0,
                "maximum_ascension": 0,
                "seed_pattern": "^[A-Za-z0-9]+$",
            }
        )

    document: dict[str, Any] = {
        "schema_version": LEGAL_ACTIONS_SCHEMA_VERSION,
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation.get("run_id"),
        "decision_id": decision_id,
        "state_seq": observation["state_seq"],
        "observation_hash": observation["observation_hash"],
        "actions": actions,
        "templates": templates,
    }
    document["legal_actions_hash"] = sha256_document(document)
    return LegalActionSnapshot(document=document, native_actions=native)


def validate_action_submission(
    submission: Any,
    snapshot: LegalActionSnapshot,
) -> NativeAction:
    if not isinstance(submission, dict):
        raise ActionValidationFailure("action submission must be an object")
    unknown = set(submission) - {"action_id", "type", "payload"}
    if unknown:
        raise ActionValidationFailure(f"unknown action fields: {sorted(unknown)}")
    if set(submission) != {"action_id", "type", "payload"}:
        raise ActionValidationFailure("action submission requires action_id, type, and payload")
    action_id = submission.get("action_id")
    if not isinstance(action_id, str):
        raise ActionValidationFailure("action_id must be a string")
    native = snapshot.native_actions.get(action_id)
    if native is None:
        raise ActionValidationFailure("action_id is not legal in the current decision")
    if submission.get("type") != native.action_type or submission.get("payload") != native.payload:
        raise ActionValidationFailure("action type or payload does not match the current legal action")
    return native


def resolve_planned_action(
    submission: Any,
    snapshot: LegalActionSnapshot,
) -> NativeAction:
    """Re-resolve a later batch action after the native state has advanced."""

    if not isinstance(submission, dict):
        raise ActionValidationFailure("planned action submission must be an object")
    unknown = set(submission) - {"action_id", "type", "payload"}
    if unknown or set(submission) != {"action_id", "type", "payload"}:
        raise ActionValidationFailure("planned action requires only action_id, type, and payload")
    action_type = submission.get("type")
    payload = submission.get("payload")
    if not isinstance(action_type, str) or not isinstance(payload, dict):
        raise ActionValidationFailure("planned action type and payload are invalid")
    matches = [
        native
        for native in snapshot.native_actions.values()
        if native.action_type == action_type and native.payload == payload
    ]
    if not matches:
        raise ActionValidationFailure("planned action is no longer legal in the current decision")
    if len(matches) > 1:
        raise ActionValidationFailure("planned action is ambiguous in the current decision")
    return matches[0]


def submission_from_public_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        "type": action["type"],
        "payload": action["payload"],
    }
