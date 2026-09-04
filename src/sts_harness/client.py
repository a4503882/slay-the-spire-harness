from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from .canonical import strict_json_loads
from .framing import read_frame, write_frame


class H1ClientFailure(RuntimeError):
    pass


class H1Client:
    def __init__(
        self,
        host: str,
        port: int,
        controller_nonce: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("H1 client accepts loopback hosts only")
        self.host = host
        self.port = port
        self.controller_nonce = controller_nonce
        self.timeout_seconds = timeout_seconds
        self._request_id = 0

    @classmethod
    def from_descriptor(cls, path: Path, timeout_seconds: float = 30.0) -> "H1Client":
        document = strict_json_loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise H1ClientFailure("H1 sidecar descriptor must be an object")
        if document.get("schema_version") != "sts-h1-sidecar-descriptor.v1":
            raise H1ClientFailure("unexpected H1 sidecar descriptor version")
        host = document.get("host")
        port = document.get("port")
        nonce = document.get("controller_nonce")
        if (
            not isinstance(host, str)
            or not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
            or not isinstance(nonce, str)
            or len(nonce) < 32
        ):
            raise H1ClientFailure("incomplete H1 sidecar descriptor")
        return cls(host, port, nonce, timeout_seconds)

    def invoke(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        mutating: bool = False,
    ) -> Any:
        self._request_id += 1
        request_params = dict(params or {})
        if mutating:
            request_params["controller_nonce"] = self.controller_nonce
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": request_params,
        }
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            write_frame(sock, request)
            response = read_frame(sock)
        if not isinstance(response, dict):
            raise H1ClientFailure("sidecar returned no JSON-RPC object")
        if response.get("jsonrpc") != "2.0":
            raise H1ClientFailure(f"invalid JSON-RPC version for {method}")
        if "error" in response:
            error = response.get("error")
            raise H1ClientFailure(f"{method} failed: {error}")
        if response.get("id") != self._request_id or "result" not in response:
            raise H1ClientFailure(f"invalid JSON-RPC response for {method}")
        return response["result"]
