from __future__ import annotations

from copy import deepcopy

from sts_harness.action_verify import verify_action_effect
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.transition import make_snapshot

from test_legal_actions import combat_raw


def _snapshot(normalizer: StateNormalizer, raw: dict, state_seq: int):
    observation = normalizer.normalize(raw, state_seq)
    legal = build_legal_actions(raw, observation)
    return (
        make_snapshot(
            state_seq=state_seq,
            raw=raw,
            observation=observation,
            legal_actions=legal.document,
        ),
        legal,
    )


def test_play_card_requires_the_selected_instance_to_leave_hand() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(iter(legal.native_actions.values()))
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["hand"] = after_raw["game_state"]["combat_state"]["hand"][1:]
    after_raw["game_state"]["combat_state"]["player"]["energy"] = 2
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["pre_location"] == "hand"
    assert proof["post_location"] != "hand"


def test_play_card_rejects_an_unrelated_state_change() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(iter(legal.native_actions.values()))
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["player"]["block"] = 1
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, _ = verify_action_effect(action, before, after)
    assert verified is False


def test_end_turn_requires_turn_advance_or_combat_end() -> None:
    normalizer = StateNormalizer("ep_test", "native_test")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    action = next(value for value in legal.native_actions.values() if value.action_type == "end_turn")
    after_raw = deepcopy(combat_raw())
    after_raw["game_state"]["combat_state"]["turn"] = 2
    after, _ = _snapshot(normalizer, after_raw, 2)
    verified, proof = verify_action_effect(action, before, after)
    assert verified is True
    assert proof["post_turn"] == 2

