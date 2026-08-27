"""Self-pacing monitor loop. launchd keeps the process alive; the process
decides its own cadence from the wall clock and heals itself without
intervention:

  - Each poll runs under a hard deadline in a worker thread, so a poll that
    wedges (e.g. a blocked DNS lookup that no socket timeout can interrupt)
    cannot freeze the loop — it is abandoned and a fresh attempt follows.
  - A poll that comes back with no reply at all counts as a failure too, not
    just one that hangs. Two long outages (3 and 10 August 2026) failed exactly
    this way — instantly, for hours — and the self-heal never fired because a
    fast failure looked like a completed poll.
  - Whilst polls are failing the loop retries sooner than the background
    cadence, so an outage is bounded tightly at both ends rather than to the
    nearest 20 minutes.
  - After too many consecutive failures the process asks a *fresh subprocess*
    to fetch the page. If the child succeeds where this process cannot, this
    process is the broken thing: exit, and launchd's KeepAlive relaunches a
    clean one. If the child fails too the machine's network is simply out —
    relaunching would fix nothing, so it stays put and keeps polling.

No third-party services: it contacts only the surgery's public page.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, time as dtime

from . import config
from . import poll
from . import rollup
from . import store

POLL_DEADLINE = 30             # seconds: hard cap on a single poll (covers DNS hangs)
MAX_CONSECUTIVE_FAILURES = 10  # failures before trying to recover (see _recover)
RETRY_INTERVAL = 60            # seconds between polls whilst they are failing
PROBE_DEADLINE = 45            # seconds: hard cap on the fresh-subprocess probe


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


def interval_for(now_local: datetime) -> int:
    """Seconds until the next poll: dense in the morning band, else background.

    Weekends get neither — just a sparse all-day spot-check, since the window
    has never once been seen open on a Saturday or Sunday.
    """
    if now_local.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return config.WEEKEND_INTERVAL
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


def _poll_outcome(route_path: str, deadline: int = POLL_DEADLINE) -> str:
    """Run one poll in a worker thread bounded by a hard deadline, and say how
    it went:

      - ``ok``          — the page answered (whatever it said).
      - ``unreachable`` — the poll finished but nothing came back: DNS failure,
        refused connection, or an exception. A record is still written by the
        poll itself, so the gap is in the log either way.
      - ``wedged``      — the poll blew its deadline and was abandoned (left as
        a daemon thread; a fresh attempt follows on the next iteration).

    Only ``ok`` counts as sight of the page; the other two are failures.
    """
    done = threading.Event()
    outcome: list[str] = []

    def target() -> None:
        try:
            record = poll.poll_once(route_path)
            outcome.append("ok" if record.get("http_status") is not None else "unreachable")
        except Exception:
            outcome.append("unreachable")
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    if not done.wait(deadline):
        return "wedged"
    return outcome[0] if outcome else "unreachable"


def sleep_seconds(now_local: datetime, consecutive_failures: int) -> int:
    """How long to wait before the next poll.

    Normally the schedule's own cadence. Whilst polls are failing, no faster
    than the schedule but no slower than RETRY_INTERVAL: a 20-minute background
    gap would leave hours-long outages barely sampled, and it is precisely the
    first reading *after* an outage that bounds when the window closed.
    """
    interval = interval_for(now_local)
    if consecutive_failures:
        return min(interval, RETRY_INTERVAL)
    return interval


def _fresh_process_can_fetch() -> bool:
    """Can a brand-new process fetch the page right now, when this one cannot?

    The decisive test between the two explanations for a run of failed polls:
    a long-lived process that has gone bad, or a machine with no network. Runs
    the package's own fetcher in a child process — no extra dependency, and the
    same single read-only GET the monitor always makes.
    """
    url = config.BASE_URL.rstrip("/") + config.CLINICAL_PATH
    try:
        probe = subprocess.run(
            [sys.executable, "-m", "monitor.fetch", url],
            capture_output=True, text=True, timeout=PROBE_DEADLINE,
        )
    except Exception:
        return False  # could not even run the probe: assume nothing
    return probe.returncode == 0 and probe.stdout.startswith("ok")


def _recover(consecutive_failures: int) -> None:
    """Act on a run of failed polls — relaunch, or wait the outage out.

    Exits (letting launchd's KeepAlive start a clean process) only when a fresh
    process proves the page is reachable and this one has stopped being able to
    reach it. When the network itself is down, exiting would relaunch every few
    minutes for the length of the outage and fix nothing, so it does not.
    """
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    if _fresh_process_can_fetch():
        print(f"{stamp}  {consecutive_failures} consecutive failed polls, but a fresh "
              "process fetched the page — this process is broken; exiting for relaunch",
              flush=True)
        os._exit(1)
    print(f"{stamp}  {consecutive_failures} consecutive failed polls, and a fresh process "
          "cannot reach the page either — the network is out; staying put", flush=True)


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
    # Nothing to observe without a real target, and polling the placeholder
    # would masquerade as a permanent outage — every poll failing, the
    # self-heal relaunching a process that cannot work. Stop instead.
    config.require_configured()

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

        outcome = _poll_outcome(config.CLINICAL_PATH)
        if outcome == "ok":
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if outcome == "wedged":
                _record_timeout(config.CLINICAL_PATH)  # a poll that answered logged itself
            # Re-check every MAX_CONSECUTIVE_FAILURES, not just at the first
            # one: an outage that outlives the probe gets asked again later.
            if consecutive_failures % MAX_CONSECUTIVE_FAILURES == 0:
                _recover(consecutive_failures)

        now_mono = time.monotonic()
        if now_mono - last_admin_poll >= config.ADMIN_INTERVAL:
            _poll_outcome(config.ADMIN_PATH)
            last_admin_poll = now_mono

        time.sleep(sleep_seconds(datetime.now().astimezone(), consecutive_failures))


if __name__ == "__main__":
    run()
