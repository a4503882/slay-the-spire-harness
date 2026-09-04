from __future__ import annotations

import argparse
import csv
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from . import __version__
from .canonical import atomic_write_json
from .environment import seal_environment
from .guard import compare_snapshots, sha256_file, snapshot_roots
from .h1_full_driver import run_full_episode
from .live_replay import run_live_replay
from .observation import BRIDGE_PROTOCOL_VERSION, BRIDGE_VERSION
from .replay_verify import verify_offline_replay


GAME_ROOT = Path(r"F:\SteamLibrary\steamapps\common\SlayTheSpire")
WORKSHOP_ROOT = Path(r"F:\SteamLibrary\steamapps\workshop\content\646570")
STEAM_MANIFEST = Path(r"F:\SteamLibrary\steamapps\appmanifest_646570.acf")
GAME_JAR_SHA256 = "CFAD868AC8D65A88E71A0BF096FB09F78811E553EFFE0787C5309A655E081673"
GAME_EXE_SHA256 = "44B8EACFD3843A8666E980DC9C71A50A069EF58610FB134464D1B606434C9603"
MTS_SHA256 = "541B5E8A875D2A404A5A6D54F4A6F814284B0CF71ACB9245239D9C5EF50EA604"
BASEMOD_SHA256 = "C3353C10E64C621B723E9FD7D0502DFA796F828B101B68513594A5F5EF83FBAF"


