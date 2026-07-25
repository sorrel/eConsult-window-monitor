# 🩺 eConsult window monitor

**Finding out when online booking is actually open — by watching, not guessing.**

Many GP surgeries in England take online consultation requests (eConsult and
similar) through a submission window that opens for a short spell each morning
and closes the moment the day's capacity is used up. The published hours are
often approximate, and the window can shut within minutes. If you don't know
when it opens, you miss it.

This tool watches one public surgery page and records, day by day, **when the
window opened and when it closed** — so you can see the real pattern instead of
setting an alarm for a guess. 🕰️

---

## ✨ What it does

- 🔁 **Polls one public page** on a schedule — often during the likely opening
  band, sparsely the rest of the day.
- 🚦 **Classifies each observation** as `open`, `closed`, or `unknown`, from the
  page's *visible text* rather than its HTML structure (so a redesign degrades
  to `unknown` rather than lying).
- 📓 **Logs every poll** to a local JSONL file, and rolls each finished day up
  into a one-line summary.
- 📈 **Reports the findings** — typical open time, typical close time, how long
  the window stayed open, and how confident that is given the sample size.
- 🖥️ **Answers questions live** via an optional read-only MCP server, so you can
  simply ask "is the window open right now?" in Claude Desktop.

## 🚫 What it deliberately does *not* do

This is an observer, and it stays one.

- ❌ **Never submits, POSTs, or fills in the form.** Read-only `GET` requests, full
  stop. It cannot book anything on your behalf.
- ❌ **No scraping of personal or clinical content**, no accounts, no logins.
- ❌ **No slot-sniping, no availability gaming, no automation of the queue.**
- 🐢 **One sequential request per poll** — no parallelism, no hammering. Honest
  non-email User-Agent, `robots.txt` respected, no JavaScript executed.
- 🔒 **Local-first.** No cloud, no telemetry, no third-party services. The only
  host it ever contacts is the page you point it at.

The intent is simply this: *learn when the door opens, so you can be there when
it does.*

## 🗺️ Place neutral by design

No surgery is named anywhere in this repository. The page to observe is supplied
locally and never committed — via the `ECONSULT_BASE_URL` environment variable,
or a one-line `target_url.local` file at the repo root (gitignored). Without one,
the monitor points at a placeholder and observes nothing real.

Observed data lives in `data/`, which is gitignored and never leaves the machine.

---

## 🚀 Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
echo "https://your-surgery.example.com" > target_url.local

uv run python -m monitor.poll      # a single poll
uv run python -m monitor.daemon    # continuous monitoring
uv run python -m monitor.analyse   # what we've learnt so far
uv run econsult view               # human-friendly summary
uv run pytest                      # tests
```

## 🍎 Running it in the background (macOS)

```bash
launchd/install.sh     # load the LaunchAgent and start polling
launchd/uninstall.sh   # remove it (your data stays put)
```

The daemon looks after itself: a wedged poll is abandoned under a hard deadline,
and repeated failures make the process exit so `launchd` starts a clean one.

## 🤖 Live view in Claude Desktop (MCP)

An optional read-only MCP server (standard library only, no network access of its
own) exposes `econsult_status`, `econsult_recent`, and `econsult_findings`. Add it
to your Claude Desktop config, restart, and ask away.

```json
"mcpServers": {
  "econsult-window-monitor": {
    "command": "<repo>/.venv/bin/python",
    "args": ["-m", "monitor.mcp_server"],
    "env": { "PYTHONPATH": "<repo>/src" }
  }
}
```

## 📦 Your data, your call

Everything observed sits in `data/` as plain JSONL.

```bash
cp data/observations.jsonl ~/somewhere   # export
rm -rf data/                             # wipe
```

## 🏗️ Project layout

```
src/monitor/    the package: fetch, classify, store, analyse, daemon, CLI, MCP
flow_capture/   dormant, opt-in browser walker (not part of the runtime)
launchd/        macOS LaunchAgent template and install scripts
tests/          the test suite
docs/           design notes and implementation plan
```

The runtime is standard-library-only for auditability; [Click](https://click.palletsprojects.com/)
is the single runtime dependency, used purely for the presentation CLI.

## 📄 Licence

[MIT](LICENSE) — anyone is free to copy, change, and reuse this, commercially or
otherwise. Just keep the copyright notice with it. No warranty of any kind.
