from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from sts_harness import scripted_baseline
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_checkpoint import build_replay_checkpoint
from sts_harness.scripted_baseline import run_scripted_baseline_episode

from h1b_fixtures import card, raw_state


def initial_transition() -> dict:
    strike = card("Strike_R", "driver-strike", target=True)
    raw = raw_state("NONE", commands=["play", "end", "state"], room_phase="COMBAT")
    raw["game_state"]["combat_state"] = {
        "turn": 1,
        "hand": [strike],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {"current_hp": 6, "max_hp": 80, "block": 0, "energy": 3, "powers": [], "orbs": []},
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
    observation = StateNormalizer("ep_driver", "native_driver").normalize(raw, 1)
    legal = build_legal_actions(raw, observation).document
    return {
        "transition_index": 0,
        "terminal": False,
        "truncated": False,
        "outcome": None,
        "observation": observation,
        "legal_actions": legal,
        "replay_checkpoint": build_replay_checkpoint(observation, legal),
        "action_results": [],
        "hashes": {"chain_hash": "sha256:initial"},
    }


@pytest.mark.parametrize(
    ("policy_id", "policy_seed"),
    [
        ("scripted_random_legal", "AMIYADRIVER"),
        ("scripted_greedy", None),
    ],
)
def test_scripted_driver_records_policy_choice_and_reaches_native_terminal(
    tmp_path: Path,
    monkeypatch,
    policy_id: str,
    policy_seed: str | None,
) -> None:
    descriptor = tmp_path / "sidecar.json"
    descriptor.write_text("{}", encoding="utf-8")
    before = initial_transition()
    calls: list[tuple[str, dict | None]] = []

    class FakeClient:
        @classmethod
        def from_descriptor(cls, path: Path, timeout_seconds: float):
            assert path == descriptor
            return cls()

        def invoke(self, method: str, params: dict | None = None, *, mutating: bool = False):
            calls.append((method, params))
            if method == "capabilities":
                return {
                    "raw_command_submission": False,
                    "fairness_profiles": ["player_visible.v1"],
                }
            if method == "env.reset":
                assert params["policy_mode"] == policy_id
                return deepcopy(before)
            if method == "env.step":
                submitted = params["actions"][0]
                after = deepcopy(before)
                after["transition_index"] = 1
                after["terminal"] = True
                after["outcome"] = "DEFEAT_COMBAT"
                after["observation"]["decision_kind"] = "game_over"
                after["observation"]["ready_for_action"] = False
                after["observation"]["run"]["outcome"] = "DEFEAT_COMBAT"
                after["observation"]["run"]["current_hp"] = 0
                after["legal_actions"]["actions"] = []
                after["action_results"] = [
                    {
                        "status": "accepted",
                        "verified": True,
                        "type": submitted["type"],
                    }
                ]
                after["hashes"] = {"chain_hash": "sha256:terminal"}
                return after
            if method == "env.close":
                return {"close_requested": True}
            raise AssertionError(method)

    monkeypatch.setattr(scripted_baseline, "H1Client", FakeClient)
    output = tmp_path / "baseline-driver.json"
    result = run_scripted_baseline_episode(
        descriptor=descriptor,
        output=output,
        seed="AMIYA20260904",
        policy_id=policy_id,
        policy_seed=policy_seed,
        max_decisions=10,
        timeout_seconds=10,
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "policy-decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["status"] == "passed"
    assert result["episode_status"] == "terminal"
    assert result["outcome"] == "DEFEAT_COMBAT"
    assert result["policy_decision_count"] == 1
    assert result["final_policy_decision_chain_hash"] == records[0]["hashes"]["chain_hash"]
    assert records[0]["selected_action"]["type"] in {"play_card", "end_turn"}
    assert [method for method, _ in calls] == [
        "capabilities",
        "env.reset",
        "env.step",
        "env.close",
    ]
