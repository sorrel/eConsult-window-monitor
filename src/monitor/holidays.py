"""England & Wales bank holidays, computed from the rules — no network, no list.

The GOV.UK bank-holiday feed would be the obvious source, but this monitor makes
no network call beyond the page it observes, and a hardcoded table goes stale the
year after it is written. The dates follow published rules instead: the fixed
days (with a substitute weekday whenever one lands at a weekend), the Monday
holidays defined by position in their month, and Good Friday / Easter Monday from
the Gregorian computus.

Rules cannot know about the one-offs — a royal funeral, a jubilee, a moved spring
holiday — so `_EXTRA` and `_MOVED` carry those by hand. Both are empty today;
2022 is the worked example of how they would be used (spring bank holiday moved
from 30 May to 2 June, with 3 June and 19 September added).

Scotland and Northern Ireland differ; this is the England & Wales set.
"""
from __future__ import annotations

from datetime import date, timedelta

# One-off holidays the rules cannot produce: ISO date -> name.
_EXTRA: dict[str, str] = {}
# Rule-generated dates that did not happen, because the day was moved.
_MOVED: set[str] = set()


def easter_sunday(year: int) -> date:
    """Easter Sunday by the Anonymous Gregorian computus."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _first_monday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(0 - first.weekday()) % 7)


def _last_monday(year: int, month: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=last.weekday())


def _substitute(day: date, taken: set[date]) -> date:
    """The next weekday not already spoken for — how a weekend holiday moves."""
    while day.weekday() >= 5 or day in taken:
        day += timedelta(days=1)
    return day


def holidays_for(year: int) -> dict[date, str]:
    """Every England & Wales bank holiday in `year`, as date -> name."""
    easter = easter_sunday(year)
    days: dict[date, str] = {}
    taken: set[date] = set()

    # Substituted days are claimed in calendar order, so Boxing Day steps past
    # the Monday Christmas Day has already taken.
    for day, name in (
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 12, 25), "Christmas Day"),
        (date(year, 12, 26), "Boxing Day"),
    ):
        moved = _substitute(day, taken)
        days[moved] = name if moved == day else f"{name} (substitute day)"
        taken.add(moved)

    days[easter - timedelta(days=2)] = "Good Friday"
    days[easter + timedelta(days=1)] = "Easter Monday"
    days[_first_monday(year, 5)] = "Early May bank holiday"
    days[_last_monday(year, 5)] = "Spring bank holiday"
    days[_last_monday(year, 8)] = "Summer bank holiday"

    for iso in _MOVED:
        days.pop(date.fromisoformat(iso), None)
    for iso, name in _EXTRA.items():
        if date.fromisoformat(iso).year == year:
            days[date.fromisoformat(iso)] = name
    return days


def _as_date(day: date | str) -> date:
    return day if isinstance(day, date) else date.fromisoformat(day[:10])


def name_for(day: date | str) -> str | None:
    """The bank holiday's name, or None if that date is an ordinary day."""
    day = _as_date(day)
    return holidays_for(day.year).get(day)


def is_bank_holiday(day: date | str) -> bool:
    return name_for(day) is not None
