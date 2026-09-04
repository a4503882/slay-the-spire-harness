from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json
from .client import H1Client
from .legal_actions import submission_from_public_action


class FullDriverFailure(RuntimeError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


class ScriptedFullRunPolicy:
    def __init__(self) -> None:
        self.card_rewards_taken = 0
        self.shop_purge_opened = False
        self.shop_purchase_made = False
        self.shop_visited_rooms: set[str] = set()
        self.boss_reward_taken = False
        self.decision_kinds: set[str] = set()
        self.action_types: set[str] = set()

    @staticmethod
    def _incoming_damage(observation: dict[str, Any]) -> int:
        total = 0
        combat = _dict(observation.get("combat"))
        for monster in _rows(combat.get("monsters")):
            if monster.get("is_gone") is True or monster.get("current_hp", 0) <= 0:
                continue
            if "ATTACK" not in str(monster.get("intent", "")):
                continue
            damage = monster.get("move_adjusted_damage")
            hits = monster.get("move_hits", 1)
            if isinstance(damage, int) and isinstance(hits, int) and damage > 0 and hits > 0:
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
                hp = monster.get("current_hp")
                return hp if isinstance(hp, int) else 1_000_000
            seen += 1
        return 1_000_000

    def _combat_action(self, observation: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        combat = _dict(observation.get("combat"))
        player = _dict(combat.get("player"))
        live_monsters = [
            monster
            for monster in _rows(combat.get("monsters"))
            if monster.get("is_gone") is not True
            and isinstance(monster.get("current_hp"), int)
            and monster["current_hp"] > 0
        ]
        incoming = self._incoming_damage(observation)
        block = player.get("block", 0) if isinstance(player.get("block"), int) else 0
        hp = player.get("current_hp", 80) if isinstance(player.get("current_hp"), int) else 80
        turn = combat.get("turn", 1) if isinstance(combat.get("turn"), int) else 1

        # H1-B validates a complete native lifecycle, not baseline strength.
        # Once every required Act 1 path including boss reward has been crossed,
        # drive a bounded authentic native defeat instead of extending the guard
        # window with an unrelated performance run (which belongs to H1-C).
        run = _dict(observation.get("run"))
        if self.boss_reward_taken and run.get("act") == 2:
            end_turn = next((action for action in actions if action.get("type") == "end_turn"), None)
            if end_turn is None:
                raise FullDriverFailure("post-coverage combat has no native end_turn action")
            return end_turn

        potion_actions = [action for action in actions if action.get("type") == "use_potion"]
        for action in potion_actions:
            potion_id = str(_dict(action.get("selector")).get("potion_id", ""))
            if potion_id in {"Fire Potion", "FirePotion", "Explosive Potion", "ExplosivePotion"}:
                return action
            if potion_id in {
                "Strength Potion",
                "StrengthPotion",
                "Dexterity Potion",
                "DexterityPotion",
                "CultistPotion",
                "PowerPotion",
                "AttackPotion",
                "SkillPotion",
                "ColorlessPotion",
            } and turn <= 2:
                return action
            if potion_id in {"Block Potion", "BlockPotion", "Speed Potion", "SpeedPotion"} and incoming - block >= 10:
                return action
            if potion_id in {"Smoke Bomb", "SmokeBomb"} and hp <= 15:
                return action

        candidates: list[tuple[int, str, dict[str, Any]]] = []
        harmful = {
            "Bloodletting",
            "Offering",
            "Hemokinesis",
            "Brutality",
            "Combust",
        }
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
        for action in actions:
            if action.get("type") != "play_card":
                continue
            presentation = _dict(action.get("presentation"))
            selector = _dict(action.get("selector"))
            card = _dict(selector.get("card"))
            card_id = str(card.get("card_id", presentation.get("card_id", "")))
            card_type = str(presentation.get("type", card.get("type", "")))
            damage = presentation.get("damage", card.get("damage", 0))
            block_value = presentation.get("block", card.get("block", 0))
            cost = presentation.get("cost_for_turn", presentation.get("cost", card.get("cost", 0)))
            damage = damage if isinstance(damage, int) else 0
            block_value = block_value if isinstance(block_value, int) else 0
            cost = cost if isinstance(cost, int) else 0
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
                    # Native non-target attacks damage every live monster. Value
                    # their board-wide damage and immediate kills so multi-enemy
                    # fights do not incorrectly prefer one Defend over Cleave.
                    affected = max(1, len(live_monsters))
                    score += 55 + max(0, damage) * 5 * affected
                    score += 45 * max(0, affected - 1)
                    score += 1_000 * sum(
                        1
                        for monster in live_monsters
                        if isinstance(monster.get("current_hp"), int)
                        and damage >= monster["current_hp"]
                    )
            if card_id in {"Offering", "Bloodletting"} and hp > 35:
                score += 120
            elif card_id in harmful:
                score -= 180 if hp <= 25 else 40
            if cost == 0:
                score += 25
            candidates.append((score, str(action.get("action_id", "")), action))
        if candidates:
            best = max(candidates, key=lambda row: (row[0], row[1]))
            if best[0] > 0:
                return best[2]
        end_turn = next((action for action in actions if action.get("type") == "end_turn"), None)
        if end_turn is None:
            raise FullDriverFailure("combat state has neither a useful card nor end_turn")
        return end_turn

    @staticmethod
    def _card_reward_score(action: dict[str, Any]) -> int:
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
        return scores.get(card_id, 140 if card.get("rarity") == "RARE" else 40 if card.get("rarity") == "UNCOMMON" else 0)

    @classmethod
    def _shop_buy_score(cls, action: dict[str, Any]) -> int:
        selector = _dict(action.get("selector"))
        item = _dict(selector.get("item"))
        kind = str(selector.get("item_kind", ""))
        item_id = str(item.get("item_id", item.get("card_id", "")))
        price = selector.get("price", 0)
        price_penalty = price // 5 if isinstance(price, int) else 0
        if kind == "card":
            value = cls._card_reward_score(
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

    def _map_action(self, observation: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        choices = [action for action in actions if action.get("type") == "choose_map_node"]
        if not choices:
            raise FullDriverFailure("map has no choose_map_node action")
        if any(_dict(action.get("selector")).get("boss") is True for action in choices):
            return next(action for action in choices if _dict(action.get("selector")).get("boss") is True)
        run = _dict(observation.get("run"))
        hp = run.get("current_hp", 80) if isinstance(run.get("current_hp"), int) else 80
        max_hp = run.get("max_hp", 80) if isinstance(run.get("max_hp"), int) else 80
        gold = run.get("gold", 0) if isinstance(run.get("gold"), int) else 0
        seen = self.decision_kinds
        priority: dict[str, int] = {"E": -100, "M": 20, "?": 35, "$": 30, "R": 40, "T": 45}
        if hp * 100 < max_hp * 65:
            priority["R"] = 150
        if "shop" not in seen and gold >= 75:
            priority["$"] = 130
        if "event" not in seen:
            priority["?"] = 120
        return max(
            choices,
            key=lambda action: (
                priority.get(str(_dict(action.get("selector")).get("symbol", "")), 0),
                -int(_dict(action.get("selector")).get("x", 0)),
            ),
        )

    def choose(self, transition: dict[str, Any]) -> dict[str, Any]:
        observation = _dict(transition.get("observation"))
        legal = _dict(transition.get("legal_actions"))
        kind = str(observation.get("decision_kind"))
        self.decision_kinds.add(kind)
        actions = _rows(legal.get("actions"))
        if kind in {"game_over", "victory"}:
            raise FullDriverFailure("policy was asked to act after terminal state")
        if kind == "unsupported":
            raise FullDriverFailure(
                f"UNSUPPORTED_SCREEN: {_dict(observation.get('screen')).get('native_screen_type')}"
            )
        if not actions:
            raise FullDriverFailure(f"no legal actions for decision kind {kind}")

        selected: dict[str, Any] | None = None
        if kind == "combat":
            selected = self._combat_action(observation, actions)
        elif kind == "map":
            selected = self._map_action(observation, actions)
        elif kind == "combat_reward":
            reward_actions = [
                action
                for action in actions
                if _dict(action.get("selector")).get("semantic") == "claim_reward"
            ]
            priorities = {"GOLD": 0, "STOLEN_GOLD": 0, "RELIC": 1, "CARD": 2, "POTION": 3, "SAPPHIRE_KEY": 4}
            if reward_actions:
                selected = min(
                    reward_actions,
                    key=lambda action: priorities.get(
                        str(_dict(action.get("selector")).get("reward_type")), 99
                    ),
                )
            else:
                selected = next((action for action in actions if action.get("type") == "proceed"), None)
        elif kind == "card_reward":
            card_actions = [
                action
                for action in actions
                if _dict(action.get("selector")).get("semantic") == "take_card"
            ]
            if card_actions and self.card_rewards_taken < 12:
                best = max(card_actions, key=lambda action: (self._card_reward_score(action), str(action.get("action_id"))))
                if self._card_reward_score(best) >= 100:
                    self.card_rewards_taken += 1
                    selected = best
            if selected is None:
                selected = next((action for action in actions if action.get("type") == "return_or_skip"), None)
        elif kind == "shop":
            shop = _dict(_dict(observation.get("screen")).get("shop"))
            room_id = str(observation.get("room_id"))
            if shop.get("phase") == "entrance":
                if room_id in self.shop_visited_rooms:
                    selected = next((action for action in actions if action.get("type") == "proceed"), None)
                else:
                    self.shop_visited_rooms.add(room_id)
                    selected = next((action for action in actions if action.get("type") == "choose_option"), None)
            else:
                self.shop_visited_rooms.add(room_id)
                removal = next(
                    (
                        action
                        for action in actions
                        if _dict(action.get("selector")).get("semantic") == "open_card_removal"
                    ),
                    None,
                )
                buys = [action for action in actions if action.get("type") == "buy_item"]
                if removal is not None and not self.shop_purge_opened:
                    self.shop_purge_opened = True
                    selected = removal
                elif buys and not self.shop_purchase_made:
                    self.shop_purchase_made = True
                    selected = max(buys, key=lambda action: (self._shop_buy_score(action), str(action.get("action_id"))))
                else:
                    selected = next((action for action in actions if action.get("type") == "return_or_skip"), None)
        elif kind == "rest":
            run = _dict(observation.get("run"))
            hp = run.get("current_hp", 0)
            max_hp = run.get("max_hp", 1)
            rest_actions = [action for action in actions if action.get("type") == "rest_site_action"]
            preferred = "rest" if isinstance(hp, int) and isinstance(max_hp, int) and hp < max_hp else "smith"
            selected = next(
                (
                    action
                    for action in rest_actions
                    if _dict(action.get("selector")).get("rest_action") == preferred
                ),
                rest_actions[0] if rest_actions else None,
            )
        elif kind in {"grid_select", "hand_select"}:
            confirm = next(
                (
                    action
                    for action in actions
                    if action.get("type") == "select_cards"
                    and _dict(action.get("selector")).get("confirm") is True
                ),
                None,
            )
            if confirm is not None:
                selected = confirm
            else:
                card_actions = [
                    action for action in actions if action.get("type") in {"select_cards", "remove_card"}
                ]
                mode = _dict(_dict(observation.get("screen")).get("selection")).get("mode")
                if mode == "remove":
                    selected = next(
                        (
                            action
                            for action in card_actions
                            if _dict(_dict(action.get("selector")).get("cards", [{}])[0]).get("card_id") == "Strike_R"
                        ),
                        card_actions[0] if card_actions else None,
                    )
                else:
                    selected = max(
                        card_actions,
                        key=lambda action: self._card_reward_score(
                            {
                                "selector": {
                                    "card": _dict(action.get("selector")).get("cards", [{}])[0]
                                }
                            }
                        ),
                        default=None,
                    )
        elif kind == "boss_reward":
            boss_actions = [action for action in actions if action.get("type") == "choose_option"]
            selected = next(
                (
                    action
                    for action in boss_actions
                    if _dict(action.get("selector")).get("relic_id")
                    in {"Black Blood", "Snecko Eye", "Runic Pyramid", "Coffee Dripper"}
                ),
                boss_actions[0] if boss_actions else None,
            )
            if selected is not None:
                self.boss_reward_taken = True
        elif kind in {"neow", "event", "treasure", "room_complete"}:
            if kind == "event":
                def event_score(action: dict[str, Any]) -> int:
                    text = str(action.get("label", "")).lower()
                    score = 0
                    if any(word in text for word in ("leave", "离开", "heal", "恢复", "remove", "移除", "upgrade", "升级")):
                        score += 50
                    if any(word in text for word in ("curse", "诅咒", "lose hp", "失去生命", "fight", "战斗")):
                        score -= 50
                    return score

                selected = max(actions, key=lambda action: (event_score(action), -int(_dict(action.get("selector")).get("choice_ordinal", 0))))
            else:
                selected = next(
                    (action for action in actions if action.get("type") in {"choose_option", "proceed"}),
                    None,
                )
        if selected is None:
            selected = next((action for action in actions if action.get("type") in {"proceed", "return_or_skip"}), None)
        if selected is None:
            raise FullDriverFailure(f"scripted policy has no supported action for {kind}")
        self.action_types.add(str(selected.get("type")))
        return selected


def _step_params(transition: dict[str, Any], action: dict[str, Any], request_index: int) -> dict[str, Any]:
    observation = transition["observation"]
    legal = transition["legal_actions"]
    return {
        "request_id": f"req_{request_index:06d}",
        "episode_id": observation["episode_id"],
        "native_session_id": observation["native_session_id"],
        "run_id": observation["run_id"],
        "expected_decision_id": observation["decision_id"],
        "expected_observation_hash": observation["observation_hash"],
        "expected_legal_actions_hash": legal["legal_actions_hash"],
        "stop_on_failure": True,
        "actions": [submission_from_public_action(action)],
    }


def run_full_episode(
    *,
    descriptor: Path,
    output: Path,
    seed: str,
    max_decisions: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while not descriptor.is_file():
        if time.monotonic() >= deadline:
            raise FullDriverFailure("timed out waiting for sidecar descriptor")
        time.sleep(0.05)
    client = H1Client.from_descriptor(descriptor, timeout_seconds=min(60.0, timeout_seconds))
    policy = ScriptedFullRunPolicy()
    transition: dict[str, Any] | None = None
    decision_count = 0
    terminal_reached = False
    error: str | None = None
    close_result: dict[str, Any] | None = None
    try:
        transition = client.invoke(
            "env.reset",
            {
                "character_id": "IRONCLAD",
                "ascension": 0,
                "seed": seed,
                "fairness_profile": "player_visible.v1",
                "policy_mode": "h1b_acceptance",
                "max_episode_decisions": max_decisions,
                "max_episode_seconds": int(timeout_seconds),
            },
            mutating=True,
        )
        while decision_count < max_decisions:
            observation = _dict(transition.get("observation"))
            policy.decision_kinds.add(str(observation.get("decision_kind")))
            if transition.get("terminal") is True or observation.get("decision_kind") in {"game_over", "victory"}:
                terminal_reached = True
                break
            if transition.get("truncated") is True:
                raise FullDriverFailure(str(transition.get("outcome")))
            action = policy.choose(transition)
            transition = client.invoke(
                "env.step",
                _step_params(transition, action, decision_count + 1),
                mutating=True,
            )
            decision_count += 1
            results = _rows(transition.get("action_results"))
            if len(results) != 1 or results[0].get("status") != "accepted" or results[0].get("verified") is not True:
                raise FullDriverFailure(f"action was not independently verified: {results}")
        if not terminal_reached:
            raise FullDriverFailure("decision limit reached before native terminal state")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if transition is not None:
                observation = transition["observation"]
                close_result = client.invoke(
                    "env.close",
                    {
                        "episode_id": observation["episode_id"],
                        "native_session_id": observation["native_session_id"],
                        "run_id": observation["run_id"],
                    },
                    mutating=True,
                )
            else:
                close_result = client.invoke("quit", {}, mutating=True)
        except Exception as close_exc:
            if error is None:
                error = f"close failed: {type(close_exc).__name__}: {close_exc}"

    observation = _dict(transition.get("observation")) if isinstance(transition, dict) else {}
    run = _dict(observation.get("run"))
    result = {
        "schema_version": "sts-h1b-full-driver-summary.v1",
        "status": "passed" if terminal_reached and error is None else "failed",
        "seed": seed,
        "terminal_reached": terminal_reached,
        "outcome": transition.get("outcome") if isinstance(transition, dict) else None,
        "decision_count": decision_count,
        "final_transition_index": transition.get("transition_index") if isinstance(transition, dict) else None,
        "final_decision_kind": observation.get("decision_kind"),
        "final_act": run.get("act"),
        "final_floor": run.get("floor"),
        "final_hp": run.get("current_hp"),
        "decision_kinds": sorted(policy.decision_kinds),
        "action_types": sorted(policy.action_types),
        "post_coverage_terminal_strategy": "act2_end_turn_until_native_defeat",
        "post_coverage_terminal_strategy_activated": policy.boss_reward_taken,
        "final_chain_hash": _dict(transition.get("hashes")).get("chain_hash") if isinstance(transition, dict) else None,
        "final_replay_checkpoint_hash": _dict(transition.get("replay_checkpoint")).get("replay_checkpoint_hash") if isinstance(transition, dict) else None,
        "close_result": close_result,
        "error": error,
    }
    atomic_write_json(output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a complete deterministic H1-B episode")
    parser.add_argument("--descriptor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--max-decisions", type=int, default=5000)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_full_episode(
            descriptor=args.descriptor.resolve(),
            output=args.output.resolve(),
            seed=args.seed,
            max_decisions=args.max_decisions,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "schema_version": "sts-h1b-full-driver-summary.v1",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        atomic_write_json(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
