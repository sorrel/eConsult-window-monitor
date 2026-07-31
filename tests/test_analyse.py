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


def _day_summary(date_str, weekday, blocks, partial=False):
    """A daily summary carrying explicit open blocks, for the weekly tests."""
    summary = {"date": date_str, "weekday": weekday, "open_blocks": [
        {"start_local": f"{date_str}T{start}+01:00",
         "end_local": f"{date_str}T{end}+01:00",
         "end_reason": reason, "duration_seconds": secs}
        for start, end, reason, secs in blocks
    ]}
    if summary["open_blocks"]:
        summary["first_open_local"] = summary["open_blocks"][0]["start_local"]
    if partial:
        summary["partial"] = True
    return summary


def test_day_total_open_sums_every_block():
    # A day that reopened: the total is both blocks, and it is reliable because
    # each one was seen to close.
    day = _day_summary("2026-07-28", "Tuesday",
                       [("07:00:00", "08:28:00", "closed", 5280),
                        ("09:40:00", "11:20:00", "closed", 6000)])
    assert analyse.day_total_open(day) == (11280, True)


def test_day_total_open_is_a_floor_when_a_block_was_lost():
    day = _day_summary("2026-07-24", "Friday",
                       [("07:00:00", "07:54:00", "closed", 3240),
                        ("10:31:00", "11:11:00", "lost", 2400)])
    assert analyse.day_total_open(day) == (5640, False)   # total known, but understated


def test_day_total_open_treats_a_partial_day_as_unreliable():
    day = _day_summary("2026-07-31", "Friday",
                       [("07:00:00", "08:30:00", "closed", 5400)], partial=True)
    assert analyse.day_total_open(day) == (5400, False)


def test_day_total_open_is_none_when_nothing_opened():
    assert analyse.day_total_open(_day_summary("2026-07-25", "Saturday", [])) == (None, False)


def test_weekday_stats_averages_total_open_across_weeks():
    # Two Thursdays a week apart: the average is over both, spanning 2 weeks.
    days = [
        _day_summary("2026-07-23", "Thursday", [("07:00:00", "08:00:00", "closed", 3600)]),
        _day_summary("2026-07-30", "Thursday", [("07:00:00", "09:00:00", "closed", 7200)]),
    ]
    stats = analyse.weekday_stats(days)
    assert stats["Thursday"]["avg"] == 5400
    assert stats["Thursday"]["days"] == 2
    assert stats["Thursday"]["weeks"] == 2
    assert stats["Thursday"]["starts"] == ["07:00"]


def test_weekday_stats_flags_days_left_out_of_the_average():
    days = [
        _day_summary("2026-07-27", "Monday", [("07:00:00", "07:20:00", "closed", 1200)]),
        _day_summary("2026-08-03", "Monday", [("07:00:00", "07:30:00", "lost", 1800)]),
        _day_summary("2026-07-25", "Saturday", []),
    ]
    stats = analyse.weekday_stats(days)
    assert stats["Monday"]["days"] == 1          # only the reliable Monday counts
    assert stats["Monday"]["floors"] == 1        # the lost one is flagged, not counted
    assert stats["Monday"]["avg"] == 1200
    assert stats["Saturday"]["days"] == 0
    assert stats["Saturday"]["no_open"] == 1
    assert stats["Saturday"]["avg"] is None


def test_latest_week_is_the_monday_first_week_of_the_newest_day():
    days = [
        _day_summary("2026-07-24", "Friday", []),      # previous week
        _day_summary("2026-07-27", "Monday", []),      # current week
        _day_summary("2026-07-31", "Friday", []),
    ]
    monday, week = analyse.latest_week(days)
    assert monday == "2026-07-27"
    assert [d["date"] for d in week] == ["2026-07-27", "2026-07-31"]


def test_latest_week_of_nothing_is_empty():
    assert analyse.latest_week([]) == (None, [])


def test_weekly_report_shows_the_pattern_and_the_latest_week():
    days = [
        _day_summary("2026-07-23", "Thursday", [("07:00:00", "08:00:00", "closed", 3600)]),
        _day_summary("2026-07-30", "Thursday", [("07:00:00", "09:00:00", "closed", 7200)]),
        _day_summary("2026-07-31", "Friday", [("07:00:00", "08:30:00", "closed", 5400)], partial=True),
    ]
    report = analyse.weekly_report(days)
    assert "Thursday" in report
    assert "1h30m" in report                     # the Thursday average
    assert "Latest week" in report
    assert "2026-07-30" in report and "2026-07-31" in report
    assert "2026-07-23" not in report            # an earlier week's row is not in the week table
