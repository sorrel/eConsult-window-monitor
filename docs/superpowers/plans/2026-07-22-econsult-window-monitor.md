# eConsult Window Monitor (Phase 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only macOS monitor that polls the eConsult page, classifies its state (open/closed/unknown) from server-rendered text, and logs every poll unambiguously to SQLite so the daily open window can be mapped over ~2 weeks.

**Architecture:** A self-pacing Python daemon (kept alive by a launchd LaunchAgent) polls one public URL on a time-of-day cadence — dense in the morning band, sparse otherwise. Each poll: fetch → classify (pure) → store one row with UTC + local + offset timestamps. A separate analysis script reads the log. Nothing is ever submitted.

**Tech Stack:** Modern Python (>=3.12), standard library only (`urllib`, `sqlite3`, `zoneinfo`/`datetime`, `hashlib`, `re`, `html`), run via `uv`. `pytest` as the only dev dependency. macOS `launchd` for scheduling.

## Global Constraints

- **Python >=3.12**, run exclusively via `uv` (`uv run …`). Modern Python idioms.
- **Standard library only** for runtime code. No third-party runtime dependencies. `pytest` is the only dev dependency.
- **British English** in all code, comments, output, and docs (`colour`, `behaviour`, `analyse`).
- **Read-only. Never submit, POST, scrape the form, or model slots/availability.** One sequential GET per poll; no parallel requests.
- **Local-first.** No cloud, no telemetry, no network calls except the GET being observed and its `robots.txt`. No cookies persisted between polls. No JavaScript executed.
- **No real email, username, hostname, or hardcoded machine path (`/Users/<name>/…`) in any committed file's contents.** Paths resolve from the repo root or `~` at runtime. The User-Agent contains no email. (Commit *signatures* are deliberate and exempt — commits are signed as normal by the user's GitHub identity.)
- **User-Agent:** `econsult-window-monitor/0.1 (personal read-only availability check)` — no email.
- **All observed data is gitignored** (`data/`, `*.db`, `snapshots/`). Only source, tests, small fixtures, docs, and the launchd plist template are tracked.
- **Detection keys off text content, not DOM structure.** Unrecognised state → `unknown`, logged and snapshotted, never guessed.
- **Snapshot every *distinct* page once, deduped by a volatile-masked content hash.** Save the raw body on any state (not just `unknown`), so a state we cannot yet see — notably the open window — is captured the first time it appears. The dedup hash is taken over the normalised visible text with volatile tokens masked (clock times, ISO datetimes, long hex fingerprints), so verified noise — the load-balancer `<!-- ec2 server name: tomcatNN -->` comment, per-deploy asset hashes, or any future visible ticking clock — never creates a duplicate. First writer wins.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `monitor/__init__.py` (empty package marker)
- Create: `tests/__init__.py` (empty)
- Create: `README.md`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `monitor` package and a working `uv run pytest` harness. `monitor/` is a top-level package so `uv run python -m monitor.<mod>` works from the repo root without an editable install.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "econsult-window-monitor"
version = "0.1.0"
description = "Read-only monitor of the eConsult clinical window (Phase 0)"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package markers**

Create `monitor/__init__.py` with a single line:

```python
"""eConsult window monitor (Phase 0). Read-only; never submits."""
```

Create `tests/__init__.py` as an empty file.

- [ ] **Step 3: Write the smoke test**

`tests/test_smoke.py`:

```python
def test_monitor_package_imports():
    import monitor  # noqa: F401
```

- [ ] **Step 4: Run it and verify it passes**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: 1 passed. (`uv` resolves the dev group and creates the environment on first run.)

- [ ] **Step 5: Create a sparse README**

Keep it minimal — it should not explain much. `README.md`:

```markdown
# eConsult window monitor (Phase 0)

Local, read-only. Polls one public page and logs when the eConsult clinical
window opens each day. Never submits anything.

```bash
uv run python -m monitor.poll      # one poll
uv run python -m monitor.daemon    # continuous
uv run python -m monitor.analyse   # findings
uv run pytest                      # tests
```

Data in `data/` (gitignored). Design and plan in `docs/`.
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml monitor/__init__.py tests/__init__.py tests/test_smoke.py README.md
git commit -m "Scaffold Phase 0 monitor package and test harness"
```

---

### Task 2: Configuration module

**Files:**
- Create: `monitor/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: module-level constants used everywhere. `REPO_ROOT: Path`, `DATA_DIR: Path`, `DB_PATH: Path`, `SNAPSHOT_DIR: Path`, `BASE_URL: str`, `CLINICAL_PATH: str` (`"/"`), `ADMIN_PATH: str` (`"/admin"`), `USER_AGENT: str`, `REQUEST_TIMEOUT: int`, `DENSE_START: str` (`"05:30"`), `DENSE_END: str` (`"08:30"`), `DENSE_INTERVAL: int` (20), `BACKGROUND_INTERVAL: int` (1200), `ADMIN_INTERVAL: int` (1200).

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path
from monitor import config


def test_paths_resolve_under_repo_root_and_no_hardcoded_user():
    assert isinstance(config.REPO_ROOT, Path)
    assert config.DB_PATH == config.DATA_DIR / "observations.db"
    assert config.SNAPSHOT_DIR == config.DATA_DIR / "snapshots"
    # The repo root is derived, not hardcoded to any user's home.
    assert "/Users/" not in str(config.BASE_URL)


def test_user_agent_has_no_email():
    assert "@" not in config.USER_AGENT
    assert config.USER_AGENT.startswith("econsult-window-monitor/")


def test_cadence_values():
    assert config.DENSE_START == "05:30"
    assert config.DENSE_END == "08:30"
    assert config.DENSE_INTERVAL == 20
    assert config.BACKGROUND_INTERVAL == 1200
    assert config.ADMIN_INTERVAL == 1200
    assert config.CLINICAL_PATH == "/"
    assert config.ADMIN_PATH == "/admin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.config'`.

- [ ] **Step 3: Write the implementation**

`monitor/config.py`:

