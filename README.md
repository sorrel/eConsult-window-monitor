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
  sparsely the rest of the day. One sequential `GET` per poll, honest
  User-Agent, `robots.txt` respected, no JavaScript executed.
- 🚦 **Classifies each poll** as `open`, `closed`, or `unknown` from the page's
  visible text rather than its HTML structure, so a redesign yields `unknown`
  instead of a wrong answer.
- 📓 **Logs everything locally** to JSONL, rolling each finished day up into a
  one-line summary.
- 📈 **Reports the pattern** — typical open and close times, how long the window
  stays open, and how much the sample size supports that.
- 🖥️ **Answers live questions** through an optional read-only MCP server, so you
  can ask "is the window open?" in Claude Desktop.

Nothing is sent anywhere: the only host contacted is the page you point it at.

## 🗺️ Place neutral

No surgery is named in this repository. Supply the page locally through the
`ECONSULT_BASE_URL` environment variable or a one-line `target_url.local` file
at the repo root (gitignored). Without one, it uses a placeholder. Observed data
stays in `data/`, also gitignored.

## 🚀 Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
echo "https://your-surgery.example.com" > target_url.local

uv run python -m monitor.poll      # a single poll
uv run python -m monitor.daemon    # continuous monitoring
uv run econsult view               # what we've learnt so far
uv run pytest                      # tests
```

## 🍎 Background monitoring (macOS)

```bash
launchd/install.sh     # load the LaunchAgent and start polling
launchd/uninstall.sh   # remove it (data stays put)
```

The daemon abandons a wedged poll under a hard deadline, and exits after
repeated failures so `launchd` starts a clean process.

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
