"""Minimal, read-only MCP server exposing the eConsult monitor's data.

Standard library only — implements just enough of the Model Context Protocol
(JSON-RPC 2.0 over stdio, newline-delimited) to let Claude Desktop query the
observation log. Read-only: it never polls, submits, or mutates anything.

Tools:
  - econsult_status   : latest observed state (open/closed/unknown) + summary
  - econsult_recent   : the most recent N polls
  - econsult_findings : the four Phase 0 findings

Run: python -m monitor.mcp_server   (stdio transport)
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import analyse
from . import config
from . import store

SERVER_NAME = "econsult-window-monitor"
SERVER_VERSION = "0.1.0"
_DEFAULT_PROTOCOL = "2024-11-05"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "econsult_status",
        "description": (
            "Latest observed state of the eConsult clinical window "
            "(open / closed / unknown), with timestamp and total polls logged."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "econsult_recent",
        "description": "The most recent eConsult polls (default 10).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many recent polls", "default": 10}
            },
        },
    },
    {
        "name": "econsult_findings",
        "description": (
            "Phase 0 findings from the log: first-open time per day, time to "
            "'booked', day-of-week, and whether the admin route ever closed."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _records() -> list[dict[str, Any]]:
    return store.read_all(config.LOG_PATH)


def _tool_status() -> str:
    records = _records()
    if not records:
        return "No polls logged yet. The monitor writes to data/observations.jsonl."
    last = records[-1]
    return (
        f"Latest: {last['state'].upper()} "
        f"at {last['ts_local']} (route {last['route']}, http {last['http_status']}). "
        f"{len(records)} polls logged in total."
    )


def _tool_recent(limit: int = 10) -> str:
    records = _records()
    if not records:
        return "No polls logged yet."
    limit = max(1, min(int(limit), 200))
    lines = [
        f"{r['ts_local']}  {r['route']:7} {r['state']:8} http={r['http_status']} {r['latency_ms']}ms"
        for r in records[-limit:]
    ]
    return "\n".join(lines)


def _tool_findings() -> str:
    summaries = store.read_all(config.SUMMARY_PATH)
    return analyse.format_findings(summaries, _records())


def _call_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "econsult_status":
        return _tool_status()
    if name == "econsult_recent":
        return _tool_recent(arguments.get("limit", 10))
    if name == "econsult_findings":
        return _tool_findings()
    raise KeyError(f"unknown tool: {name}")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Returns a response dict, or None for notifications."""
    method = request.get("method")
    request_id = request.get("id")

    # Notifications (no id) get no response.
    if request_id is None and method != "ping":
        return None

    if method == "initialize":
        protocol = request.get("params", {}).get("protocolVersion", _DEFAULT_PROTOCOL)
        return _result(request_id, {
            "protocolVersion": protocol,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})

    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        try:
            text = _call_tool(name, arguments)
        except KeyError as exc:
            return _error(request_id, -32602, str(exc))
        except Exception as exc:  # surface as a tool error, not a transport crash
            return _result(request_id, {
                "content": [{"type": "text", "text": f"error: {exc}"}],
                "isError": True,
            })
        return _result(request_id, {"content": [{"type": "text", "text": text}]})

    return _error(request_id, -32601, f"method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