```python
"""Single tunable configuration block for the monitor.

All paths derive from the repo root at runtime; nothing is hardcoded to a
specific user's home directory.
"""
from __future__ import annotations

from pathlib import Path

# Repo root = parent of this package directory. Derived, never hardcoded.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
DB_PATH: Path = DATA_DIR / "observations.db"
SNAPSHOT_DIR: Path = DATA_DIR / "snapshots"

# The public page being observed.
BASE_URL: str = "https://example-surgery.example.com"
CLINICAL_PATH: str = "/"
ADMIN_PATH: str = "/admin"

# Polite fetching. No email or personal identifier in the User-Agent.
USER_AGENT: str = "econsult-window-monitor/0.1 (personal read-only availability check)"
REQUEST_TIMEOUT: int = 15  # seconds

# Cadence, expressed in local time. One place to tune the whole schedule.
DENSE_START: str = "05:30"       # morning band start (local)
DENSE_END: str = "08:30"         # morning band end (local)
DENSE_INTERVAL: int = 20         # seconds between polls inside the band
BACKGROUND_INTERVAL: int = 1200  # seconds between polls otherwise (20 min)
ADMIN_INTERVAL: int = 1200       # poll the /admin route at most this often
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add monitor/config.py tests/test_config.py
git commit -m "Add configuration module with URLs, cadence, and repo-relative paths"
```

---

### Task 3: Classification (the core, pure)

**Files:**
- Create: `monitor/classify.py`
- Create: `tests/fixtures/closed.html`
- Create: `tests/fixtures/open.html`
- Create: `tests/fixtures/admin_open.html`
- Create: `tests/fixtures/unknown.html`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: nothing (pure functions over strings).
- Produces:
  - `STATE_OPEN`, `STATE_CLOSED`, `STATE_UNKNOWN` string constants.
  - `Classification` frozen dataclass with fields `state: str`, `markers: tuple[str, ...]`, `routes: tuple[str, ...]`.
  - `normalise(raw_html: str) -> str` — tag-stripped, entity-decoded, lower-cased, whitespace-collapsed visible text. Used for detection.
  - `classify(raw_html: str) -> Classification`.
  - `stable_text(raw_html: str) -> str` — `normalise()` output with volatile tokens masked (clock times, ISO datetimes, long hex fingerprints), so per-request/deploy noise does not change page identity. Used only for snapshot dedup, never for detection.
  - `content_fingerprint(raw_html: str) -> str` — sha256 hex digest of `stable_text()`. This is the value stored as `content_sha256` and used as the snapshot filename.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/closed.html` (mirrors the real live closed-state markers observed 2026-07-22 — id, class, and both visible-text strings):

```html
<!doctype html>
<html lang="en"><head><title>Consult Online from Home - Example Surgery</title></head>
<body>
<section id="serviceClosedSubheadingFirstLine" class="service-closed-header">
All our GP appointments are booked today so we can&#39;t accept online requests at this time.
</section>
<section id="serviceClosedSubheadingSecondLine">
You can submit a request again from 7am tomorrow. If you need help, call the practice.
Outside of practice hours, call 111. In emergencies, call 999 or go to A&amp;E.
</section>
<div class="paeds-promotion-banner">Find out how to manage your problem at home. Consultation for child path.</div>
</body></html>
```

`tests/fixtures/open.html` (clinical routes live — the inferred open state):

```html
<!doctype html>
<html lang="en"><head><title>Consult Online from Home - Example Surgery</title></head>
<body>
<h2>Get help for a health problem</h2>
<a class="route-card" href="/adult">Adult health problems</a>
<a class="route-card" href="/child">Child health problems</a>
</body></html>
```

`tests/fixtures/admin_open.html` (the admin route, which stays open all day):

```html
<!doctype html>
<html lang="en"><head><title>Admin requests - Example Surgery</title></head>
<body>
<h2>Admin requests</h2>
<a class="route-card" href="/sicknote">Sick note</a>
<a class="route-card" href="/results">Test result query</a>
<a class="route-card" href="/meds">Medication query</a>
</body></html>
```

`tests/fixtures/unknown.html` (unrecognised — neither open nor closed markers):

```html
<!doctype html>
<html lang="en"><head><title>Maintenance</title></head>
<body><h1>The site is temporarily unavailable</h1><p>Please check back soon.</p></body></html>
```

- [ ] **Step 2: Write the failing test**

`tests/test_classify.py`:

```python
from pathlib import Path

