# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

Phase 0 of the eConsult project: a small, local, **read-only** monitor
that polls one public page (`https://example-surgery.example.com/`) and logs
when the clinical submission window opens each day. Design and plan live in
`docs/superpowers/`.

## Hard rules

- **Never submit, POST, or scrape the eConsult form.** This tool only ever does a
  read-only GET and records what it sees. No slots, no availability modelling.
- **One sequential request per poll.** No parallelism, no hammering. Honest
  non-email User-Agent. Respect robots.txt. Execute no JavaScript.
- **Local-first.** No cloud, no telemetry, no network calls beyond the observed
  page and its robots.txt. All data stays in `data/` (gitignored).
- **Detection keys off page *text*, not DOM structure.** Anything unrecognised is
  `unknown` and gets snapshotted, never guessed.
- **Snapshots are deduped by normalised-content hash:** save every *distinct*
  page once (any state), so the states we can't yet see get captured, but
  volatile noise (e.g. the load-balancer comment) never makes a duplicate.

## Conventions

Shares the design ethos of the sibling projects under `scripts/`:

- **Simple approach first.** Don't overcomplicate. Start straightforward; add
  complexity only when something demands it.
- **uv + modern Python (>=3.12).** The daemon/runtime is standard-library-only
  for auditability; **Click** is the one runtime dependency, used solely for the
  `econsult` presentation CLI (matching the sibling tools). `pytest` is the dev
  dependency; `playwright` is an optional group for the dormant flow walker.
  Run everything via `uv run …` (e.g. `uv run econsult view`).
- **British English** throughout (code, comments, output, docs).
- **Git: feature branches only — never commit directly to `main`.** The remote is
  `github.com/sorrel/eConsult-window-monitor` (public). Branch first
  (`feature/…`, `bugfix/…`, `docs/…`), commit there, then open a PR to merge.
  Keep in mind the repo is public: check anything new for identifying content
  before it goes up.
- **Nothing that identifies the user or machine in committed file contents** — no
  real email, username, hostname, or `/Users/<name>/…` path. Commits are signed
  as normal (that attribution is deliberate and fine).

## Commands

```bash
uv run pytest                    # tests
uv run python -m monitor.poll    # one poll
uv run python -m monitor.daemon  # continuous monitor
uv run python -m monitor.analyse # findings
launchd/install.sh               # load the background LaunchAgent
```

## Source layout & environment (updated July 2026)

- The shippable package lives at **`src/monitor/`** (src layout — see the
  workspace conventions in `../CLAUDE.md`). `flow_capture/` stays at the repo
  root (dormant, un-packaged). `pyproject.toml` reflects this:
  `packages = ["src/monitor"]`, `pythonpath = ["src", "."]`. Module and console
  entry points are unchanged (`monitor.cli:cli`, `python -m monitor.<mod>`).
- **The target URL is resolved in `src/monitor/config.py`**, in precedence
  order: `ECONSULT_BASE_URL` → `ECONSULT_BASE_URL` in a repo-root `.env` →
  `target_url.local`. The `.env` is normally a **1Password local-env file**,
  which is a *FIFO*: it yields its contents only when 1Password is unlocked and
  the read authorised. `config` is imported at module scope by the CLI and the
  tests, so it is read **non-blocking, under a deadline** (stdlib only — no
  `python-dotenv`), falling back to `target_url.local` rather than hanging a
  boot-time launchd start. Anything unresolved leaves the placeholder, and
  `config.require_configured()` then aborts loudly rather than letting the
  monitor poll a domain that does not exist.
- **Keep this repo out of iCloud.** iCloud hides `.venv` (breaking editable
  installs under Python 3.13) and uploads the local-first `data/`. See
  `../CLAUDE.md` for the full explanation. The repo now lives outside iCloud at
  `~/Developer/Program/scripts/econsult-window-monitor` (moved July 2026); the
  LaunchAgent, venv, and `data/` were all re-pointed there.