class LauncherFailure(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return sha256_file(path).upper()


def _real_python_executable() -> Path:
    path = Path(psutil.Process(os.getpid()).exe()).resolve()
    if not path.is_file():
        raise LauncherFailure(f"real Python executable is unavailable: {path}")
    return path


def _verify_file(path: Path, expected: str) -> None:
    if not path.is_file():
        raise LauncherFailure(f"required target is missing: {path}")
    actual = _sha256(path)
    if actual != expected:
        raise LauncherFailure(f"target hash mismatch for {path}: expected {expected}, got {actual}")


def _related_processes() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    game_root = str(GAME_ROOT).lower()
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = process.info
            name = str(info.get("name") or "").lower()
            if name not in {"java.exe", "javaw.exe", "slaythespire.exe"}:
                continue
            executable = str(info.get("exe") or "")
            command_line = " ".join(info.get("cmdline") or [])
            relevant = executable.lower().startswith(game_root) or any(
                marker in command_line.lower()
                for marker in ("slaythespire", "desktop-1.0.jar", "modthespire")
            )
            if relevant:
                result.append(
                    {
                        "pid": info.get("pid"),
                        "ppid": info.get("ppid"),
                        "name": info.get("name"),
                        "exe": executable,
                        "cmdline": command_line,
                        "create_time": info.get("create_time"),
                    }
                )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return result


def _active_steam_clients() -> list[dict[str, Any]]:
    """Return the interactive Steam client only, never the system service."""
    result: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            info = process.info
            if str(info.get("name") or "").lower() != "steam.exe":
                continue
            result.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "create_time": info.get("create_time"),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return sorted(result, key=lambda row: int(row.get("pid") or 0))


def _guard_roots() -> list[tuple[str, Path]]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    roots: list[tuple[str, Path]] = [
        ("game_install", GAME_ROOT),
        ("workshop_mods", WORKSHOP_ROOT),
        ("modthespire_config", local_app_data / "ModTheSpire"),
        ("steam_manifest", STEAM_MANIFEST),
    ]
    steam_userdata = Path(r"C:\Program Files (x86)\Steam\userdata")
    if steam_userdata.is_dir():
        for path in sorted(steam_userdata.rglob("localconfig.vdf")):
            account = path.parent.parent.name
            roots.append((f"steam_localconfig_{account}", path))
    return roots


def _build_bridge(project_root: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        raise LauncherFailure("PowerShell is unavailable for the bridge build")
    command = [shell, "-NoProfile", "-File", str(project_root / "tools" / "build_bridge.ps1")]
    completed = subprocess.run(command, cwd=project_root, check=False)
    if completed.returncode != 0:
        raise LauncherFailure(f"bridge build failed with exit code {completed.returncode}")


def _current_user_sid() -> str:
    completed = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    row = next(csv.reader([completed.stdout.strip()]))
    if len(row) < 2 or not row[1].startswith("S-1-"):
        raise LauncherFailure("could not resolve the current Windows user SID")
    return row[1]


def _restrict_descriptor(path: Path) -> None:
    sid = _current_user_sid()
    completed = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(F)",
            "*S-1-5-18:(F)",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise LauncherFailure(
            f"descriptor ACL restriction failed with exit code {completed.returncode}"
        )


def _harness_hashes(project_root: Path) -> dict[str, str]:
    paths = sorted((project_root / "src" / "sts_harness").glob("*.py"))
    paths.extend(
        sorted(
            path
            for path in (project_root / "tools").glob("*")
            if path.suffix.lower() in {".py", ".ps1"}
        )
    )
    return {
        path.relative_to(project_root).as_posix(): _sha256(path)
        for path in paths
        if path.is_file()
    }


def _environment_document(
    project_root: Path,
    *,
    bridge_jar: Path,
    game_java: Path,
) -> dict[str, Any]:
    version = subprocess.run(
        [str(game_java), "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    basis = {
        "schema_version": "sts-environment.v2",
        "target": {
            "steam_app_id": 646570,
            "steam_build": 10180494,
            "game_sha256": GAME_JAR_SHA256,
            "executable_sha256": GAME_EXE_SHA256,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "jvm": {"sha256": _sha256(game_java), "version": (version.stderr or version.stdout).strip()},
        "mod_the_spire": {"version": "3.30.3", "sha256": MTS_SHA256},
        "base_mod": {"version": "5.56.0", "sha256": BASEMOD_SHA256},
        "bridge": {
            "version": BRIDGE_VERSION,
            "protocol_version": BRIDGE_PROTOCOL_VERSION,
            "upstream_commit": "5e417eb189530986b9047a3c9426889fb261d146",
            "sha256": _sha256(bridge_jar),
        },
        "harness": {
            "version": __version__,
            "python_version": platform.python_version(),
            "python_executable_sha256": _sha256(_real_python_executable()),
            "files": _harness_hashes(project_root),
        },
        "enabled_mods": ["basemod", "CommunicationMod"],
        "observation_schema": "sts-observation.v1",
        "legal_actions_schema": "sts-legal-actions.v1",
        "transition_schema": "sts-transition.v1",
        "replay_checkpoint_schema": "sts-replay-checkpoint.v1",
        "fairness_profile": "player_visible.v1",
    }
    return seal_environment(basis)


def _prepare_worktree(project_root: Path, run_root: Path, bridge_jar: Path) -> dict[str, Path]:
    work_root = run_root / "work"
    profile_root = run_root / "profile"
    paths = {
        "work": work_root,
        "profile": profile_root,
        "local_app_data": profile_root / "LocalAppData",
        "app_data": profile_root / "AppData",
        "user_home": profile_root / "UserHome",
        "mods": work_root / "mods",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    cache_root = project_root / ".tools" / "game-cache" / GAME_JAR_SHA256
    cache_root.mkdir(parents=True, exist_ok=True)
    cached_game = cache_root / "desktop-1.0.jar"
    game_jar = GAME_ROOT / "desktop-1.0.jar"
    if not cached_game.exists():
        shutil.copy2(game_jar, cached_game)
    _verify_file(cached_game, GAME_JAR_SHA256)
    os.link(cached_game, work_root / "desktop-1.0.jar")
    shutil.copy2(GAME_ROOT / "config.json", work_root / "config.json")
    shutil.copy2(WORKSHOP_ROOT / "1605833019" / "BaseMod.jar", paths["mods"] / "BaseMod.jar")
    shutil.copy2(bridge_jar, paths["mods"] / "CommunicationMod.jar")
    preferences = GAME_ROOT / "preferences"
    if preferences.is_dir():
        shutil.copytree(preferences, work_root / "preferences")
    (work_root / "saves").mkdir(exist_ok=True)
    (work_root / "betaPreferences").mkdir(exist_ok=True)
    return paths


def _wait_for_file_or_exit(path: Path, process: subprocess.Popen[Any], deadline: float) -> None:
    while not path.is_file():
        code = process.poll()
        if code is not None:
            raise LauncherFailure(f"owned Java process exited early with code {code}")
        if time.monotonic() >= deadline:
            raise LauncherFailure(f"timed out waiting for {path.name}")
        time.sleep(0.1)


def _stop_owned_process(process: subprocess.Popen[Any] | None) -> bool:
    if process is None:
        return True
    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    return process.poll() is not None


def launch_episode(
    *,
    project_root: Path,
    mode: str,
    seed: str,
    timeout_seconds: int,
    max_decisions: int,
    source_run: Path | None = None,
    build_bridge: bool = True,
) -> dict[str, Any]:
    if os.name != "nt":
        raise LauncherFailure("the accepted H1-B launcher target is Windows")
    project_root = project_root.resolve()
    if mode not in {"full", "replay"}:
        raise LauncherFailure(f"unsupported episode mode: {mode}")
    if mode == "replay" and source_run is None:
        raise LauncherFailure("replay mode requires source_run")
    if _related_processes():
        raise LauncherFailure("a related Slay the Spire process is already active")
    steam_clients = _active_steam_clients()
    if steam_clients:
        pids = ", ".join(str(row["pid"]) for row in steam_clients)
        raise LauncherFailure(
            "the interactive Steam client must be closed for the exact normal-data guard; "
            f"active steam.exe PID(s): {pids}"
        )

    game_jar = GAME_ROOT / "desktop-1.0.jar"
    game_exe = GAME_ROOT / "SlayTheSpire.exe"
    game_java = GAME_ROOT / "jre" / "bin" / "java.exe"
    mts_jar = WORKSHOP_ROOT / "1605060445" / "ModTheSpire.jar"
    base_mod = WORKSHOP_ROOT / "1605833019" / "BaseMod.jar"
    for path, expected in (
        (game_jar, GAME_JAR_SHA256),
        (game_exe, GAME_EXE_SHA256),
        (mts_jar, MTS_SHA256),
        (base_mod, BASEMOD_SHA256),
    ):
        _verify_file(path, expected)
    if not game_java.is_file() or not (GAME_ROOT / "config.json").is_file():
        raise LauncherFailure("game Java runtime or config is missing")
    if build_bridge:
        _build_bridge(project_root)
    bridge_jar = project_root / "vendor" / "CommunicationMod" / "target" / "CommunicationMod.jar"
    if not bridge_jar.is_file():
        raise LauncherFailure("built bridge JAR is missing")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"h1b-{mode}-{stamp}-{uuid.uuid4().hex[:8]}"
    episode_id = f"ep_{uuid.uuid4().hex}"
    native_session_id = f"native_{uuid.uuid4().hex}"
    run_root = project_root / "artifacts" / "h1b-runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)

    guard_roots = _guard_roots()
    before_guard = snapshot_roots(guard_roots)
    atomic_write_json(run_root / "normal-guard-before.json", before_guard)
    paths = _prepare_worktree(project_root, run_root, bridge_jar)
    environment = _environment_document(project_root, bridge_jar=bridge_jar, game_java=game_java)
    atomic_write_json(run_root / "environment.json", environment)
    config = {
        "schema_version": "sts-h1b-run-config.v1",
        "run_id": run_id,
        "episode_id": episode_id,
        "native_session_id": native_session_id,
        "mode": mode,
        "seed": seed.upper(),
        "character_id": "IRONCLAD",
        "ascension": 0,
        "fairness_profile": "player_visible.v1",
        "policy_mode": "scripted_greedy" if mode == "full" else "scripted_replay",
        "max_episode_decisions": max_decisions,
        "max_episode_seconds": timeout_seconds,
        "environment_fingerprint_id": environment["environment_fingerprint_id"],
        "source_run": str(source_run.resolve()) if source_run else None,
    }
    atomic_write_json(run_root / "config.json", config)

    stdout_path = run_root / "modthespire-stdout.log"
    stderr_path = run_root / "modthespire-stderr.log"
    descriptor_path = run_root / "sidecar.json"
    worker_summary_path = run_root / "worker-summary.json"
    driver_output = run_root / ("driver-summary.json" if mode == "full" else "live-replay.json")
    process: subprocess.Popen[Any] | None = None
    worker_pid: int | None = None
    worker_create_time: float | None = None
    worker_parent_pid: int | None = None
    driver: dict[str, Any] | None = None
    launch_error: str | None = None
    timed_out = False
    owned_java_stopped = False
    descriptor_acl_restricted = False
    deadline = time.monotonic() + timeout_seconds
    started_at = utc_now()

    try:
        environment_variables = os.environ.copy()
        environment_variables.update(
            {
                "LOCALAPPDATA": str(paths["local_app_data"]),
                "APPDATA": str(paths["app_data"]),
                "USERPROFILE": str(paths["user_home"]),
                "STS_HARNESS_AUTOSTART": "1",
                "STS_HARNESS_PYTHON": sys.executable,
                "STS_HARNESS_WORKER": str(project_root / "tools" / "h1_bridge_worker.py"),
                "STS_HARNESS_RUN_DIR": str(run_root),
                "STS_HARNESS_EPISODE_ID": episode_id,
                "STS_HARNESS_NATIVE_SESSION_ID": native_session_id,
                "STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID": environment[
                    "environment_fingerprint_id"
                ],
                "STS_HARNESS_STATE_TIMEOUT_SECONDS": "45",
                "PYTHONPATH": str(project_root / "src"),
            }
        )
        command = [
            str(game_java),
            "-Xmx1G",
            "-Dsun.java2d.dpiaware=true",
            f"-Duser.home={paths['user_home']}",
            "-jar",
            str(mts_jar),
            "--skip-launcher",
            "--skip-intro",
            "--mods",
            "basemod,CommunicationMod",
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            process = subprocess.Popen(
                command,
                cwd=paths["work"],
                env=environment_variables,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                creationflags=creation_flags,
            )
            _wait_for_file_or_exit(descriptor_path, process, deadline)
            descriptor = __import__("json").loads(descriptor_path.read_text(encoding="utf-8"))
            worker_pid = descriptor.get("sidecar_pid")
            if isinstance(worker_pid, int):
                worker_identity = psutil.Process(worker_pid)
                worker_create_time = worker_identity.create_time()
                worker_parent_pid = worker_identity.ppid()
                if worker_parent_pid != process.pid:
                    raise LauncherFailure(
                        f"sidecar PID {worker_pid} is not owned by Java PID {process.pid}"
                    )
            _restrict_descriptor(descriptor_path)
            descriptor_acl_restricted = True
            remaining = max(1.0, deadline - time.monotonic())
            if mode == "full":
                driver = run_full_episode(
                    descriptor=descriptor_path,
                    output=driver_output,
                    seed=seed.upper(),
                    max_decisions=max_decisions,
                    timeout_seconds=remaining,
                )
            else:
                driver = run_live_replay(
                    source_run=source_run.resolve(),  # type: ignore[union-attr]
                    descriptor=descriptor_path,
                    output=driver_output,
                    timeout_seconds=remaining,
                )
            while not worker_summary_path.is_file() and process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(0.1)
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
    finally:
        owned_java_stopped = _stop_owned_process(process)

    owned_worker_stopped = worker_pid is None
    if isinstance(worker_pid, int):
        for _ in range(50):
            if not psutil.pid_exists(worker_pid):
                break
            time.sleep(0.1)
        try:
            worker_process = psutil.Process(worker_pid)
            if worker_process.is_running():
                identity_matches = (
                    worker_create_time is not None
                    and abs(worker_process.create_time() - worker_create_time) < 0.001
                    and process is not None
                    and worker_parent_pid == process.pid
                )
                if identity_matches:
                    worker_process.terminate()
                    worker_process.wait(timeout=5)
                else:
                    launch_error = launch_error or "worker ownership changed before cleanup"
            owned_worker_stopped = not worker_process.is_running()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            owned_worker_stopped = True
        except (psutil.AccessDenied, psutil.TimeoutExpired) as exc:
            launch_error = launch_error or f"worker cleanup verification failed: {exc}"
            owned_worker_stopped = False

    for _ in range(30):
        if not descriptor_path.exists():
            break
        time.sleep(0.1)
    descriptor_removed = not descriptor_path.exists()
    after_guard = snapshot_roots(guard_roots)
    atomic_write_json(run_root / "normal-guard-after.json", after_guard)
    guard_result = compare_snapshots(before_guard, after_guard)
    atomic_write_json(run_root / "normal-guard-result.json", guard_result)
    worker = (
        __import__("json").loads(worker_summary_path.read_text(encoding="utf-8"))
        if worker_summary_path.is_file()
        else None
    )
    offline: dict[str, Any] | None = None
    if (run_root / "transitions.jsonl").is_file():
        try:
            offline = verify_offline_replay(run_root)
        except Exception as exc:
            offline = {"status": "REPLAY_INVALID", "valid": False, "error": str(exc)}
        atomic_write_json(run_root / "replay.json", offline)
    residual = _related_processes()
    mode_passed = (
        driver is not None
        and (
            driver.get("status") == "passed"
            if mode == "full"
            else driver.get("status") == "REPLAY_PARITY"
        )
    )
    status = "passed" if all(
        (
            mode_passed,
            worker is not None and worker.get("status") == "passed",
            offline is not None and offline.get("status") == "REPLAY_VALID",
            guard_result.get("unchanged") is True,
            owned_java_stopped,
            owned_worker_stopped,
            descriptor_removed,
            not residual,
            not timed_out,
            launch_error is None,
        )
    ) else "failed"
    report = {
        "schema_version": "sts-h1b-episode-report.v1",
        "status": status,
        "mode": mode,
        "run_id": run_id,
        "episode_id": episode_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "run_root": str(run_root),
        "environment_fingerprint_id": environment["environment_fingerprint_id"],
        "java_pid": process.pid if process is not None else None,
        "java_exit_code": process.returncode if process is not None else None,
        "worker_pid": worker_pid,
        "worker_create_time": worker_create_time,
        "worker_parent_pid": worker_parent_pid,
        "owned_java_stopped": owned_java_stopped,
        "owned_worker_stopped": owned_worker_stopped,
        "sidecar_descriptor_removed": descriptor_removed,
        "descriptor_acl_restricted": descriptor_acl_restricted,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "residual_related_processes": residual,
        "driver": driver,
        "worker": worker,
        "offline_replay": offline,
        "normal_guard": guard_result,
        "bridge_sha256": _sha256(bridge_jar),
        "game_jar_materialization": "hardlink-to-verified-cache",
    }
    atomic_write_json(run_root / "episode-report.json", report)
    summary = {
        "schema_version": "sts-h1b-episode-summary.v1",
        "status": status,
        "mode": mode,
        "run_id": run_id,
        "episode_id": episode_id,
        "outcome": (driver or {}).get("outcome"),
        "metrics": (worker or {}).get("metrics"),
        "replay": driver if mode == "replay" else offline,
        "normal_guard": guard_result,
        "process_cleanup": {
            "owned_java_stopped": owned_java_stopped,
            "owned_worker_stopped": owned_worker_stopped,
            "sidecar_descriptor_removed": descriptor_removed,
            "residual_related_process_count": len(residual),
        },
        "report": str(run_root / "episode-report.json"),
    }
    atomic_write_json(run_root / "summary.json", summary)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch one isolated H1-B native episode")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--mode", choices=("full", "replay"), required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-decisions", type=int, default=5000)
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = launch_episode(
            project_root=args.project_root,
            mode=args.mode,
            seed=args.seed,
            timeout_seconds=args.timeout_seconds,
            max_decisions=args.max_decisions,
            source_run=args.source_run,
            build_bridge=not args.skip_build,
        )
    except Exception as exc:
        print(f"H1B_LAUNCH_FAILED={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"H1B_EPISODE_STATUS={report['status'].upper()}")
    print(f"MODE={report['mode']}")
    print(f"RUN_ROOT={report['run_root']}")
    print(f"OUTCOME={(report.get('driver') or {}).get('outcome')}")
    print(f"NORMAL_GUARD_UNCHANGED={report['normal_guard']['unchanged']}")
    print(f"OWNED_JAVA_STOPPED={report['owned_java_stopped']}")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