from monitor import classify
from monitor.classify import (
    STATE_OPEN,
    STATE_CLOSED,
    STATE_UNKNOWN,
    normalise,
    classify as classify_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_normalise_strips_tags_decodes_entities_and_lowercases():
    text = normalise("<p>All our <b>GP</b> appointments are booked&nbsp;today</p>")
    assert "<" not in text and ">" not in text
    assert "booked today" in text  # entity collapsed, lower-cased


def test_closed_page_detected_via_text_and_structural_markers():
    result = classify_html(_load("closed.html"))
    assert result.state == STATE_CLOSED
    # Both visible-text markers and at least one structural marker fired.
    assert "booked today" in result.markers
    assert "from 7am tomorrow" in result.markers
    assert "serviceclosed" in result.markers


def test_closed_page_not_misread_as_open_despite_child_and_problem_words():
    # The closed page contains "child" and "problem" in the paeds banner;
    # those must NOT trigger an open verdict.
    result = classify_html(_load("closed.html"))
    assert result.state == STATE_CLOSED


def test_open_clinical_page_detected():
    result = classify_html(_load("open.html"))
    assert result.state == STATE_OPEN
    assert "health problem" in result.markers
    assert "adult" in result.routes
    assert "child" in result.routes


def test_admin_open_page_detected_via_admin_signals():
    result = classify_html(_load("admin_open.html"))
    assert result.state == STATE_OPEN
    assert "sick note" in result.markers or "test result" in result.markers


def test_unknown_page_is_unknown_not_guessed():
    result = classify_html(_load("unknown.html"))
    assert result.state == STATE_UNKNOWN
    assert result.markers == ()


def test_wording_variant_still_closed():
    # A layout/copy change that keeps "fully booked ... try again from 7am".
    html = '<div>Today is fully booked. Please try again from 7am tomorrow.</div>'
    result = classify_html(html)
    assert result.state == STATE_CLOSED
    assert "try again from 7am" in result.markers


def test_content_fingerprint_ignores_volatile_comment_and_asset_hashes():
    from monitor.classify import content_fingerprint
    a = '<html><!-- ec2 server name: tomcat03 --><body>' \
        '<script src="/assets/app-0993e8e58ef26218aff90cb9f9c7510e.js"></script>' \
        '<div>All our GP appointments are booked today.</div></body></html>'
    b = a.replace("tomcat03", "tomcat04").replace(
        "0993e8e58ef26218aff90cb9f9c7510e", "b4f843a325943b19b10d30881d4e2cd6")
    # Only the load-balancer comment and an asset-hash differ -> same fingerprint.
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_masks_visible_clock_time():
    from monitor.classify import content_fingerprint
    a = "<div>Queue updated at 08:14</div>"
    b = "<div>Queue updated at 08:57</div>"
    # A visible clock that ticks must not create a new page identity.
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_distinguishes_real_content_change():
    from monitor.classify import content_fingerprint
    closed = "<div>All our GP appointments are booked today.</div>"
    opened = "<div>Get help for a health problem.</div>"
    assert content_fingerprint(closed) != content_fingerprint(opened)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_classify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.classify'`.

- [ ] **Step 4: Write the implementation**

`monitor/classify.py`:

```python
"""Pure classification of the eConsult page state from its HTML.

Keys off text CONTENT, not DOM structure. Visible-text markers are matched
against the tag-stripped visible text; structural markers (element ids / CSS
classes that live inside tags) are matched against the raw lower-cased HTML.
Anything unrecognised is UNKNOWN and never guessed.
"""
from __future__ import annotations

import hashlib
import html as html_module
import re
from dataclasses import dataclass

STATE_OPEN = "open"
STATE_CLOSED = "closed"
STATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Classification:
    state: str
    markers: tuple[str, ...]
    routes: tuple[str, ...]


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalise(raw_html: str) -> str:
    """Tag-stripped, entity-decoded, lower-cased, whitespace-collapsed text."""
    text = _TAG_RE.sub(" ", raw_html)
    text = html_module.unescape(text)
    text = text.lower()
    return _WS_RE.sub(" ", text).strip()


# Closed markers found in the visible text.
_CLOSED_TEXT_MARKERS: tuple[str, ...] = (
    "booked today",
    "from 7am tomorrow",
    "try again from 7am",
)
# Closed markers that live inside tags (id / class) -> matched on raw HTML.
_CLOSED_STRUCT_MARKERS: tuple[str, ...] = (
    "serviceclosed",
    "service-closed-header",
)
# Any of these in the visible text signals a live route (clinical or admin).
# Chosen so they are ABSENT on the observed closed clinical page.
_OPEN_SIGNALS: tuple[str, ...] = (
    "health problem",
    "sick note",
    "test result",
    "medication query",
    "medication",
)
# Best-effort route metadata (recorded regardless of state).
_ROUTE_MARKERS: dict[str, str] = {
    "adult": "adult health problem",
    "child": "child health problem",
    "admin_sicknote": "sick note",
    "admin_testresult": "test result",
    "admin_medication": "medication",
}


def classify(raw_html: str) -> Classification:
    raw_lower = raw_html.lower()
    text = normalise(raw_html)

    closed_hits = tuple(m for m in _CLOSED_TEXT_MARKERS if m in text)
    closed_hits += tuple(m for m in _CLOSED_STRUCT_MARKERS if m in raw_lower)
    routes = tuple(name for name, phrase in _ROUTE_MARKERS.items() if phrase in text)

    if closed_hits:
        return Classification(STATE_CLOSED, closed_hits, routes)

    open_hits = tuple(s for s in _OPEN_SIGNALS if s in text)
    if open_hits:
        return Classification(STATE_OPEN, open_hits, routes)

    return Classification(STATE_UNKNOWN, (), routes)


# --- Content fingerprint for snapshot dedup (NOT used for detection) ---------
# Mask volatile tokens BEFORE hashing so per-request/deploy noise does not create
# a new page identity. Order matters: ISO datetimes before bare clock times.
_VOLATILE_SUBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b[0-9a-f]{16,}\b"), "<hex>"),                        # asset/build hashes, ids (text is lower-cased)
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?\b"), "<ts>"),  # ISO datetime
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<time>"),            # clock HH:MM[:SS]
)


def stable_text(raw_html: str) -> str:
    """normalise() with volatile tokens masked, for stable page identity."""
    text = normalise(raw_html)
    for pattern, replacement in _VOLATILE_SUBS:
        text = pattern.sub(replacement, text)
    return text


def content_fingerprint(raw_html: str) -> str:
    """sha256 of the stable text — the snapshot filename and content_sha256."""
    return hashlib.sha256(stable_text(raw_html).encode("utf-8", errors="replace")).hexdigest()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_classify.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add monitor/classify.py tests/test_classify.py tests/fixtures/
git commit -m "Add page-state classifier and volatile-masked content fingerprint"
```

---

### Task 4: SQLite store

**Files:**
- Create: `monitor/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `connect(db_path: Path) -> sqlite3.Connection` (creates parent dir, sets `Row` factory).
  - `init_db(conn) -> None` (idempotent schema creation).
  - `record(conn, obs: dict) -> int` (inserts one row, returns `lastrowid`). Expected keys of `obs`: `ts_utc`, `ts_local`, `utc_offset`, `state`, `route`, `routes_present`, `http_status`, `latency_ms`, `matched_markers`, `content_sha256`, `notes`.

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
from monitor import store


def _sample_obs() -> dict:
    return {
        "ts_utc": "2026-07-22T19:09:54+00:00",
        "ts_local": "2026-07-22T20:09:54+01:00",
        "utc_offset": "+01:00",
        "state": "closed",
        "route": "/",
        "routes_present": "child",
        "http_status": 200,
        "latency_ms": 431,
        "matched_markers": "booked today,from 7am tomorrow,serviceclosed",
        "content_sha256": "abc123",
        "notes": "",
    }


def test_init_db_is_idempotent(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    store.init_db(conn)  # second call must not raise
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='observations'"
    ).fetchall()
    assert len(rows) == 1


def test_record_round_trips_all_columns(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    rowid = store.record(conn, _sample_obs())
    assert rowid == 1
    row = conn.execute("SELECT * FROM observations WHERE id = ?", (rowid,)).fetchone()
    assert row["ts_utc"] == "2026-07-22T19:09:54+00:00"
    assert row["ts_local"] == "2026-07-22T20:09:54+01:00"
    assert row["utc_offset"] == "+01:00"
    assert row["state"] == "closed"
    assert row["route"] == "/"
    assert row["http_status"] == 200
    assert row["latency_ms"] == 431
    assert row["matched_markers"].startswith("booked today")


def test_connect_creates_missing_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "obs.db"
    conn = store.connect(db_path)
    store.init_db(conn)
    assert db_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.store'`.

- [ ] **Step 3: Write the implementation**

`monitor/store.py`:

```python
"""SQLite persistence for observations. One row per poll."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT    NOT NULL,
    ts_local        TEXT    NOT NULL,
    utc_offset      TEXT    NOT NULL,
    state           TEXT    NOT NULL,
    route           TEXT    NOT NULL,
    routes_present  TEXT    NOT NULL,
    http_status     INTEGER,
    latency_ms      INTEGER,
    matched_markers TEXT    NOT NULL,
    content_sha256  TEXT,    -- sha256 of the NORMALISED visible text (stable page identity; also the snapshot filename)
    notes           TEXT
);
"""

_COLUMNS = (
    "ts_utc", "ts_local", "utc_offset", "state", "route", "routes_present",
    "http_status", "latency_ms", "matched_markers", "content_sha256", "notes",
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def record(conn: sqlite3.Connection, obs: dict[str, Any]) -> int:
    placeholders = ",".join("?" for _ in _COLUMNS)
    values = [obs.get(col) for col in _COLUMNS]
    cur = conn.execute(
        f"INSERT INTO observations ({','.join(_COLUMNS)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return int(cur.lastrowid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add monitor/store.py tests/test_store.py
git commit -m "Add SQLite store with one-row-per-poll schema and round-trip record"
```

---

### Task 5: Polite fetcher

**Files:**
- Create: `monitor/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing (takes URL + UA as arguments).
- Produces:
  - `FetchResult` frozen dataclass: `status: int | None`, `body: str`, `latency_ms: int`, `final_url: str`, `error: str | None`.
  - `fetch(url: str, user_agent: str, timeout: int = 15) -> FetchResult` — single GET, follows redirects, no cookies, never raises.
  - `robots_allows(base_url: str, path: str, user_agent: str, timeout: int = 15) -> bool` — defaults to allowed when no readable robots.txt.

- [ ] **Step 1: Write the failing test**

`tests/test_fetch.py` (uses a stdlib localhost server — deterministic, no external network):

```python
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from monitor import fetch


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"<html><body>hello</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")

    def log_message(self, *args):  # silence test server logging
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


