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
    result = CliRunner().invoke(cli.cli, ["view", "-x"])
    assert result.exit_code == 0
    assert "eConsult opening hours" in result.output
    assert "2026-07-23" in result.output
    assert "1h49m" in result.output
    assert "Thursday" in result.output


def test_view_defaults_to_the_weekly_pattern(tmp_path, monkeypatch):
    # Two Thursdays a week apart plus one Friday: the default view averages by
    # weekday and shows only the latest week day by day.
    summary = tmp_path / "summary.jsonl"
    for date_str, weekday, secs in [("2026-07-23", "Thursday", 3600),
                                    ("2026-07-30", "Thursday", 7200),
                                    ("2026-07-31", "Friday", 5400)]:
        store.append_json({
            "date": date_str, "weekday": weekday,
            "first_open_local": f"{date_str}T07:00:00+01:00",
            "open_blocks": [{
                "start_local": f"{date_str}T07:00:00+01:00",
                "end_local": f"{date_str}T08:00:00+01:00",
                "end_reason": "closed", "duration_seconds": secs,
            }],
        }, summary)
    monkeypatch.setattr(config, "SUMMARY_PATH", summary)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")

    result = CliRunner().invoke(cli.cli, ["view"])
    assert result.exit_code == 0
    assert "weekly pattern" in result.output
    assert "1h30m" in result.output              # the two Thursdays, averaged
    assert "Latest week" in result.output
    assert "2026-07-30" in result.output         # in the latest week
    assert "2026-07-23" not in result.output     # an earlier week: only in the average


def test_view_summarises_the_weekend_in_one_line(tmp_path, monkeypatch):
    # A weekend day never seen open belongs in a note, not in the pattern table;
    # -x still lists it day by day.
    summary = tmp_path / "summary.jsonl"
    for date_str, weekday in [("2026-07-31", "Friday"), ("2026-08-01", "Saturday")]:
        store.append_json({
            "date": date_str, "weekday": weekday,
            "first_open_local": f"{date_str}T07:00:00+01:00" if weekday == "Friday" else None,
            "open_blocks": [{
                "start_local": f"{date_str}T07:00:00+01:00",
                "end_local": f"{date_str}T08:00:00+01:00",
                "end_reason": "closed", "duration_seconds": 3600,
            }] if weekday == "Friday" else [],
            "first_poll_local": f"{date_str}T00:01:00+01:00",
        }, summary)
    monkeypatch.setattr(config, "SUMMARY_PATH", summary)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")

    weekly = CliRunner().invoke(cli.cli, ["view"])
    assert weekly.exit_code == 0
    assert not any(line.startswith("  Saturday") for line in weekly.output.splitlines())
    assert "Weekends: 1 day(s) logged, never seen open" in weekly.output

    everything = CliRunner().invoke(cli.cli, ["view", "-x"])
    assert "2026-08-01" in everything.output


def test_view_x_shows_every_day(tmp_path, monkeypatch):
    summary = tmp_path / "summary.jsonl"
    for date_str, weekday in [("2026-07-23", "Thursday"), ("2026-07-30", "Thursday")]:
        store.append_json({
            "date": date_str, "weekday": weekday,
            "first_open_local": f"{date_str}T07:00:00+01:00",
            "closed_after_open_local": f"{date_str}T08:00:00+01:00",
            "open_duration_seconds": 3600,
        }, summary)
    monkeypatch.setattr(config, "SUMMARY_PATH", summary)
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "obs.jsonl")

    result = CliRunner().invoke(cli.cli, ["view", "-x"])
    assert result.exit_code == 0
    assert "2026-07-23" in result.output and "2026-07-30" in result.output
    assert "weekly pattern" not in result.output


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
