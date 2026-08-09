"""Read the observation log and report the four Phase 0 findings.

A working skeleton: the logic is correct now and becomes meaningful as data
accrues. It draws no conclusions from thin data — it states how many days it has.
The analysis functions are pure over a list of records (easy to test); `main()`
reads the JSONL log and prints.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from . import config
from . import store
from .records import Record, day as _day

# Monday-first, matching datetime.weekday() (Monday == 0).
_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# The weekly pattern is a working-week pattern: Sat/Sun get a single summary
# line instead of a row each (see `_weekend_line`). `-x` still lists every day.
_WEEKEND = ("Saturday", "Sunday")

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


def day_total_open(summary: dict[str, Any]) -> tuple[int | None, bool]:
    """A day's total observed open time, and whether that total can be trusted.

    Sums every open block, so a day that reopened counts all of its open time,
    not just the first stretch. The total is *reliable* only when the day is
    complete and every block was seen to close — a 'lost' or 'ongoing' block,
    or a partial day, makes it a floor rather than a fact. Returns
    ``(None, False)`` for a day on which nothing was ever seen open.
    """
    blocks = _display_blocks(summary)
    if not blocks:
        return None, False
    total = sum(b["duration"] or 0 for b in blocks)
    reliable = (
        not summary.get("partial")
        and all(b.get("end_reason") == "closed" for b in blocks)
    )
    return total, reliable


def opening_was_watched(summary: dict[str, Any]) -> bool:
    """Were we already polling on this day before the window could have opened?

    'Never seen open' is only a finding if we were watching at the time. Coverage
    comes from the day's first poll (or, for summaries written before that field
    existed, its earliest recorded transition). A day whose watch began after the
    dense morning band — or whose coverage is unrecorded — says nothing either
    way, and is excluded rather than counted as a day the window stayed shut.
    """
    first = summary.get("first_poll_local")
    if first is None:
        first = min((t["at_local"] for t in summary.get("transitions") or []), default=None)
    if first is None:
        return False
    return first[11:16] <= config.DENSE_START


def week_start(day: str) -> str:
    """The Monday of the week containing this local date (British week, Monday-first)."""
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def weekday_stats(day_summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-weekday averages of total open time, across all the weeks logged.

    Each weekday entry carries the honest denominators alongside the average:
    ``days`` counted, ``weeks`` those days span, and three ways a day can fall
    outside the average — ``floors`` (seen open, but never seen to close, so its
    time is a lower bound; ``floor_avg`` is the mean of those bounds),
    ``no_open`` (we watched right through the morning and it never opened) and
    ``unknown`` (nothing seen open and we weren't watching, which asserts
    nothing either way).
    """
    counted: dict[str, list[int]] = defaultdict(list)
    weeks: dict[str, set[str]] = defaultdict(set)
    floors: dict[str, list[int]] = defaultdict(list)
    no_open: dict[str, int] = defaultdict(int)
    unknown: dict[str, int] = defaultdict(int)
    starts: dict[str, set[str]] = defaultdict(set)

    for summary in day_summaries:
        weekday = summary.get("weekday") or "?"
        opened = summary.get("first_open_local")
        if opened:
            starts[weekday].add(opened[11:16])
        total, reliable = day_total_open(summary)
        if total is None:
            # Nothing seen open — a finding only if we watched the whole morning;
            # otherwise (today so far, or a day we started logging late) it is
            # simply an absence of data, with no floor to state.
            if summary.get("partial") or not opening_was_watched(summary):
                unknown[weekday] += 1
            else:
                no_open[weekday] += 1
        elif reliable:
            counted[weekday].append(total)
            weeks[weekday].add(week_start(summary["date"]))
        else:
            floors[weekday].append(total)

    seen = set(counted) | set(floors) | set(no_open) | set(unknown) | set(starts)
    return {
        weekday: {
            "avg": sum(counted[weekday]) // len(counted[weekday]) if counted[weekday] else None,
            "days": len(counted[weekday]),
            "weeks": len(weeks[weekday]),
            "floors": len(floors[weekday]),
            "floor_avg": (sum(floors[weekday]) // len(floors[weekday])
                          if floors[weekday] else None),
            "no_open": no_open[weekday],
            "unknown": unknown[weekday],
            "starts": sorted(starts[weekday]),
        }
        for weekday in seen
    }


def recent_weekdays(day_summaries: list[dict[str, Any]],
                    span: int = 5) -> tuple[str | None, list[dict[str, Any]]]:
    """(first date shown, summaries) for the last ``span`` weekdays with data.

    A rolling window, not the calendar week: counting back from the newest day
    logged and skipping Saturdays and Sundays, so a Monday still shows the
    previous Tuesday–Friday alongside it rather than sitting on its own.
    """
    dated = [s for s in day_summaries if s.get("date")]
    if not dated:
        return None, []

    day = date.fromisoformat(max(s["date"] for s in dated))
    window: set[str] = set()
    while len(window) < span:
        if day.weekday() < 5:                     # Monday–Friday only
            window.add(day.isoformat())
        day -= timedelta(days=1)

    week = sorted((s for s in dated if s["date"] in window), key=lambda s: s["date"])
    return (week[0]["date"] if week else None), week


def _pretty_date(day: str) -> str:
    """'2026-07-27' -> '27 Jul', for the week heading."""
    return date.fromisoformat(day).strftime("%-d %b")


