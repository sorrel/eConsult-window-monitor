"""Self-pacing monitor loop. launchd keeps the process alive; the process
decides its own cadence from the wall clock and heals itself without
intervention:

  - Each poll runs under a hard deadline in a worker thread, so a poll that
    wedges (e.g. a blocked DNS lookup that no socket timeout can interrupt)
    cannot freeze the loop — it is abandoned and a fresh attempt follows.
  - After too many consecutive wedged polls the process deliberately exits so
    launchd's KeepAlive relaunches a clean one (fresh DNS resolution).

No third-party services: it contacts only the surgery's public page.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, time as dtime

from . import config
from . import poll
from . import rollup
from . import store

POLL_DEADLINE = 30             # seconds: hard cap on a single poll (covers DNS hangs)
MAX_CONSECUTIVE_FAILURES = 10  # after this many wedged polls, exit -> launchd relaunches


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


def interval_for(now_local: datetime) -> int:
    """Seconds until the next poll: dense in the morning band, else background."""
    start = _parse_hhmm(config.DENSE_START)
    end = _parse_hhmm(config.DENSE_END)
    current = now_local.time()
    if start <= current <= end:
        return config.DENSE_INTERVAL
    return config.BACKGROUND_INTERVAL


def should_poll(now_local: datetime, weekdays_only: bool | None = None) -> bool:
    """Whether to poll now. When weekdays-only is on, skip Saturday and Sunday
    (the window is closed then); otherwise always poll."""
    if weekdays_only is None:
        weekdays_only = config.WEEKDAYS_ONLY
    if weekdays_only and now_local.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    return True


def _poll_with_deadline(route_path: str, deadline: int = POLL_DEADLINE) -> bool:
    """Run one poll in a worker thread bounded by a hard deadline.

    Returns True if the poll completed (a record was written), False if it
    exceeded the deadline (the worker is abandoned as a daemon thread; a fresh
    attempt follows on the next iteration).
    """
    done = threading.Event()

    def target() -> None:
        try:
            poll.poll_once(route_path)
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    return done.wait(deadline)


def _record_timeout(route_path: str) -> None:
    """Log a synthetic 'unknown' record when a poll wedged past its deadline,
    so the gap is visible in the log rather than a silent absence. The absent
    fields (http_status, latency_ms, …) are filled with None by store.append."""
    ts_utc, ts_local, utc_offset = poll.build_timestamps()
    store.append(
        {
            "ts_utc": ts_utc,
            "ts_local": ts_local,
            "utc_offset": utc_offset,
            "state": "unknown",
            "route": route_path,
            "routes_present": [],
            "matched_markers": [],
            "notes": "poll exceeded deadline (network wedge)",
        },
        config.LOG_PATH,
    )


def run() -> None:
    last_admin_poll = 0.0
    consecutive_failures = 0
    while True:
        # Roll any completed day up into a summary and drop its raw polls.
        # Must never break monitoring, so failures here are swallowed.
        try:
            rollup.rollup()
        except Exception:
            pass

        now_local = datetime.now().astimezone()
        if not should_poll(now_local):
            # Weekend, weekdays-only mode: idle without polling, re-check soon.
            time.sleep(config.BACKGROUND_INTERVAL)
            continue

        if _poll_with_deadline(config.CLINICAL_PATH):
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            _record_timeout(config.CLINICAL_PATH)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                os._exit(1)  # let launchd KeepAlive relaunch a clean process

        now_mono = time.monotonic()
        if now_mono - last_admin_poll >= config.ADMIN_INTERVAL:
            _poll_with_deadline(config.ADMIN_PATH)
            last_admin_poll = now_mono

        time.sleep(interval_for(datetime.now().astimezone()))


if __name__ == "__main__":
    run()
