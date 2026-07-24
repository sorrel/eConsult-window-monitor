import json

from monitor import store


def _sample_obs() -> dict:
    return {
        "ts_utc": "2026-07-22T19:09:54+00:00",
        "ts_local": "2026-07-22T20:09:54+01:00",
        "utc_offset": "+01:00",
        "state": "closed",
        "route": "/",
        "routes_present": ["child"],
        "http_status": 200,
        "latency_ms": 431,
        "matched_markers": ["booked today", "from 7am tomorrow", "serviceclosed"],
        "content_sha256": "abc123",
        "notes": "",
    }


def test_append_then_read_round_trips(tmp_path):
    log = tmp_path / "obs.jsonl"
    store.append(_sample_obs(), log)
    records = store.read_all(log)
    assert len(records) == 1
    record = records[0]
    assert record["ts_utc"] == "2026-07-22T19:09:54+00:00"
    assert record["ts_local"] == "2026-07-22T20:09:54+01:00"
    assert record["utc_offset"] == "+01:00"
    assert record["state"] == "closed"
    assert record["route"] == "/"
    assert record["http_status"] == 200
    assert record["latency_ms"] == 431
    assert record["routes_present"] == ["child"]
    assert record["matched_markers"][0] == "booked today"


def test_append_is_append_only(tmp_path):
    log = tmp_path / "obs.jsonl"
    store.append(_sample_obs(), log)
    store.append(_sample_obs() | {"state": "open"}, log)
    records = store.read_all(log)
    assert len(records) == 2
    assert records[0]["state"] == "closed"
    assert records[1]["state"] == "open"


def test_each_line_is_valid_standalone_json(tmp_path):
    log = tmp_path / "obs.jsonl"
    store.append(_sample_obs(), log)
    store.append(_sample_obs() | {"state": "open"}, log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each line parses independently


def test_append_creates_missing_parent_directory(tmp_path):
    log = tmp_path / "nested" / "dir" / "obs.jsonl"
    store.append(_sample_obs(), log)
    assert log.exists()


def test_read_all_missing_file_returns_empty(tmp_path):
    assert store.read_all(tmp_path / "does-not-exist.jsonl") == []
