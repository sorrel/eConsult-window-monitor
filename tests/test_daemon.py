import time

from monitor import daemon, config


def _local(hh, mm):
    from datetime import datetime
    # A naive local datetime is sufficient; interval_for only reads .time().
    return datetime(2026, 7, 22, hh, mm, 0)


def test_interval_dense_inside_morning_band():
    assert daemon.interval_for(_local(5, 30)) == config.DENSE_INTERVAL
    assert daemon.interval_for(_local(7, 0)) == config.DENSE_INTERVAL
    assert daemon.interval_for(_local(8, 45)) == config.DENSE_INTERVAL  # was background at 08:30 cutoff
    assert daemon.interval_for(_local(9, 30)) == config.DENSE_INTERVAL  # was background at 09:00 cutoff
    assert daemon.interval_for(_local(10, 0)) == config.DENSE_INTERVAL


def test_interval_background_outside_band():
    assert daemon.interval_for(_local(5, 29)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(10, 1)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(14, 0)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(0, 0)) == config.BACKGROUND_INTERVAL


def test_interval_is_sparse_all_weekend():
    from datetime import datetime
    # Sat 25 / Sun 26 July: no dense morning band — an hourly spot-check only,
    # since the window has never been seen open at a weekend.
    assert daemon.interval_for(datetime(2026, 7, 25, 7, 0)) == config.WEEKEND_INTERVAL
    assert daemon.interval_for(datetime(2026, 7, 25, 14, 0)) == config.WEEKEND_INTERVAL
    assert daemon.interval_for(datetime(2026, 7, 26, 7, 0)) == config.WEEKEND_INTERVAL
    # Monday morning is dense again.
    assert daemon.interval_for(datetime(2026, 7, 27, 7, 0)) == config.DENSE_INTERVAL


def test_polls_all_days_by_default():
    from datetime import datetime
    # Default (weekdays_only off): weekends still poll — the 2-week verification.
    assert daemon.should_poll(datetime(2026, 7, 25, 8, 0), weekdays_only=False) is True  # Sat
    assert daemon.should_poll(datetime(2026, 7, 26, 8, 0), weekdays_only=False) is True  # Sun


def test_weekdays_only_skips_saturday_and_sunday():
    from datetime import datetime
    assert daemon.should_poll(datetime(2026, 7, 24, 8, 0), weekdays_only=True) is True   # Fri
    assert daemon.should_poll(datetime(2026, 7, 25, 8, 0), weekdays_only=True) is False  # Sat
    assert daemon.should_poll(datetime(2026, 7, 26, 8, 0), weekdays_only=True) is False  # Sun
    assert daemon.should_poll(datetime(2026, 7, 27, 8, 0), weekdays_only=True) is True   # Mon


def _record(http_status):
    return {"state": "open" if http_status else "unknown", "http_status": http_status}


def test_poll_outcome_ok_when_the_page_answers(monkeypatch):
    calls = []
    monkeypatch.setattr(daemon.poll, "poll_once",
                        lambda route: calls.append(route) or _record(200))
    assert daemon._poll_outcome("/", deadline=2) == "ok"
    assert calls == ["/"]


def test_poll_outcome_wedged_when_poll_hangs(monkeypatch):
    # A poll that hangs past the deadline must not block: gives up fast.
    monkeypatch.setattr(daemon.poll, "poll_once", lambda route: time.sleep(5))
    started = time.monotonic()
    outcome = daemon._poll_outcome("/", deadline=0.3)
    elapsed = time.monotonic() - started
    assert outcome == "wedged"
    assert elapsed < 2  # gave up near the deadline, did not wait the full 5s


def test_poll_outcome_unreachable_when_nothing_came_back(monkeypatch):
    # The 3 Aug / 10 Aug fault: the poll finishes instantly with no reply at all.
    # It completed, so it is not wedged — but it is still a failure, and used to
    # reset the failure count and disarm the self-heal entirely.
    monkeypatch.setattr(daemon.poll, "poll_once", lambda route: _record(None))
    assert daemon._poll_outcome("/", deadline=2) == "unreachable"


def test_poll_outcome_unreachable_when_the_poll_raises(monkeypatch):
    def boom(route):
        raise OSError(9, "Bad file descriptor")
    monkeypatch.setattr(daemon.poll, "poll_once", boom)
    assert daemon._poll_outcome("/", deadline=2) == "unreachable"


def test_failing_polls_retry_sooner_than_the_background_cadence():
    quiet = _local(14, 0)   # outside the dense band: normally 20 minutes apart
    assert daemon.sleep_seconds(quiet, 0) == config.BACKGROUND_INTERVAL
    assert daemon.sleep_seconds(quiet, 3) == daemon.RETRY_INTERVAL


def test_failing_polls_never_retry_faster_than_the_schedule():
    dense = _local(7, 0)    # in the band the schedule is already tighter
    assert daemon.sleep_seconds(dense, 3) == config.DENSE_INTERVAL


def test_recovery_relaunches_when_a_fresh_process_can_fetch(monkeypatch):
    # Child succeeds where we cannot: this process is the broken thing, so exit
    # and let launchd start a clean one.
    monkeypatch.setattr(daemon, "_fresh_process_can_fetch", lambda: True)
    exits = []
    monkeypatch.setattr(daemon.os, "_exit", lambda code: exits.append(code))
    daemon._recover(10)
    assert exits == [1]


def test_recovery_stays_put_when_the_network_itself_is_down(monkeypatch):
    # Child fails too: the machine has no network (asleep, off wifi). Relaunching
    # would fix nothing and only thrash launchd — keep polling instead.
    monkeypatch.setattr(daemon, "_fresh_process_can_fetch", lambda: False)
    exits = []
    monkeypatch.setattr(daemon.os, "_exit", lambda code: exits.append(code))
    daemon._recover(10)
    assert exits == []
