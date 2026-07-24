from monitor import rollup, store


def _rec(ts_local: str, state: str, route: str = "/") -> dict:
    return {
        "ts_utc": ts_local.replace("+01:00", "+00:00"), "ts_local": ts_local,
        "utc_offset": "+01:00", "state": state, "route": route, "routes_present": [],
        "http_status": 200, "latency_ms": 100, "matched_markers": [],
        "content_sha256": None, "notes": "",
    }


def test_summarise_day_captures_edge_and_duration():
    records = [
        _rec("2026-07-23T06:58:40+01:00", "closed"),
        _rec("2026-07-23T06:59:00+01:00", "closed"),
        _rec("2026-07-23T07:00:00+01:00", "open"),
        _rec("2026-07-23T07:01:40+01:00", "open"),
        _rec("2026-07-23T07:02:00+01:00", "closed"),
        _rec("2026-07-23T07:00:05+01:00", "closed", route="/admin"),
    ]
    s = rollup.summarise_day(records, "2026-07-23")
    assert s["date"] == "2026-07-23"
    assert s["weekday"] == "Thursday"          # 2026-07-23 is a Thursday
    assert s["first_open_local"] == "2026-07-23T07:00:00+01:00"
    assert s["first_open_offset"] == "+01:00"  # DST evidence preserved
    assert s["last_closed_before_open_local"] == "2026-07-23T06:59:00+01:00"
    assert s["closed_after_open_local"] == "2026-07-23T07:02:00+01:00"
    assert s["open_duration_seconds"] == 120
    assert s["admin_closed_seen"] is True
    assert s["states"]["closed"] == 4 and s["states"]["open"] == 2


def test_open_blocks_captures_reopens_and_lost_visibility():
    # Opens, closes, reopens, then fetches start failing ('unknown') before any
    # close — the second block must be 'lost', not given a fake close time.
    records = [
        _rec("2026-07-24T07:00:00+01:00", "open"),
        _rec("2026-07-24T07:54:00+01:00", "closed"),   # block 1 closes here
        _rec("2026-07-24T07:56:00+01:00", "closed"),
        _rec("2026-07-24T07:58:00+01:00", "open"),      # reopens
        _rec("2026-07-24T08:19:00+01:00", "open"),
        _rec("2026-07-24T08:20:00+01:00", "unknown"),   # lost sight before a close
    ]
    blocks = rollup.open_blocks(records)
    assert len(blocks) == 2
    assert blocks[0]["end_reason"] == "closed"
    assert blocks[0]["end_local"] == "2026-07-24T07:54:00+01:00"
    assert blocks[0]["duration_seconds"] == 3240
    assert blocks[1]["end_reason"] == "lost"          # never observed a close
    assert blocks[1]["end_local"] == "2026-07-24T08:19:00+01:00"  # last seen open, a floor


def test_open_blocks_still_open_at_end_is_ongoing():
    records = [
        _rec("2026-07-24T07:00:00+01:00", "open"),
        _rec("2026-07-24T07:20:00+01:00", "open"),
    ]
    blocks = rollup.open_blocks(records)
    assert len(blocks) == 1
    assert blocks[0]["end_reason"] == "ongoing"


def test_summarise_day_records_open_blocks():
    records = [
        _rec("2026-07-23T07:00:00+01:00", "open"),
        _rec("2026-07-23T07:02:00+01:00", "closed"),
    ]
    s = rollup.summarise_day(records, "2026-07-23")
    assert s["open_blocks"] == [{
        "start_local": "2026-07-23T07:00:00+01:00",
        "last_open_local": "2026-07-23T07:00:00+01:00",
        "end_local": "2026-07-23T07:02:00+01:00",
        "end_reason": "closed",
        "duration_seconds": 120,
    }]


def test_transitions_capture_change_points_and_drop_flat_runs():
    # A flat run of closed, then open, then closed again -> three clinical
    # transitions, each bounded by the previous state's last poll.
    records = [
        _rec("2026-07-23T06:59:38+01:00", "closed"),
        _rec("2026-07-23T06:59:58+01:00", "closed"),
        _rec("2026-07-23T07:00:18+01:00", "open"),
        _rec("2026-07-23T07:00:38+01:00", "open"),
        _rec("2026-07-23T08:50:16+01:00", "closed"),
    ]
    ts = rollup.transitions(records)
    assert len(ts) == 3  # the two flat 'closed'/'open' runs collapse to their change points
    assert ts[0] == {
        "route": "/", "state": "closed", "at_local": "2026-07-23T06:59:38+01:00",
        "at_utc": "2026-07-23T06:59:38+00:00", "at_offset": "+01:00",
        "prev_state": None, "prev_last_local": None,
    }
    assert ts[1]["state"] == "open"
    assert ts[1]["at_local"] == "2026-07-23T07:00:18+01:00"
    assert ts[1]["prev_state"] == "closed"
    assert ts[1]["prev_last_local"] == "2026-07-23T06:59:58+01:00"  # edge pinned
    assert ts[2]["state"] == "closed"
    assert ts[2]["at_local"] == "2026-07-23T08:50:16+01:00"


def test_summary_includes_transitions():
    records = [
        _rec("2026-07-23T06:59:58+01:00", "closed"),
        _rec("2026-07-23T07:00:18+01:00", "open"),
    ]
    s = rollup.summarise_day(records, "2026-07-23")
    assert [t["state"] for t in s["transitions"]] == ["closed", "open"]


def test_summarise_day_with_no_open():
    records = [_rec("2026-07-22T21:00:00+01:00", "closed")]
    s = rollup.summarise_day(records, "2026-07-22")
    assert s["first_open_local"] is None
    assert s["open_duration_seconds"] is None
    assert s["polls"] == 1


def test_rollup_summarises_past_days_and_keeps_today(tmp_path):
    log = tmp_path / "obs.jsonl"
    summary = tmp_path / "summary.jsonl"
    for r in [
        _rec("2026-07-22T21:40:00+01:00", "closed"),
        _rec("2026-07-22T22:00:00+01:00", "closed"),
        _rec("2026-07-23T06:00:00+01:00", "closed"),
        _rec("2026-07-23T07:00:00+01:00", "open"),
    ]:
        store.append(r, log)

    n = rollup.rollup(log, summary, today="2026-07-23")
    assert n == 1  # only 2026-07-22 was a completed past day

    summaries = store.read_all(summary)
    assert [s["date"] for s in summaries] == ["2026-07-22"]

    kept = store.read_all(log)
    assert {r["ts_local"][:10] for r in kept} == {"2026-07-23"}  # today's raw polls remain
    assert len(kept) == 2


def test_rollup_is_idempotent(tmp_path):
    log = tmp_path / "obs.jsonl"
    summary = tmp_path / "summary.jsonl"
    for r in [_rec("2026-07-22T21:40:00+01:00", "closed"),
              _rec("2026-07-23T06:00:00+01:00", "closed")]:
        store.append(r, log)

    assert rollup.rollup(log, summary, today="2026-07-23") == 1
    # Running again summarises nothing new and does not duplicate.
    assert rollup.rollup(log, summary, today="2026-07-23") == 0
    assert len(store.read_all(summary)) == 1


def test_rollup_no_op_when_only_today(tmp_path):
    log = tmp_path / "obs.jsonl"
    summary = tmp_path / "summary.jsonl"
    store.append(_rec("2026-07-23T06:00:00+01:00", "closed"), log)
    assert rollup.rollup(log, summary, today="2026-07-23") == 0
    assert store.read_all(summary) == []
    assert len(store.read_all(log)) == 1  # untouched
