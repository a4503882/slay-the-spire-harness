from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import append_jsonl, atomic_write_json, sha256_document, strict_json_loads
from .m1_policy import M1ProbePolicy


MAX_LINE_BYTES = 16 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _summary(
    *,
    status: str,
    policy: M1ProbePolicy | None,
    started_at: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "sts-m1-probe-summary.v1",
        "status": status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "pid": os.getpid(),
        "seed": policy.seed if policy else None,
        "states_seen": policy.states_seen if policy else 0,
        "commands_sent": policy.commands_sent if policy else 0,
        "evidence": dict(policy.evidence) if policy else {},
        "verifications": list(policy.verifications) if policy else [],
        "error": error,
    }


def run() -> int:
    started_at = utc_now()
    policy: M1ProbePolicy | None = None
    summary_path: Path | None = None
    try:
        run_dir = Path(_required_environment("STS_HARNESS_RUN_DIR")).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "worker-summary.json"
        seed = os.environ.get("STS_HARNESS_SEED", "AMIYA20260904")
        policy = M1ProbePolicy(seed)
        max_commands = int(os.environ.get("STS_HARNESS_MAX_COMMANDS", "64"))
        if max_commands < 4 or max_commands > 1000:
            raise RuntimeError("STS_HARNESS_MAX_COMMANDS must be between 4 and 1000")

        atomic_write_json(
            run_dir / "worker-environment.json",
            {
                "schema_version": "sts-m1-worker-environment.v1",
                "started_at": started_at,
                "pid": os.getpid(),
                "python": sys.executable,
                "seed": policy.seed,
                "max_commands": max_commands,
            },
        )

        sys.stdout.write("ready\n")
        sys.stdout.flush()
        sys.stderr.write("M1_WORKER_READY\n")
        sys.stderr.flush()

        state_path = run_dir / "bridge-states.jsonl"
        command_path = run_dir / "bridge-commands.jsonl"

        while True:
            raw_line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
            if not raw_line:
                raise RuntimeError("bridge input closed before M-1 evidence completed")
            if len(raw_line) > MAX_LINE_BYTES:
                raise RuntimeError("bridge state line exceeds the 16 MiB limit")
            text = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
            if not text:
                continue
            document = strict_json_loads(text)
            if not isinstance(document, dict):
                raise RuntimeError("bridge state must be a JSON object")
            append_jsonl(
                state_path,
                {
                    "schema_version": "sts-m1-raw-state.v1",
                    "received_at": utc_now(),
                    "state_index": policy.states_seen + 1,
                    "raw_hash": sha256_document(document),
                    "raw": document,
                    "non_benchmark": True,
                },
            )

            command = policy.next_command(document)
            if policy.commands_sent > max_commands:
                raise RuntimeError("M-1 command limit exceeded")
            if policy.complete:
                result = _summary(
                    status="passed",
                    policy=policy,
                    started_at=started_at,
                )
                atomic_write_json(summary_path, result)
                sys.stderr.write("M1_PROBE_COMPLETE\n")
                sys.stderr.flush()
                return 0
            if command is None:
                raise RuntimeError("policy returned no command before completing M-1")

            append_jsonl(
                command_path,
                {
                    "schema_version": "sts-m1-native-command.v1",
                    "sent_at": utc_now(),
                    "command_index": policy.commands_sent,
                    "command": command,
                },
            )
            sys.stdout.write(command + "\n")
            sys.stdout.flush()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if summary_path is not None:
            atomic_write_json(
                summary_path,
                _summary(
                    status="failed",
                    policy=policy,
                    started_at=started_at,
                    error=message,
                ),
            )
        sys.stderr.write("M1_PROBE_FAILED " + message + "\n")
        sys.stderr.flush()
        return 2


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

