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


def test_block_cells_state_the_range_a_lost_block_closed_in():
    # We know it was open at 09:40 and shut by 16:02 — so say so, rather than
    # throwing the ceiling away and printing 'lost'.
    cells = analyse.block_cells({
        "opened": "07:00:05", "closed": "09:40:19", "duration": 9614,
        "end_reason": "lost", "bound": "16:02:10", "bound_duration": 32525,
    })
    assert cells == ("09:40–16:02", "2h40m–9h02m")


def test_block_cells_still_say_lost_when_sight_never_returned():
    cells = analyse.block_cells({
        "opened": "07:00:15", "closed": "08:17:20", "duration": 4625,
        "end_reason": "lost", "bound": None, "bound_duration": None,
    })
    assert cells == ("lost", "≥ 1h17m")


def test_display_blocks_bound_a_lost_block_from_an_old_summary():
    # Summaries rolled up before bound_local existed still carry their
    # transitions, so the ceiling can be recovered from those.
    rows = analyse.opening_hours_rows([{
        "date": "2026-08-07", "weekday": "Friday",
        "first_open_local": "2026-08-07T07:00:00+01:00",
        "open_blocks": [
            {"start_local": "2026-08-07T07:00:00+01:00",
             "end_local": "2026-08-07T09:40:00+01:00",
             "end_reason": "lost", "duration_seconds": 9600},
        ],
        "transitions": [
            {"route": "/", "state": "open", "at_local": "2026-08-07T07:00:00+01:00"},
            {"route": "/", "state": "unknown", "at_local": "2026-08-07T09:41:00+01:00"},
            {"route": "/admin", "state": "closed", "at_local": "2026-08-07T09:50:00+01:00"},
            {"route": "/", "state": "open", "at_local": "2026-08-07T15:22:00+01:00"},
            {"route": "/", "state": "closed", "at_local": "2026-08-07T16:02:00+01:00"},
        ],
    }])
    block = rows[0]["blocks"][0]
    assert block["bound"] == "16:02:00"          # the clinical close, not the admin one
    assert block["bound_duration"] == 32520
    assert analyse.block_cells(block)[0] == "09:40–16:02"


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


def _day_summary(date_str, weekday, blocks, partial=False, first_poll="00:01:00"):
    """A daily summary carrying explicit open blocks, for the weekly tests.

    `first_poll` is the day's first observation — by default just after midnight,
    i.e. a day watched right through the morning window."""
    summary = {"date": date_str, "weekday": weekday, "open_blocks": [
        {"start_local": f"{date_str}T{start}+01:00",
         "end_local": f"{date_str}T{end}+01:00",
         "end_reason": reason, "duration_seconds": secs}
        for start, end, reason, secs in blocks
    ]}
    if first_poll:
        summary["first_poll_local"] = f"{date_str}T{first_poll}+01:00"
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
    assert stats["Monday"]["floor_avg"] == 1800  # but what it did show is kept
    assert stats["Monday"]["avg"] == 1200
    assert stats["Saturday"]["days"] == 0
    assert stats["Saturday"]["no_open"] == 1
    assert stats["Saturday"]["avg"] is None


def test_weekday_stats_averages_the_floors_of_days_never_seen_to_close():
    # Neither Monday completed, so there is no reliable average — but we know
    # each was open at least this long, and that is worth stating.
    days = [
        _day_summary("2026-07-27", "Monday", [("07:00:00", "07:30:00", "lost", 1800)]),
        _day_summary("2026-08-03", "Monday", [("07:00:00", "08:00:00", "ongoing", 3600)],
                     partial=True),
    ]
    stats = analyse.weekday_stats(days)
    assert stats["Monday"]["avg"] is None
    assert stats["Monday"]["days"] == 0
    assert stats["Monday"]["floors"] == 2
    assert stats["Monday"]["floor_avg"] == 2700


