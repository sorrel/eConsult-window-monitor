"""Single tunable configuration block for the monitor.

All paths derive from the repo root at runtime; nothing is hardcoded to a
specific user's home directory.
"""
from __future__ import annotations

import os
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
#   1. the ECONSULT_BASE_URL environment variable, or
#   2. a one-line, gitignored `target_url.local` file at the repo root.
# Absent both, a neutral placeholder is used (the monitor then observes nothing
# real until configured).
_PLACEHOLDER_URL = "https://example-surgery.example.com"
_LOCAL_URL_FILE = REPO_ROOT / "target_url.local"


def _resolve_base_url() -> str:
    env = os.environ.get("ECONSULT_BASE_URL")
    if env and env.strip():
        return env.strip().rstrip("/")
    if _LOCAL_URL_FILE.exists():
        local = _LOCAL_URL_FILE.read_text(encoding="utf-8").strip()
        if local:
            return local.rstrip("/")
    return _PLACEHOLDER_URL


BASE_URL: str = _resolve_base_url()
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
