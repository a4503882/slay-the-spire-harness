from __future__ import annotations

import socket
import struct
from typing import Any

from .canonical import canonical_json_bytes, strict_json_loads


MAX_FRAME_BYTES = 4 * 1024 * 1024


class FrameError(ValueError):
    pass


def recv_exact(sock: socket.socket, count: int) -> bytes | None:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            if not data:
                return None
            raise FrameError("connection closed inside a frame")
        data.extend(chunk)
    return bytes(data)


def read_frame(sock: socket.socket) -> Any | None:
    header = recv_exact(sock, 4)
    if header is None:
        return None
    size = struct.unpack(">I", header)[0]
    if size == 0:
        raise FrameError("zero-length frame")
    if size > MAX_FRAME_BYTES:
        raise FrameError(f"frame too large: {size}")
    payload = recv_exact(sock, size)
    if payload is None:
        raise FrameError("missing frame payload")
    try:
        text = payload.decode("utf-8", errors="strict")
        return strict_json_loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FrameError(f"invalid strict UTF-8 JSON: {exc}") from exc


def write_frame(sock: socket.socket, value: Any) -> None:
    payload = canonical_json_bytes(value)
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise FrameError(f"response frame size out of range: {len(payload)}")
    sock.sendall(struct.pack(">I", len(payload)) + payload)

