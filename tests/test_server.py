from __future__ import annotations

from pathlib import Path

import pytest

from sts_harness.client import H1Client, H1ClientFailure
from sts_harness.runtime import H1Runtime
from sts_harness.server import H1RpcServer


def test_server_binds_loopback_and_serves_framed_json_rpc(tmp_path: Path) -> None:
    descriptor = tmp_path / "sidecar.json"
    nonce = "s" * 64
    runtime = H1Runtime(
        run_dir=tmp_path,
        episode_id="ep_test",
        native_session_id="native_test",
        environment_fingerprint_id="sha256:environment",
        controller_nonce=nonce,
        command_sink=lambda _: None,
        state_timeout_seconds=1,
    )
    server = H1RpcServer(runtime, descriptor, nonce)
    try:
        server.start()
        client = H1Client.from_descriptor(descriptor, timeout_seconds=1)
        assert client.invoke("ping") == {"ok": True}
        capabilities = client.invoke("capabilities")
        assert capabilities["raw_command_submission"] is False
        assert server.host == "127.0.0.1"
        bad_client = H1Client(server.host, server.port, "wrong", timeout_seconds=1)
        with pytest.raises(H1ClientFailure, match="CONTROLLER_AUTH_FAILED"):
            bad_client.invoke("env.close", {"episode_id": "ep_test"}, mutating=True)
    finally:
        server.close()
