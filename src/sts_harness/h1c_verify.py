from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, sha256_document
from .h1b_verify import (
    FORBIDDEN_PUBLIC_KEYS,
    _contains_key,
    _object,
    _rows as _artifact_rows,
    _verify_episode,
)
from .h1c_run import (
    REQUIRED_POLICIES,
    SUITE_REPORT_SCHEMA_VERSION,
    _aggregate,
    validate_suite_config,
)
from .scripted_baseline import build_policy_decision_record
from .scripted_policy import create_policy, policy_descriptor


class H1CVerificationFailure(RuntimeError):
    pass


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _document_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _verify_policy_decisions(
    *,
    run_dir: Path,
    episode: dict[str, Any],
    policy_id: str,
    policy_seed: str | None,
) -> dict[str, Any]:
    driver = episode["driver"]
    transitions = episode["transitions"]
    records = _artifact_rows(run_dir / "policy-decisions.jsonl")
    policy = create_policy(policy_id, policy_seed)
    descriptor = policy.descriptor()
    transitions_by_index = {
        transition.get("transition_index"): transition
        for transition in transitions
        if isinstance(transition.get("transition_index"), int)
    }
    results = [
        result
        for transition in transitions
        for result in transition.get("action_results", [])
        if isinstance(result, dict)
    ]
    exact_records = True
    selected_results_match = len(results) == len(records)
    previous_chain_hash: str | None = None
    failure_index: int | None = None
    for index, record in enumerate(records):
        try:
            if record.get("policy_decision_index") != index:
                raise H1CVerificationFailure("policy decision index is not contiguous")
            transition_index = record.get("pre_transition_index")
            if not isinstance(transition_index, int):
                raise H1CVerificationFailure("policy decision lacks a pre-transition index")
            transition = transitions_by_index[transition_index]
            choice = policy.choose(
                observation=_dict(transition.get("observation")),
                legal_actions=_dict(transition.get("legal_actions")),
                decision_index=index,
            )
            expected = build_policy_decision_record(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_decision_index=index,
                transition=transition,
                choice=choice,
                previous_chain_hash=previous_chain_hash,
            )
            if expected != record:
                raise H1CVerificationFailure("policy decision record does not recompute")
            if index >= len(results) or results[index].get("selector") != choice.semantic_action["selector"] or results[index].get("type") != choice.semantic_action["type"]:
                selected_results_match = False
            previous_chain_hash = record["hashes"]["chain_hash"]
        except Exception:
            exact_records = False
            failure_index = index
            break
    checks = {
        "policy_descriptor_matches": driver.get("policy") == descriptor,
        "policy_decision_count_matches": driver.get("policy_decision_count") == len(records)
        and len(records) == episode.get("action_count"),
        "policy_decisions_recompute_exactly": exact_records,
        "selected_actions_match_verified_results": selected_results_match,
        "policy_decision_chain_matches": driver.get("final_policy_decision_chain_hash")
        == previous_chain_hash,
        "policy_audit_has_no_forbidden_key": not any(
            _contains_key(record, FORBIDDEN_PUBLIC_KEYS) for record in records
        ),
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "failure_index": failure_index,
        "record_count": len(records),
        "final_policy_decision_chain_hash": previous_chain_hash,
    }


def _verify_case(
    *,
    case: dict[str, Any],
    suite_config: dict[str, Any],
    suite_config_hash: str,
) -> dict[str, Any]:
    policy_document = _dict(case.get("policy"))
    policy_id = policy_document.get("policy_id")
    if not isinstance(policy_id, str):
        raise H1CVerificationFailure("case has no policy ID")
    configured_policy = next(
        (
            policy
            for policy in suite_config["policies"]
            if policy.get("policy_id") == policy_id
        ),
        None,
    )
    if not isinstance(configured_policy, dict):
        raise H1CVerificationFailure(f"case policy is absent from suite config: {policy_id}")
    run_root = case.get("run_root")
    if not isinstance(run_root, str):
        raise H1CVerificationFailure(f"case has no run root: {case.get('case_id')}")
    run_dir = Path(run_root).resolve()
    episode = _verify_episode(run_dir, "baseline")
    report = episode["report"]
    driver = episode["driver"]
    metrics = episode["metrics"]
    run_config = _object(run_dir / "config.json")
    descriptor = policy_descriptor(policy_id, configured_policy.get("policy_seed"))
    policy_audit = _verify_policy_decisions(
        run_dir=run_dir,
        episode=episode,
        policy_id=policy_id,
        policy_seed=configured_policy.get("policy_seed"),
    )
    baseline_identity = {
        "suite_id": suite_config["suite_id"],
        "case_id": case.get("case_id"),
        "suite_config_hash": suite_config_hash,
        "policy": descriptor,
    }
    checks = {
        "case_status_passed": case.get("status") == "passed",
        "episode_independently_valid": episode["valid"] is True,
        "episode_report_schema": report.get("schema_version")
        == "sts-scripted-baseline-episode-report.v1",
        "embedded_report_exact": case.get("report") == report,
        "run_config_schema": run_config.get("schema_version")
        == "sts-scripted-baseline-run-config.v1",
        "baseline_identity_exact": report.get("baseline") == baseline_identity
        and run_config.get("baseline") == baseline_identity,
        "policy_descriptor_exact": case.get("policy") == descriptor
        and driver.get("policy") == descriptor,
        "policy_mode_separated": metrics.get("policy_mode") == policy_id
        and run_config.get("policy_mode") == policy_id,
        "player_visible_only": run_config.get("fairness_profile") == "player_visible.v1",
        "native_terminal": driver.get("terminal_reached") is True
        and driver.get("episode_status") == "terminal"
        and driver.get("truncated") is False,
        "policy_audit_valid": policy_audit["valid"] is True,
        "model_metrics_unavailable": all(
            value is None for key, value in metrics.items() if key.startswith("model_")
        ),
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "failures": [name for name, passed in checks.items() if not passed],
        "case_id": case.get("case_id"),
        "seed": case.get("seed"),
        "policy_id": policy_id,
        "run_root": str(run_dir),
        "environment_fingerprint_id": report.get("environment_fingerprint_id"),
        "outcome": driver.get("outcome"),
        "metrics": metrics,
        "episode_checks": episode["checks"],
        "policy_audit": policy_audit,
        "final_chain_hash": episode.get("final_chain_hash"),
    }


