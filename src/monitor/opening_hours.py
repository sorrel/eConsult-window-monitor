"""Running, day-by-day record of the clinical eConsult window's opening hours.

Reads the daily summaries (completed days) plus today's raw log. By default it
prints the weekly pattern — total open time averaged per day of the week across
the weeks logged, then the latest week day by day. With `-x` it prints every
logged day instead, with running averages. Today is marked partial (in
progress), so its duration is shown but excluded from the averages.

    uv run python -m monitor.opening_hours       # weekly pattern
    uv run python -m monitor.opening_hours -x    # every logged day
"""
from __future__ import annotations

import sys

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
    """Weekly pattern by default; `-x` for every logged day — mirrors `econsult view`."""
    days = assemble_days()
    print(analyse.opening_hours_report(days) if "-x" in sys.argv
          else analyse.weekly_report(days))


if __name__ == "__main__":
    main()
