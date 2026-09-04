from __future__ import annotations

import json
from pathlib import Path

import pytest

from sts_harness import h1c_run
from sts_harness.canonical import sha256_document
from sts_harness.h1c_run import H1CSuiteFailure, _aggregate, run_h1c_suite, validate_suite_config


def suite_config() -> dict:
    return {
        "schema_version": "sts-scripted-baseline-suite.v1",
        "suite_id": "h1c-scripted-test-v1",
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


def test_suite_config_requires_exact_two_policy_contract() -> None:
    config = suite_config()
    assert validate_suite_config(config) is config

    extra = {**config, "unexpected": True}
    with pytest.raises(H1CSuiteFailure, match="fields differ"):
        validate_suite_config(extra)

    missing = suite_config()
    missing["policies"] = missing["policies"][:1]
    with pytest.raises(H1CSuiteFailure, match="exactly the two"):
        validate_suite_config(missing)

    wrong_version = suite_config()
    wrong_version["policies"][0]["policy_version"] = "9.0.0"
    with pytest.raises(H1CSuiteFailure, match="version"):
        validate_suite_config(wrong_version)

    hidden_native_seed_style = suite_config()
    hidden_native_seed_style["native_seeds"] = ["lowercase"]
    with pytest.raises(H1CSuiteFailure, match="uppercase"):
        validate_suite_config(hidden_native_seed_style)


def test_policy_aggregate_is_integer_rational_and_policy_scoped() -> None:
    cases = [
        {
            "status": "passed",
            "episode_status": "terminal",
            "terminal_reached": True,
            "outcome": "DEFEAT_COMBAT",
            "metrics": {
                "final_floor": 10,
                "native_score": 100,
                "combat_turns": 20,
                "actions_attempted": 80,
            },
        },
        {
            "status": "passed",
            "episode_status": "terminal",
            "terminal_reached": True,
            "outcome": "VICTORY_ACT3",
            "metrics": {
                "final_floor": 51,
                "native_score": 900,
                "combat_turns": 100,
                "actions_attempted": 400,
            },
        },
    ]
    aggregate = _aggregate("scripted_greedy", cases)

    assert aggregate["policy_id"] == "scripted_greedy"
    assert aggregate["terminal_case_count"] == 2
    assert aggregate["victory_count"] == 1
    assert aggregate["defeat_count"] == 1
    assert aggregate["final_floor"] == {"numerator": 61, "denominator": 2}
    assert aggregate["native_score"] == {"numerator": 1000, "denominator": 2}


def _fake_report(policy_id: str, seed: str, run_root: str) -> dict:
    metrics = {
        "policy_mode": policy_id,
        "outcome": "DEFEAT_COMBAT",
        "final_floor": 8,
        "native_score": 75,
        "combat_turns": 15,
        "actions_attempted": 50,
    }
    return {
        "status": "passed",
        "run_root": run_root,
        "environment_fingerprint_id": "sha256:environment",
        "launch_error": None,
        "normal_guard": {"unchanged": True, "changes": []},
        "owned_java_stopped": True,
        "owned_worker_stopped": True,
        "sidecar_descriptor_removed": True,
        "residual_related_processes": [],
        "driver": {
            "status": "passed",
            "episode_status": "terminal",
            "terminal_reached": True,
            "truncated": False,
            "outcome": "DEFEAT_COMBAT",
        },
        "worker": {"metrics": metrics},
    }


def test_suite_runs_same_seed_matrix_serially_and_separates_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = suite_config()
    config_path = tmp_path / "suite.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    calls: list[dict] = []

    def fake_launch_episode(**kwargs):
        calls.append(kwargs)
        return _fake_report(
            kwargs["baseline_policy_id"],
            kwargs["seed"],
            str(tmp_path / kwargs["baseline_policy_id"]),
        )

    monkeypatch.setattr(h1c_run, "launch_episode", fake_launch_episode)
    report = run_h1c_suite(
        project_root=tmp_path,
        config_path=config_path,
        build_bridge=True,
    )

    assert report["status"] == "passed"
    assert [call["baseline_policy_id"] for call in calls] == [
        "scripted_random_legal",
        "scripted_greedy",
    ]
    assert [call["seed"] for call in calls] == ["AMIYA20260904", "AMIYA20260904"]
    assert [call["build_bridge"] for call in calls] == [True, False]
    assert report["suite_config_hash"] == sha256_document(config)
    assert set(report["results_by_policy"]) == {
        "scripted_random_legal",
        "scripted_greedy",
    }
    assert "combined_score" not in report
    assert report["h1b_acceptance_runs_included"] is False
    assert report["tactical_solver"]["status"] == "not_implemented"


def test_suite_halts_and_retains_not_run_case_after_launcher_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "suite.json"
    config_path.write_text(json.dumps(suite_config()), encoding="utf-8")

    def fail_launch(**kwargs):
        raise RuntimeError("preflight failed")

    monkeypatch.setattr(h1c_run, "launch_episode", fail_launch)
    report = run_h1c_suite(
        project_root=tmp_path,
        config_path=config_path,
        build_bridge=False,
    )
    statuses = [
        case["status"]
        for section in report["results_by_policy"].values()
        for case in section["cases"]
    ]

    assert report["status"] == "failed"
    assert sorted(statuses) == ["failed", "not_run"]
    assert "preflight failed" in report["halt_reason"]
