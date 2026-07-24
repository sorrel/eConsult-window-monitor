from click.testing import CliRunner

from monitor import cli, config, store


def test_view_with_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_PATH", tmp_path / "summary.jsonl")
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")
    result = CliRunner().invoke(cli.cli, ["view"])
    assert result.exit_code == 0
    assert "No days logged" in result.output


def test_view_renders_a_day(tmp_path, monkeypatch):
    summary = tmp_path / "summary.jsonl"
    store.append_json({
        "date": "2026-07-23", "weekday": "Thursday",
        "first_open_local": "2026-07-23T07:00:18+01:00",
        "closed_after_open_local": "2026-07-23T08:50:16+01:00",
        "open_duration_seconds": 6598,
    }, summary)
    monkeypatch.setattr(config, "SUMMARY_PATH", summary)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")
    result = CliRunner().invoke(cli.cli, ["view"])
    assert result.exit_code == 0
    assert "eConsult opening hours" in result.output
    assert "2026-07-23" in result.output
    assert "1h49m" in result.output
    assert "Thursday" in result.output


def test_status_with_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")
    result = CliRunner().invoke(cli.cli, ["status"])
    assert result.exit_code == 0
    assert "No polls logged" in result.output


def test_status_shows_latest(tmp_path, monkeypatch):
    log = tmp_path / "obs.jsonl"
    store.append({"ts_utc": "2026-07-24T06:00:11+00:00", "ts_local": "2026-07-24T07:00:11+01:00",
                  "utc_offset": "+01:00", "state": "open", "route": "/", "routes_present": [],
                  "http_status": 200, "latency_ms": 90, "matched_markers": [],
                  "content_sha256": "x", "notes": ""}, log)
    monkeypatch.setattr(config, "LOG_PATH", log)
    result = CliRunner().invoke(cli.cli, ["status"])
    assert result.exit_code == 0
    assert "OPEN" in result.output
