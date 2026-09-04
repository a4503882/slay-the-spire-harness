from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import canonical_json_bytes, sha256_document


REPLAY_CHECKPOINT_SCHEMA_VERSION = "sts-replay-checkpoint.v1"
INACTIVE_COMBAT_CARD_ZONES = ("draw_pile", "discard_pile", "exhaust_pile", "limbo")
INACTIVE_COMBAT_CARD_CACHE_FIELDS = (
    "damage",
    "block",
    "cost_for_turn",
    "is_playable",
    "free_to_play_once",
    "retain",
)
RUN_LOCAL_KEYS = {
    "episode_id",
    "native_session_id",
    "run_id",
    "room_id",
    "combat_id",
    "state_seq",
    "decision_id",
    "observation_hash",
    "legal_actions_hash",
    "action_id",
    "choice_id",
    "card_instance_id",
    "target_id",
    "map_node_id",
    "reward_id",
    "shop_item_id",
    "selection_template_id",
    "native_index",
}


class ReplayCheckpointFailure(ValueError):
    pass


def identity_rebased(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: identity_rebased(item)
            for key, item in value.items()
            if key not in RUN_LOCAL_KEYS
        }
    if isinstance(value, list):
        return [identity_rebased(item) for item in value]
    if isinstance(value, float):
        raise ReplayCheckpointFailure("floating-point value in replay checkpoint")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ReplayCheckpointFailure(
        f"unsupported replay checkpoint value: {type(value).__name__}"
    )


def _action_selectors(legal_actions: dict[str, Any]) -> list[dict[str, Any]]:
    actions = legal_actions.get("actions")
    if not isinstance(actions, list):
        raise ReplayCheckpointFailure("legal actions document has no actions list")
    selectors: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("selector"), dict):
            raise ReplayCheckpointFailure("public action has no canonical selector")
        selector = identity_rebased(action["selector"])
        if not isinstance(selector, dict):
            raise ReplayCheckpointFailure("canonical action selector is not an object")
        selectors.append(selector)
    return sorted(selectors, key=canonical_json_bytes)


def _inactive_card_semantics(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in card.items()
        if key not in INACTIVE_COMBAT_CARD_CACHE_FIELDS
    }


def _semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    value = identity_rebased(observation)
    if not isinstance(value, dict):
        raise ReplayCheckpointFailure("semantic observation is not an object")
    combat = value.get("combat")
    if not isinstance(combat, dict):
        return value

    draw_pile = combat.get("draw_pile")
    if isinstance(draw_pile, dict) and isinstance(draw_pile.get("cards"), list):
        merged: dict[bytes, dict[str, Any]] = {}
        for raw_card in draw_pile["cards"]:
            if not isinstance(raw_card, dict):
                raise ReplayCheckpointFailure("draw-pile semantic card is not an object")
            count = raw_card.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise ReplayCheckpointFailure("draw-pile semantic card has invalid count")
            card = _inactive_card_semantics(raw_card)
            card.pop("count", None)
            key = canonical_json_bytes(card)
            if key not in merged:
                merged[key] = {**card, "count": 0}
            merged[key]["count"] += count
        draw_pile["cards"] = [merged[key] for key in sorted(merged)]

    for zone in ("discard_pile", "exhaust_pile", "limbo"):
        cards = combat.get(zone)
        if not isinstance(cards, list):
            continue
        normalized = []
        for raw_card in cards:
            if not isinstance(raw_card, dict):
                raise ReplayCheckpointFailure(f"{zone} semantic card is not an object")
            normalized.append(_inactive_card_semantics(raw_card))
        combat[zone] = sorted(normalized, key=canonical_json_bytes)
    return value


def build_replay_checkpoint(
    observation: dict[str, Any],
    legal_actions: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(observation, dict) or not isinstance(legal_actions, dict):
        raise ReplayCheckpointFailure("checkpoint inputs must be objects")
    checkpoint: dict[str, Any] = {
        "schema_version": REPLAY_CHECKPOINT_SCHEMA_VERSION,
        "observation_schema_version": observation.get("schema_version"),
        "legal_actions_schema_version": legal_actions.get("schema_version"),
        "fairness_profile": observation.get("fairness_profile"),
        "projection_contract": {
            "run_local_identity": "removed",
            "inactive_combat_pile_order": "semantic_multiset",
            "inactive_combat_card_cache_fields_ignored": list(
                INACTIVE_COMBAT_CARD_CACHE_FIELDS
            ),
        },
        "semantic_observation": _semantic_observation(observation),
        "legal_action_selectors": _action_selectors(legal_actions),
    }
    checkpoint["replay_checkpoint_hash"] = sha256_document(checkpoint)
    return checkpoint


def recompute_replay_checkpoint_hash(checkpoint: dict[str, Any]) -> str:
    value = deepcopy(checkpoint)
    value.pop("replay_checkpoint_hash", None)
    return sha256_document(value)


def resolve_action_selector(
    selector: dict[str, Any],
    legal_actions: dict[str, Any],
) -> dict[str, Any]:
    expected = canonical_json_bytes(identity_rebased(selector))
    matches = [
        action
        for action in legal_actions.get("actions", [])
        if isinstance(action, dict)
        and isinstance(action.get("selector"), dict)
        and canonical_json_bytes(identity_rebased(action["selector"])) == expected
    ]
    if not matches:
        raise ReplayCheckpointFailure("recorded action selector is not resolvable")
    if len(matches) > 1:
        raise ReplayCheckpointFailure("recorded action selector is ambiguous")
    return deepcopy(matches[0])


def bounded_structural_diff(
    recorded: Any,
    replayed: Any,
    *,
    limit: int = 256,
) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("diff limit must be a positive integer")
    result: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if len(result) >= limit:
            return
        if type(left) is not type(right):
            result.append({"path": path, "recorded": left, "replayed": right})
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                child = f"{path}/{key}"
                if key not in left:
                    result.append({"path": child, "recorded": "<absent>", "replayed": right[key]})
                elif key not in right:
                    result.append({"path": child, "recorded": left[key], "replayed": "<absent>"})
                else:
                    walk(left[key], right[key], child)
                if len(result) >= limit:
                    return
            return
        if isinstance(left, list):
            if len(left) != len(right):
                result.append(
                    {"path": f"{path}/length", "recorded": len(left), "replayed": len(right)}
                )
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(left_item, right_item, f"{path}/{index}")
                if len(result) >= limit:
                    return
            return
        if left != right:
            result.append({"path": path, "recorded": left, "replayed": right})

    walk(recorded, replayed, "")
    return result
