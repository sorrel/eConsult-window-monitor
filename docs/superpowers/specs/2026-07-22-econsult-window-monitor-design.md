# Design: eConsult window monitor (Phase 0)

Date: 2026-07-22
Status: Approved (design), pending implementation plan

## Purpose

Build the smallest, most auditable useful thing first: a read-only monitor that
observes **when the the GP surgery eConsult clinical window opens
and how long it stays open**, and logs every observation unambiguously. After
roughly two weeks of data — ideally spanning the 26 October 2026 DST boundary —
the log answers the four questions in the brief and decides what, if anything,
the later "acting" tool needs to be.

This tool **never submits anything**. It reads one public page politely. It is
deliberately throwaway once the window is mapped.

This is Phase 0 of the wider brief only. Profiles, the guided write-up composer,
paste-ready output, and any alerting are explicitly **out of scope** for this
session and are deferred to evidence-led later phases.

## Critical constraints (from the brief)

- Do **not** automate, scrape, or POST against the eConsult / webGP form.
- Do **not** model slots, availability, or appointments — there are none.
- Local-first. No cloud, no telemetry, no third-party calls except the single
  GET to the public page being observed.
- macOS only. Prefer a `launchd` LaunchAgent over cron.
- Keep the poller small, self-contained, and auditable — likely throwaway.

## Empirical findings (observed 2026-07-22, ~19:10 UTC / 20:10 BST)

Verified directly against `https://example-surgery.example.com/` before
designing, because it determines feasibility:

- The page is served by Apache/Tomcat and the **state text is server-rendered
  in the raw HTML** — no JavaScript execution required to detect it. A plain
  `urllib` GET is sufficient. (This was the key risk; it is now retired.)
- The live **closed**-state copy currently reads:
  > "All our GP appointments are booked today so we can't accept online
  > requests at this time. You can submit a request again from 7am tomorrow.
  > If you need help, call the practice…"
- Stable structural hooks present in the closed state: element ids
  `serviceClosedSubheadingFirstLine` / `serviceClosedSubheadingSecondLine`
  and CSS class `service-closed-header`.
- **The wording differs from the brief's quoted strings** ("Today's urgent GP
  appointments are fully booked" / "please try again from 7am tomorrow"). This
  vindicates the brief's instruction to match tolerant text content and treat
  anything unrecognised as `unknown` rather than guessing.
- `robots.txt` returns a 302 (no disallow rules to honour today); the code will
  still fetch and respect it if it later returns rules.
- The page carries third-party analytics (Matomo `_paq`, Segment, Intercom) and
  a `sendBeacon('/logEvent')` self-referral tracker. Because the poller does a
  raw GET and **executes no JavaScript**, none of these beacons fire — better
  for the surgery and for privacy.
- The `/admin` route serves its own content ("sick note", "test result") and is
  the route the brief says stays open all day; it is polled separately so
  "does the admin route ever close?" is answerable.

## Detection logic

`fetch(url) -> normalise -> classify -> {open | closed | unknown}`, keying off
**text content, not DOM structure**.

Normalisation: strip tags, lower-case, collapse whitespace, decode common HTML
entities.

Classification against the normalised body:

- **closed** — any of these markers present:
  - substring `booked today`
  - substring `from 7am tomorrow` (and a tolerant variant `try again from 7am`)
  - id/class markers `serviceclosed` / `service-closed-header`
- **open** — closed markers **absent** AND a clinical-route signal present
  (e.g. `health problem`, or the Adult/Child route cards).
- **unknown** — neither pattern matched. Logged; never guessed.

Each poll also records which route headings are present (adult / child / admin),
so day-over-day route availability can be analysed. Marker matching is defined
as a small, named table so it is easy to audit and extend if the copy changes.