def weekly_report(day_summaries: list[dict[str, Any]]) -> str:
    """Plain-text weekly view: the day-of-week pattern, then the latest week."""
    stats = weekday_stats(day_summaries)
    opens_w = opens_at_width(stats)

    lines = ["Opening hours — the weekly pattern, averaged across the weeks logged", ""]
    lines.append(f"  {'Day':10}  {'Avg open':10}  {'Opens at':{opens_w}}  {'Days':5}  {'Weeks':5}")
    lines.append(f"  {'-'*10}  {'-'*10}  {'-'*opens_w}  {'-'*5}  {'-'*5}")

    for weekday in _WEEKDAY_ORDER:
        if weekday not in stats or weekday in _WEEKEND:
            continue
        row = stats[weekday]
        avg = weekday_avg_cell(row)
        opens = opens_at_cell(row)
        note = _weekday_note(row)
        lines.append(f"  {weekday:10}  {avg:10}  {opens:{opens_w}}  {row['days']:<5}  {row['weeks']:<5}{note}")

    weekend = _weekend_line(stats)
    if weekend:
        lines.append("")
        lines.append(weekend)

    start, week = recent_weekdays(day_summaries)
    if week:
        span = f"{_pretty_date(start)} – {_pretty_date(week[-1]['date'])}"
        lines.append("")
        lines.append(f"  Latest week ({span})")
        lines.append(f"  {'Date':10}  {'Day':9}  {'Opened':8}  {'Closed':10}  {'Open for':10}")
        lines.append(f"  {'-'*10}  {'-'*9}  {'-'*8}  {'-'*10}  {'-'*10}")
        for line in _week_table_lines(week):
            lines.append(line)

    lines.append("")
    lines.append(f"  {len(day_summaries)} day(s) logged in total.  "
                 "Run 'econsult view -x' for every day.")
    return "\n".join(lines)


def _weekend_line(stats: dict[str, dict[str, Any]]) -> str | None:
    """The one line the weekend gets, in place of a row each in the pattern.

    Saturday and Sunday have never been seen open, so a full row apiece is two
    rows of dashes; but the days logged are still evidence, so state how many
    there are — and say so loudly if one ever does open."""
    rows = {day: stats[day] for day in _WEEKEND if day in stats}
    if not rows:
        return None
    days = sum(r["days"] + r["floors"] + r["no_open"] + r["unknown"] for r in rows.values())
    opened = [day for day, r in rows.items() if r["starts"]]
    if opened:
        return (f"  Weekends: {days} day(s) logged — {' and '.join(opened)} seen open; "
                "run 'econsult view -x' for the detail.")
    unknown = sum(r["unknown"] for r in rows.values())
    caveat = f" — {unknown} with no data (gap or in progress)" if unknown else ""
    return f"  Weekends: {days} day(s) logged, never seen open{caveat}."


def weekday_avg_cell(row: dict[str, Any]) -> str:
    """The 'Avg open' figure for a weekday: the average of the days seen right
    through, or — failing that — the floor we can still stand behind."""
    if row["days"]:
        return fmt_duration(row["avg"])
    if row["floor_avg"] is not None:
        return "≥ " + fmt_duration(row["floor_avg"])
    return "—"


def opens_at_cell(row: dict[str, Any]) -> str:
    """The 'Opens at' figure for a weekday — every distinct opening time seen."""
    return ", ".join(row["starts"]) if row["starts"] else "—"


def opens_at_width(stats: dict[str, dict[str, Any]]) -> int:
    """Width the 'Opens at' column needs: a day that opens twice carries two
    times, and a fixed width would push the columns after it out of line.

    Weekends are measured out — they have no row in the table to size for."""
    return max([len("Opens at")]
               + [len(opens_at_cell(r)) for day, r in stats.items() if day not in _WEEKEND])


def _weekday_note(row: dict[str, Any]) -> str:
    """The caveat that keeps a weekday average honest — what it left out.

    A day never seen to close still says something ('open at least this long'),
    so it is reported with its floor rather than as a bare exclusion count."""
    notes = []
    if row["floors"]:
        floor = fmt_duration(row["floor_avg"])
        counted = ", not counted" if row["days"] else ""
        notes.append(f"{row['floors']} day(s) open ≥ {floor}{counted}")
    if row["unknown"]:
        notes.append(f"{row['unknown']} day(s) no data — gap or in progress")
    if row["no_open"]:
        notes.append(f"{row['no_open']} day(s) never seen open")
    return "  (" + "; ".join(notes) + ")" if notes else ""


def _week_table_lines(week: list[dict[str, Any]]) -> list[str]:
    """The day-by-day rows for one week, in the same shape as the full table."""
    lines = []
    for row in opening_hours_rows(week):
        day_cell = row["weekday"][:3] + ("*" if row["partial"] else "")
        if not row["blocks"]:
            lines.append(f"  {row['date']:10}  {day_cell:9}  {'—':8}  {'—':10}  {'—':10}")
            continue
        for i, block in enumerate(row["blocks"]):
            closed, dur = block_cells(block)
            note = "" if i == 0 else "  (reopened)"
            lines.append(f"  {row['date'] if i == 0 else '':10}  {day_cell if i == 0 else '':9}  "
                         f"{block['opened']:8}  {closed:10}  {dur:10}{note}")
    return lines


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
