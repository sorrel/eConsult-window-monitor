from monitor import analyse


def test_fmt_duration():
    assert analyse.fmt_duration(None) == "—"
    assert analyse.fmt_duration(6598) == "1h49m"   # yesterday's ~110 min
    assert analyse.fmt_duration(3600) == "1h00m"
    assert analyse.fmt_duration(125) == "2m05s"


def _day(date, weekday, opened=None, closed=None, dur=None, partial=False):
    return {
        "date": date, "weekday": weekday,
        "first_open_local": opened, "closed_after_open_local": closed,
        "open_duration_seconds": dur, "partial": partial,
    }


def test_report_lists_days_and_averages_excluding_partial():
    days = [
        _day("2026-07-22", "Wednesday"),  # no open
        _day("2026-07-23", "Thursday", "2026-07-23T07:00:18+01:00",
             "2026-07-23T08:50:16+01:00", 6598),
        _day("2026-07-24", "Friday", "2026-07-24T07:00:11+01:00", None, 5400, partial=True),
    ]
    report = analyse.opening_hours_report(days)
    # every day appears
    assert "2026-07-22" in report and "2026-07-23" in report and "2026-07-24" in report
    # the reliable day's duration shows
    assert "1h49m" in report
    # partial day is flagged and its duration marked, but excluded from the average
    assert "Fri*" in report
    # With only one reliable day, don't dress it up as an "average" — show N=1 plainly.
    assert "from 1 open day" in report
    assert "average 1h49m" not in report      # no fake "average" over a single day
    assert "Open duration over" not in report  # the multi-day averaging line is absent
    assert "with an open observed: 2" in report
    assert "Thursday" in report               # by-weekday breakdown


def test_average_only_over_open_completed_days():
    # Two reliable open days average their durations; a no-open day and a
    # provisional day never enter the average.
    days = [
        _day("2026-07-20", "Monday"),  # no open — must not count
        _day("2026-07-21", "Tuesday", "2026-07-21T07:00:00+01:00",
             "2026-07-21T08:00:00+01:00", 3600),   # 1h00m
        _day("2026-07-22", "Wednesday", "2026-07-22T07:00:00+01:00",
             "2026-07-22T09:00:00+01:00", 7200),   # 2h00m
        _day("2026-07-23", "Thursday", "2026-07-23T07:00:00+01:00", None, 9999, partial=True),
    ]
    report = analyse.opening_hours_report(days)
    assert "over 2 open days" in report        # provisional + no-open excluded from the count
    assert "average 1h30m" in report           # (1h + 2h) / 2, not dragged down by the no-open day
    assert "shortest 1h00m" in report and "longest 2h00m" in report


def test_report_handles_no_data():
    report = analyse.opening_hours_report([])
    assert "Days logged: 0" in report