def verify_h1c_suite(suite_dir: Path) -> dict[str, Any]:
    suite_dir = suite_dir.resolve()
    report = _object(suite_dir / "suite-report.json")
    stored_config = _object(suite_dir / "suite-config.json")
    config = validate_suite_config(stored_config)
    config_hash = sha256_document(config)
    results_by_policy = _dict(report.get("results_by_policy"))
    cases = [
        case
        for policy_id in sorted(results_by_policy)
        for case in _document_rows(_dict(results_by_policy.get(policy_id)).get("cases"))
    ]
    case_verifications: list[dict[str, Any]] = []
    case_errors: list[str] = []
    for case in cases:
        try:
            case_verifications.append(
                _verify_case(
                    case=case,
                    suite_config=config,
                    suite_config_hash=config_hash,
                )
            )
        except Exception as exc:
            case_errors.append(
                f"{case.get('case_id')}: {type(exc).__name__}: {exc}"
            )

    expected_case_count = len(config["native_seeds"]) * len(config["policies"])
    environments = {
        verification.get("environment_fingerprint_id")
        for verification in case_verifications
        if isinstance(verification.get("environment_fingerprint_id"), str)
    }
    aggregates_match = True
    for policy_id in REQUIRED_POLICIES:
        policy_section = _dict(results_by_policy.get(policy_id))
        policy_cases = _document_rows(policy_section.get("cases"))
        if policy_section.get("aggregate") != _aggregate(policy_id, policy_cases):
            aggregates_match = False
    checks = {
        "suite_report_schema": report.get("schema_version") == SUITE_REPORT_SCHEMA_VERSION,
        "suite_report_passed": report.get("status") == "passed",
        "suite_config_embedded_exactly": report.get("suite_config") == config,
        "suite_config_hash_matches": report.get("suite_config_hash") == config_hash,
        "suite_root_matches": report.get("suite_root") == str(suite_dir),
        "required_policies_separated": set(results_by_policy) == REQUIRED_POLICIES,
        "configured_case_count_matches": report.get("case_count") == expected_case_count
        and len(cases) == expected_case_count,
        "same_seed_matrix": report.get("same_native_seed_matrix_for_every_policy") is True
        and all(
            sorted(
                case.get("seed")
                for case in _document_rows(_dict(results_by_policy.get(policy_id)).get("cases"))
            )
            == sorted(config["native_seeds"])
            for policy_id in REQUIRED_POLICIES
        ),
        "same_environment": report.get("same_environment_for_every_run") is True
        and len(environments) == 1,
        "every_case_independently_valid": len(case_verifications) == expected_case_count
        and not case_errors
        and all(case["valid"] is True for case in case_verifications),
        "aggregates_recompute": aggregates_match,
        "combined_score_absent": "combined_score" not in report
        and report.get("combined_score_prohibited") is True,
        "h1b_results_excluded": report.get("h1b_acceptance_runs_included") is False
        and all("h1b-" not in str(case.get("run_root", "")) for case in cases),
        "tactical_solver_not_claimed": report.get("tactical_solver")
        == {"included": False, "status": "not_implemented", "performance_claim": None},
        "no_halt_or_omitted_case": report.get("halt_reason") is None
        and all(case.get("status") != "not_run" for case in cases),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "sts-h1c-scripted-independent-verification.v1",
        "valid": not failures,
        "suite_root": str(suite_dir),
        "suite_id": config["suite_id"],
        "suite_config_hash": config_hash,
        "checks": checks,
        "failures": failures,
        "case_errors": case_errors,
        "case_verifications": case_verifications,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify an H1-C scripted suite")
    parser.add_argument("--suite-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_h1c_suite(args.suite_dir)
    except Exception as exc:
        result = {
            "schema_version": "sts-h1c-scripted-independent-verification.v1",
            "valid": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = args.output or (args.suite_dir / "h1c-independent-verification.json")
    atomic_write_json(output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
