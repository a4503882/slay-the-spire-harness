from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_json_bytes, sha256_document
from .transition import recompute_document_hash


POLICY_SCHEMA_VERSION = "sts-scripted-policy.v1"
POLICY_DECISION_SCHEMA_VERSION = "sts-scripted-policy-decision.v1"
CANDIDATE_SET_SCHEMA_VERSION = "sts-scripted-candidate-set.v1"
RANDOM_DRAW_SCHEMA_VERSION = "sts-scripted-random-draw.v1"
POLICY_STATE_SCHEMA_VERSION = "sts-scripted-policy-state.v1"
POLICY_VERSIONS = {
    "scripted_random_legal": "1.0.0",
    "scripted_greedy": "1.0.0",
}
FORBIDDEN_POLICY_INPUT_KEYS = {
    "seed",
    "uuid",
    "available_commands",
    "last_move_id",
    "second_last_move_id",
    "native_command",
    "controller_nonce",
    "raw",
}


class ScriptedPolicyFailure(RuntimeError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _integer(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key in forbidden or _contains_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def validate_policy_input(
    observation: dict[str, Any],
    legal_actions: dict[str, Any],
) -> None:
    if observation.get("schema_version") != "sts-observation.v1":
        raise ScriptedPolicyFailure("policy input has an unsupported observation schema")
    if observation.get("fairness_profile") != "player_visible.v1":
        raise ScriptedPolicyFailure("scripted baseline requires player_visible.v1")
    if legal_actions.get("schema_version") != "sts-legal-actions.v1":
        raise ScriptedPolicyFailure("policy input has an unsupported legal-action schema")
    if _contains_key(observation, FORBIDDEN_POLICY_INPUT_KEYS) or _contains_key(
        legal_actions,
        FORBIDDEN_POLICY_INPUT_KEYS,
    ):
        raise ScriptedPolicyFailure("policy input contains a forbidden hidden/native field")
    observation_hash = observation.get("observation_hash")
    if observation_hash != recompute_document_hash(observation, "observation_hash"):
        raise ScriptedPolicyFailure("policy observation hash is invalid")
    if legal_actions.get("observation_hash") != observation_hash:
        raise ScriptedPolicyFailure("legal actions reference another observation")
    if legal_actions.get("legal_actions_hash") != recompute_document_hash(
        legal_actions,
        "legal_actions_hash",
    ):
        raise ScriptedPolicyFailure("policy legal-action hash is invalid")


def semantic_candidate(action: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get("type")
    selector = action.get("selector")
    if not isinstance(action_type, str) or not isinstance(selector, dict):
        raise ScriptedPolicyFailure("legal action lacks a typed semantic selector")
    if selector.get("schema_version") != "sts-action-selector.v1":
        raise ScriptedPolicyFailure("legal action selector has an unsupported schema")
    candidate = {"type": action_type, "selector": deepcopy(selector)}
    if _contains_key(candidate, FORBIDDEN_POLICY_INPUT_KEYS):
        raise ScriptedPolicyFailure("semantic action candidate contains a forbidden field")
    return candidate


def ordered_candidates(
    legal_actions: dict[str, Any],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], str]:
    actions = _rows(legal_actions.get("actions"))
    if not actions:
        raise ScriptedPolicyFailure("non-terminal policy decision has no legal actions")
    keyed: list[tuple[bytes, dict[str, Any], dict[str, Any]]] = []
    seen: set[bytes] = set()
    for action in actions:
        candidate = semantic_candidate(action)
        key = canonical_json_bytes(candidate)
        if key in seen:
            raise ScriptedPolicyFailure("legal actions contain duplicate semantic candidates")
        seen.add(key)
        keyed.append((key, action, candidate))
    keyed.sort(key=lambda row: row[0])
    ordered = [(deepcopy(action), candidate) for _, action, candidate in keyed]
    candidate_set_hash = sha256_document(
        {
            "schema_version": CANDIDATE_SET_SCHEMA_VERSION,
            "candidates": [candidate for _, candidate in ordered],
        }
    )
    return ordered, candidate_set_hash


@dataclass(frozen=True)
class PolicyChoice:
    action: dict[str, Any]
    semantic_action: dict[str, Any]
    candidate_count: int
    candidate_set_hash: str
    selected_index: int
    selection_evidence: dict[str, Any]
    state_before: dict[str, Any]
    state_after: dict[str, Any]


class ScriptedPolicy:
    policy_id: str
    policy_version: str
    algorithm_id: str

    def descriptor(self) -> dict[str, Any]:
        raise NotImplementedError

    def state_document(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_STATE_SCHEMA_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
        }

    def choose(
        self,
        *,
        observation: dict[str, Any],
        legal_actions: dict[str, Any],
        decision_index: int,
    ) -> PolicyChoice:
        raise NotImplementedError


class RandomLegalPolicy(ScriptedPolicy):
    policy_id = "scripted_random_legal"
    policy_version = POLICY_VERSIONS[policy_id]
    algorithm_id = "sha256-rejection-v1"

    def __init__(self, policy_seed: str) -> None:
        if not isinstance(policy_seed, str) or not policy_seed:
            raise ScriptedPolicyFailure("random-legal policy requires a non-empty policy seed")
        if len(policy_seed.encode("utf-8")) > 256:
            raise ScriptedPolicyFailure("policy seed exceeds 256 UTF-8 bytes")
        self.policy_seed = policy_seed

    def descriptor(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "fairness_profile": "player_visible.v1",
            "deterministic_given_policy_seed": True,
            "policy_seed": self.policy_seed,
            "algorithm_id": self.algorithm_id,
            "candidate_order": "canonical-semantic-action-utf8-ascending",
            "tactical_solver": False,
        }

    def choose(
        self,
        *,
        observation: dict[str, Any],
        legal_actions: dict[str, Any],
        decision_index: int,
    ) -> PolicyChoice:
        if not isinstance(decision_index, int) or isinstance(decision_index, bool) or decision_index < 0:
            raise ScriptedPolicyFailure("policy decision index must be a non-negative integer")
        validate_policy_input(observation, legal_actions)
        ordered, candidate_set_hash = ordered_candidates(legal_actions)
        candidate_count = len(ordered)
        state_before = self.state_document()
        range_size = 1 << 256
        acceptance_limit = range_size - (range_size % candidate_count)
        counter = 0
        while True:
            draw_basis = {
                "schema_version": RANDOM_DRAW_SCHEMA_VERSION,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "policy_seed": self.policy_seed,
                "decision_index": decision_index,
                "candidate_set_hash": candidate_set_hash,
                "counter": counter,
            }
            digest_bytes = hashlib.sha256(canonical_json_bytes(draw_basis)).digest()
            draw_value = int.from_bytes(digest_bytes, "big")
            if draw_value < acceptance_limit:
                break
            counter += 1
        selected_index = draw_value % candidate_count
        action, candidate = ordered[selected_index]
        return PolicyChoice(
            action=action,
            semantic_action=candidate,
            candidate_count=candidate_count,
            candidate_set_hash=candidate_set_hash,
            selected_index=selected_index,
            selection_evidence={
                "algorithm_id": self.algorithm_id,
                "draw_digest": "sha256:" + digest_bytes.hex(),
                "draw_counter": counter,
                "selected_index": selected_index,
            },
            state_before=state_before,
            state_after=self.state_document(),
        )


class GreedyPolicy(ScriptedPolicy):
    policy_id = "scripted_greedy"
    policy_version = POLICY_VERSIONS[policy_id]
    algorithm_id = "integer-score-canonical-tie-v1"

    def __init__(self) -> None:
        self.visited_shop_rooms: set[str] = set()

    def descriptor(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "fairness_profile": "player_visible.v1",
            "deterministic_given_policy_seed": True,
            "policy_seed": None,
            "algorithm_id": self.algorithm_id,
            "candidate_order": "canonical-semantic-action-utf8-ascending",
            "score_type": "integer",
            "tie_break": "lowest-canonical-semantic-index",
            "tactical_solver": False,
        }

    def state_document(self) -> dict[str, Any]:
        return {
            **super().state_document(),
            "visited_shop_rooms": sorted(self.visited_shop_rooms),
        }

    @staticmethod
    def _incoming_damage(observation: dict[str, Any]) -> int:
        total = 0
        for monster in _rows(_dict(observation.get("combat")).get("monsters")):
            if monster.get("is_gone") is True or _integer(monster.get("current_hp")) <= 0:
                continue
            if "ATTACK" not in str(monster.get("intent", "")):
                continue
            damage = _integer(monster.get("move_adjusted_damage"), -1)
            hits = _integer(monster.get("move_hits"), 1)
            if damage > 0 and hits > 0:
                total += damage * hits
        return total

    @staticmethod
    def _target_hp(observation: dict[str, Any], selector: dict[str, Any]) -> int:
        target = _dict(selector.get("target"))
        monster_id = target.get("monster_id")
        ordinal = target.get("spawn_ordinal")
        seen = 0
        for monster in _rows(_dict(observation.get("combat")).get("monsters")):
            if monster.get("monster_id") != monster_id:
                continue
            if seen == ordinal:
                return _integer(monster.get("current_hp"), 1_000_000)
            seen += 1
        return 1_000_000

    @staticmethod
    def _card_score(action: dict[str, Any]) -> int:
        selector = _dict(action.get("selector"))
        card = {**_dict(action.get("presentation")), **_dict(selector.get("card"))}
        card_id = str(card.get("card_id", ""))
        scores = {
            "Feed": 300,
            "Immolate": 290,
            "Corruption": 280,
            "Offering": 275,
            "Reaper": 270,
            "Demon Form": 260,
            "Barricade": 250,
            "Bludgeon": 240,
            "Limit Break": 235,
            "Inflame": 225,
            "Disarm": 220,
            "Uppercut": 215,
            "Shockwave": 210,
            "Flame Barrier": 205,
            "Metallicize": 205,
            "Shrug It Off": 200,
            "Pommel Strike": 190,
            "Battle Trance": 190,
            "Armaments": 185,
            "True Grit": 180,
            "Headbutt": 175,
            "Carnage": 170,
            "Combust": 165,
            "Clothesline": 160,
            "Iron Wave": 150,
            "Cleave": 145,
            "Berserk": 125,
        }
        rarity = str(card.get("rarity", ""))
        return scores.get(card_id, 140 if rarity == "RARE" else 40 if rarity == "UNCOMMON" else 0)

    @classmethod
    def _shop_buy_score(cls, action: dict[str, Any]) -> int:
        selector = _dict(action.get("selector"))
        item = _dict(selector.get("item"))
        kind = str(selector.get("item_kind", ""))
        item_id = str(item.get("item_id", item.get("card_id", "")))
        price_penalty = _integer(selector.get("price")) // 5
        if kind == "card":
            value = cls._card_score(
                {"selector": {"card": item}, "presentation": action.get("presentation", {})}
            )
        elif kind == "relic":
            value = {
                "Vajra": 350,
                "Bag of Preparation": 340,
                "Lantern": 330,
                "Anchor": 320,
                "Preserved Insect": 300,
                "Red Skull": 290,
                "Bag of Marbles": 270,
                "Oddly Smooth Stone": 260,
                "Orichalcum": 250,
                "Chemical X": 20,
            }.get(item_id, 180)
        elif kind == "potion":
            value = {
                "Strength Potion": 180,
                "StrengthPotion": 180,
                "PowerPotion": 170,
                "AttackPotion": 160,
                "Fire Potion": 150,
                "FirePotion": 150,
            }.get(item_id, 100)
        else:
            value = 0
        return value - price_penalty

    @staticmethod
    def _room_key(observation: dict[str, Any]) -> str:
        run = _dict(observation.get("run"))
        return f"act-{_integer(run.get('act'), -1)}-floor-{_integer(run.get('floor'), -1)}"

    def _combat_scores(
        self,
        observation: dict[str, Any],
        ordered: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[tuple[int, str]]:
        combat = _dict(observation.get("combat"))
        player = _dict(combat.get("player"))
        live_monsters = [
            monster
            for monster in _rows(combat.get("monsters"))
            if monster.get("is_gone") is not True and _integer(monster.get("current_hp")) > 0
        ]
        incoming = self._incoming_damage(observation)
        block = _integer(player.get("block"))
        hp = _integer(player.get("current_hp"), 80)
        turn = _integer(combat.get("turn"), 1)
        harmful = {"Bloodletting", "Offering", "Hemokinesis", "Brutality", "Combust"}
        premium = {
            "Demon Form": 180,
            "Inflame": 170,
            "Spot Weakness": 160,
            "Limit Break": 155,
            "Corruption": 145,
            "Barricade": 145,
            "Feel No Pain": 140,
            "Dark Embrace": 135,
            "Bash": 125,
            "Uppercut": 125,
            "Shockwave": 120,
            "Disarm": 120,
        }
        scores: list[tuple[int, str]] = []
        for action, candidate in ordered:
            action_type = candidate["type"]
            selector = _dict(candidate.get("selector"))
            if action_type == "end_turn":
                scores.append((0, "end-turn-fallback"))
                continue
            if action_type == "discard_potion":
                scores.append((-1_000, "preserve-held-potion"))
                continue
            if action_type == "use_potion":
                potion_id = str(selector.get("potion_id", ""))
                score = 20
                if potion_id in {"Fire Potion", "FirePotion", "Explosive Potion", "ExplosivePotion"}:
                    score = 260
                elif potion_id in {
                    "Strength Potion",
                    "StrengthPotion",
                    "Dexterity Potion",
                    "DexterityPotion",
                    "CultistPotion",
                    "PowerPotion",
                    "AttackPotion",
                    "SkillPotion",
                    "ColorlessPotion",
                }:
                    score = 230 if turn <= 2 else 25
                elif potion_id in {"Block Potion", "BlockPotion", "Speed Potion", "SpeedPotion"}:
                    score = 240 if incoming - block >= 10 else 15
                elif potion_id in {"Smoke Bomb", "SmokeBomb"}:
                    score = 300 if hp <= 15 else -100
                scores.append((score, "combat-potion"))
                continue
            if action_type != "play_card":
                scores.append((-10_000, "unsupported-combat-action"))
                continue
            presentation = _dict(action.get("presentation"))
            card = _dict(selector.get("card"))
            card_id = str(card.get("card_id", presentation.get("card_id", "")))
            card_type = str(presentation.get("type", card.get("type", "")))
            damage = _integer(presentation.get("damage", card.get("damage", 0)))
            block_value = _integer(presentation.get("block", card.get("block", 0)))
            cost = _integer(
                presentation.get(
                    "cost_for_turn",
                    presentation.get("cost", card.get("cost", 0)),
                )
            )
            score = premium.get(card_id, 0)
            if card_type == "POWER":
                score += 130 if turn <= 3 else 30
            if block_value > 0:
                remaining = max(0, incoming - block)
                score += min(block_value, remaining) * 12 + (70 if remaining > 0 else 5)
            if card_type == "ATTACK":
                target = _dict(selector.get("target"))
                if target:
                    score += 55 + max(0, damage) * 5
                    target_hp = self._target_hp(observation, selector)
                    if damage >= target_hp:
                        score += 1_000
                    elif damage * 2 >= target_hp:
                        score += 180
                    score += max(0, 40 - min(target_hp, 40))
                else:
                    affected = max(1, len(live_monsters))
                    score += 55 + max(0, damage) * 5 * affected
                    score += 45 * max(0, affected - 1)
                    score += 1_000 * sum(
                        1
                        for monster in live_monsters
                        if damage >= _integer(monster.get("current_hp"), 1_000_000)
                    )
            if card_id in {"Offering", "Bloodletting"} and hp > 35:
                score += 120
            elif card_id in harmful:
                score -= 180 if hp <= 25 else 40
            if cost == 0:
                score += 25
            scores.append((score, "combat-integer-score"))
        return scores

    def _scores(
        self,
        observation: dict[str, Any],
        ordered: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> list[tuple[int, str]]:
        kind = str(observation.get("decision_kind"))
        if kind == "combat":
            return self._combat_scores(observation, ordered)
        if kind == "map":
            run = _dict(observation.get("run"))
            hp = _integer(run.get("current_hp"), 80)
            max_hp = max(1, _integer(run.get("max_hp"), 80))
            gold = _integer(run.get("gold"))
            priorities = {"E": 65 if hp * 100 >= max_hp * 75 else -80, "M": 30, "?": 45, "$": 60 if gold >= 150 else 10, "R": 35, "T": 50}
            if hp * 100 < max_hp * 65:
                priorities["R"] = 140
            result = []
            for _, candidate in ordered:
                selector = _dict(candidate.get("selector"))
                if candidate["type"] != "choose_map_node":
                    result.append((-1_000, "avoid-nonprogress-map-return"))
                elif selector.get("boss") is True:
                    result.append((1_000, "choose-visible-boss-node"))
                else:
                    result.append(
                        (
                            priorities.get(str(selector.get("symbol", "")), 0),
                            "map-visible-risk-score",
                        )
                    )
            return result
        if kind == "combat_reward":
            priorities = {"GOLD": 600, "STOLEN_GOLD": 600, "RELIC": 550, "CARD": 500, "POTION": 450, "SAPPHIRE_KEY": 400}
            return [
                (
                    priorities.get(str(_dict(candidate.get("selector")).get("reward_type", "")), 0)
                    if _dict(candidate.get("selector")).get("semantic") == "claim_reward"
                    else 0,
                    "claim-visible-reward",
                )
                for _, candidate in ordered
            ]
        if kind == "card_reward":
            result: list[tuple[int, str]] = []
            for action, candidate in ordered:
                selector = _dict(candidate.get("selector"))
                if selector.get("semantic") == "take_card":
                    result.append((self._card_score(action), "card-reward-table"))
                elif selector.get("semantic") == "singing_bowl":
                    result.append((180, "singing-bowl"))
                else:
                    result.append((100, "skip-low-value-card"))
            return result
        if kind == "shop":
            shop = _dict(_dict(observation.get("screen")).get("shop"))
            room_key = self._room_key(observation)
            result = []
            for action, candidate in ordered:
                selector = _dict(candidate.get("selector"))
                action_type = candidate["type"]
                if shop.get("phase") == "entrance":
                    if action_type == "choose_option" and room_key not in self.visited_shop_rooms:
                        result.append((1_000, "enter-unvisited-shop"))
                    elif action_type == "proceed" and room_key in self.visited_shop_rooms:
                        result.append((1_000, "leave-visited-shop-room"))
                    else:
                        result.append((0, "shop-entrance-fallback"))
                elif action_type == "buy_item":
                    result.append((self._shop_buy_score(action), "shop-item-score"))
                elif selector.get("semantic") == "open_card_removal":
                    result.append((230, "remove-basic-card"))
                elif action_type == "return_or_skip":
                    result.append((0, "leave-shop"))
                else:
                    result.append((-100, "shop-fallback"))
            return result
        if kind == "rest":
            run = _dict(observation.get("run"))
            hp = _integer(run.get("current_hp"))
            max_hp = max(1, _integer(run.get("max_hp"), 1))
            prefer_rest = hp * 100 < max_hp * 75
            scores = {"rest": 400 if prefer_rest else 100, "smith": 350 if not prefer_rest else 120, "dig": 300, "lift": 280, "recall": 10}
            return [
                (scores.get(str(_dict(candidate.get("selector")).get("rest_action", "")), 0), "rest-visible-hp-score")
                for _, candidate in ordered
            ]
        if kind in {"grid_select", "hand_select"}:
            selection = _dict(_dict(observation.get("screen")).get("selection"))
            mode = str(selection.get("mode", "select"))
            selected_count = len(_rows(selection.get("selected_cards")))
            minimum = max(0, _integer(selection.get("minimum")))
            maximum = max(minimum, _integer(selection.get("maximum"), minimum))
            desired = maximum if mode in {"remove", "upgrade", "transform"} else minimum
            result = []
            for action, candidate in ordered:
                selector = _dict(candidate.get("selector"))
                if selector.get("confirm") is True:
                    # CommunicationMod may expose confirm_up=true while leaving
                    # selected_cards empty. The current legal confirm action is
                    # the authoritative player-visible proof that cardinality
                    # has been satisfied.
                    result.append((1_000, "confirm-current-legal-selection"))
                    continue
                if candidate["type"] == "return_or_skip":
                    result.append((-1_000, "avoid-cancelling-active-selection"))
                    continue
                cards = _rows(selector.get("cards"))
                card_id = str(_dict(cards[0] if cards else {}).get("card_id", ""))
                if selected_count >= desired:
                    score = -500
                elif mode == "remove":
                    score = 500 if card_id.startswith("Curse") else 450 if card_id == "Strike_R" else 300
                elif mode == "upgrade":
                    score = self._card_score({"selector": {"card": cards[0] if cards else {}}})
                elif mode == "transform":
                    score = 400 if card_id in {"Strike_R", "Defend_R"} else 250
                else:
                    score = self._card_score({"selector": {"card": cards[0] if cards else {}}}) + 200
                result.append((score, "visible-card-selection"))
            return result
        if kind == "boss_reward":
            relic_scores = {
                "Snecko Eye": 500,
                "Runic Pyramid": 480,
                "Black Blood": 420,
                "Coffee Dripper": 400,
                "Cursed Key": 390,
                "Astrolabe": 360,
                "Calling Bell": 340,
                "Ectoplasm": 120,
                "Busted Crown": 80,
            }
            result = []
            for _, candidate in ordered:
                selector = _dict(candidate.get("selector"))
                if selector.get("semantic") != "take_boss_relic":
                    result.append((-1_000, "avoid-skipping-boss-relic"))
                else:
                    result.append(
                        (
                            relic_scores.get(str(selector.get("relic_id", "")), 250),
                            "boss-relic-table",
                        )
                    )
            return result
        if kind in {"neow", "event"}:
            result = []
            for action, candidate in ordered:
                label = str(action.get("label", "")).lower()
                score = 100
                if any(word in label for word in ("heal", "恢复", "remove", "移除", "upgrade", "升级", "max hp", "最大生命", "gold", "金币")):
                    score += 80
                if any(word in label for word in ("leave", "离开")):
                    score += 30
                if any(word in label for word in ("curse", "诅咒", "lose hp", "失去生命", "fight", "战斗")):
                    score -= 80
                result.append((score, "visible-option-text-score"))
            return result
        preferred = {
            "choose_option": 300,
            "proceed": 250,
            "return_or_skip": 100,
            "end_turn": 0,
        }
        return [
            (preferred.get(candidate["type"], 0), "generic-visible-action-priority")
            for _, candidate in ordered
        ]

    def choose(
        self,
        *,
        observation: dict[str, Any],
        legal_actions: dict[str, Any],
        decision_index: int,
    ) -> PolicyChoice:
        if not isinstance(decision_index, int) or isinstance(decision_index, bool) or decision_index < 0:
            raise ScriptedPolicyFailure("policy decision index must be a non-negative integer")
        validate_policy_input(observation, legal_actions)
        kind = str(observation.get("decision_kind"))
        if kind in {"game_over", "victory"}:
            raise ScriptedPolicyFailure("policy was asked to act on a terminal state")
        if kind == "unsupported":
            raise ScriptedPolicyFailure("policy encountered an unsupported screen")
        ordered, candidate_set_hash = ordered_candidates(legal_actions)
        state_before = self.state_document()
        scores = self._scores(observation, ordered)
        if len(scores) != len(ordered):
            raise ScriptedPolicyFailure("greedy policy produced an incomplete score vector")
        best_score = max(score for score, _ in scores)
        selected_index = next(index for index, (score, _) in enumerate(scores) if score == best_score)
        action, candidate = ordered[selected_index]
        if kind == "shop":
            shop = _dict(_dict(observation.get("screen")).get("shop"))
            if shop.get("phase") == "entrance" and candidate["type"] == "choose_option":
                self.visited_shop_rooms.add(self._room_key(observation))
        return PolicyChoice(
            action=action,
            semantic_action=candidate,
            candidate_count=len(ordered),
            candidate_set_hash=candidate_set_hash,
            selected_index=selected_index,
            selection_evidence={
                "algorithm_id": self.algorithm_id,
                "selected_score": best_score,
                "selected_reason": scores[selected_index][1],
                "selected_index": selected_index,
            },
            state_before=state_before,
            state_after=self.state_document(),
        )


def create_policy(policy_id: str, policy_seed: str | None) -> ScriptedPolicy:
    if policy_id == "scripted_random_legal":
        if not isinstance(policy_seed, str):
            raise ScriptedPolicyFailure("scripted_random_legal requires policy_seed")
        return RandomLegalPolicy(policy_seed)
    if policy_id == "scripted_greedy":
        if policy_seed is not None:
            raise ScriptedPolicyFailure("scripted_greedy does not accept policy_seed")
        return GreedyPolicy()
    raise ScriptedPolicyFailure(f"unsupported scripted policy: {policy_id}")


def policy_descriptor(policy_id: str, policy_seed: str | None) -> dict[str, Any]:
    return create_policy(policy_id, policy_seed).descriptor()
