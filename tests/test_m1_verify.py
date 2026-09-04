from __future__ import annotations

import json
from pathlib import Path

from sts_harness.m1_verify import verify_m1_run


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def test_independent_m1_verifier_accepts_complete_evidence(tmp_path: Path) -> None:
    report = {
        "status": "passed",
        "run_id": "m1-test",
        "bridge_sha256": "A" * 64,
        "owned_process_stopped": True,
        "timed_out": False,
    }
    worker = {
        "status": "passed",
        "states_seen": 2,
        "commands_sent": 4,
        "evidence": {
            "start_verified": True,
            "non_combat_choice_verified": True,
            "card_play_verified": True,
            "end_turn_verified": True,
        },
    }
    raw_base = {
        "bridge_version": "1.2.1-sts-harness.1",
        "protocol_version": "communicationmod-harness.v1",
        "in_game": False,
    }
    raw_turn = {
        **raw_base,
        "in_game": True,
        "game_state": {"combat_state": {"turn": 2}},
    }
    states = [
        {"raw": raw_base},
        {"raw": raw_turn},
        {"raw": raw_turn},
        {"raw": raw_turn},
    ]
    worker["states_seen"] = len(states)
    commands = [
        {"command": "start ironclad 0 TESTSEED"},
        {"command": "choose 0"},
        {"command": "play 1 0"},
        {"command": "end"},
    ]
    _write_json(tmp_path / "m1-report.json", report)
    _write_json(tmp_path / "worker-summary.json", worker)
    _write_json(tmp_path / "normal-guard-result.json", {"unchanged": True, "changes": []})
    guard = b'{"same":true}\n'
    (tmp_path / "normal-guard-before.json").write_bytes(guard)
    (tmp_path / "normal-guard-after.json").write_bytes(guard)
    (tmp_path / "bridge-states.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in states), encoding="utf-8"
    )
    (tmp_path / "bridge-commands.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in commands), encoding="utf-8"
    )

    result = verify_m1_run(tmp_path)
    assert result["valid"] is True
    assert not result["failures"]

