from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RpcFailure(Exception):
    code: int
    message: str
    data: Any = None


Dispatch = Callable[[str, dict[str, Any]], Any]


def error_response(request_id: Any, failure: RpcFailure) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": failure.code,
        "message": failure.message,
    }
    if failure.data is not None:
        error["data"] = failure.data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def handle_request(document: Any, dispatch: Dispatch) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        return error_response(None, RpcFailure(-32600, "Invalid Request"))
    request_id = document.get("id")
    is_notification = "id" not in document
    if set(document) - {"jsonrpc", "id", "method", "params"}:
        return None if is_notification else error_response(
            request_id, RpcFailure(-32600, "Invalid Request")
        )
    if document.get("jsonrpc") != "2.0" or not isinstance(document.get("method"), str):
        return None if is_notification else error_response(
            request_id, RpcFailure(-32600, "Invalid Request")
        )
    params = document.get("params", {})
    if not isinstance(params, dict):
        return None if is_notification else error_response(
            request_id, RpcFailure(-32602, "Invalid params")
        )
    try:
        result = dispatch(document["method"], params)
    except RpcFailure as failure:
        return None if is_notification else error_response(request_id, failure)
    except Exception as exc:  # defensive public protocol boundary
        failure = RpcFailure(
            -32603,
            "Internal error",
            {"type": type(exc).__name__, "detail": str(exc)},
        )
        return None if is_notification else error_response(request_id, failure)
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}

