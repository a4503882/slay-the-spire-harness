from __future__ import annotations

from typing import Any

from .canonical import sha256_document
from .legal_actions import NativeAction
from .replay_checkpoint import identity_rebased
from .transition import StateSnapshot


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    value = identity_rebased(observation)
    if not isinstance(value, dict):
        raise ValueError("semantic observation must remain an object")
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


def _run(snapshot: StateSnapshot) -> dict[str, Any]:
    return _dict(snapshot.observation.get("run"))


def _screen(snapshot: StateSnapshot) -> dict[str, Any]:
    return _dict(snapshot.observation.get("screen"))


def _card_semantic_count(snapshot: StateSnapshot, selector: dict[str, Any]) -> int:
    return sum(
        1
        for card in _rows(_run(snapshot).get("deck"))
        if card.get("card_id") == selector.get("card_id")
        and card.get("upgrades") == selector.get("upgrades")
        and card.get("misc") == selector.get("misc")
    )


def _combat_hand_semantic_count(snapshot: StateSnapshot, selector: dict[str, Any]) -> int:
    return sum(
        1
        for card in _rows(_dict(snapshot.observation.get("combat")).get("hand"))
        if card.get("card_id") == selector.get("card_id")
        and card.get("upgrades") == selector.get("upgrades")
        and card.get("misc") == selector.get("misc")
    )


def _owned_relic_ids(snapshot: StateSnapshot) -> list[Any]:
    return [relic.get("relic_id") for relic in _rows(_run(snapshot).get("relics"))]


def _owned_potion_ids(snapshot: StateSnapshot) -> list[Any]:
    return [potion.get("potion_id") for potion in _rows(_run(snapshot).get("potions"))]


