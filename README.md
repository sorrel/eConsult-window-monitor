# 🩺 eConsult window monitor

**Works out when a GP surgery's online consultation window is actually open.**

Many surgeries in England accept eConsult requests only through a submission
window that opens each morning and closes once the day's capacity is gone. The
published hours are often approximate, and the window can shut within minutes.

This watches one public surgery page and records when the window opens and
closes each day, so the real pattern replaces the guesswork. 🕰️

---

## ✨ How it works

- 🔁 **Polls one public page** — frequently during the likely opening band,
  sparsely the rest of the day, and hourly at weekends and on bank holidays
  (never yet seen open on a Saturday or Sunday). One sequential `GET` per poll,
  honest User-Agent,
  `robots.txt` respected, no JavaScript executed.
- 🚦 **Classifies each poll** as `open`, `closed`, or `unknown` from the page's
  visible text rather than its HTML structure, so a redesign yields `unknown`
  instead of a wrong answer.
- 📓 **Logs everything locally** to JSONL, rolling each finished day up into a
  one-line summary.
- 📈 **Reports the pattern** — typical open and close times, how long the window
  stays open, and how much the sample size supports that. Weekends and bank
  holidays are counted and named on their own lines rather than dragged through
  a weekday's average, so a shut Easter Monday never reads as an ordinary Monday
  the surgery happened not to open.
- 🖥️ **Answers live questions** through an optional read-only MCP server, so you
  can ask "is the window open?" in Claude Desktop.

Nothing is sent anywhere: the only host contacted is the page you point it at.

## 🗺️ Place neutral

No surgery is named in this repository. Supply the page locally, in order of
precedence:

1. the `ECONSULT_BASE_URL` environment variable,
2. `ECONSULT_BASE_URL` in a `.env` at the repo root, or
3. a one-line `target_url.local` file at the repo root.

All three are gitignored. Without any of them the tools refuse to run rather
than quietly polling a placeholder domain. Observed data stays in `data/`, also
gitignored.

The `.env` may be a [1Password local env file][1p] — a FIFO rather than a
regular file, which yields its contents only when 1Password is unlocked and the
read authorised. It is read non-blocking under a short deadline, so a locked
1Password falls through to `target_url.local` instead of hanging an unattended
run at boot.

[1p]: https://www.1password.dev/environments/local-env-file

## 🚀 Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
echo "https://your-surgery.example.com" > target_url.local

uv run python -m monitor.poll      # a single poll
uv run python -m monitor.daemon    # continuous monitoring
uv run econsult view               # the weekly pattern, by day of the week
uv run econsult view -x            # every logged day
uv run pytest                      # tests
```

## 🍎 Background monitoring (macOS)

```bash
launchd/install.sh     # load the LaunchAgent and start polling
launchd/uninstall.sh   # remove it (data stays put)
```

The daemon abandons a wedged poll under a hard deadline, and counts a poll that
comes back with no reply as a failure too. Whilst polls are failing it retries
sooner than its background cadence, so the outage is bounded tightly at both
ends. After a run of failures it asks a fresh subprocess to fetch the page: if
the child succeeds, this process is the broken one and it exits for `launchd` to
start a clean one; if the child fails too, the network is simply out and it
waits rather than relaunching for nothing.

## 🤖 Live view in Claude Desktop (MCP)

An optional read-only MCP server (standard library only) exposes
`econsult_status`, `econsult_recent`, and `econsult_findings`.

```json
"mcpServers": {
  "econsult-window-monitor": {
    "command": "<repo>/.venv/bin/python",
    "args": ["-m", "monitor.mcp_server"],
    "env": { "PYTHONPATH": "<repo>/src" }
  }
}
```

## 📦 Your data

Plain JSONL in `data/` — `cp data/observations.jsonl ~/somewhere` to export,
`rm -rf data/` to wipe.

## 🏗️ Layout

```
src/monitor/    the package: fetch, classify, store, analyse, daemon, CLI, MCP
flow_capture/   dormant, opt-in browser walker (not part of the runtime)
launchd/        macOS LaunchAgent template and install scripts
tests/          the test suite
docs/           design notes and implementation plan
```

The runtime is standard-library-only; [Click](https://click.palletsprojects.com/)
is the single runtime dependency, used for the presentation CLI.

## 📄 Licence

[MIT](LICENSE) — do whatever you like with it.
