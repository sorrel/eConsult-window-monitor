"""Running, day-by-day record of the clinical eConsult window's opening hours.

Reads the daily summaries (completed days) plus today's raw log, and prints a
table of open / close / duration per day with running averages and a
by-weekday breakdown. Today is marked partial (in progress), so its duration is
shown but excluded from the averages.

    uv run python -m monitor.opening_hours
"""
from __future__ import annotations

from . import analyse
from . import config
from . import rollup
from . import store


def assemble_days() -> list[dict]:
    """Completed-day summaries plus today's (computed from the raw log, partial)."""
    summaries = list(store.read_all(config.SUMMARY_PATH))
    seen = {s.get("date") for s in summaries}
    today_records = store.read_all(config.LOG_PATH)
    if today_records:
        today_date = today_records[-1]["ts_local"][:10]
        if today_date not in seen:
            today_summary = rollup.summarise_day(today_records, today_date)
            today_summary["partial"] = True
            summaries.append(today_summary)
    return summaries


def main() -> None:
    print(analyse.opening_hours_report(assemble_days()))


if __name__ == "__main__":
    main()
