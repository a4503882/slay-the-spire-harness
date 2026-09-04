import socket
import struct

import pytest

from sts_harness.framing import MAX_FRAME_BYTES, FrameError, read_frame, write_frame


def test_framing_round_trip() -> None:
    left, right = socket.socketpair()
    try:
        write_frame(left, {"message": "尖塔", "value": 3})
        assert read_frame(right) == {"message": "尖塔", "value": 3}
    finally:
        left.close()
        right.close()


def test_framing_rejects_duplicate_json_keys() -> None:
    left, right = socket.socketpair()
    try:
        payload = b'{"a":1,"a":2}'
        left.sendall(struct.pack(">I", len(payload)) + payload)
        with pytest.raises(FrameError, match="duplicate JSON key"):
            read_frame(right)
    finally:
        left.close()
        right.close()


def test_framing_rejects_oversized_header_without_reading_payload() -> None:
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack(">I", MAX_FRAME_BYTES + 1))
        with pytest.raises(FrameError, match="frame too large"):
            read_frame(right)
    finally:
        left.close()
        right.close()