def test_fetch_returns_body_and_status(server):
    result = fetch.fetch(f"{server}/ok", "test-agent/0.1")
    assert result.status == 200
    assert "hello" in result.body
    assert result.error is None
    assert result.latency_ms >= 0


def test_fetch_follows_redirect(server):
    result = fetch.fetch(f"{server}/redir", "test-agent/0.1")
    assert result.status == 200
    assert "hello" in result.body
    assert result.final_url.endswith("/ok")


def test_fetch_never_raises_on_connection_error():
    # Nothing listening on this port; must return an error result, not raise.
    result = fetch.fetch("http://127.0.0.1:1/never", "test-agent/0.1", timeout=2)
    assert result.status is None
    assert result.error is not None
    assert result.body == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.fetch'`.

- [ ] **Step 3: Write the implementation**

`monitor/fetch.py`:

```python
"""Polite, read-only HTTP GET with robots.txt awareness.

Single request, follows redirects, no cookies persisted, never executes
JavaScript, and never raises — failures come back as a FetchResult with an
error string so the poll loop can log and carry on.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    status: int | None
    body: str
    latency_ms: int
    final_url: str
    error: str | None


def _opener(user_agent: str) -> urllib.request.OpenerDirector:
    # Default opener follows redirects and does NOT persist cookies.
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", user_agent)]
    return opener


def robots_allows(base_url: str, path: str, user_agent: str, timeout: int = 15) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(base_url.rstrip("/") + "/robots.txt")
    try:
        parser.read()
    except Exception:
        return True  # no readable robots.txt -> treat as allowed
    return parser.can_fetch(user_agent, base_url.rstrip("/") + path)


def fetch(url: str, user_agent: str, timeout: int = 15) -> FetchResult:
    opener = _opener(user_agent)
    start = time.monotonic()
    try:
        with opener.open(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            latency_ms = int((time.monotonic() - start) * 1000)
            return FetchResult(resp.status, body, latency_ms, resp.geturl(), None)
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return FetchResult(exc.code, body, latency_ms, url, f"HTTPError {exc.code}")
    except Exception as exc:  # connection refused, timeout, DNS, etc.
        latency_ms = int((time.monotonic() - start) * 1000)
        return FetchResult(None, "", latency_ms, url, str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add monitor/fetch.py tests/test_fetch.py
git commit -m "Add polite read-only fetcher with redirect handling and robots check"
```

---

### Task 6: Poll orchestration

**Files:**
- Create: `monitor/poll.py`
- Test: `tests/test_poll.py`

