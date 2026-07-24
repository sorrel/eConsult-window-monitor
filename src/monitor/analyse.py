"""Read the observation log and report the four Phase 0 findings.

A working skeleton: the logic is correct now and becomes meaningful as data
accrues. It draws no conclusions from thin data — it states how many days it has.
The analysis functions are pure over a list of records (easy to test); `main()`
reads the JSONL log and prints.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from . import config
from . import store
from .records import Record, day as _day

# Monday-first, matching datetime.weekday() (Monday == 0).
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_CLINICAL = config.CLINICAL_PATH
_ADMIN = config.ADMIN_PATH


def _clinical_opens(records: list[Record]) -> list[Record]:
    return [r for r in records if r["route"] == _CLINICAL and r["state"] == "open"]


def first_open_by_day(records: list[Record]) -> list[tuple[str, str]]:
    """(local_date, earliest 'open' ts_local) for the clinical route, per day."""
    by_day: dict[str, str] = {}
    for r in _clinical_opens(records):
        day = _day(r["ts_local"])
        if day not in by_day or r["ts_local"] < by_day[day]:
            by_day[day] = r["ts_local"]
    return sorted(by_day.items())


def last_closed_before_first_open(records: list[Record], day: str) -> str | None:
    """The last 'closed' clinical poll before that day's first 'open' — bounds the edge."""
    opens = [r["ts_local"] for r in _clinical_opens(records) if _day(r["ts_local"]) == day]
    if not opens:
        return None
    first_open = min(opens)
    closed = [
        r["ts_local"]
        for r in records
        if r["route"] == _CLINICAL and r["state"] == "closed"
        and _day(r["ts_local"]) == day and r["ts_local"] < first_open
    ]
    return max(closed) if closed else None


def open_duration_by_day(records: list[Record]) -> list[tuple[str, str, str | None]]:
    """(local_date, first_open_ts, first 'closed' after it) per day."""
    out: list[tuple[str, str, str | None]] = []
    for day, first_open in first_open_by_day(records):
        closed_after = [
            r["ts_local"]
            for r in records
            if r["route"] == _CLINICAL and r["state"] == "closed"
            and _day(r["ts_local"]) == day and r["ts_local"] > first_open
        ]
        out.append((day, first_open, min(closed_after) if closed_after else None))
    return out


def _weekday_name(day: str) -> str:
    return _WEEKDAY_ORDER[date.fromisoformat(day).weekday()]


def weekday_open_times(records: list[Record]) -> list[tuple[str, str]]:
    """(weekday_name, earliest 'open' ts_local) for day-of-week comparison."""
    return [(_weekday_name(day), ts) for day, ts in first_open_by_day(records)]


def admin_ever_closed(records: list[Record]) -> bool:
    return any(r["route"] == _ADMIN and r["state"] == "closed" for r in records)


def format_summary_line(summary: dict[str, Any]) -> str:
    """One human-readable line for a rolled-up day."""
    if summary.get("first_open_local"):
        opened = summary["first_open_local"][11:19]
        before = summary.get("last_closed_before_open_local")
        before_txt = before[11:19] if before else "n/a"
        duration = summary.get("open_duration_seconds")
        if duration is None:
            dur_txt = "open (no later close observed)"
        else:
            dur_txt = f"{duration // 60}m{duration % 60:02d}s"
        return (
            f"{summary['date']} ({summary.get('weekday', '?')}): opened {opened} "
            f"(offset {summary.get('first_open_offset', '?')}), last closed before {before_txt}, "
            f"open for {dur_txt}, {summary.get('polls', 0)} polls"
        )
    return f"{summary['date']} ({summary.get('weekday', '?')}): no open observed, {summary.get('polls', 0)} polls"


def format_findings(summaries: list[dict[str, Any]], records: list[Record]) -> str:
    """Combined readout: history from daily summaries + today's live raw log."""
    lines = [f"{len(summaries)} summarised day(s); {len(records)} polls in today's log."]

    if summaries:
        lines.append("\nPast days (from daily summary):")
        for summary in summaries:
            lines.append("  " + format_summary_line(summary))

    lines.append("\nToday (live from raw log):")
    opens = first_open_by_day(records)
    if opens:
        for day, first_open in opens:
            edge = last_closed_before_first_open(records, day)
            lines.append(f"  {day}: open at {first_open} (last closed before: {edge or 'n/a'})")
        for day, first_open, first_closed in open_duration_by_day(records):
            lines.append(f"  {day}: open -> {first_closed or 'still open / not observed'}")
    else:
        states: dict[str, int] = {}
        for record in records:
            states[record["state"]] = states.get(record["state"], 0) + 1
        lines.append(f"  no open observed yet today; states so far: {states or 'none'}")

    lines.append(f"\nAdmin ever observed closed (today): {admin_ever_closed(records)}")
    return "\n".join(lines)


def fmt_duration(seconds: int | None) -> str:
    """Seconds -> compact 'Hh MMm' / 'Mm SSs', or a dash when unknown."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s"


def opening_hours_rows(day_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One display row per day — the shared source of truth for plain and
    coloured renderings. Each daily summary dict may carry a `partial` flag
    (today, or a day with a logging gap) so its duration is not trusted."""
    rows = []
    for summary in day_summaries:
        opened_iso = summary.get("first_open_local")
        closed_iso = summary.get("closed_after_open_local")
        rows.append({
            "date": summary.get("date", "?"),
            "weekday": summary.get("weekday") or "?",
            "opened": opened_iso[11:19] if opened_iso else None,
            "closed": closed_iso[11:19] if closed_iso else None,
            "has_open": bool(opened_iso),
            "duration": summary.get("open_duration_seconds"),
            "partial": bool(summary.get("partial")),
            "blocks": _display_blocks(summary),
        })
    return rows


