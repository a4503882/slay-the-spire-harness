from __future__ import annotations

from copy import deepcopy

import pytest

from sts_harness.canonical import sha256_document
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_checkpoint import build_replay_checkpoint
from sts_harness.scripted_baseline import (
    build_policy_decision_record,
    compute_policy_decision_hash,
)
from sts_harness.scripted_policy import (
    GreedyPolicy,
    RandomLegalPolicy,
    ScriptedPolicyFailure,
    create_policy,
    ordered_candidates,
)
from sts_harness.transition import recompute_document_hash

from h1b_fixtures import card, raw_state


def transition(raw: dict, *, episode: str = "ep_policy", native: str = "native_policy") -> dict:
    observation = StateNormalizer(episode, native).normalize(raw, 1)
    legal_actions = build_legal_actions(raw, observation).document
    return {
        "transition_index": 0,
        "observation": observation,
        "legal_actions": legal_actions,
        "replay_checkpoint": build_replay_checkpoint(observation, legal_actions),
    }


def combat_transition(*, act: int = 1) -> dict:
    strike = card("Strike_R", "combat-strike", target=True)
    defend = card("Defend_R", "combat-defend", card_type="SKILL", target=False)
    raw = raw_state(
        "NONE",
        commands=["play", "end", "state"],
        room_phase="COMBAT",
    )
    raw["game_state"]["act"] = act
    raw["game_state"]["combat_state"] = {
        "turn": 1,
        "hand": [strike, defend],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {
            "current_hp": 70,
            "max_hp": 80,
            "block": 0,
            "energy": 3,
            "powers": [],
            "orbs": [],
        },
        "monsters": [
            {
                "id": "JawWorm",
                "name": "Jaw Worm",
                "current_hp": 40,
                "max_hp": 40,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 11,
                "move_hits": 1,
                "powers": [],
            }
        ],
    }
    return transition(raw)


def reverse_legal_action_order(value: dict) -> dict:
    result = deepcopy(value)
    result["legal_actions"]["actions"].reverse()
    result["legal_actions"]["legal_actions_hash"] = recompute_document_hash(
        result["legal_actions"],
        "legal_actions_hash",
    )
    return result


def test_random_legal_is_reproducible_across_order_and_run_identity() -> None:
    first = combat_transition()
    second_raw = raw_state_for_transition(first)
    second = transition(
        second_raw,
        episode="ep_other",
        native="native_other",
    )
    second = reverse_legal_action_order(second)

    left = RandomLegalPolicy("AMIYA-RANDOM").choose(
        observation=first["observation"],
        legal_actions=first["legal_actions"],
        decision_index=7,
    )
    right = RandomLegalPolicy("AMIYA-RANDOM").choose(
        observation=second["observation"],
        legal_actions=second["legal_actions"],
        decision_index=7,
    )

    assert left.semantic_action == right.semantic_action
    assert left.candidate_set_hash == right.candidate_set_hash
    assert left.selection_evidence == right.selection_evidence


def raw_state_for_transition(value: dict) -> dict:
    observation = value["observation"]
    hand = observation["combat"]["hand"]
    strike = card("Strike_R", "combat-strike", target=True)
    defend = card("Defend_R", "combat-defend", card_type="SKILL", target=False)
    assert [row["card_id"] for row in hand] == ["Strike_R", "Defend_R"]
    raw = raw_state("NONE", commands=["play", "end", "state"], room_phase="COMBAT")
    raw["game_state"]["combat_state"] = {
        "turn": 1,
        "hand": [strike, defend],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {
            "current_hp": 70,
            "max_hp": 80,
            "block": 0,
            "energy": 3,
            "powers": [],
            "orbs": [],
        },
        "monsters": [
            {
                "id": "JawWorm",
                "name": "Jaw Worm",
                "current_hp": 40,
                "max_hp": 40,
                "block": 0,
                "is_gone": False,
                "intent": "ATTACK",
                "move_adjusted_damage": 11,
                "move_hits": 1,
                "powers": [],
            }
        ],
    }
    return raw


def test_random_legal_includes_every_current_action_and_records_draw() -> None:
    current = combat_transition()
    choice = RandomLegalPolicy("AMIYA-RANDOM").choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )

    assert choice.candidate_count == len(current["legal_actions"]["actions"])
    assert choice.semantic_action in [
        candidate for _, candidate in ordered_candidates(current["legal_actions"])[0]
    ]
    assert choice.selection_evidence["algorithm_id"] == "sha256-rejection-v1"
    assert choice.selection_evidence["draw_digest"].startswith("sha256:")


def test_random_legal_rejects_duplicate_semantic_candidates() -> None:
    current = combat_transition()
    duplicate = deepcopy(current["legal_actions"]["actions"][0])
    duplicate["action_id"] = "action_duplicate"
    current["legal_actions"]["actions"].append(duplicate)
    current["legal_actions"]["legal_actions_hash"] = recompute_document_hash(
        current["legal_actions"],
        "legal_actions_hash",
    )

    with pytest.raises(ScriptedPolicyFailure, match="duplicate semantic"):
        RandomLegalPolicy("AMIYA-RANDOM").choose(
            observation=current["observation"],
            legal_actions=current["legal_actions"],
            decision_index=0,
        )