**Interfaces:**
- Consumes: `config`, `fetch.FetchResult` + `fetch.fetch`, `classify.classify`, `store.record`.
- Produces:
  - `build_timestamps(now_utc: datetime | None = None) -> tuple[str, str, str]` returning `(ts_utc_iso, ts_local_iso, utc_offset)` where offset is `"+HH:MM"`.
  - `poll_once(conn, route_path: str, *, fetcher=fetch.fetch, now_utc: datetime | None = None, snapshot_dir: Path = config.SNAPSHOT_DIR) -> dict` — fetches, classifies, writes one row, and snapshots the raw body for every *distinct* normalised page once (any state), returning the observation dict. `content_sha256` is the sha256 of the normalised visible text and doubles as the snapshot filename.
  - `main() -> None` — a single clinical-route poll against the live site (used by `python -m monitor.poll`).

- [ ] **Step 1: Write the failing test**

`tests/test_poll.py`:

```python
from datetime import datetime, timezone, timedelta

from monitor import poll, store, config
from monitor.fetch import FetchResult


def _fake_fetcher(body: str, status: int = 200):
    def _f(url, user_agent, timeout=15):
        return FetchResult(status, body, 12, url, None)
    return _f


def test_build_timestamps_formats_offset_with_colon():
    fixed = datetime(2026, 7, 22, 19, 9, 54, tzinfo=timezone.utc)
    ts_utc, ts_local, offset = poll.build_timestamps(fixed)
    assert ts_utc == "2026-07-22T19:09:54+00:00"
    # Offset is +HH:MM and both local + utc are present (DST-disambiguation).
    assert len(offset) == 6 and offset[3] == ":"


def test_poll_once_writes_closed_row(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    body = '<div id="serviceClosed">All our GP appointments are booked today. Submit a request again from 7am tomorrow.</div>'
    obs = poll.poll_once(
        conn, "/",
        fetcher=_fake_fetcher(body),
        now_utc=datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        snapshot_dir=tmp_path / "snaps",
    )
    assert obs["state"] == "closed"
    assert obs["route"] == "/"
    assert obs["content_sha256"] is not None
    row = conn.execute("SELECT * FROM observations").fetchone()
    assert row["state"] == "closed"
    assert row["ts_utc"].startswith("2026-07-22T06:00")


def test_poll_once_snapshots_distinct_pages_and_dedupes(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    snaps = tmp_path / "snaps"
    now = datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc)

    body_a = (
        '<html><body><!-- ec2 server name: tomcat03 -->'
        '<div id="serviceClosed">booked today. submit again from 7am tomorrow.</div>'
        "</body></html>"
    )
    # Same visible content, only the volatile load-balancer comment differs.
    body_a2 = body_a.replace("tomcat03", "tomcat02")
    body_b = "<html><body><h2>get help for a health problem</h2></body></html>"

    o1 = poll.poll_once(conn, "/", fetcher=_fake_fetcher(body_a), now_utc=now, snapshot_dir=snaps)
    o2 = poll.poll_once(conn, "/", fetcher=_fake_fetcher(body_a2), now_utc=now, snapshot_dir=snaps)
    o3 = poll.poll_once(conn, "/", fetcher=_fake_fetcher(body_b), now_utc=now, snapshot_dir=snaps)

    # a and a2 differ only by the volatile comment -> identical normalised hash -> one snapshot.
    assert o1["content_sha256"] == o2["content_sha256"]
    assert o1["content_sha256"] != o3["content_sha256"]
    files = sorted(p.name for p in snaps.glob("*.html"))
    assert len(files) == 2  # {a, a2} collapse to one; b is the second
    # First writer wins: the kept raw body is the first one seen (tomcat03).
    kept = (snaps / f"{o1['content_sha256']}.html").read_text(encoding="utf-8")
    assert "tomcat03" in kept
    # Every poll is still logged, even the deduplicated one.
    assert conn.execute("SELECT COUNT(*) c FROM observations").fetchone()["c"] == 3


def test_poll_once_records_error_note_on_failed_fetch(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)

    def _broken(url, user_agent, timeout=15):
        return FetchResult(None, "", 5, url, "Connection refused")

    obs = poll.poll_once(
        conn, "/",
        fetcher=_broken,
        now_utc=datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        snapshot_dir=tmp_path / "snaps",
    )
    assert obs["state"] == "unknown"  # empty body -> unknown
    assert obs["notes"] == "Connection refused"
    assert obs["content_sha256"] is None  # no body, no hash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_poll.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.poll'`.

- [ ] **Step 3: Write the implementation**

`monitor/poll.py`:

```python
"""One poll = fetch -> classify -> store. Snapshots every distinct page once."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import classify as classify_mod
from . import config
from . import fetch as fetch_mod
from . import store


def build_timestamps(now_utc: datetime | None = None) -> tuple[str, str, str]:
    """Return (utc_iso, local_iso, '+HH:MM').

    Storing UTC, local, and the offset together is what later distinguishes a
    UTC-scheduled reset from a local one at the DST boundary.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone()  # system local timezone
    raw_offset = now_local.strftime("%z") or "+0000"  # e.g. '+0100'
    utc_offset = f"{raw_offset[:3]}:{raw_offset[3:]}"  # -> '+01:00'
    return now_utc.isoformat(), now_local.isoformat(), utc_offset


def poll_once(
    conn,
    route_path: str,
    *,
    fetcher: Callable = fetch_mod.fetch,
    now_utc: datetime | None = None,
    snapshot_dir: Path = config.SNAPSHOT_DIR,
) -> dict:
    url = config.BASE_URL.rstrip("/") + route_path
    result = fetcher(url, config.USER_AGENT, config.REQUEST_TIMEOUT)
    verdict = classify_mod.classify(result.body)

    # Content identity masks volatile tokens (server-name comment, asset hashes,
    # clock times) so per-request/deploy noise does not change it.
    content_key = classify_mod.content_fingerprint(result.body) if result.body else None

    ts_utc, ts_local, utc_offset = build_timestamps(now_utc)
    obs = {
        "ts_utc": ts_utc,
        "ts_local": ts_local,
        "utc_offset": utc_offset,
        "state": verdict.state,
        "route": route_path,
        "routes_present": ",".join(verdict.routes),
        "http_status": result.status,
        "latency_ms": result.latency_ms,
        "matched_markers": ",".join(verdict.markers),
        "content_sha256": content_key,
        "notes": result.error or "",
    }

    # Keep a copy of every DISTINCT page we ever see (any state), so a state we
    # cannot yet observe is captured the first time it appears. First writer wins.
    if result.body and content_key:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_dir / f"{content_key}.html"
        if not snapshot.exists():
            snapshot.write_text(result.body, encoding="utf-8")

    store.record(conn, obs)
    return obs


def main() -> None:
    conn = store.connect(config.DB_PATH)
    store.init_db(conn)
    obs = poll_once(conn, config.CLINICAL_PATH)
    print(f"{obs['ts_local']}  {obs['state']}  markers={obs['matched_markers']!r}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_poll.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add monitor/poll.py tests/test_poll.py
git commit -m "Add poll orchestration: fetch, classify, timestamp, store, snapshot unknowns"
```

