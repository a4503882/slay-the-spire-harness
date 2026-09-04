from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sts_harness.client import H1Client

from test_runtime import _menu_raw
from test_legal_actions import combat_raw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER = PROJECT_ROOT / "tools" / "h1_bridge_worker.py"


def _write_state(process: subprocess.Popen[str], state: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n")
    process.stdin.flush()


def test_h1_worker_exposes_protocol_and_closes_cleanly(tmp_path: Path) -> None:
    environment = os.environ.copy()
    source_root = str(PROJECT_ROOT / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["STS_HARNESS_RUN_DIR"] = str(tmp_path)
    environment["STS_HARNESS_EPISODE_ID"] = "ep_worker"
    environment["STS_HARNESS_NATIVE_SESSION_ID"] = "native_worker"
    environment["STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID"] = "sha256:environment"
    environment["STS_HARNESS_STATE_TIMEOUT_SECONDS"] = "2"
    process = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
        env=environment,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        descriptor = tmp_path / "sidecar.json"
        deadline = time.monotonic() + 2
        while not descriptor.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        client = H1Client.from_descriptor(descriptor, timeout_seconds=2)
        assert client.invoke("ping") == {"ok": True}
        _write_state(process, _menu_raw())

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.invoke,
                "env.reset",
                {
                    "character_id": "IRONCLAD",
                    "ascension": 0,
                    "seed": "AMIYA20260904",
                    "fairness_profile": "player_visible.v1",
                    "policy_mode": "scripted",
                    "max_episode_decisions": 10,
                    "max_episode_seconds": 60,
                },
                mutating=True,
            )
            assert process.stdout.readline().strip() == "start ironclad 0 AMIYA20260904"
            _write_state(process, combat_raw())
            transition = future.result(timeout=2)
        assert transition["transition_index"] == 0

        observation = transition["observation"]
        close = client.invoke(
            "env.close",
            {
                "episode_id": observation["episode_id"],
                "native_session_id": observation["native_session_id"],
                "run_id": observation["run_id"],
            },
            mutating=True,
        )
        assert close["close_requested"] is True
        assert process.stdout.readline().strip() == "state"
        _write_state(process, combat_raw())
        assert process.wait(timeout=5) == 0
        summary = json.loads((tmp_path / "worker-summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "passed"
        assert summary["close_requested"] is True
        assert not descriptor.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_h1_worker_reports_bridge_eof_as_failure(tmp_path: Path) -> None:
    environment = os.environ.copy()
    source_root = str(PROJECT_ROOT / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["STS_HARNESS_RUN_DIR"] = str(tmp_path)
    environment["STS_HARNESS_EPISODE_ID"] = "ep_crash"
    environment["STS_HARNESS_NATIVE_SESSION_ID"] = "native_crash"
    environment["STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID"] = "sha256:environment"
    process = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
        env=environment,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    assert process.stdin is not None
    process.stdin.close()
    assert process.wait(timeout=5) == 2
    summary = json.loads((tmp_path / "worker-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert "bridge input closed" in summary["error"]


def test_h1_worker_authenticated_abort_needs_no_native_wakeup(tmp_path: Path) -> None:
    environment = os.environ.copy()
    source_root = str(PROJECT_ROOT / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["STS_HARNESS_RUN_DIR"] = str(tmp_path)
    environment["STS_HARNESS_EPISODE_ID"] = "ep_abort_worker"
    environment["STS_HARNESS_NATIVE_SESSION_ID"] = "native_abort_worker"
    environment["STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID"] = "sha256:environment"
    process = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
        env=environment,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        descriptor = tmp_path / "sidecar.json"
        deadline = time.monotonic() + 2
        while not descriptor.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        client = H1Client.from_descriptor(descriptor, timeout_seconds=2)

        result = client.invoke("quit", {}, mutating=True)

        assert result["aborted"] is True
        assert process.wait(timeout=5) == 0
        summary = json.loads((tmp_path / "worker-summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "passed"
        assert summary["abort_requested"] is True
        assert summary["raw_receive_count"] == 0
        assert not descriptor.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