def test_policy_rejects_hidden_native_input_even_with_valid_public_hash() -> None:
    current = combat_transition()
    current["observation"]["seed"] = 123
    current["observation"]["observation_hash"] = recompute_document_hash(
        current["observation"],
        "observation_hash",
    )
    current["legal_actions"]["observation_hash"] = current["observation"]["observation_hash"]
    current["legal_actions"]["legal_actions_hash"] = recompute_document_hash(
        current["legal_actions"],
        "legal_actions_hash",
    )

    with pytest.raises(ScriptedPolicyFailure, match="forbidden"):
        GreedyPolicy().choose(
            observation=current["observation"],
            legal_actions=current["legal_actions"],
            decision_index=0,
        )


def test_greedy_policy_does_not_inherit_h1b_act2_terminal_strategy() -> None:
    current = combat_transition(act=2)
    choice = GreedyPolicy().choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )

    assert choice.semantic_action["type"] == "play_card"


def test_greedy_tie_break_uses_canonical_semantics_not_action_order() -> None:
    raw = raw_state(
        "MAP",
        screen_state={
            "current_node": {"x": 1, "y": 3, "symbol": "M"},
            "next_nodes": [
                {"x": 2, "y": 4, "symbol": "M"},
                {"x": 0, "y": 4, "symbol": "M"},
            ],
            "first_node_chosen": True,
            "boss_available": False,
        },
        choices=["right", "left"],
        commands=["choose", "state"],
    )
    first = transition(raw)
    second = reverse_legal_action_order(first)

    left = GreedyPolicy().choose(
        observation=first["observation"],
        legal_actions=first["legal_actions"],
        decision_index=0,
    )
    right = GreedyPolicy().choose(
        observation=second["observation"],
        legal_actions=second["legal_actions"],
        decision_index=0,
    )

    assert left.semantic_action == right.semantic_action
    assert left.semantic_action["selector"]["x"] == 0


def test_greedy_chooses_only_progress_node_when_map_return_scores_higher() -> None:
    raw = raw_state(
        "MAP",
        screen_state={
            "current_node": {"x": 0, "y": 3, "symbol": "$"},
            "next_nodes": [{"x": 0, "y": 4, "symbol": "E"}],
            "first_node_chosen": True,
            "boss_available": False,
        },
        choices=["elite"],
        commands=["choose", "return", "state"],
    )
    raw["game_state"]["current_hp"] = 40
    current = transition(raw)
    choice = GreedyPolicy().choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )

    assert choice.semantic_action["type"] == "choose_map_node"
    assert choice.semantic_action["selector"]["symbol"] == "E"


def test_greedy_shop_memory_is_player_visible_and_auditable() -> None:
    raw = raw_state(
        "SHOP_ROOM",
        choices=["shop"],
        commands=["choose", "proceed", "state"],
        room_type="ShopRoom",
    )
    current = transition(raw)
    policy = GreedyPolicy()
    first = policy.choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )
    second = policy.choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=1,
    )

    assert first.semantic_action["type"] == "choose_option"
    assert first.state_before["visited_shop_rooms"] == []
    assert first.state_after["visited_shop_rooms"] == ["act-1-floor-5"]
    assert second.semantic_action["type"] == "proceed"


def test_greedy_trusts_legal_confirm_when_bridge_omits_selected_cards() -> None:
    raw = raw_state(
        "GRID",
        screen_state={
            "cards": [card("Strike_R", "grid-strike")],
            "selected_cards": [],
            "num_cards": 1,
            "any_number": False,
            "for_upgrade": False,
            "for_transform": False,
            "for_purge": True,
            "confirm_up": True,
        },
        choices=[],
        commands=["confirm", "cancel", "state"],
    )
    current = transition(raw)
    choice = GreedyPolicy().choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )

    assert current["observation"]["screen"]["selection"]["selected_cards"] == []
    assert choice.semantic_action["type"] == "select_cards"
    assert choice.semantic_action["selector"]["confirm"] is True
    assert choice.selection_evidence["selected_reason"] == "confirm-current-legal-selection"


def test_greedy_does_not_skip_unknown_boss_relic() -> None:
    raw = raw_state(
        "BOSS_REWARD",
        screen_state={
            "relics": [
                {
                    "id": "Future Boss Relic",
                    "name": "Future Boss Relic",
                    "counter": -1,
                    "description": "Visible description",
                }
            ]
        },
        choices=["future boss relic"],
        commands=["choose", "skip", "state"],
    )
    current = transition(raw)
    choice = GreedyPolicy().choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )

    assert choice.semantic_action["selector"]["semantic"] == "take_boss_relic"


def test_policy_decision_record_recomputes_and_binds_state() -> None:
    current = combat_transition()
    policy = GreedyPolicy()
    choice = policy.choose(
        observation=current["observation"],
        legal_actions=current["legal_actions"],
        decision_index=0,
    )
    record = build_policy_decision_record(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_decision_index=0,
        transition=current,
        choice=choice,
        previous_chain_hash=None,
    )

    assert record["hashes"]["decision_hash"] == compute_policy_decision_hash(record)
    assert record["policy_state_before_hash"] == sha256_document(choice.state_before)
    forged = deepcopy(record)
    forged["selected_action"]["type"] = "end_turn"
    assert forged["hashes"]["decision_hash"] != compute_policy_decision_hash(forged)


def test_policy_factory_enforces_policy_seed_contract() -> None:
    assert create_policy("scripted_random_legal", "AMIYA").policy_id == "scripted_random_legal"
    assert create_policy("scripted_greedy", None).policy_id == "scripted_greedy"
    with pytest.raises(ScriptedPolicyFailure):
        create_policy("scripted_random_legal", None)
    with pytest.raises(ScriptedPolicyFailure):
        create_policy("scripted_greedy", "unexpected")
