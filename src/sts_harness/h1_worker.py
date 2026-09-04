from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

from .canonical import strict_json_loads
from .runtime import H1Runtime
from .server import H1RpcServer


MAX_LINE_BYTES = 16 * 1024 * 1024


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def run() -> int:
    run_dir: Path | None = None
    runtime: H1Runtime | None = None
    server: H1RpcServer | None = None
    descriptor_path: Path | None = None
    try:
        run_dir = Path(_required_environment("STS_HARNESS_RUN_DIR")).resolve()
        episode_id = _required_environment("STS_HARNESS_EPISODE_ID")
        native_session_id = _required_environment("STS_HARNESS_NATIVE_SESSION_ID")
        environment_id = _required_environment("STS_HARNESS_ENVIRONMENT_FINGERPRINT_ID")
        timeout_seconds = float(os.environ.get("STS_HARNESS_STATE_TIMEOUT_SECONDS", "30"))
        if timeout_seconds < 1 or timeout_seconds > 120:
            raise RuntimeError("STS_HARNESS_STATE_TIMEOUT_SECONDS must be in [1, 120]")
        run_dir.mkdir(parents=True, exist_ok=True)
        descriptor_path = run_dir / "sidecar.json"
        controller_nonce = secrets.token_hex(32)

        def send_command(command: str) -> None:
            sys.stdout.write(command + "\n")
            sys.stdout.flush()

        runtime = H1Runtime(
            run_dir=run_dir,
            episode_id=episode_id,
            native_session_id=native_session_id,
            environment_fingerprint_id=environment_id,
            controller_nonce=controller_nonce,
            command_sink=send_command,
            state_timeout_seconds=timeout_seconds,
        )
        server = H1RpcServer(runtime, descriptor_path, controller_nonce)
        server.start()
        sys.stdout.write("ready\n")
        sys.stdout.flush()
        sys.stderr.write("H1_WORKER_READY\n")
        sys.stderr.flush()

        while True:
            raw_line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
            if not raw_line:
                raise RuntimeError("bridge input closed before env.close completed")
            if len(raw_line) > MAX_LINE_BYTES:
                raise RuntimeError("bridge state line exceeds the 16 MiB limit")
            text = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
            if not text:
                continue
            document = strict_json_loads(text)
            if not isinstance(document, dict):
                raise RuntimeError("bridge state must be a JSON object")
            runtime.ingest_bridge_document(document)
            if runtime.close_requested and runtime.close_wakeup_observed:
                break

        runtime.write_summary(status="passed")
        sys.stderr.write("H1_WORKER_COMPLETE\n")
        sys.stderr.flush()
        return 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if runtime is not None:
            runtime.write_summary(status="failed", error=message)
        sys.stderr.write("H1_WORKER_FAILED " + message + "\n")
        sys.stderr.flush()
        return 2
    finally:
        if server is not None:
            server.close()
        if descriptor_path is not None:
            for _ in range(5):
                try:
                    descriptor_path.unlink(missing_ok=True)
                    break
                except OSError:
                    time.sleep(0.05)


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

