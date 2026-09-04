from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, sha256_document, strict_json_loads
from .episode_launcher import launch_episode
from .scripted_policy import POLICY_VERSIONS, policy_descriptor


SUITE_SCHEMA_VERSION = "sts-scripted-baseline-suite.v1"
CASE_RESULT_SCHEMA_VERSION = "sts-scripted-baseline-case-result.v1"
SUITE_REPORT_SCHEMA_VERSION = "sts-scripted-baseline-suite-report.v1"
REQUIRED_POLICIES = {"scripted_random_legal", "scripted_greedy"}


class H1CSuiteFailure(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise H1CSuiteFailure(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def validate_suite_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise H1CSuiteFailure("suite configuration must be an object")
    expected = {
        "schema_version",
        "suite_id",
        "character_id",
        "ascension",
        "fairness_profile",
        "native_seeds",
        "policies",
        "max_episode_decisions",
        "max_episode_seconds",
        "require_native_terminal",
    }
    _exact_keys(value, expected, "suite configuration")
    if value.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise H1CSuiteFailure("unsupported scripted baseline suite schema")
    suite_id = value.get("suite_id")
    if not isinstance(suite_id, str) or re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", suite_id) is None:
        raise H1CSuiteFailure("suite_id must be a stable lowercase identifier")
    if value.get("character_id") != "IRONCLAD" or value.get("ascension") != 0:
        raise H1CSuiteFailure("initial scripted suite accepts only IRONCLAD ascension 0")
    if value.get("fairness_profile") != "player_visible.v1":
        raise H1CSuiteFailure("formal scripted suite requires player_visible.v1")
    native_seeds = value.get("native_seeds")
    if (
        not isinstance(native_seeds, list)
        or not native_seeds
        or not all(
            isinstance(seed, str)
            and re.fullmatch(r"[A-Za-z0-9]+", seed) is not None
            and seed == seed.upper()
            for seed in native_seeds
        )
        or len(native_seeds) != len(set(native_seeds))
    ):
        raise H1CSuiteFailure("native_seeds must be a non-empty unique uppercase seed list")
    policies = value.get("policies")
    if not isinstance(policies, list) or len(policies) != len(REQUIRED_POLICIES):
        raise H1CSuiteFailure("suite must contain exactly the two required scripted policies")
    seen: set[str] = set()
    for index, policy in enumerate(policies):
        if not isinstance(policy, dict):
            raise H1CSuiteFailure(f"policy {index} must be an object")
        _exact_keys(policy, {"policy_id", "policy_version", "policy_seed"}, f"policy {index}")
        policy_id = policy.get("policy_id")
        if policy_id not in REQUIRED_POLICIES or policy_id in seen:
            raise H1CSuiteFailure(f"policy {index} has a missing, duplicate, or unsupported ID")
        seen.add(str(policy_id))
        if policy.get("policy_version") != POLICY_VERSIONS[policy_id]:
            raise H1CSuiteFailure(f"policy {policy_id} version does not match the implementation")
        expected_descriptor = policy_descriptor(str(policy_id), policy.get("policy_seed"))
        if expected_descriptor["policy_version"] != policy["policy_version"]:
            raise H1CSuiteFailure(f"policy {policy_id} descriptor version mismatch")
    if seen != REQUIRED_POLICIES:
        raise H1CSuiteFailure("suite policy set is incomplete")
    max_decisions = value.get("max_episode_decisions")
    max_seconds = value.get("max_episode_seconds")
    if not isinstance(max_decisions, int) or isinstance(max_decisions, bool) or not 1 <= max_decisions <= 10_000:
        raise H1CSuiteFailure("max_episode_decisions must be an integer in [1, 10000]")
    if not isinstance(max_seconds, int) or isinstance(max_seconds, bool) or not 1 <= max_seconds <= 14_400:
        raise H1CSuiteFailure("max_episode_seconds must be an integer in [1, 14400]")
    if value.get("require_native_terminal") is not True:
        raise H1CSuiteFailure("the initial H1-C acceptance suite must require native terminal states")
    return value


def load_suite_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise H1CSuiteFailure(f"suite configuration does not exist: {path}")
    return validate_suite_config(strict_json_loads(path.read_text(encoding="utf-8")))


def _case_result(
    *,
    case_id: str,
    seed: str,
    policy: dict[str, Any],
    report: dict[str, Any] | None,
    error: str | None,
    status: str,
) -> dict[str, Any]:
    driver = report.get("driver") if isinstance(report, dict) else None
    driver = driver if isinstance(driver, dict) else {}
    worker = report.get("worker") if isinstance(report, dict) else None
    worker = worker if isinstance(worker, dict) else {}
    metrics = worker.get("metrics") if isinstance(worker.get("metrics"), dict) else None
    return {
        "schema_version": CASE_RESULT_SCHEMA_VERSION,
        "case_id": case_id,
        "seed": seed,
        "policy": policy,
        "status": status,
        "episode_status": driver.get("episode_status"),
        "terminal_reached": driver.get("terminal_reached"),
        "truncated": driver.get("truncated"),
        "outcome": driver.get("outcome"),
        "run_root": report.get("run_root") if isinstance(report, dict) else None,
        "environment_fingerprint_id": (
            report.get("environment_fingerprint_id") if isinstance(report, dict) else None
        ),
        "metrics": metrics,
        "report": report,
        "error": error,
    }


def _ratio(total: int, count: int) -> dict[str, int]:
    return {"numerator": total, "denominator": count}


def _aggregate(policy_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [case for case in cases if case.get("status") == "passed"]
    metrics = [case["metrics"] for case in completed if isinstance(case.get("metrics"), dict)]
    outcomes = Counter(
        str(case.get("outcome"))
        for case in completed
        if isinstance(case.get("outcome"), str)
    )
    terminal = [case for case in completed if case.get("terminal_reached") is True]
    return {
        "schema_version": "sts-scripted-baseline-policy-aggregate.v1",
        "policy_id": policy_id,
        "configured_case_count": len(cases),
        "completed_case_count": len(completed),
        "terminal_case_count": len(terminal),
        "truncated_case_count": sum(case.get("episode_status") == "truncated" for case in cases),
        "failed_case_count": sum(case.get("status") == "failed" for case in cases),
        "not_run_case_count": sum(case.get("status") == "not_run" for case in cases),
        "victory_count": sum(str(case.get("outcome", "")).startswith("VICTORY") for case in terminal),
        "defeat_count": sum(str(case.get("outcome", "")).startswith("DEFEAT") for case in terminal),
        "outcome_counts": dict(sorted(outcomes.items())),
        "final_floor": _ratio(
            sum(int(metric["final_floor"]) for metric in metrics if isinstance(metric.get("final_floor"), int)),
            sum(isinstance(metric.get("final_floor"), int) for metric in metrics),
        ),
        "native_score": _ratio(
            sum(int(metric["native_score"]) for metric in metrics if isinstance(metric.get("native_score"), int)),
            sum(isinstance(metric.get("native_score"), int) for metric in metrics),
        ),
        "combat_turns": _ratio(
            sum(int(metric["combat_turns"]) for metric in metrics if isinstance(metric.get("combat_turns"), int)),
            sum(isinstance(metric.get("combat_turns"), int) for metric in metrics),
        ),
        "actions_attempted": _ratio(
            sum(int(metric["actions_attempted"]) for metric in metrics if isinstance(metric.get("actions_attempted"), int)),
            sum(isinstance(metric.get("actions_attempted"), int) for metric in metrics),
        ),
    }


def run_h1c_suite(
    *,
    project_root: Path,
    config_path: Path,
    build_bridge: bool = True,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    config_path = config_path.resolve()
    config = load_suite_config(config_path)
    config_hash = sha256_document(config)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suite_root = (
        project_root
        / "artifacts"
        / "h1c-scripted-corpus"
        / f"{config['suite_id']}-{stamp}"
    )
    suite_root.mkdir(parents=True, exist_ok=False)
    atomic_write_json(suite_root / "suite-config.json", config)

    started_at = utc_now()
    cases: list[dict[str, Any]] = []
    halt_reason: str | None = None
    first_launch = True
    for seed in config["native_seeds"]:
        for configured_policy in config["policies"]:
            policy_id = configured_policy["policy_id"]
            case_id = f"{policy_id}--{seed.lower()}"
            descriptor = policy_descriptor(policy_id, configured_policy.get("policy_seed"))
            if halt_reason is not None:
                cases.append(
                    _case_result(
                        case_id=case_id,
                        seed=seed,
                        policy=descriptor,
                        report=None,
                        error=halt_reason,
                        status="not_run",
                    )
                )
                continue
            report: dict[str, Any] | None = None
            error: str | None = None
            try:
                report = launch_episode(
                    project_root=project_root,
                    mode="baseline",
                    seed=seed,
                    timeout_seconds=config["max_episode_seconds"],
                    max_decisions=config["max_episode_decisions"],
                    build_bridge=build_bridge and first_launch,
                    baseline_policy_id=policy_id,
                    baseline_policy_seed=configured_policy.get("policy_seed"),
                    baseline_suite_id=config["suite_id"],
                    baseline_case_id=case_id,
                    baseline_config_hash=config_hash,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                halt_reason = f"suite halted after launcher failure in {case_id}: {error}"
            finally:
                first_launch = False
            status = "passed" if isinstance(report, dict) and report.get("status") == "passed" else "failed"
            cases.append(
                _case_result(
                    case_id=case_id,
                    seed=seed,
                    policy=descriptor,
                    report=report,
                    error=error or (report.get("launch_error") if isinstance(report, dict) else None),
                    status=status,
                )
            )
            if isinstance(report, dict) and any(
                (
                    report.get("normal_guard", {}).get("unchanged") is not True,
                    report.get("owned_java_stopped") is not True,
                    report.get("owned_worker_stopped") is not True,
                    report.get("sidecar_descriptor_removed") is not True,
                    bool(report.get("residual_related_processes")),
                )
            ):
                halt_reason = f"suite halted after isolation/lifecycle failure in {case_id}"

    results_by_policy: dict[str, Any] = {}
    for configured_policy in config["policies"]:
        policy_id = configured_policy["policy_id"]
        policy_cases = [case for case in cases if case["policy"]["policy_id"] == policy_id]
        results_by_policy[policy_id] = {
            "policy": policy_descriptor(policy_id, configured_policy.get("policy_seed")),
            "cases": policy_cases,
            "aggregate": _aggregate(policy_id, policy_cases),
        }

    environments = sorted(
        {
            str(case["environment_fingerprint_id"])
            for case in cases
            if isinstance(case.get("environment_fingerprint_id"), str)
        }
    )
    all_cases_pass = all(case.get("status") == "passed" for case in cases)
    all_terminal = all(case.get("terminal_reached") is True for case in cases)
    status = "passed" if all_cases_pass and all_terminal and len(environments) == 1 else "failed"
    report = {
        "schema_version": SUITE_REPORT_SCHEMA_VERSION,
        "status": status,
        "suite_id": config["suite_id"],
        "suite_root": str(suite_root),
        "source_config": str(config_path),
        "suite_config": config,
        "suite_config_hash": config_hash,
        "started_at": started_at,
        "finished_at": utc_now(),
        "case_count": len(cases),
        "environment_fingerprint_ids": environments,
        "same_environment_for_every_run": len(environments) == 1,
        "same_native_seed_matrix_for_every_policy": all(
            sorted(case["seed"] for case in value["cases"])
            == sorted(config["native_seeds"])
            for value in results_by_policy.values()
        ),
        "results_by_policy": results_by_policy,
        "combined_score_prohibited": True,
        "h1b_acceptance_runs_included": False,
        "tactical_solver": {
            "included": False,
            "status": "not_implemented",
            "performance_claim": None,
        },
        "halt_reason": halt_reason,
    }
    atomic_write_json(suite_root / "suite-report.json", report)
    report["suite_root"] = str(suite_root)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the formal H1-C scripted baseline suite")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "benchmarks" / "h1c-scripted-smoke.v1.json",
    )
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_h1c_suite(
            project_root=args.project_root,
            config_path=args.config,
            build_bridge=not args.skip_build,
        )
    except Exception as exc:
        print(f"H1C_SCRIPTED_FAILED={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    summary = {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "suite_id": result["suite_id"],
        "suite_root": result["suite_root"],
        "suite_config_hash": result["suite_config_hash"],
        "case_count": result["case_count"],
        "same_environment_for_every_run": result["same_environment_for_every_run"],
        "same_native_seed_matrix_for_every_policy": result[
            "same_native_seed_matrix_for_every_policy"
        ],
        "halt_reason": result["halt_reason"],
    }
    print(__import__("json").dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"H1C_SCRIPTED_STATUS={result['status'].upper()}")
    print(f"SUITE_ROOT={result['suite_root']}")
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