def test_weekday_stats_does_not_call_a_day_still_in_progress_never_open():
    # Today, nothing open yet: that is 'not yet', not 'never seen open'. Nothing
    # was seen open, so there is no floor to state either — just no data.
    days = [_day_summary("2026-08-02", "Sunday", [], partial=True)]
    stats = analyse.weekday_stats(days)
    assert stats["Sunday"]["no_open"] == 0
    assert stats["Sunday"]["floors"] == 0
    assert stats["Sunday"]["floor_avg"] is None
    assert stats["Sunday"]["unknown"] == 1


def test_weekday_stats_excludes_a_day_whose_watch_began_after_the_window():
    # Monitoring started that evening — the morning was never observed, so the
    # day is no evidence that the window did not open.
    days = [_day_summary("2026-07-22", "Wednesday", [], first_poll="23:10:00")]
    stats = analyse.weekday_stats(days)
    assert stats["Wednesday"]["no_open"] == 0
    assert stats["Wednesday"]["unknown"] == 1


def test_weekday_stats_excludes_a_day_of_unknown_coverage():
    # An older summary that recorded no coverage at all: nothing to assert.
    days = [_day_summary("2026-07-22", "Wednesday", [], first_poll=None)]
    assert analyse.weekday_stats(days)["Wednesday"]["no_open"] == 0


def test_weekday_stats_still_reports_a_watched_day_that_never_opened():
    days = [_day_summary("2026-07-25", "Saturday", [])]
    stats = analyse.weekday_stats(days)
    assert stats["Saturday"]["no_open"] == 1
    assert stats["Saturday"]["floors"] == 0


def test_recent_weekdays_rolls_back_over_the_weekend():
    # Newest day is a Monday: the window is the previous Tue–Fri plus that Monday,
    # not the Monday on its own.
    days = [
        _day_summary("2026-07-27", "Monday", []),      # outside the five-day window
        _day_summary("2026-07-28", "Tuesday", []),
        _day_summary("2026-07-29", "Wednesday", []),
        _day_summary("2026-07-30", "Thursday", []),
        _day_summary("2026-07-31", "Friday", []),
        _day_summary("2026-08-01", "Saturday", []),    # weekend, never counted
        _day_summary("2026-08-03", "Monday", []),
    ]
    start, week = analyse.recent_weekdays(days)
    assert start == "2026-07-28"
    assert [d["date"] for d in week] == [
        "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03",
    ]


def test_recent_weekdays_skips_weekend_days_that_have_data():
    days = [
        _day_summary("2026-07-31", "Friday", []),
        _day_summary("2026-08-01", "Saturday", []),
        _day_summary("2026-08-02", "Sunday", []),
    ]
    _, week = analyse.recent_weekdays(days)
    assert [d["date"] for d in week] == ["2026-07-31"]


def test_recent_weekdays_of_nothing_is_empty():
    assert analyse.recent_weekdays([]) == (None, [])


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


def test_weekly_report_leaves_the_weekend_out_of_the_pattern():
    # Sat/Sun have never been seen open, so they get a one-line note rather than
    # a row each; 'econsult view -x' still lists them day by day.
    days = [
        _day_summary("2026-07-31", "Friday", [("07:00:00", "08:00:00", "closed", 3600)]),
        _day_summary("2026-08-01", "Saturday", []),
        _day_summary("2026-08-02", "Sunday", []),
    ]
    report = analyse.weekly_report(days)
    assert not any(line.startswith(("  Saturday", "  Sunday")) for line in report.splitlines())
    assert "Weekends: 2 day(s) logged, never seen open" in report


def test_weekly_report_says_so_if_a_weekend_day_ever_opens():
    days = [_day_summary("2026-08-01", "Saturday", [("09:00:00", "10:00:00", "closed", 3600)])]
    report = analyse.weekly_report(days)
    assert "Saturday seen open" in report


def test_weekly_report_omits_the_weekend_note_when_no_weekend_logged():
    days = [_day_summary("2026-07-31", "Friday", [("07:00:00", "08:00:00", "closed", 3600)])]
    assert "Weekends:" not in analyse.weekly_report(days)


