from sts_harness.rpc_protocol import RpcFailure, handle_request


def test_rpc_success() -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}},
        lambda method, params: {"method": method, "params": params},
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"method": "ping", "params": {}},
    }


def test_rpc_rejects_unknown_top_level_field() -> None:
    response = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "extra": True},
        lambda method, params: None,
    )
    assert response["error"]["code"] == -32600


def test_rpc_preserves_typed_failure() -> None:
    def dispatch(method, params):
        raise RpcFailure(-32004, "STALE_OBSERVATION", {"current": "sha256:x"})

    response = handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "env.step", "params": {}},
        dispatch,
    )
    assert response["error"] == {
        "code": -32004,
        "message": "STALE_OBSERVATION",
        "data": {"current": "sha256:x"},
    }