---

### Task 7: Self-pacing daemon

**Files:**
- Create: `monitor/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `config`, `store.connect`/`store.init_db`, `poll.poll_once`.
- Produces:
  - `interval_for(now_local: datetime) -> int` — `DENSE_INTERVAL` inside the morning band, else `BACKGROUND_INTERVAL`.
  - `run() -> None` — the continuous loop (polls `/` every tick; polls `/admin` at most every `ADMIN_INTERVAL`). Not unit-tested (integration).

- [ ] **Step 1: Write the failing test**

`tests/test_daemon.py`:

```python
from datetime import datetime

from monitor import daemon, config


def _local(hh, mm):
    # A naive local datetime is sufficient; interval_for only reads .time().
    return datetime(2026, 7, 22, hh, mm, 0)


def test_interval_dense_inside_morning_band():
    assert daemon.interval_for(_local(5, 30)) == config.DENSE_INTERVAL
    assert daemon.interval_for(_local(7, 0)) == config.DENSE_INTERVAL
    assert daemon.interval_for(_local(8, 30)) == config.DENSE_INTERVAL


def test_interval_background_outside_band():
    assert daemon.interval_for(_local(5, 29)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(8, 31)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(14, 0)) == config.BACKGROUND_INTERVAL
    assert daemon.interval_for(_local(0, 0)) == config.BACKGROUND_INTERVAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.daemon'`.

- [ ] **Step 3: Write the implementation**

`monitor/daemon.py`:

```python
"""Self-pacing monitor loop. launchd keeps this process alive; the process
itself decides how often to poll based on the local wall clock.
"""
from __future__ import annotations

import time
from datetime import datetime, time as dtime

from . import config
from . import poll
from . import store


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


def run() -> None:
    conn = store.connect(config.DB_PATH)
    store.init_db(conn)
    last_admin_poll = 0.0
    while True:
        poll.poll_once(conn, config.CLINICAL_PATH)

        now_mono = time.monotonic()
        if now_mono - last_admin_poll >= config.ADMIN_INTERVAL:
            poll.poll_once(conn, config.ADMIN_PATH)
            last_admin_poll = now_mono

        time.sleep(interval_for(datetime.now().astimezone()))


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: 2 passed.

- [ ] **Step 5: Manual smoke test (optional, ~1 min)**

Run: `uv run python -m monitor.poll`
Expected: prints one line like `2026-07-22T20:15:00+01:00  closed  markers='booked today,from 7am tomorrow,serviceclosed'` and creates `data/observations.db`. Then:
Run: `uv run python -c "import sqlite3; print(sqlite3.connect('data/observations.db').execute('select count(*) from observations').fetchone())"`
Expected: `(1,)` (or more).

- [ ] **Step 6: Commit**

```bash
git add monitor/daemon.py tests/test_daemon.py
git commit -m "Add self-pacing daemon loop with morning-band cadence and admin polling"
```

---

### Task 8: Analysis readout

**Files:**
- Create: `monitor/analyse.py`
- Test: `tests/test_analyse.py`

**Interfaces:**
- Consumes: `config`, `store.connect`, a populated `observations` table.
- Produces:
  - `first_open_by_day(conn) -> list[tuple[str, str]]` — `(local_date, earliest_open_ts_local)` for the clinical route.
  - `last_closed_before_first_open(conn, day: str) -> str | None` — the local timestamp of the last `closed` clinical poll before that day's first `open` (bounds the edge).
  - `open_duration_by_day(conn) -> list[tuple[str, str, str]]` — `(local_date, first_open_ts, first_closed_after_open_ts)`.
  - `weekday_open_times(conn) -> list[tuple[str, str]]` — `(weekday_name, earliest_open_ts_local)` rows for day-of-week comparison.
  - `admin_ever_closed(conn) -> bool`.
  - `main() -> None` — prints the four findings with an honest "N days of data" preamble.

- [ ] **Step 1: Write the failing test**

`tests/test_analyse.py`:

```python
from monitor import analyse, store


def _seed(conn, rows):
    for r in rows:
        base = {
            "ts_utc": r["ts_local"], "ts_local": r["ts_local"], "utc_offset": "+01:00",
            "state": r["state"], "route": r.get("route", "/"), "routes_present": "",
            "http_status": 200, "latency_ms": 100, "matched_markers": "", 
            "content_sha256": None, "notes": "",
        }
        store.record(conn, base)


