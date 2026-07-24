from monitor import analyse, store


def _rec(ts_local: str, state: str, route: str = "/") -> dict:
    return {
        "ts_utc": ts_local, "ts_local": ts_local, "utc_offset": "+01:00",
        "state": state, "route": route, "routes_present": [],
        "http_status": 200, "latency_ms": 100, "matched_markers": [],
        "content_sha256": None, "notes": "",
    }


def test_first_open_by_day():
    records = [
        _rec("2026-07-22T06:58:40+01:00", "closed"),
        _rec("2026-07-22T07:00:00+01:00", "open"),
        _rec("2026-07-22T07:00:20+01:00", "open"),
    ]
    assert analyse.first_open_by_day(records) == [("2026-07-22", "2026-07-22T07:00:00+01:00")]


def test_last_closed_before_first_open_bounds_the_edge():
    records = [
        _rec("2026-07-22T06:58:40+01:00", "closed"),
        _rec("2026-07-22T06:59:00+01:00", "closed"),
        _rec("2026-07-22T07:00:00+01:00", "open"),
    ]
    assert analyse.last_closed_before_first_open(records, "2026-07-22") == "2026-07-22T06:59:00+01:00"


def test_admin_ever_closed():
    records = [_rec("2026-07-22T09:00:00+01:00", "open", route="/admin")]
    assert analyse.admin_ever_closed(records) is False
    records.append(_rec("2026-07-23T09:00:00+01:00", "closed", route="/admin"))
    assert analyse.admin_ever_closed(records) is True


def test_open_duration_by_day():
    records = [
        _rec("2026-07-22T07:00:00+01:00", "open"),
        _rec("2026-07-22T07:01:40+01:00", "open"),
        _rec("2026-07-22T07:02:00+01:00", "closed"),
    ]
    assert analyse.open_duration_by_day(records) == [
        ("2026-07-22", "2026-07-22T07:00:00+01:00", "2026-07-22T07:02:00+01:00")
    ]


def test_weekday_open_times():
    # 2026-07-22 is a Wednesday.
    records = [_rec("2026-07-22T07:00:00+01:00", "open")]
    assert analyse.weekday_open_times(records) == [("Wednesday", "2026-07-22T07:00:00+01:00")]


def test_opening_hours_report_shows_every_block_and_no_question_mark():
    # A partial day that reopened: the report must list both blocks and must not
    # hedge the duration with a '?' (dropped by request), keeping only the '*'.
    summaries = [{
        "date": "2026-07-24", "weekday": "Friday", "partial": True,
        "first_open_local": "2026-07-24T07:00:00+01:00",
        "closed_after_open_local": "2026-07-24T07:54:00+01:00",
        "open_duration_seconds": 3240,
        "open_blocks": [
            {"start_local": "2026-07-24T07:00:00+01:00",
             "end_local": "2026-07-24T07:54:00+01:00",
             "end_reason": "closed", "duration_seconds": 3240},
            {"start_local": "2026-07-24T10:31:00+01:00",
             "end_local": "2026-07-24T11:11:00+01:00",
             "end_reason": "lost", "duration_seconds": 2400},
        ],
    }]
    report = analyse.opening_hours_report(summaries)
    assert "?" not in report                 # question marks dropped
    assert "Fri*" in report                  # provisional marker kept
    assert "07:00:00" in report and "10:31:00" in report   # both blocks shown
    assert "(reopened)" in report
    assert "lost" in report                  # honest about the un-closed block


def test_display_blocks_falls_back_for_old_summaries():
    # A summary written before open_blocks existed still yields one block.
    rows = analyse.opening_hours_rows([{
        "date": "2026-07-23", "weekday": "Thursday",
        "first_open_local": "2026-07-23T07:00:00+01:00",
        "closed_after_open_local": "2026-07-23T08:50:00+01:00",
        "open_duration_seconds": 6600,
    }])
    assert len(rows[0]["blocks"]) == 1
    assert rows[0]["blocks"][0]["opened"] == "07:00:00"
    assert rows[0]["blocks"][0]["end_reason"] == "closed"


def test_analyse_reads_from_jsonl_log(tmp_path):
    log = tmp_path / "obs.jsonl"
    store.append(_rec("2026-07-22T07:00:00+01:00", "open"), log)
    records = store.read_all(log)
    assert analyse.first_open_by_day(records) == [("2026-07-22", "2026-07-22T07:00:00+01:00")]
