from __future__ import annotations

from copy import deepcopy

import pytest

from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_checkpoint import (
    ReplayCheckpointFailure,
    bounded_structural_diff,
    build_replay_checkpoint,
    resolve_action_selector,
)

from test_legal_actions import combat_raw


def _documents(episode: str, native: str, raw: dict):
    observation = StateNormalizer(episode, native).normalize(raw, 1)
    legal = build_legal_actions(raw, observation).document
    return observation, legal


def test_checkpoint_rebases_run_local_identity() -> None:
    first_raw = combat_raw()
    second_raw = deepcopy(first_raw)
    for card in second_raw["game_state"]["deck"]:
        card["uuid"] = "second-deck-" + card["uuid"]
    for card in second_raw["game_state"]["combat_state"]["hand"]:
        card["uuid"] = "second-hand-" + card["uuid"]
    first_observation, first_legal = _documents("ep_first", "native_first", first_raw)
    second_observation, second_legal = _documents("ep_second", "native_second", second_raw)
    assert first_observation["observation_hash"] != second_observation["observation_hash"]
    first_checkpoint = build_replay_checkpoint(first_observation, first_legal)
    second_checkpoint = build_replay_checkpoint(second_observation, second_legal)
    assert first_checkpoint == second_checkpoint


def test_checkpoint_detects_semantic_state_divergence() -> None:
    first_observation, first_legal = _documents("ep_first", "native_first", combat_raw())
    changed = combat_raw()
    changed["game_state"]["current_hp"] = 79
    changed["game_state"]["combat_state"]["player"]["current_hp"] = 79
    second_observation, second_legal = _documents("ep_second", "native_second", changed)
    first = build_replay_checkpoint(first_observation, first_legal)
    second = build_replay_checkpoint(second_observation, second_legal)
    assert first["replay_checkpoint_hash"] != second["replay_checkpoint_hash"]
    diff = bounded_structural_diff(first, second)
    assert any(row["path"].endswith("/current_hp") for row in diff)


def test_checkpoint_ignores_cached_card_values_outside_the_hand() -> None:
    first_raw = combat_raw()
    strike = deepcopy(first_raw["game_state"]["combat_state"]["hand"][0])
    first_raw["game_state"]["combat_state"]["hand"] = []
    first_raw["game_state"]["combat_state"]["discard_pile"] = [strike]
    second_raw = deepcopy(first_raw)
    first_raw["game_state"]["combat_state"]["discard_pile"][0].update(
        {"damage": 9, "block": 0, "cost_for_turn": 1}
    )
    second_raw["game_state"]["combat_state"]["discard_pile"][0].update(
        {"damage": 6, "block": -1, "cost_for_turn": 3}
    )
    first_observation, first_legal = _documents("ep_first", "native_first", first_raw)
    second_observation, second_legal = _documents("ep_second", "native_second", second_raw)

    assert first_observation["observation_hash"] != second_observation["observation_hash"]
    assert build_replay_checkpoint(first_observation, first_legal) == build_replay_checkpoint(
        second_observation, second_legal
    )


def test_checkpoint_retains_dynamic_card_values_in_the_hand() -> None:
    first_raw = combat_raw()
    second_raw = deepcopy(first_raw)
    first_raw["game_state"]["combat_state"]["hand"][0]["damage"] = 9
    second_raw["game_state"]["combat_state"]["hand"][0]["damage"] = 6
    first_observation, first_legal = _documents("ep_first", "native_first", first_raw)
    second_observation, second_legal = _documents("ep_second", "native_second", second_raw)

    first = build_replay_checkpoint(first_observation, first_legal)
    second = build_replay_checkpoint(second_observation, second_legal)
    assert first["replay_checkpoint_hash"] != second["replay_checkpoint_hash"]
    assert any(
        row["path"].endswith("/hand/0/damage")
        for row in bounded_structural_diff(first, second)
    )


def test_recorded_selector_resolves_across_runs() -> None:
    first_observation, first_legal = _documents("ep_first", "native_first", combat_raw())
    second_observation, second_legal = _documents("ep_second", "native_second", combat_raw())
    recorded = first_legal["actions"][0]
    resolved = resolve_action_selector(recorded["selector"], second_legal)
    assert resolved["type"] == recorded["type"]
    assert resolved["selector"] == recorded["selector"]
    assert resolved["payload"] == recorded["payload"]


def test_unknown_selector_is_not_silently_fuzzed() -> None:
    observation, legal = _documents("ep_test", "native_test", combat_raw())
    assert observation
    with pytest.raises(ReplayCheckpointFailure, match="not resolvable"):
        resolve_action_selector(
            {"schema_version": "sts-action-selector.v1", "type": "invented"},
            legal,
        )