def test_weekly_report_states_the_floor_for_a_weekday_that_never_completed():
    # The one Monday was still open when we last looked: say how long we know it
    # was open for rather than printing a dash.
    days = [_day_summary("2026-08-03", "Monday", [("07:00:00", "08:33:00", "ongoing", 5580)],
                         partial=True)]
    report = analyse.weekly_report(days)
    monday = next(line for line in report.splitlines() if line.startswith("  Monday"))
    assert "≥ 1h33m" in monday
    assert "1 day(s) open ≥ 1h33m" in monday


def test_weekly_report_keeps_a_completed_average_free_of_floors():
    days = [
        _day_summary("2026-07-29", "Wednesday", [("07:00:00", "12:00:00", "closed", 18000)]),
        _day_summary("2026-08-05", "Wednesday", [("07:00:00", "09:10:00", "lost", 7800)]),
    ]
    report = analyse.weekly_report(days)
    wednesday = next(line for line in report.splitlines() if line.startswith("  Wednesday"))
    assert "5h00m" in wednesday                   # the average is the completed day alone
    assert "1 day(s) open ≥ 2h10m, not counted" in wednesday


def _closed_day(date_: str, weekday: str) -> dict:
    """A day we watched right through and never saw open."""
    return {
        "date": date_, "weekday": weekday,
        "first_poll_local": f"{date_}T00:00:41+01:00",
        "first_open_local": None, "open_blocks": [],
    }


def _open_day(date_: str, weekday: str, seconds: int = 3600) -> dict:
    opened = f"{date_}T07:00:00+01:00"
    closed = f"{date_}T08:00:00+01:00"
    return {
        "date": date_, "weekday": weekday,
        "first_poll_local": f"{date_}T00:00:41+01:00",
        "first_open_local": opened, "closed_after_open_local": closed,
        "open_duration_seconds": seconds,
        "open_blocks": [{"start_local": opened, "end_local": closed,
                         "end_reason": "closed", "duration_seconds": seconds}],
    }


def test_bank_holiday_is_kept_out_of_its_weekday_counts():
    # Mon 31 Aug 2026 is the summer bank holiday: closed all day, but that says
    # nothing about ordinary Mondays, so it must not land in Monday's counters.
    days = [_open_day("2026-08-24", "Monday"), _closed_day("2026-08-31", "Monday")]
    monday = analyse.weekday_stats(days)["Monday"]
    assert monday["days"] == 1
    assert monday["no_open"] == 0
    assert monday["unknown"] == 0


def test_bank_holiday_line_reports_the_days_set_aside():
    days = [_open_day("2026-08-24", "Monday"), _closed_day("2026-08-31", "Monday")]
    line = analyse.bank_holiday_line(days)
    assert "1 day(s) logged" in line
    assert "never seen open" in line
    assert "Summer bank holiday" in line


def test_bank_holiday_line_is_absent_when_no_bank_holiday_was_logged():
    assert analyse.bank_holiday_line([_open_day("2026-08-24", "Monday")]) is None


def test_bank_holiday_line_says_so_loudly_when_one_opened():
    days = [_open_day("2026-08-31", "Monday")]
    line = analyse.bank_holiday_line(days)
    assert "seen open" in line and "never" not in line


def test_bank_holiday_day_is_flagged_and_labelled_in_the_day_table():
    row = analyse.opening_hours_rows([_closed_day("2026-08-31", "Monday")])[0]
    assert row["bank_holiday"] is True
    assert analyse.day_cell(row) == "Mon BH"


def test_partial_marker_and_bank_holiday_label_coexist():
    day = _closed_day("2026-08-31", "Monday") | {"partial": True}
    assert analyse.day_cell(analyse.opening_hours_rows([day])[0]) == "Mon* BH"


def test_weekly_report_includes_the_bank_holiday_line():
    days = [_open_day("2026-08-24", "Monday"), _closed_day("2026-08-31", "Monday")]
    assert "Bank holidays:" in analyse.weekly_report(days)


def test_bank_holidays_are_excluded_from_the_by_weekday_aggregate():
    days = [_open_day("2026-08-24", "Monday"), _open_day("2026-08-31", "Monday", 60)]
    stats = analyse.opening_hours_stats(days)
    assert stats["by_weekday"]["Monday"] == 3600      # the bank holiday's 60s left out
    assert stats["bank_holidays"] == 1
