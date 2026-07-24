from monitor import mcp_server, store


def test_initialize_echoes_protocol_and_advertises_tools():
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2025-06-18"}}
    resp = mcp_server.handle_request(req)
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2025-06-18"  # echoes client's version
    assert resp["result"]["capabilities"]["tools"] == {}
    assert resp["result"]["serverInfo"]["name"] == "econsult-window-monitor"


def test_initialize_defaults_protocol_when_absent():
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["protocolVersion"] == "2024-11-05"


def test_notification_returns_no_response():
    # A notification (no id) must not produce a response.
    assert mcp_server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_contains_the_three_tools():
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"econsult_status", "econsult_recent", "econsult_findings"}
    for tool in resp["result"]["tools"]:
        assert "inputSchema" in tool and tool["inputSchema"]["type"] == "object"


def test_status_tool_reads_the_log(tmp_path, monkeypatch):
    log = tmp_path / "obs.jsonl"
    store.append({"ts_utc": "2026-07-22T20:53:17+00:00", "ts_local": "2026-07-22T21:53:17+01:00",
                  "utc_offset": "+01:00", "state": "closed", "route": "/", "routes_present": [],
                  "http_status": 200, "latency_ms": 97, "matched_markers": [],
                  "content_sha256": "abc", "notes": ""}, log)
    monkeypatch.setattr(mcp_server.config, "LOG_PATH", log)
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                      "params": {"name": "econsult_status", "arguments": {}}})
    text = resp["result"]["content"][0]["text"]
    assert "CLOSED" in text
    assert "1 polls logged" in text


def test_recent_tool_respects_limit(tmp_path, monkeypatch):
    log = tmp_path / "obs.jsonl"
    for i in range(5):
        store.append({"ts_utc": f"2026-07-22T20:0{i}:00+00:00", "ts_local": f"2026-07-22T21:0{i}:00+01:00",
                      "utc_offset": "+01:00", "state": "closed", "route": "/", "routes_present": [],
                      "http_status": 200, "latency_ms": 100, "matched_markers": [],
                      "content_sha256": None, "notes": ""}, log)
    monkeypatch.setattr(mcp_server.config, "LOG_PATH", log)
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                      "params": {"name": "econsult_recent", "arguments": {"limit": 2}}})
    text = resp["result"]["content"][0]["text"]
    assert len(text.splitlines()) == 2


def test_unknown_method_returns_error():
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "no/such"})
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_error():
    resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                                      "params": {"name": "bogus", "arguments": {}}})
    assert resp["error"]["code"] == -32602
