from __future__ import annotations

from collections import Counter
from typing import Any

from .transition import StateSnapshot


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _deck_ids(observation: dict[str, Any]) -> Counter[str]:
    return Counter(
        str(card.get("card_id"))
        for card in _rows(_dict(observation.get("run")).get("deck"))
        if isinstance(card.get("card_id"), str)
    )


def _upgrade_total(observation: dict[str, Any]) -> int:
    return sum(
        card.get("upgrades", 0)
        for card in _rows(_dict(observation.get("run")).get("deck"))
        if isinstance(card.get("upgrades"), int)
        and not isinstance(card.get("upgrades"), bool)
    )


def _relic_ids(observation: dict[str, Any]) -> Counter[str]:
    return Counter(
        str(relic.get("relic_id"))
        for relic in _rows(_dict(observation.get("run")).get("relics"))
        if isinstance(relic.get("relic_id"), str)
    )


def _potion_ids(observation: dict[str, Any]) -> Counter[str]:
    return Counter(
        str(potion.get("potion_id"))
        for potion in _rows(_dict(observation.get("run")).get("potions"))
        if isinstance(potion.get("potion_id"), str)
        and potion.get("potion_id") != "Potion Slot"
    )


class EpisodeMetrics:
    def __init__(self) -> None:
        self.seed: str | None = None
        self.policy_mode: str | None = None
        self.character_id: str | None = None
        self.ascension: int | None = None
        self.starting_hp: int | None = None
        self.minimum_hp: int | None = None
        self.final_hp: int | None = None
        self.final_max_hp: int | None = None
        self.final_gold: int | None = None
        self.final_act: int | None = None
        self.final_floor: int | None = None
        self.final_room_type: str | None = None
        self.native_score: int | None = None
        self.outcome: str | None = None
        self.gold_gained = 0
        self.gold_spent = 0
        self.cards_added = 0
        self.cards_removed = 0
        self.cards_transformed = 0
        self.cards_upgraded = 0
        self.relics_acquired = 0
        self.potions_acquired = 0
        self.potions_used = 0
        self.potions_discarded = 0
        self.rewards_skipped = 0
        self.hp_lost_combat = 0
        self.hp_lost_noncombat = 0
        self.rooms_completed = 0
        self.combats_completed = 0
        self.actions_attempted = 0
        self.actions_accepted = 0
        self.actions_rejected = 0
        self.actions_unverified = 0
        self.actions_skipped = 0
        self.partial_batches = 0
        self.unsupported_screens = 0
        self.decision_kinds: set[str] = set()
        self.action_types: set[str] = set()
        self.room_ids: set[str] = set()
        self.combat_ids: set[str] = set()
        self.combat_turns: set[tuple[str, int]] = set()
        self._previous: StateSnapshot | None = None
        self.replay_status: str | None = None
        self.replay_first_divergence: int | None = None

    def configure(self, *, seed: str, policy_mode: str) -> None:
        self.seed = seed
        self.policy_mode = policy_mode

    def observe_snapshot(self, snapshot: StateSnapshot) -> None:
        observation = snapshot.observation
        run = _dict(observation.get("run"))
        if not run:
            return
        self.decision_kinds.add(str(observation.get("decision_kind")))
        room_id = observation.get("room_id")
        combat_id = observation.get("combat_id")
        if isinstance(room_id, str):
            self.room_ids.add(room_id)
        if isinstance(combat_id, str):
            self.combat_ids.add(combat_id)
        combat = _dict(observation.get("combat"))
        turn = _integer(combat.get("turn"))
        if isinstance(combat_id, str) and turn is not None:
            self.combat_turns.add((combat_id, turn))

        hp = _integer(run.get("current_hp"))
        max_hp = _integer(run.get("max_hp"))
        gold = _integer(run.get("gold"))
        if self.starting_hp is None:
            self.character_id = run.get("character_id") if isinstance(run.get("character_id"), str) else None
            self.ascension = _integer(run.get("ascension"))
            self.starting_hp = hp
            self.minimum_hp = hp
        if hp is not None:
            self.final_hp = hp
            self.minimum_hp = hp if self.minimum_hp is None else min(self.minimum_hp, hp)
        self.final_max_hp = max_hp
        self.final_gold = gold
        self.final_act = _integer(run.get("act"))
        self.final_floor = _integer(run.get("floor"))
        self.final_room_type = run.get("room_type") if isinstance(run.get("room_type"), str) else None
        self.native_score = _integer(run.get("native_score"))
        if isinstance(run.get("outcome"), str):
            self.outcome = run["outcome"]
        if observation.get("decision_kind") == "unsupported":
            self.unsupported_screens += 1
            self.outcome = "FAILED_UNSUPPORTED_SCREEN"

        previous = self._previous
        if previous is not None:
            before_observation = previous.observation
            before_run = _dict(before_observation.get("run"))
            before_gold = _integer(before_run.get("gold"))
            if before_gold is not None and gold is not None:
                delta = gold - before_gold
                if delta > 0:
                    self.gold_gained += delta
                elif delta < 0:
                    self.gold_spent += -delta
            before_hp = _integer(before_run.get("current_hp"))
            if before_hp is not None and hp is not None and hp < before_hp:
                lost = before_hp - hp
                if before_observation.get("combat") is not None or observation.get("combat") is not None:
                    self.hp_lost_combat += lost
                else:
                    self.hp_lost_noncombat += lost

            before_deck = _deck_ids(before_observation)
            after_deck = _deck_ids(observation)
            added = sum((after_deck - before_deck).values())
            removed = sum((before_deck - after_deck).values())
            if added and removed and sum(after_deck.values()) == sum(before_deck.values()):
                transformed = min(added, removed)
                self.cards_transformed += transformed
                added -= transformed
                removed -= transformed
            self.cards_added += added
            self.cards_removed += removed
            self.cards_upgraded += max(0, _upgrade_total(observation) - _upgrade_total(before_observation))
            self.relics_acquired += sum((_relic_ids(observation) - _relic_ids(before_observation)).values())
            self.potions_acquired += sum((_potion_ids(observation) - _potion_ids(before_observation)).values())
            if observation.get("room_id") != before_observation.get("room_id"):
                self.rooms_completed += 1
        self._previous = snapshot

    def observe_action_result(self, result: dict[str, Any]) -> None:
        status = result.get("status")
        action_type = result.get("type")
        if isinstance(action_type, str):
            self.action_types.add(action_type)
        if status != "skipped":
            self.actions_attempted += 1
        if status == "accepted":
            self.actions_accepted += 1
        elif status == "rejected" or status == "native_failed":
            self.actions_rejected += 1
        elif status == "unverified":
            self.actions_unverified += 1
        elif status == "skipped":
            self.actions_skipped += 1
        if status == "accepted" and action_type == "use_potion":
            self.potions_used += 1
        if status == "accepted" and action_type == "discard_potion":
            self.potions_discarded += 1
        selector = _dict(result.get("selector"))
        if (
            status == "accepted"
            and action_type == "return_or_skip"
            and selector.get("decision_kind") in {"card_reward", "combat_reward", "boss_reward"}
        ):
            self.rewards_skipped += 1

    def observe_events(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            if event.get("type") == "combat_completed":
                self.combats_completed += 1
            elif event.get("type") == "ACTION_PARTIAL_SUCCESS":
                self.partial_batches += 1

    def set_replay(self, status: str, first_divergence: int | None = None) -> None:
        self.replay_status = status
        self.replay_first_divergence = first_divergence

    def document(
        self,
        *,
        state_count: int,
        decision_count: int,
        duplicate_state_count: int,
        process_wall_ms: int | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "sts-episode-metrics.v1",
            "character_id": self.character_id,
            "ascension": self.ascension,
            "seed": self.seed,
            "policy_mode": self.policy_mode,
            "final_act": self.final_act,
            "final_floor": self.final_floor,
            "final_room_type": self.final_room_type,
            "native_score": self.native_score,
            "outcome": self.outcome,
            "starting_hp": self.starting_hp,
            "minimum_hp": self.minimum_hp,
            "final_hp": self.final_hp,
            "final_max_hp": self.final_max_hp,
            "hp_lost_combat": self.hp_lost_combat,
            "hp_lost_noncombat": self.hp_lost_noncombat,
            "final_gold": self.final_gold,
            "gold_gained": self.gold_gained,
            "gold_spent": self.gold_spent,
            "cards_added": self.cards_added,
            "cards_removed": self.cards_removed,
            "cards_transformed": self.cards_transformed,
            "cards_upgraded": self.cards_upgraded,
            "relics_acquired": self.relics_acquired,
            "potions_acquired": self.potions_acquired,
            "potions_used": self.potions_used,
            "potions_discarded": self.potions_discarded,
            "rewards_skipped": self.rewards_skipped,
            "combat_turns": len(self.combat_turns),
            "combats_entered": len(self.combat_ids),
            "combats_completed": self.combats_completed,
            "rooms_entered": len(self.room_ids),
            "rooms_completed": self.rooms_completed,
            "actions_attempted": self.actions_attempted,
            "actions_accepted": self.actions_accepted,
            "actions_rejected": self.actions_rejected,
            "actions_unverified": self.actions_unverified,
            "actions_skipped": self.actions_skipped,
            "partial_batches": self.partial_batches,
            "unsupported_screen_count": self.unsupported_screens,
            "state_count": state_count,
            "decision_count": decision_count,
            "deduplicated_state_count": duplicate_state_count,
            "decision_kinds": sorted(self.decision_kinds),
            "action_types": sorted(self.action_types),
            "process_wall_ms": process_wall_ms,
            "model_calls": None,
            "model_repairs": None,
            "model_input_tokens": None,
            "model_cache_read_tokens": None,
            "model_reasoning_tokens": None,
            "model_output_tokens": None,
            "model_total_tokens": None,
            "model_first_token_latency_ms": None,
            "model_generation_latency_ms": None,
            "model_end_to_end_latency_ms": None,
            "replay_parity_status": self.replay_status,
            "replay_first_divergence": self.replay_first_divergence,
        }
