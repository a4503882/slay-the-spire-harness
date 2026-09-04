from __future__ import annotations

import os
import socketserver
import threading
from pathlib import Path
from typing import Any

from .canonical import atomic_write_json
from .framing import FrameError, read_frame, write_frame
from .rpc_protocol import RpcFailure, error_response, handle_request
from .runtime import H1Runtime


class _ThreadingLoopbackServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = False
    daemon_threads = True


class _RequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        runtime: H1Runtime = server.runtime  # type: ignore[attr-defined]
        method: str | None = None
        try:
            document = read_frame(self.request)
            if document is None:
                return
            if isinstance(document, dict) and isinstance(document.get("method"), str):
                method = document["method"]
            response = handle_request(document, runtime.dispatch)
            if response is not None:
                write_frame(self.request, response)
        except FrameError as exc:
            try:
                write_frame(self.request, error_response(None, RpcFailure(-32700, "Parse error", str(exc))))
            except OSError:
                pass
        except OSError:
            return
        finally:
            if method in {"env.close", "quit"} and runtime.close_requested:
                runtime.mark_close_response_sent()


class H1RpcServer:
    def __init__(self, runtime: H1Runtime, descriptor_path: Path, controller_nonce: str) -> None:
        self.runtime = runtime
        self.descriptor_path = descriptor_path.resolve()
        self.controller_nonce = controller_nonce
        self._server = _ThreadingLoopbackServer(("127.0.0.1", 0), _RequestHandler)
        self._server.runtime = runtime  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="sts-h1-rpc",
            daemon=True,
        )

    @property
    def host(self) -> str:
        return str(self._server.server_address[0])

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self.host != "127.0.0.1":
            raise RuntimeError("H1 sidecar did not bind to IPv4 loopback")
        atomic_write_json(
            self.descriptor_path,
            {
                "schema_version": "sts-h1-sidecar-descriptor.v1",
                "host": self.host,
                "port": self.port,
                "controller_nonce": self.controller_nonce,
                "sidecar_pid": os.getpid(),
            },
        )
        try:
            os.chmod(self.descriptor_path, 0o600)
        except OSError:
            pass
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)