**Snapshotting (capture what we cannot yet see):** on every poll, of any state,
the raw body is saved to `data/snapshots/<content_hash>.html` — but only if a
snapshot with that content hash does not already exist. The content hash is the
sha256 of the *normalised visible text with volatile tokens masked* (clock times,
ISO datetimes, long hex fingerprints), not the raw bytes. This neutralises the
verified per-request noise (the load-balancer `<!-- ec2 server name: tomcatNN -->`
comment — the only difference between two back-to-back fetches — plus per-deploy
asset hashes in `src=`/`href=`) and pre-empts any future visible ticking value on
a state we have not yet observed. The result: the first time an unobserved state
appears — notably the open window — its page is captured, while steady-state
closed pages are stored exactly once. First writer wins. Masking applies only to
this dedup hash; detection classification is unaffected.

## Scheduling

**Self-pacing daemon**, kept alive by a `launchd` LaunchAgent (`KeepAlive`).
The daemon decides cadence from the wall clock; launchd only keeps it running
and restarts it on login/crash. Rationale: one place to read the cadence logic,
no per-poll process spawn, and launchd cannot cleanly express a time-of-day
varying interval.

Default cadence (single tunable config block):

- **Morning band 05:30–08:30 local**: poll every **20 seconds**, steadily and
  evenly across the whole band (an even interval is what pins the flip wherever
  it actually falls).
- **Rest of day**: light background poll every **20 minutes**, so "the reset
  happens once, in the morning" is a finding, not an assumption.

All closed and unknown polls are logged too — the precise edge is fixed by the
last `closed` immediately before the first `open`.

## Data model

SQLite at `data/observations.db` (single locatable, greppable, backup-able
file). SQLite over CSV because analysis needs day-of-week grouping and
edge-bounding queries. One row per poll:

| column            | meaning                                             |
| ----------------- | --------------------------------------------------- |
| `id`              | autoincrement                                       |
| `ts_utc`          | ISO 8601 UTC timestamp                              |
| `ts_local`        | ISO 8601 local timestamp                            |
| `utc_offset`      | e.g. `+01:00` (BST) / `+00:00` (GMT)                |
| `state`           | `open` \| `closed` \| `unknown`                     |
| `route`           | which URL was polled (`/` or `/admin`)              |
| `routes_present`  | comma list of detected route headings               |
| `http_status`     | HTTP status code                                    |
| `latency_ms`      | request round-trip                                  |
| `matched_markers` | which markers fired (audit trail for the verdict)   |
| `content_sha256`  | sha256 of the normalised visible text (page identity + snapshot name) |
| `notes`           | free text (errors, redirects, etc.)                 |

Storing UTC **and** local **and** offset on every row is the whole point: it is
what later distinguishes a UTC-scheduled reset from a local one. Within a single
BST fortnight the two are indistinguishable; they separate at the 26 October
2026 DST boundary. Logging unambiguously now keeps that answer available to a
monitor left running across that date.

## Good-citizen rules (baked in, non-negotiable)

- Honest, identifiable, **non-email** User-Agent (the security hook blocks
  emails in commands; also good practice to avoid embedding PII in a UA).
- One sequential request per poll. Never parallel. No hammering.
- Fetch and honour `robots.txt`.
- No cookies persisted between polls (each poll is stateless).
- Execute no JavaScript, so no third-party analytics beacons fire.
- Sane rates as specified above; read-only throughout.

## Analysis

`analyse.py` reads the DB and prints the brief's four findings:

1. Real open time and its jitter (is it 07:00:00 sharp, or is there variance?).
2. Time from open to booked, per day.
3. Day-of-week variation.
4. Whether the admin route ever closed.

Shipped now as a **working skeleton**: correct queries, honest "N days of data
so far" framing, meaningful the moment data accrues. It is not expected to yield
conclusions in this session.

## Project layout

