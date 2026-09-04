from __future__ import annotations

from copy import deepcopy

from sts_harness.legal_actions import build_legal_actions
from sts_harness.metrics import EpisodeMetrics
from sts_harness.observation import StateNormalizer
from sts_harness.transition import make_snapshot

from test_legal_actions import combat_raw


def snapshot(normalizer: StateNormalizer, raw: dict, state_seq: int):
    observation = normalizer.normalize(raw, state_seq)
    legal = build_legal_actions(raw, observation)
    return make_snapshot(
        state_seq=state_seq,
        raw=raw,
        observation=observation,
        legal_actions=legal.document,
    )


def test_episode_metrics_use_null_for_unavailable_provider_values() -> None:
    normalizer = StateNormalizer("ep_metrics", "native_metrics")
    first_raw = combat_raw()
    first = snapshot(normalizer, first_raw, 1)
    second_raw = deepcopy(first_raw)
    second_raw["game_state"]["current_hp"] = 73
    second_raw["game_state"]["gold"] = 109
    second_raw["game_state"]["combat_state"]["player"]["current_hp"] = 73
    second_raw["game_state"]["combat_state"]["turn"] = 2
    second = snapshot(normalizer, second_raw, 2)

    metrics = EpisodeMetrics()
    metrics.configure(seed="AMIYA", policy_mode="scripted")
    metrics.observe_snapshot(first)
    metrics.observe_snapshot(second)
    metrics.observe_action_result({"type": "end_turn", "status": "accepted", "selector": {}})
    document = metrics.document(
        state_count=2,
        decision_count=2,
        duplicate_state_count=0,
        process_wall_ms=50,
    )
    assert document["starting_hp"] == 80
    assert document["minimum_hp"] == 73
    assert document["hp_lost_combat"] == 7
    assert document["gold_gained"] == 10
    assert document["combat_turns"] == 2
    assert document["actions_accepted"] == 1
    assert document["model_total_tokens"] is None
    assert document["replay_parity_status"] is None
