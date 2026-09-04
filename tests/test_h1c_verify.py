from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sts_harness.canonical import append_jsonl, atomic_write_json, sha256_document
from sts_harness.h1c_run import _aggregate
from sts_harness.h1c_verify import _verify_policy_decisions, verify_h1c_suite
from sts_harness.legal_actions import build_legal_actions
from sts_harness.observation import StateNormalizer
from sts_harness.replay_checkpoint import build_replay_checkpoint
from sts_harness.scripted_baseline import build_policy_decision_record
from sts_harness.scripted_policy import GreedyPolicy

from h1b_fixtures import card, raw_state


def policy_transition() -> dict:
    strike = card("Strike_R", "verify-strike", target=True)
    raw = raw_state("NONE", commands=["play", "end", "state"], room_phase="COMBAT")
    raw["game_state"]["combat_state"] = {
        "turn": 1,
        "hand": [strike],
        "draw_pile": [],
        "discard_pile": [],
        "exhaust_pile": [],
        "limbo": [],
        "player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3, "powers": [], "orbs": []},
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
    observation = StateNormalizer("ep_verify", "native_verify").normalize(raw, 1)
    legal = build_legal_actions(raw, observation).document
    return {
        "transition_index": 0,
        "observation": observation,
        "legal_actions": legal,
        "replay_checkpoint": build_replay_checkpoint(observation, legal),
        "action_results": [],
    }


def test_policy_decision_audit_is_independently_reexecuted_and_tamper_detected(
    tmp_path: Path,
) -> None:
    before = policy_transition()
    policy = GreedyPolicy()
    choice = policy.choose(
        observation=before["observation"],
        legal_actions=before["legal_actions"],
        decision_index=0,
    )
    record = build_policy_decision_record(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_decision_index=0,
        transition=before,
        choice=choice,
        previous_chain_hash=None,
    )
    append_jsonl(tmp_path / "policy-decisions.jsonl", record)
    after = {
        "transition_index": 1,
        "action_results": [
            {
                "type": choice.semantic_action["type"],
                "selector": choice.semantic_action["selector"],
            }
        ],
    }
    episode = {
        "driver": {
            "policy": policy.descriptor(),
            "policy_decision_count": 1,
            "final_policy_decision_chain_hash": record["hashes"]["chain_hash"],
        },
        "transitions": [before, after],
        "action_count": 1,
    }

    valid = _verify_policy_decisions(
        run_dir=tmp_path,
        episode=episode,
        policy_id="scripted_greedy",
        policy_seed=None,
    )
    assert valid["valid"] is True

    forged = deepcopy(record)
    forged["selection_evidence"]["selected_score"] += 1
    (tmp_path / "policy-decisions.jsonl").unlink()
    append_jsonl(tmp_path / "policy-decisions.jsonl", forged)
    invalid = _verify_policy_decisions(
        run_dir=tmp_path,
        episode=episode,
        policy_id="scripted_greedy",
        policy_seed=None,
    )
    assert invalid["valid"] is False
    assert invalid["failure_index"] == 0


def test_suite_verifier_filters_embedded_case_lists_without_treating_them_as_paths(
    tmp_path: Path,
) -> None:
    config = {
        "schema_version": "sts-scripted-baseline-suite.v1",
        "suite_id": "h1c-scripted-empty-test-v1",
        "character_id": "IRONCLAD",
        "ascension": 0,
        "fairness_profile": "player_visible.v1",
        "native_seeds": ["AMIYA20260904"],
        "policies": [
            {
                "policy_id": "scripted_random_legal",
                "policy_version": "1.0.0",
                "policy_seed": "AMIYATEST",
            },
            {
                "policy_id": "scripted_greedy",
                "policy_version": "1.0.0",
                "policy_seed": None,
            },
        ],
        "max_episode_decisions": 2000,
        "max_episode_seconds": 1800,
        "require_native_terminal": True,
    }
    report = {
        "schema_version": "sts-scripted-baseline-suite-report.v1",
        "status": "failed",
        "suite_id": config["suite_id"],
        "suite_root": str(tmp_path),
        "suite_config": config,
        "suite_config_hash": sha256_document(config),
        "case_count": 0,
        "same_environment_for_every_run": False,
        "same_native_seed_matrix_for_every_policy": False,
        "results_by_policy": {
            policy_id: {
                "cases": [],
                "aggregate": _aggregate(policy_id, []),
            }
            for policy_id in ("scripted_random_legal", "scripted_greedy")
        },
        "combined_score_prohibited": True,
        "h1b_acceptance_runs_included": False,
        "tactical_solver": {
            "included": False,
            "status": "not_implemented",
            "performance_claim": None,
        },
        "halt_reason": None,
    }
    atomic_write_json(tmp_path / "suite-config.json", config)
    atomic_write_json(tmp_path / "suite-report.json", report)

    result = verify_h1c_suite(tmp_path)

    assert result["valid"] is False
    assert "configured_case_count_matches" in result["failures"]
    assert result["case_errors"] == []