```
econsult-window-monitor/
  README.md                 # what it is, how to run, how to install/remove the agent, how to wipe data
  pyproject.toml            # uv, modern Python (>=3.12), stdlib only
  .gitignore                # data/ (db + snapshots), venv, caches
  src/monitor/
    __init__.py
    config.py               # single tunable block: URLs, cadence, band, UA, paths
    fetch.py                # polite GET + robots.txt handling
    classify.py             # pure: normalised text -> (state, markers, routes)
    store.py                # SQLite schema + append
    poll.py                 # one poll = fetch -> classify -> store
    daemon.py               # self-pacing loop (cadence from wall clock)
    analyse.py              # the four findings
  tests/
    fixtures/closed.html    # the real captured closed-state page
    fixtures/open.html      # hand-built open-state fixture
    fixtures/unknown.html   # unrecognised page
    test_classify.py        # detection verified before any live run
    test_store.py           # schema + round-trip
  launchd/
    com.econsult.window-monitor.plist
    install.sh              # copies plist to ~/Library/LaunchAgents and loads it
    uninstall.sh            # unloads and removes it
  data/                     # gitignored: observations.db + snapshots/
```

`classify.py` is pure and unit-tested against the **real captured closed-state
HTML** as a fixture, plus hand-built open and unknown fixtures, so detection is
proven correct before the daemon ever runs live.

## Testing

- `test_classify.py`: closed fixture -> `closed` with expected markers; open
  fixture -> `open`; unknown fixture -> `unknown`; wording-variant robustness.
- `test_store.py`: schema creation is idempotent; a written row round-trips with
  all timestamp/offset columns intact.
- Manual: run one poll by hand (`python -m monitor.poll`), confirm a row lands
  in the DB with correct UTC/local/offset, then run the daemon briefly.

## Privacy and data control

- All data stays in `data/` on the user's machine; nothing leaves it.
- Export: the DB is a single SQLite file the user can copy.
- Wipe: deleting `data/` (or a documented `--wipe` note in the README) removes
  everything. No cloud state exists to reconcile.

## Repository hygiene — no attribution, small repo

Scope of the rule: it targets **incidental leakage in file contents and
machine identifiers**, not the user's deliberate commit signature. Commits are
**signed by the user as normal** (SSH signing via the 1Password agent) using
their standard GitHub identity — the privacy-preserving
`@users.noreply.github.com` email, which yields a **Verified** badge without
exposing a real address. Signing is intentional attribution and takes
precedence; "a determined party can deconstruct who I am" is accepted.

Hard requirements on everything committed:

- **No real email, username, hostname, or machine path in any committed file's
  contents.** (The author identity on a signed commit is deliberate and
  exempt.)
- **No hardcoded machine paths.** Code must never embed `/Users/<name>/…`.
  Paths resolve relative to the repo root or `~` at runtime, defined once in
  `config.py`.
- **User-Agent contains no email or personal identifier** (also enforced by the
  local security hook, which blocks emails in commands).
- **`.gitignore` excludes all observed data and machine cruft**: `data/`,
  `*.db`/`*.sqlite`, `snapshots/`, `*.log`, `.env*`, keys, `.DS_Store`,
  editor dirs. The observation log is health-adjacent special-category-ish data
  and must never be committed.
- **Keep the repo small**: stdlib only, no vendored dependencies, no build
  artefacts, no committed data. Only source, tests, small fixtures, docs, and
  the launchd plist are tracked.
- A pre-commit PII sweep (`git grep` for name/username/hostname/paths) is part
  of the manual release check.

## Scope guardrails

In scope this session: the poller, its self-pacing daemon, the launchd plist +
install/uninstall scripts (written, **user runs the install**), the SQLite
store, the classification tests, and the analysis skeleton.

Out of scope this session: profiles, the guided write-up composer, paste-ready
output, alerting/notifications, and anything that submits. These are later,
evidence-led phases decided by what the log shows.

## Open questions

None blocking. The DST question is answered by data, not design — the tool is
built to keep that option open by running across 26 October 2026.
