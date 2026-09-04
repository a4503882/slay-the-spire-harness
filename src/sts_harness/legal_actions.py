from __future__ import annotations

from dataclasses import dataclass
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
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action_id": _action_id(decision_id, action_type, payload),
        "type": action_type,
        "payload": payload,
        "label": label,
    }
    if presentation:
        result["presentation"] = presentation
    return result


def build_legal_actions(raw: dict[str, Any], observation: dict[str, Any]) -> LegalActionSnapshot:
    decision_id = observation["decision_id"]
    commands = _commands(raw)
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
    ) -> None:
        public = _public_action(
            decision_id=decision_id,
            action_type=action_type,
            payload=payload,
            label=label,
            presentation=presentation,
        )
        actions.append(public)
        native[public["action_id"]] = NativeAction(
            action_id=public["action_id"],
            action_type=action_type,
            payload=payload,
            command=command,
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
        for hand_index, (raw_card, card) in enumerate(zip(raw_hand, hand), start=1):
            if raw_card.get("is_playable") is not True:
                continue
            instance_id = card.get("card_instance_id")
            if not isinstance(instance_id, str):
                continue
            presentation = {
                key: card[key]
                for key in ("card_id", "name", "cost", "type", "upgrades")
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
                    )
            else:
                payload = {"card_instance_id": instance_id}
                add(
                    "play_card",
                    payload,
                    f"play {hand_index}",
                    f"Play {card.get('name', card.get('card_id', instance_id))}",
                    presentation,
                )

    if "end" in commands and combat_raw:
        add("end_turn", {}, "end", "End turn")

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
                    )
            else:
                add(
                    "use_potion",
                    {"potion_slot_id": slot_id},
                    f"potion use {index}",
                    f"Use {potion.get('name', slot_id)}",
                )

    if "choose" in commands:
        choices = _rows(_dict(observation.get("screen")).get("choices"))
        decision_kind = observation.get("decision_kind")
        event_options = _rows(
            _dict(_dict(observation.get("screen")).get("event")).get("options")
        )
        map_nodes = _rows(
            _dict(_dict(observation.get("screen")).get("map_choice")).get("next_nodes")
        )
        for index, choice in enumerate(choices):
            if (
                decision_kind == "event"
                and index < len(event_options)
                and event_options[index].get("disabled") is True
            ):
                continue
            if decision_kind == "map" and index < len(map_nodes):
                node = map_nodes[index]
                payload = {"map_node_id": node["map_node_id"]}
                add(
                    "choose_map_node",
                    payload,
                    f"choose {index}",
                    f"Choose map node ({node['x']}, {node['y']}) {node.get('symbol', '')}".strip(),
                    node,
                )
            else:
                choice_id = choice.get("choice_id")
                if not isinstance(choice_id, str):
                    continue
                payload = {"choice_id": choice_id}
                add(
                    "choose_option",
                    payload,
                    f"choose {index}",
                    str(choice.get("label", choice_id)),
                )

    if commands & {"proceed", "confirm", "open", "continue"}:
        add("proceed", {}, "proceed", "Proceed")
    return_aliases = commands & {"return", "skip", "cancel", "leave"}
    if return_aliases:
        semantic = sorted(return_aliases)[0]
        add(
            "return_or_skip",
            {"semantic": semantic},
            "return",
            semantic.replace("_", " ").title(),
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


def submission_from_public_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        "type": action["type"],
        "payload": action["payload"],
    }
