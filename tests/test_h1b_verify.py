from __future__ import annotations

from copy import deepcopy

from sts_harness.action_verify import verify_action_effect
from sts_harness.h1b_verify import _proof_matches
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


def test_independent_verifier_accepts_only_a_provable_settled_effect() -> None:
    normalizer = StateNormalizer("ep_verify", "native_verify")
    before, legal = _snapshot(normalizer, combat_raw(), 1)
    native = next(iter(legal.native_actions.values()))

    intermediate_raw = deepcopy(combat_raw())
    intermediate_raw["game_state"]["combat_state"]["player"]["block"] = 1
    intermediate, _ = _snapshot(normalizer, intermediate_raw, 2)

    final_raw = deepcopy(intermediate_raw)
    final_raw["game_state"]["combat_state"]["hand"] = final_raw["game_state"][
        "combat_state"
    ]["hand"][1:]
    final, _ = _snapshot(normalizer, final_raw, 3)
    verified, proof = verify_action_effect(native, before, final)
    assert verified is True
    recorded = {
        **proof,
        "verification_attempts": 2,
        "initial_post_state_seq": 2,
        "settled_post_state_seq": 3,
    }

    assert _proof_matches(
        native=native,
        before=before,
        after=final,
        recorded_proof=recorded,
        snapshots={1: before, 2: intermediate, 3: final},
    )

    forged = deepcopy(recorded)
    forged["initial_post_state_seq"] = 3
    assert not _proof_matches(
        native=native,
        before=before,
        after=final,
        recorded_proof=forged,
        snapshots={1: before, 2: intermediate, 3: final},
    )