def test_first_open_by_day(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    _seed(conn, [
        {"ts_local": "2026-07-22T06:58:40+01:00", "state": "closed"},
        {"ts_local": "2026-07-22T07:00:00+01:00", "state": "open"},
        {"ts_local": "2026-07-22T07:00:20+01:00", "state": "open"},
    ])
    result = analyse.first_open_by_day(conn)
    assert result == [("2026-07-22", "2026-07-22T07:00:00+01:00")]


def test_last_closed_before_first_open_bounds_the_edge(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    _seed(conn, [
        {"ts_local": "2026-07-22T06:58:40+01:00", "state": "closed"},
        {"ts_local": "2026-07-22T06:59:00+01:00", "state": "closed"},
        {"ts_local": "2026-07-22T07:00:00+01:00", "state": "open"},
    ])
    assert analyse.last_closed_before_first_open(conn, "2026-07-22") == "2026-07-22T06:59:00+01:00"


def test_admin_ever_closed(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    _seed(conn, [
        {"ts_local": "2026-07-22T09:00:00+01:00", "state": "open", "route": "/admin"},
    ])
    assert analyse.admin_ever_closed(conn) is False
    _seed(conn, [
        {"ts_local": "2026-07-23T09:00:00+01:00", "state": "closed", "route": "/admin"},
    ])
    assert analyse.admin_ever_closed(conn) is True


def test_open_duration_by_day(tmp_path):
    conn = store.connect(tmp_path / "obs.db")
    store.init_db(conn)
    _seed(conn, [
        {"ts_local": "2026-07-22T07:00:00+01:00", "state": "open"},
        {"ts_local": "2026-07-22T07:01:40+01:00", "state": "open"},
        {"ts_local": "2026-07-22T07:02:00+01:00", "state": "closed"},
    ])
    result = analyse.open_duration_by_day(conn)
    assert result == [("2026-07-22", "2026-07-22T07:00:00+01:00", "2026-07-22T07:02:00+01:00")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analyse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monitor.analyse'`.

- [ ] **Step 3: Write the implementation**

`monitor/analyse.py`:

```python
"""Read the observation log and report the four Phase 0 findings.

A working skeleton: the queries are correct now and become meaningful as data
accrues. It draws no conclusions from thin data — it states how many days it has.
"""
from __future__ import annotations

from . import config
from . import store

_CLINICAL = "/"
_ADMIN = "/admin"


def first_open_by_day(conn) -> list[tuple[str, str]]:
    cur = conn.execute(
        """
        SELECT date(ts_local) AS day, MIN(ts_local) AS first_open
        FROM observations
        WHERE state = 'open' AND route = ?
        GROUP BY day
        ORDER BY day
        """,
        (_CLINICAL,),
    )
    return [(row["day"], row["first_open"]) for row in cur.fetchall()]


def last_closed_before_first_open(conn, day: str) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(ts_local) AS last_closed
        FROM observations
        WHERE state = 'closed' AND route = ? AND date(ts_local) = ?
          AND ts_local < (
            SELECT MIN(ts_local) FROM observations
            WHERE state = 'open' AND route = ? AND date(ts_local) = ?
          )
        """,
        (_CLINICAL, day, _CLINICAL, day),
    ).fetchone()
    return row["last_closed"] if row and row["last_closed"] else None


def open_duration_by_day(conn) -> list[tuple[str, str, str]]:
    days = [d for d, _ in first_open_by_day(conn)]
    out: list[tuple[str, str, str]] = []
    for day in days:
        first_open = conn.execute(
            "SELECT MIN(ts_local) AS t FROM observations "
            "WHERE state='open' AND route=? AND date(ts_local)=?",
            (_CLINICAL, day),
        ).fetchone()["t"]
        first_closed_after = conn.execute(
            "SELECT MIN(ts_local) AS t FROM observations "
            "WHERE state='closed' AND route=? AND date(ts_local)=? AND ts_local > ?",
            (_CLINICAL, day, first_open),
        ).fetchone()["t"]
        out.append((day, first_open, first_closed_after))
    return out


def weekday_open_times(conn) -> list[tuple[str, str]]:
    # SQLite %w: 0=Sunday..6=Saturday.
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return [(names[int(d.split("-")[0]) % 7] if False else names[_weekday_index(conn, day)], ts)
            for day, ts in first_open_by_day(conn)]


def _weekday_index(conn, day: str) -> int:
    row = conn.execute("SELECT strftime('%w', ?) AS w", (day,)).fetchone()
    return int(row["w"])


def admin_ever_closed(conn) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM observations WHERE route = ? AND state = 'closed'",
        (_ADMIN,),
    ).fetchone()
    return row["c"] > 0


def main() -> None:
    conn = store.connect(config.DB_PATH)
    store.init_db(conn)
    opens = first_open_by_day(conn)
    print(f"eConsult window monitor — findings ({len(opens)} day(s) with an observed open)\n")

    print("1. First observed 'open' per day (and the last 'closed' before it):")
    for day, first_open in opens:
        edge = last_closed_before_first_open(conn, day)
        print(f"   {day}: open at {first_open}  (last closed before: {edge or 'n/a'})")

    print("\n2. Open -> first 'closed/booked' per day:")
    for day, first_open, first_closed in open_duration_by_day(conn):
        print(f"   {day}: {first_open} -> {first_closed or 'still open / not observed'}")

    print("\n3. Day-of-week of first open:")
    for weekday, ts in weekday_open_times(conn):
        print(f"   {weekday}: {ts}")

    print(f"\n4. Admin route ever observed closed: {admin_ever_closed(conn)}")


if __name__ == "__main__":
    main()
```

Note: `weekday_open_times` uses `_weekday_index` (a SQLite `strftime('%w', day)` lookup) for correctness; the inline `if False` guard is removed in Step 3's final form below.

- [ ] **Step 3a: Simplify `weekday_open_times` (remove the dead branch)**

Replace the `weekday_open_times` function body with the clean version:

```python
def weekday_open_times(conn) -> list[tuple[str, str]]:
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return [(names[_weekday_index(conn, day)], ts) for day, ts in first_open_by_day(conn)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_analyse.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add monitor/analyse.py tests/test_analyse.py
git commit -m "Add analysis readout for the four Phase 0 findings"
```

---

### Task 9: launchd LaunchAgent (template + install/uninstall) and README finalisation

**Files:**
- Create: `launchd/com.econsult.window-monitor.plist` (template with placeholders — no machine path committed)
- Create: `launchd/install.sh`
- Create: `launchd/uninstall.sh`
- Modify: `README.md` (add install/uninstall + wipe/export sections)
- Test: `tests/test_launchd_template.py`

**Interfaces:**
- Consumes: the `monitor.daemon` entry point.
- Produces: a loadable LaunchAgent after the user runs `launchd/install.sh`. The committed plist contains `__REPO_DIR__` and `__UV_PATH__` placeholders; `install.sh` substitutes real values at install time so no machine path is ever committed.

- [ ] **Step 1: Write the failing test (guards against committing a machine path)**

`tests/test_launchd_template.py`:

```python
from pathlib import Path

PLIST = Path(__file__).parent.parent / "launchd" / "com.econsult.window-monitor.plist"


def test_plist_uses_placeholders_not_machine_paths():
    text = PLIST.read_text(encoding="utf-8")
    assert "__REPO_DIR__" in text
    assert "__UV_PATH__" in text
    # No real user home path may be committed.
    assert "/Users/" not in text


def test_plist_declares_keepalive_and_runatload():
    text = PLIST.read_text(encoding="utf-8")
    assert "com.econsult.window-monitor" in text
    assert "KeepAlive" in text
    assert "RunAtLoad" in text
    assert "monitor.daemon" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_launchd_template.py -v`
Expected: FAIL with `FileNotFoundError` (plist does not exist yet).

- [ ] **Step 3: Create the plist template**

`launchd/com.econsult.window-monitor.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.econsult.window-monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>__UV_PATH__</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>monitor.daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>__REPO_DIR__</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>__REPO_DIR__/data/daemon.out.log</string>
    <key>StandardErrorPath</key>
    <string>__REPO_DIR__/data/daemon.err.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_launchd_template.py -v`
Expected: 2 passed.

- [ ] **Step 5: Create the install script**

`launchd/install.sh`:

```bash
#!/usr/bin/env bash
# Installs the eConsult monitor LaunchAgent for the current user.
# Substitutes the real repo path and uv path into the committed template so no
# machine path is ever stored in git.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.econsult.window-monitor"
TEMPLATE="${REPO_DIR}/launchd/${LABEL}.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET="${TARGET_DIR}/${LABEL}.plist"

UV_PATH="$(command -v uv || true)"
if [[ -z "${UV_PATH}" ]]; then
    echo "error: 'uv' not found on PATH. Install uv first." >&2
    exit 1
fi

mkdir -p "${TARGET_DIR}" "${REPO_DIR}/data"

sed -e "s#__REPO_DIR__#${REPO_DIR}#g" \
    -e "s#__UV_PATH__#${UV_PATH}#g" \
    "${TEMPLATE}" > "${TARGET}"

# Reload cleanly if already present.
launchctl unload "${TARGET}" 2>/dev/null || true
launchctl load "${TARGET}"

echo "Loaded ${LABEL}."
echo "  plist:  ${TARGET}"
echo "  logs:   ${REPO_DIR}/data/daemon.{out,err}.log"
echo "  data:   ${REPO_DIR}/data/observations.db"
echo "Check status: launchctl list | grep econsult"
```

- [ ] **Step 6: Create the uninstall script**

`launchd/uninstall.sh`:

```bash
#!/usr/bin/env bash
# Unloads and removes the eConsult monitor LaunchAgent. Leaves data/ intact.
set -euo pipefail

LABEL="com.econsult.window-monitor"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "${TARGET}" ]]; then
    launchctl unload "${TARGET}" 2>/dev/null || true
    rm -f "${TARGET}"
    echo "Removed ${LABEL}. Observed data in data/ is untouched."
else
    echo "${LABEL} is not installed."
fi
```

- [ ] **Step 7: Make the scripts executable and add a sparse install note**

Run: `chmod +x launchd/install.sh launchd/uninstall.sh`

Append to `README.md` (keep it minimal):

```markdown
## Background monitor (macOS)

```bash
launchd/install.sh     # load the LaunchAgent (starts polling)
launchd/uninstall.sh   # remove it (keeps data)
```

Export: copy `data/observations.db`. Wipe: `rm -rf data/`.
```

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (smoke, config, classify, store, fetch, poll, daemon, analyse, launchd_template).

- [ ] **Step 9: Pre-commit PII sweep**

Run:
```bash
git grep -nE "/Users/|sorrel340|$(hostname -s)" -- . ':!docs/**'
```
Expected: no matches (the only permissible `/Users/<name>/…` reference is illustrative text inside `docs/`). If anything else appears, fix it before committing.

- [ ] **Step 10: Commit**

```bash
git add launchd/ tests/test_launchd_template.py README.md
git commit -m "Add launchd LaunchAgent template, install/uninstall scripts, and docs"
```

---

## Self-Review

**Spec coverage:**
- Observe/map window, read-only, never submit → Tasks 5–7 (fetch/poll/daemon), enforced in Global Constraints. ✓
- Text-content detection with open/closed/unknown + snapshot unknowns → Task 3 (classify), Task 6 (snapshot). ✓
- 07:00 treated as unverified; dense even morning-band poll + light background → Task 7 (`interval_for`), Task 2 (cadence). ✓
- Log every poll incl. closed/unknown; UTC + local + offset per row → Task 4 (schema), Task 6 (`build_timestamps`). ✓
- Admin route polled separately; "does admin ever close?" → Task 7 (admin polling), Task 8 (`admin_ever_closed`). ✓
- SQLite local store; export/wipe → Task 4, Task 9 (README). ✓
- Good-citizen: honest non-email UA, robots.txt, no cookies, no JS, sequential → Task 5, Global Constraints. ✓
- Four findings analysis skeleton → Task 8. ✓
- launchd LaunchAgent, no committed machine path → Task 9 (template + install substitution, guarded by test). ✓
- No PII/machine identifiers in committed content → Task 2 (UA/paths tests), Task 9 (plist test + PII sweep). ✓
- macOS, uv, stdlib-only, British English → Global Constraints, `pyproject.toml`. ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". The one intentional `if False` in Task 8 Step 3 is explicitly cleaned in Step 3a. ✓

**Type consistency:** `Classification(state, markers, routes)`, `FetchResult(status, body, latency_ms, final_url, error)`, `poll_once(conn, route_path, *, fetcher, now_utc, snapshot_dir) -> dict`, `build_timestamps(now_utc) -> tuple[str,str,str]`, `interval_for(now_local) -> int`, and the `store.record` column set are used consistently across Tasks 3–8. ✓

**Out of scope (deferred, correctly absent):** profiles, write-up composer, paste-ready output, alerting, submission. ✓
