# eConsult window monitor (Phase 0)

Local, read-only. Polls one public page and logs when the eConsult clinical
window opens each day. Never submits anything.

```bash
uv run python -m monitor.poll      # one poll
uv run python -m monitor.daemon    # continuous
uv run python -m monitor.analyse   # findings
uv run pytest                      # tests
```

## Background monitor (macOS)

```bash
launchd/install.sh     # load the LaunchAgent (starts polling)
launchd/uninstall.sh   # remove it (keeps data)
```

Export: copy `data/observations.jsonl`. Wipe: `rm -rf data/`.

## Live view in Claude Desktop (MCP)

Read-only MCP server (stdlib, no network) exposing `econsult_status`,
`econsult_recent`, `econsult_findings`. Add to Claude Desktop config, then
restart Claude Desktop and ask e.g. "is the eConsult window open?".

```json
"mcpServers": {
  "econsult-window-monitor": {
    "command": "<repo>/.venv/bin/python",
    "args": ["-m", "monitor.mcp_server"],
    "env": { "PYTHONPATH": "<repo>" }
  }
}
```

No third-party services: the monitor contacts only the surgery's public page.
The daemon self-heals — a wedged poll is abandoned under a hard deadline, and
repeated failures make it exit so launchd relaunches a clean process.

Data in `data/` (gitignored). Design and plan in `docs/`.
