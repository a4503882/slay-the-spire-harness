from __future__ import annotations

import pytest

from sts_harness import episode_launcher
from sts_harness.episode_launcher import (
    LauncherFailure,
    _active_steam_clients,
    _owned_worker_identity_matches,
    _real_python_executable,
    _sha256,
)


def test_launcher_hashes_real_python_not_windowsapps_alias() -> None:
    executable = _real_python_executable()
    assert executable.is_file()
    assert len(_sha256(executable)) == 64


def test_launcher_steam_preflight_ignores_service_and_finds_client(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, pid: int, name: str) -> None:
            self.info = {"pid": pid, "name": name, "create_time": 123.0}

    monkeypatch.setattr(
        episode_launcher.psutil,
        "process_iter",
        lambda _: [
            FakeProcess(10, "SteamService.exe"),
            FakeProcess(20, "steamwebhelper.exe"),
            FakeProcess(30, "steam.exe"),
        ],
    )

    assert _active_steam_clients() == [
        {"pid": 30, "name": "steam.exe", "create_time": 123.0}
    ]


def test_worker_cleanup_requires_exact_creation_time_and_recorded_owner() -> None:
    class FakeWorker:
        @staticmethod
        def create_time() -> float:
            return 123.5

    worker = FakeWorker()
    assert _owned_worker_identity_matches(
        worker,  # type: ignore[arg-type]
        expected_create_time=123.5,
        recorded_parent_pid=40,
        owner_pid=40,
    )
    assert not _owned_worker_identity_matches(
        worker,  # type: ignore[arg-type]
        expected_create_time=124.0,
        recorded_parent_pid=40,
        owner_pid=40,
    )
    assert not _owned_worker_identity_matches(
        worker,  # type: ignore[arg-type]
        expected_create_time=123.5,
        recorded_parent_pid=41,
        owner_pid=40,
    )


def test_baseline_launcher_rejects_incomplete_identity_before_preflight() -> None:
    with pytest.raises(LauncherFailure, match="requires exact policy, suite, case"):
        episode_launcher.launch_episode(
            project_root=episode_launcher.Path.cwd(),
            mode="baseline",
            seed="AMIYA20260904",
            timeout_seconds=60,
            max_decisions=10,
            build_bridge=False,
            baseline_policy_id="scripted_greedy",
        )


def test_non_baseline_launcher_rejects_baseline_identity_fields() -> None:
    with pytest.raises(LauncherFailure, match="only in baseline mode"):
        episode_launcher.launch_episode(
            project_root=episode_launcher.Path.cwd(),
            mode="full",
            seed="AMIYA20260904",
            timeout_seconds=60,
            max_decisions=10,
            build_bridge=False,
            baseline_policy_id="scripted_greedy",
        )