def _visible_run_reward_hash(snapshot: StateSnapshot) -> str:
    run = _run(snapshot)
    reward_state = {
        key: run.get(key)
        for key in ("current_hp", "max_hp", "gold", "deck", "relics", "potions")
    }
    return sha256_document(identity_rebased(reward_state))


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
        "pre_state_seq": before.state_seq,
        "post_state_seq": after.state_seq,
        "pre_observation_hash": before_observation.get("observation_hash"),
        "post_observation_hash": after_observation.get("observation_hash"),
    }
    action_type = action.action_type

    if action_type == "play_card":
        card_id = action.payload.get("card_instance_id")
        before_location = _card_locations(before).get(card_id)
        after_location = _card_locations(after).get(card_id)
        combat_ended = before_observation.get("combat") is not None and (
            after_observation.get("combat") is None
            or after_observation.get("decision_kind") in {"game_over", "victory"}
        )
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
        combat_ended = before_observation.get("combat") is not None and (
            after_observation.get("combat") is None
            or after_observation.get("decision_kind") in {"game_over", "victory"}
        )
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
        combat_ended = before_observation.get("combat") is not None and (
            after_observation.get("combat") is None
            or after_observation.get("decision_kind") in {"game_over", "victory"}
        )
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
        selector = action.selector
        decision_kind = selector.get("decision_kind") or before_observation.get("decision_kind")
        semantic = selector.get("semantic")
        if decision_kind == "neow" and len(_rows(_screen(before).get("choices"))) > 1:
            before_reward_hash = _visible_run_reward_hash(before)
            after_reward_hash = _visible_run_reward_hash(after)
            reward_effect_visible = before_reward_hash != after_reward_hash
            proof.update(
                {
                    "neow_reward_effect_visible": reward_effect_visible,
                    "pre_visible_run_reward_hash": before_reward_hash,
                    "post_visible_run_reward_hash": after_reward_hash,
                }
            )
            return semantic_changed and reward_effect_visible, proof
        if decision_kind == "card_reward" and semantic == "take_card":
            card_selector = _dict(selector.get("card"))
            in_combat_reward = _screen(before).get("room_phase") == "COMBAT"
            if in_combat_reward:
                before_count = _combat_hand_semantic_count(before, card_selector)
                after_count = _combat_hand_semantic_count(after, card_selector)
                destination = "combat_hand"
            else:
                before_count = _card_semantic_count(before, card_selector)
                after_count = _card_semantic_count(after, card_selector)
                destination = "master_deck"
            proof.update(
                {
                    "card_destination": destination,
                    "pre_card_count": before_count,
                    "post_card_count": after_count,
                }
            )
            return after_count > before_count, proof
        if decision_kind == "combat_reward" and semantic == "claim_reward":
            reward_type = selector.get("reward_type")
            before_rewards = _rows(_dict(_screen(before).get("combat_reward")).get("rewards"))
            after_rewards = _rows(_dict(_screen(after).get("combat_reward")).get("rewards"))
            reward_removed = len(after_rewards) < len(before_rewards)
            proof.update(
                {
                    "reward_type": reward_type,
                    "pre_reward_count": len(before_rewards),
                    "post_reward_count": len(after_rewards),
                }
            )
            if reward_type in {"GOLD", "STOLEN_GOLD"}:
                before_gold = _run(before).get("gold")
                after_gold = _run(after).get("gold")
                proof.update({"pre_gold": before_gold, "post_gold": after_gold})
                return reward_removed and isinstance(before_gold, int) and isinstance(after_gold, int) and after_gold > before_gold, proof
            if reward_type == "CARD":
                return after_observation.get("decision_kind") == "card_reward", proof
            if reward_type == "RELIC":
                relic_id = selector.get("relic_id")
                return reward_removed and relic_id in _owned_relic_ids(after), proof
            if reward_type == "POTION":
                potion_id = selector.get("potion_id")
                return reward_removed and potion_id in _owned_potion_ids(after), proof
            return reward_removed or semantic_changed, proof
        if decision_kind == "boss_reward" and semantic == "take_boss_relic":
            relic_id = selector.get("relic_id")
            proof["relic_id"] = relic_id
            return relic_id in _owned_relic_ids(after) and relic_id not in _owned_relic_ids(before), proof
        if decision_kind == "shop" and semantic == "open_card_removal":
            return after_observation.get("decision_kind") == "grid_select", proof
        return semantic_changed, proof

    if action_type == "buy_item":
        selector = action.selector
        item_kind = selector.get("item_kind")
        item = _dict(selector.get("item"))
        before_gold = _run(before).get("gold")
        after_gold = _run(after).get("gold")
        price = selector.get("price")
        acquired = False
        if item_kind == "card":
            acquired = _card_semantic_count(after, item) > _card_semantic_count(before, item)
        elif item_kind == "relic":
            item_id = item.get("item_id")
            acquired = item_id in _owned_relic_ids(after) and item_id not in _owned_relic_ids(before)
        elif item_kind == "potion":
            item_id = item.get("item_id")
            acquired = _owned_potion_ids(after).count(item_id) > _owned_potion_ids(before).count(item_id)
        gold_coherent = (
            isinstance(before_gold, int)
            and isinstance(after_gold, int)
            and isinstance(price, int)
            and after_gold == before_gold - price
        )
        proof.update(
            {
                "item_kind": item_kind,
                "price": price,
                "pre_gold": before_gold,
                "post_gold": after_gold,
                "acquired": acquired,
                "gold_coherent": gold_coherent,
            }
        )
        return acquired and gold_coherent, proof

    if action_type == "rest_site_action":
        rest_action = action.selector.get("rest_action")
        before_hp = _run(before).get("current_hp")
        after_hp = _run(after).get("current_hp")
        after_rest = _dict(_screen(after).get("rest"))
        proof.update(
            {
                "rest_action": rest_action,
                "pre_hp": before_hp,
                "post_hp": after_hp,
                "post_has_rested": after_rest.get("has_rested"),
            }
        )
        if rest_action == "rest":
            return isinstance(before_hp, int) and isinstance(after_hp, int) and after_hp > before_hp, proof
        return (
            after_observation.get("decision_kind") == "grid_select"
            or after_rest.get("has_rested") is True
            or after_observation.get("decision_kind") != "rest"
        ), proof

    if action_type in {"select_cards", "remove_card"}:
        selector = action.selector
        confirm = selector.get("confirm") is True
        if confirm:
            left_selection = after_observation.get("decision_kind") not in {"grid_select", "hand_select"}
            proof["left_selection_screen"] = left_selection
            return left_selection or semantic_changed, proof
        before_selection = _dict(_screen(before).get("selection"))
        after_selection = _dict(_screen(after).get("selection"))
        selected_ids = {
            card.get("card_instance_id")
            for card in _rows(after_selection.get("selected_cards"))
            if isinstance(card.get("card_instance_id"), str)
        }
        selected_id = action.payload.get("card_instance_id")
        if action_type == "select_cards":
            ids = action.payload.get("card_instance_ids")
            selected_id = ids[0] if isinstance(ids, list) and len(ids) == 1 else None
        left_selection = after_observation.get("decision_kind") not in {
            "grid_select",
            "hand_select",
        }
        entered_confirm = (
            before_selection.get("confirm_up") is not True
            and after_selection.get("confirm_up") is True
        )
        proof.update(
            {
                "selected_card_instance_id": selected_id,
                "post_selected_ids": sorted(selected_ids),
                "left_selection_screen": left_selection,
                "entered_confirm_stage": entered_confirm,
            }
        )
        return isinstance(selected_id, str) and (
            selected_id in selected_ids or entered_confirm or left_selection
        ), proof

    proof["unsupported_action_type"] = action_type
    return False, proof
