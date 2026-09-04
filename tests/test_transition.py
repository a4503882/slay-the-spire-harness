from __future__ import annotations

from copy import deepcopy

from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.transition import (
    build_transition,
    compute_chain_hash,
    compute_transition_hash,
    make_snapshot,
    raw_export_hash,
)

from test_legal_actions import combat_raw


def _snapshot(normalizer: StateNormalizer, raw: dict, state_seq: int):
    observation = normalizer.normalize(raw, state_seq)
    legal = build_legal_actions(raw, observation)
    return make_snapshot(
        state_seq=state_seq,
        raw=raw,
        observation=observation,
        legal_actions=legal.document,
    )


def test_raw_hash_ignores_native_uuid_and_command_set_order() -> None:
    first = combat_raw()
    second = deepcopy(first)
    second["available_commands"].reverse()
    second["game_state"]["deck"][0]["uuid"] = "another-native-uuid"
    second["game_state"]["combat_state"]["hand"][0]["uuid"] = "another-native-uuid"
    assert raw_export_hash(first) == raw_export_hash(second)


def test_transition_and_chain_hashes_recompute() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    first = _snapshot(normalizer, combat_raw(), 1)
    second_raw = deepcopy(combat_raw())
    second_raw["game_state"]["combat_state"]["player"]["energy"] = 2
    second_raw["game_state"]["combat_state"]["hand"] = second_raw["game_state"]["combat_state"]["hand"][1:]
    second = _snapshot(normalizer, second_raw, 2)

    initial = build_transition(
        episode_id="ep_test",
        transition_index=0,
        environment_fingerprint_id="sha256:environment",
        previous=None,
        current=first,
        previous_chain_hash=None,
        submitted_batch=None,
        action_results=[],
    )
    stepped = build_transition(
        episode_id="ep_test",
        transition_index=1,
        environment_fingerprint_id="sha256:environment",
        previous=first,
        current=second,
        previous_chain_hash=initial["hashes"]["chain_hash"],
        submitted_batch={"actions": [{"type": "play_card"}]},
        action_results=[{"status": "accepted"}],
    )
    assert initial["hashes"]["transition_hash"] == compute_transition_hash(initial)
    assert stepped["hashes"]["transition_hash"] == compute_transition_hash(stepped)
    assert stepped["hashes"]["chain_hash"] == compute_chain_hash(
        initial["hashes"]["chain_hash"],
        stepped["hashes"]["transition_hash"],
    )
    assert stepped["pre_hashes"] == first.hashes


def test_transition_hash_detects_a_modified_action_result() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    snapshot = _snapshot(normalizer, combat_raw(), 1)
    transition = build_transition(
        episode_id="ep_test",
        transition_index=0,
        environment_fingerprint_id="sha256:environment",
        previous=None,
        current=snapshot,
        previous_chain_hash=None,
        submitted_batch=None,
        action_results=[],
    )
    recorded = transition["hashes"]["transition_hash"]
    transition["action_results"].append({"status": "forged"})
    assert compute_transition_hash(transition) != recorded
