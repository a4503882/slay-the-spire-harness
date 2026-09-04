from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _state(*, commands: list[str], in_game: bool, game_state: dict | None = None) -> dict:
    result = {
        "protocol_version": "communicationmod-harness.v1",
        "bridge_version": "1.2.1-sts-harness.1",
        "available_commands": commands,
        "ready_for_command": True,
        "in_game": in_game,
    }
    if game_state is not None:
        result["game_state"] = game_state
    return result


def test_worker_stdout_is_protocol_only_and_writes_pass_summary(tmp_path: Path) -> None:
    states = [
        _state(commands=["start", "state"], in_game=False),
        _state(
            commands=["choose", "state"],
            in_game=True,
            game_state={
                "screen_type": "EVENT",
                "room_phase": "EVENT",
                "choice_list": ["one"],
            },
        ),
        _state(
            commands=["choose", "state"],
            in_game=True,
            game_state={
                "screen_type": "MAP",
                "room_phase": "COMPLETE",
                "choice_list": ["x=1,y=0"],
            },
        ),
        _state(
            commands=["play", "end", "state"],
            in_game=True,
            game_state={
                "screen_type": "NONE",
                "room_phase": "COMBAT",
                "combat_state": {
                    "turn": 1,
                    "hand": [
                        {
                            "id": "Strike_R",
                            "uuid": "card-1",
                            "is_playable": True,
                            "has_target": True,
                        }
                    ],
                    "monsters": [
                        {"id": "JawWorm", "current_hp": 40, "is_gone": False}
                    ],
                },
            },
        ),
        _state(
            commands=["play", "end", "state"],
            in_game=True,
            game_state={
                "screen_type": "NONE",
                "room_phase": "COMBAT",
                "combat_state": {"turn": 1, "hand": [], "monsters": []},
            },
        ),
        _state(
            commands=["play", "end", "state"],
            in_game=True,
            game_state={
                "screen_type": "NONE",
                "room_phase": "COMBAT",
                "combat_state": {"turn": 2, "hand": [], "monsters": []},
            },
        ),
    ]
    input_text = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in states)
    environment = os.environ.copy()
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SRC) + (
        os.pathsep + inherited_pythonpath if inherited_pythonpath else ""
    )
    environment["STS_HARNESS_RUN_DIR"] = str(tmp_path)
    environment["STS_HARNESS_SEED"] = "AMIYA20260904"
    result = subprocess.run(
        [sys.executable, "-u", "-m", "sts_harness.m1_worker"],
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "ready",
        "start ironclad 0 AMIYA20260904",
        "choose 0",
        "choose 0",
        "play 1 0",
        "end",
    ]
    assert "M1_WORKER_READY" in result.stderr
    assert "M1_PROBE_COMPLETE" in result.stderr
    summary = json.loads((tmp_path / "worker-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert all(summary["evidence"].values())
