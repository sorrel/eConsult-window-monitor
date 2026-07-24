# flow_capture — safe, read-only walker (never submits)

A one-off research tool that records **what an eConsult submission requires**
(the questions and fields), so Stage 1 can be designed around the real form. It
**never submits** and builds nothing toward submitting.

## Safety — why it cannot submit

Defence in depth:

1. **Writes are physically blocked.** The browser aborts every non-GET request
   to `example-surgery.example.com` at the network layer. The final
   submission is a write, so it cannot leave the machine — regardless of what is
   clicked or mis-navigated. Blocked attempts are logged to `blocked_writes.json`.
2. **Never clicks a terminal control.** Each candidate button/link is classified
   (`classify_control`); anything matching submit / send / finish / "review your
   answers" is treated as terminal and the walk stops there. Only clearly
   non-terminal "Continue / Next" controls are ever clicked. (Unit-tested in
   `tests/test_capture.py`.)
3. **Never consents, never uses real data.** Consent checkboxes are left
   unchecked (which naturally halts the walk at the consent/submit gate); any
   text field needed to advance gets an obvious placeholder, never real details.

## Being a good citizen (WAF-friendly)

- One pass, one representative problem, capped screens (`--max-screens`).
- Randomised human-paced dwell between actions (`--min-dwell`/`--max-dwell`,
  default 4–9s). No parallelism, no prefetch; the browser reuses its cache.
- Runs **headed** with a normal desktop Chrome user-agent (a headless-Chromium
  UA is a WAF tell), so it looks like one patient's browser session.
- Run it **once**, and **pause the poller first** so the same IP is not doing
  uptime GETs and a browser session at the same time.

## Running it (only during the open window, with an explicit go)

```bash
# 1. Install the browser (one-off; downloads Chromium from Microsoft's CDN)
uv sync --group capture
uv run playwright install chromium

# 2. Pause the poller so footprints don't stack
launchd/uninstall.sh

# 3. Walk once (headed), capturing to data/flow-capture/<stamp>/
uv run --group capture python flow_capture/capture.py --run-stamp 2026-07-24

# 4. Resume the poller
launchd/install.sh
```

Output per run: `NN.png`, `NN.html`, `NN.fields.json` (questions + field
inventory) per screen, plus `blocked_writes.json` and `network.jsonl`.

## Scope

Read-only. No submission logic, now or implied. If auto-submission is ever
wanted (a separate, deferred decision), it would be designed explicitly and
never share code with this walker.
