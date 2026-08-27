"""Single tunable configuration block for the monitor.

All paths derive from the repo root at runtime; nothing is hardcoded to a
specific user's home directory.
"""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

# Repo root = parent of the `src/` dir that holds this package. This file lives
# at src/monitor/config.py, so the root is three parents up. Derived, never
# hardcoded.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
LOG_PATH: Path = DATA_DIR / "observations.jsonl"       # current day's raw polls
SUMMARY_PATH: Path = DATA_DIR / "daily_summary.jsonl"  # one summary line per past day
SNAPSHOT_DIR: Path = DATA_DIR / "snapshots"

# The page being observed is kept out of the (public) source tree so it names no
# particular surgery. Set it locally, in order of precedence:
#   1. the ECONSULT_BASE_URL environment variable,
#   2. ECONSULT_BASE_URL in a `.env` at the repo root — normally mounted from
#      the "eConsult Monitor" 1Password Environment, or
#   3. a one-line, gitignored `target_url.local` file at the repo root.
# Absent all three, a neutral placeholder is used. That is never a working
# configuration, so `require_configured()` turns it into a loud failure rather
# than letting the monitor quietly observe a domain that does not exist.
_PLACEHOLDER_URL = "https://example-surgery.example.com"
_LOCAL_URL_FILE = REPO_ROOT / "target_url.local"
_ENV_FILE = REPO_ROOT / ".env"

# A 1Password local-env file is a FIFO, not a regular file: it yields its
# contents only once 1Password attaches as a writer, which needs the app
# unlocked and the read authorised. Unattended (launchd starts us at boot) that
# may never happen, and a plain blocking read would hang forever — this module
# is imported by the CLI and the tests too, so that hang would be everywhere.
# We therefore read it non-blocking under a deadline and fall back to
# `target_url.local`, which holds the same URL. Short, because the fallback
# costs nothing: a locked 1Password should not stall an interactive command.
_ENV_READ_TIMEOUT = 5.0


def _read_env_file(path: Path, timeout: float = _ENV_READ_TIMEOUT) -> str:
    """Return the text of `path`, or "" — never blocking longer than `timeout`.

    Handles both a regular file and a 1Password FIFO. For the FIFO, O_NONBLOCK
    makes open() return even with no writer attached (the open is itself what
    prompts 1Password to attach), then we poll until the writer has written and
    closed. An empty read means "no writer *yet*", not end-of-data, so it only
    counts as EOF once some bytes have actually arrived.
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return ""

    if not stat.S_ISFIFO(mode):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return ""

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                chunk = None          # writer attached but nothing ready yet
            except OSError:
                return ""
            if chunk:
                chunks.append(chunk)
                continue
            if chunk == b"" and chunks:
                break                 # writer closed after writing: real EOF
            time.sleep(0.05)          # no writer yet — give 1Password a moment
        else:
            return ""                 # deadline passed; treat as unconfigured
    finally:
        os.close(fd)

    return b"".join(chunks).decode("utf-8", "replace")


def _parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Deliberately does not touch os.environ: reading a
    config file should not mutate process-wide state behind the caller's back.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _resolve_base_url() -> str:
    env = os.environ.get("ECONSULT_BASE_URL")
    if env and env.strip():
        return env.strip().rstrip("/")
    from_file = _parse_env(_read_env_file(_ENV_FILE)).get("ECONSULT_BASE_URL", "")
    if from_file.strip():
        return from_file.strip().rstrip("/")
    if _LOCAL_URL_FILE.exists():
        local = _LOCAL_URL_FILE.read_text(encoding="utf-8").strip()
        if local:
            return local.rstrip("/")
    return _PLACEHOLDER_URL


BASE_URL: str = _resolve_base_url()
IS_CONFIGURED: bool = BASE_URL != _PLACEHOLDER_URL


def require_configured() -> None:
    """Abort unless a real target URL was resolved.

    Polling the placeholder domain looks like a total outage: every request
    fails, the failure counter climbs, and the self-heal relaunches a process
    that was never going to work. Far better to say so and stop.
    """
    if IS_CONFIGURED:
        return
    raise SystemExit(
        "econsult: no target URL configured, so there is nothing to observe.\n"
        "Set one of, in order of precedence:\n"
        "  1. the ECONSULT_BASE_URL environment variable\n"
        f"  2. ECONSULT_BASE_URL in {_ENV_FILE} (mount the 'eConsult Monitor'\n"
        "     1Password Environment there, and unlock 1Password)\n"
        f"  3. a one-line {_LOCAL_URL_FILE}\n"
        "Refusing to poll the placeholder domain."
    )


CLINICAL_PATH: str = "/"
ADMIN_PATH: str = "/admin"

# Polite fetching. No email or personal identifier in the User-Agent.
USER_AGENT: str = "econsult-window-monitor/0.1 (personal read-only availability check)"
REQUEST_TIMEOUT: int = 15  # seconds

# Cadence, expressed in local time. One place to tune the whole schedule.
DENSE_START: str = "05:30"       # morning band start (local)
DENSE_END: str = "10:00"         # morning band end (local) — well past the observed close
DENSE_INTERVAL: int = 20         # seconds between polls inside the band
BACKGROUND_INTERVAL: int = 1200  # seconds between polls otherwise (20 min)
WEEKEND_INTERVAL: int = 3600     # seconds between polls at a weekend (hourly, all day)
ADMIN_INTERVAL: int = 1200       # poll the /admin route at most this often

# Weekends. The first fortnight polled every day at the weekday cadence to see
# whether the window ever opens Sat/Sun: across 25–26 Jul, 1–2 Aug and 8 Aug it
# never did — closed on every one of ~700+ polls a day. From 2026-08-09 weekends
# drop to WEEKEND_INTERVAL (an hourly spot-check, no dense morning band), which
# keeps the evidence accumulating at a fraction of the requests. Setting
# WEEKDAYS_ONLY = True stops weekend polling altogether.
WEEKDAYS_ONLY: bool = False
