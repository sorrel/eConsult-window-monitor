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


def test_poll_with_deadline_true_when_poll_completes(monkeypatch):
    calls = []
    monkeypatch.setattr(daemon.poll, "poll_once", lambda route: calls.append(route))
    assert daemon._poll_with_deadline("/", deadline=2) is True
    assert calls == ["/"]


def test_poll_with_deadline_false_when_poll_wedges(monkeypatch):
    # A poll that hangs past the deadline must not block: returns False fast.
    monkeypatch.setattr(daemon.poll, "poll_once", lambda route: time.sleep(5))
    started = time.monotonic()
    result = daemon._poll_with_deadline("/", deadline=0.3)
    elapsed = time.monotonic() - started
    assert result is False
    assert elapsed < 2  # gave up near the deadline, did not wait the full 5s
