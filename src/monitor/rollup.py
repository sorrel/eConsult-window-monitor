"""Roll completed days up into one summary line each, dropping their raw polls.

Retention: the raw observation log keeps only the current (incomplete) day; each
past day is reduced to a single summary in daily_summary.jsonl. Snapshots of
distinct pages are kept separately and untouched.

Each summary preserves what the Phase 0 findings need — first-open time (with
UTC, local, and offset, so the DST question survives), the last 'closed' before
it (the edge lower bound), the open duration, state counts, and whether the
admin route was ever seen closed.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from . import store
from .records import Record, day as _day

_CLINICAL = config.CLINICAL_PATH
_ADMIN = config.ADMIN_PATH


def _count_states(records: list[Record]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record["state"]] = counts.get(record["state"], 0) + 1
    return counts


def _duration_seconds(start_local: str, end_local: str) -> int:
    start = datetime.fromisoformat(start_local)
    end = datetime.fromisoformat(end_local)
    return int((end - start).total_seconds())


def transitions(records: list[Record]) -> list[dict[str, Any]]:
    """The day's state-change points — the fundamentals, minus the flat runs.

    One entry per state change (and the day's opening state), per route, each
    bounded by the last poll of the previous state so the change is pinned
    between two timestamps. Keeps UTC + offset on the change point so the DST
    question survives after the raw polls are dropped.
    """
    changes: list[dict[str, Any]] = []
    for route in sorted({r["route"] for r in records}):
        ordered = sorted((r for r in records if r["route"] == route), key=lambda r: r["ts_local"])
        previous: Record | None = None
        for record in ordered:
            if previous is None or record["state"] != previous["state"]:
                changes.append({
                    "route": route,
                    "state": record["state"],
                    "at_local": record["ts_local"],
                    "at_utc": record["ts_utc"],
                    "at_offset": record["utc_offset"],
                    "prev_state": previous["state"] if previous else None,
                    "prev_last_local": previous["ts_local"] if previous else None,
                })
            previous = record
    changes.sort(key=lambda c: c["at_local"])
    return changes


def open_blocks(clinical_sorted: list[Record]) -> list[dict[str, Any]]:
    """Every distinct open block in a day's clinical readings, in time order.

    A block runs from the first 'open' of a contiguous open run to how it ended:

    - ``closed`` — a 'closed' reading was seen; ``end_local`` is that close and
      ``duration_seconds`` is the real open span.
    - ``lost`` — the run ran into a gap (fetches failing / 'unknown') before any
      close was observed; ``end_local`` is the last seen open, so
      ``duration_seconds`` is a *floor*, not the true duration. Never guessed.
    - ``ongoing`` — still open at the last reading of the data.

    ``clinical_sorted`` must be the clinical-route readings sorted by ``ts_local``.
    """
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for r in clinical_sorted:
        state = r["state"]
        if state == "open":
            if cur is None:
                cur = {"start_local": r["ts_local"], "last_open_local": r["ts_local"]}
            else:
                cur["last_open_local"] = r["ts_local"]
        elif cur is not None:
            if state == "closed":
                cur["end_local"], cur["end_reason"] = r["ts_local"], "closed"
            else:  # 'unknown' — fetch failed / page unrecognised: we lost sight of it
                cur["end_local"], cur["end_reason"] = cur["last_open_local"], "lost"
            cur["duration_seconds"] = _duration_seconds(cur["start_local"], cur["end_local"])
            blocks.append(cur)
            cur = None
    if cur is not None:
        cur["end_local"], cur["end_reason"] = cur["last_open_local"], "ongoing"
        cur["duration_seconds"] = _duration_seconds(cur["start_local"], cur["end_local"])
        blocks.append(cur)
    return blocks


def summarise_day(records: list[Record], date: str) -> dict[str, Any]:
    """Reduce one local day's poll records to a single summary object."""
    day = [r for r in records if _day(r["ts_local"]) == date]
    clinical = sorted((r for r in day if r["route"] == _CLINICAL), key=lambda r: r["ts_local"])
    opens = [r for r in clinical if r["state"] == "open"]
    closed = [r for r in clinical if r["state"] == "closed"]
    first_open = opens[0] if opens else None
    blocks = open_blocks(clinical)

    summary: dict[str, Any] = {
        "date": date,
        "weekday": datetime.fromisoformat(date).strftime("%A"),
        "polls": len(day),
        "clinical_polls": len(clinical),
        "states": _count_states(day),
        "unknowns": sum(1 for r in day if r["state"] == "unknown"),
        "admin_closed_seen": any(r["route"] == _ADMIN and r["state"] == "closed" for r in day),
        "transitions": transitions(day),
        "first_open_local": None,
        "first_open_utc": None,
        "first_open_offset": None,
        "last_closed_before_open_local": None,
        "closed_after_open_local": None,
        "open_duration_seconds": None,
        "open_blocks": blocks,
    }
    if first_open:
        first_open_local = first_open["ts_local"]
        summary["first_open_local"] = first_open_local
        summary["first_open_utc"] = first_open["ts_utc"]
        summary["first_open_offset"] = first_open["utc_offset"]
        before = [r["ts_local"] for r in closed if r["ts_local"] < first_open_local]
        summary["last_closed_before_open_local"] = max(before) if before else None
        after = [r["ts_local"] for r in closed if r["ts_local"] > first_open_local]
        if after:
            closed_after = min(after)
            summary["closed_after_open_local"] = closed_after
            summary["open_duration_seconds"] = _duration_seconds(first_open_local, closed_after)
    return summary


def rollup(
    log_path: Path | None = None,
    summary_path: Path | None = None,
    today: str | None = None,
) -> int:
    """Summarise every completed (past) day, append to the summary file, and
    rewrite the raw log to keep only today's records. Idempotent — a day already
    in the summary file is skipped. Returns the number of days newly summarised.
    """
    log_path = log_path or config.LOG_PATH
    summary_path = summary_path or config.SUMMARY_PATH
    if today is None:
        today = datetime.now().astimezone().date().isoformat()

    records = store.read_all(log_path)
    if not records:
        return 0
    dates = sorted({_day(r["ts_local"]) for r in records})
    past = [d for d in dates if d < today]
    if not past:
        return 0

    already = {s.get("date") for s in store.read_all(summary_path)}
    summarised = 0
    for date in past:
        if date in already:
            continue
        store.append_json(summarise_day(records, date), summary_path)
        summarised += 1

    kept = [r for r in records if _day(r["ts_local"]) >= today]
    store.rewrite(kept, log_path)
    return summarised


if __name__ == "__main__":
    n = rollup()
    print(f"summarised {n} completed day(s) into {config.SUMMARY_PATH}")