def _display_blocks(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Every open block of a day, ready to render — one per open/reopen. Falls
    back to a single synthesised block for summaries written before the
    open_blocks field existed, so old daily summaries still render."""
    blocks = summary.get("open_blocks")
    if blocks is None:
        opened_iso = summary.get("first_open_local")
        if not opened_iso:
            return []
        closed_iso = summary.get("closed_after_open_local")
        blocks = [{
            "start_local": opened_iso,
            "end_local": closed_iso or opened_iso,
            "end_reason": "closed" if closed_iso else "ongoing",
            "duration_seconds": summary.get("open_duration_seconds"),
        }]
    return [{
        "opened": b["start_local"][11:19],
        "closed": b["end_local"][11:19],
        "duration": b.get("duration_seconds"),
        "end_reason": b.get("end_reason", "closed"),
    } for b in blocks]


def opening_hours_stats(day_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Running aggregates over the days, counting only reliable (non-partial) durations."""
    reliable: list[int] = []
    by_weekday: dict[str, list[int]] = defaultdict(list)
    open_times: list[str] = []
    for summary in day_summaries:
        if summary.get("first_open_local"):
            open_times.append(summary["first_open_local"][11:16])
        duration = summary.get("open_duration_seconds")
        if duration is not None and not summary.get("partial"):
            reliable.append(duration)
            by_weekday[summary.get("weekday") or "?"].append(duration)
    return {
        "days_logged": len(day_summaries),
        "days_with_open": sum(1 for s in day_summaries if s.get("first_open_local")),
        "reliable_count": len(reliable),
        "avg": sum(reliable) // len(reliable) if reliable else None,
        "shortest": min(reliable) if reliable else None,
        "longest": max(reliable) if reliable else None,
        "total": sum(reliable),
        "by_weekday": {wd: sum(v) // len(v) for wd, v in by_weekday.items()},
        "weekday_counts": {wd: len(v) for wd, v in by_weekday.items()},
        "open_times": sorted(set(open_times)),
    }


def block_cells(block: dict[str, Any]) -> tuple[str, str]:
    """Closed and 'Open for' cell text for one open block, honest about blocks
    that never had a close observed. Shared by the plain and coloured views."""
    reason = block.get("end_reason", "closed")
    if reason == "closed":
        return block["closed"], fmt_duration(block["duration"])
    if reason == "ongoing":
        return "still open", "≥ " + fmt_duration(block["duration"])
    return "lost", "≥ " + fmt_duration(block["duration"])  # fetches failed before a close


def opening_hours_report(day_summaries: list[dict[str, Any]]) -> str:
    """Plain-text running, day-by-day record of how long the window is open.

    A day that opened more than once gets one continuation line per reopen."""
    lines = ["Opening hours — how long the clinical eConsult window is open each day", ""]
    lines.append(f"  {'Date':10}  {'Day':9}  {'Opened':8}  {'Closed':10}  {'Open for':10}")
    lines.append(f"  {'-'*10}  {'-'*9}  {'-'*8}  {'-'*10}  {'-'*10}")

    for row in opening_hours_rows(day_summaries):
        day_cell = row["weekday"][:3] + ("*" if row["partial"] else "")
        if not row["blocks"]:
            lines.append(f"  {row['date']:10}  {day_cell:9}  {'—':8}  {'—':10}  {'—':10}")
            continue
        for i, block in enumerate(row["blocks"]):
            closed, dur = block_cells(block)
            note = "" if i == 0 else "  (reopened)"
            date_cell = row["date"] if i == 0 else ""
            day_col = day_cell if i == 0 else ""
            lines.append(f"  {date_cell:10}  {day_col:9}  {block['opened']:8}  {closed:10}  {dur:10}{note}")

    stats = opening_hours_stats(day_summaries)
    lines.append("")
    lines.append(f"  Days logged: {stats['days_logged']}   with an open observed: {stats['days_with_open']}")
    n = stats["reliable_count"]  # completed days that actually opened; non-open and provisional days excluded
    if n == 1:
        lines.append(f"  Open duration: {fmt_duration(stats['avg'])}  (from 1 open day so far)")
    elif n >= 2:
        lines.append(
            f"  Open duration over {n} open days: average {fmt_duration(stats['avg'])}, "
            f"shortest {fmt_duration(stats['shortest'])}, longest {fmt_duration(stats['longest'])}"
        )
    if stats["open_times"]:
        lines.append(f"  Open times seen: {', '.join(stats['open_times'])}")
    if stats["by_weekday"]:
        lines.append("  By weekday (average open, reliable days):")
        for weekday in _WEEKDAY_ORDER:
            if weekday in stats["by_weekday"]:
                lines.append(f"     {weekday:9} {fmt_duration(stats['by_weekday'][weekday])}"
                             f"  ({stats['weekday_counts'][weekday]} day(s))")
    if any(s.get("partial") for s in day_summaries):
        lines.append("  * partial day (in progress or a logging gap) — duration not counted in averages")
    return "\n".join(lines)


def main() -> None:
    summaries = store.read_all(config.SUMMARY_PATH)
    records = store.read_all(config.LOG_PATH)
    print("eConsult window monitor — findings\n")
    print(format_findings(summaries, records))


if __name__ == "__main__":
    main()
