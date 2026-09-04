from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import sha256_document
from .legal_actions import NativeAction
from .transition import StateSnapshot


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(observation)
    value.pop("observation_hash", None)
    value.pop("state_seq", None)
    value.pop("decision_id", None)
    screen = _dict(value.get("screen"))
    for choice in _rows(screen.get("choices")):
        choice.pop("choice_id", None)
    event = _dict(screen.get("event"))
    for choice in _rows(event.get("options")):
        choice.pop("choice_id", None)
    return value


def _card_locations(snapshot: StateSnapshot) -> dict[str, str]:
    combat = _dict(snapshot.observation.get("combat"))
    result: dict[str, str] = {}
    for location in ("hand", "discard_pile", "exhaust_pile", "limbo"):
        for card in _rows(combat.get(location)):
            card_id = card.get("card_instance_id")
            if isinstance(card_id, str):
                result[card_id] = location
    card_in_play = combat.get("card_in_play")
    if isinstance(card_in_play, dict) and isinstance(card_in_play.get("card_instance_id"), str):
        result[card_in_play["card_instance_id"]] = "card_in_play"
    return result


def verify_action_effect(
    action: NativeAction,
    before: StateSnapshot,
    after: StateSnapshot,
) -> tuple[bool, dict[str, Any]]:
    """Verify one native action from observable pre/post state only."""

    before_observation = before.observation
    after_observation = after.observation
    semantic_changed = sha256_document(_semantic_observation(before_observation)) != sha256_document(
        _semantic_observation(after_observation)
    )
    proof: dict[str, Any] = {
        "new_stable_state": after.state_seq > before.state_seq,
        "semantic_state_changed": semantic_changed,
        "pre_decision_id": before_observation.get("decision_id"),
        "post_decision_id": after_observation.get("decision_id"),
    }
    action_type = action.action_type

    if action_type == "play_card":
        card_id = action.payload.get("card_instance_id")
        before_location = _card_locations(before).get(card_id)
        after_location = _card_locations(after).get(card_id)
        combat_ended = before_observation.get("combat") is not None and after_observation.get("combat") is None
        proof.update(
            {
                "card_instance_id": card_id,
                "pre_location": before_location,
                "post_location": after_location,
                "combat_ended": combat_ended,
            }
        )
        return before_location == "hand" and (after_location != "hand" or combat_ended), proof

    if action_type == "end_turn":
        before_turn = _dict(before_observation.get("combat")).get("turn")
        after_turn = _dict(after_observation.get("combat")).get("turn")
        combat_ended = before_observation.get("combat") is not None and after_observation.get("combat") is None
        proof.update(
            {
                "pre_turn": before_turn,
                "post_turn": after_turn,
                "combat_ended": combat_ended,
            }
        )
        return combat_ended or (
            isinstance(before_turn, int) and isinstance(after_turn, int) and after_turn > before_turn
        ), proof

    if action_type == "choose_map_node":
        selected = action.payload.get("map_node_id")
        post_choice = _dict(_dict(after_observation.get("screen")).get("map_choice"))
        current = _dict(post_choice.get("current_node")).get("map_node_id")
        room_changed = after_observation.get("room_id") != before_observation.get("room_id")
        proof.update(
            {
                "selected_map_node_id": selected,
                "post_current_map_node_id": current,
                "room_changed": room_changed,
            }
        )
        return current == selected or room_changed, proof

    if action_type in {"use_potion", "discard_potion"}:
        slot_id = action.payload.get("potion_slot_id")

        def potion_at(snapshot: StateSnapshot) -> Any:
            run = _dict(snapshot.observation.get("run"))
            for potion in _rows(run.get("potions")):
                if potion.get("potion_slot_id") == slot_id:
                    return potion.get("potion_id")
            return None

        before_potion = potion_at(before)
        after_potion = potion_at(after)
        combat_ended = before_observation.get("combat") is not None and after_observation.get("combat") is None
        proof.update(
            {
                "potion_slot_id": slot_id,
                "pre_potion_id": before_potion,
                "post_potion_id": after_potion,
                "combat_ended": combat_ended,
            }
        )
        return before_potion is not None and (before_potion != after_potion or combat_ended), proof

    if action_type in {"choose_option", "proceed", "return_or_skip"}:
        return semantic_changed, proof

    proof["unsupported_action_type"] = action_type
    return False, proof
