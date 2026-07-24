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
    assert "average 1h49m" in report          # only the one reliable day counts
    assert "with an open observed: 2" in report
    assert "Thursday" in report               # by-weekday breakdown


def test_report_handles_no_data():
    report = analyse.opening_hours_report([])
    assert "Days logged: 0" in report
