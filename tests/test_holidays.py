"""England & Wales bank holidays, computed rather than listed (no network)."""
from datetime import date

import pytest

from monitor import holidays


def test_fixed_and_easter_holidays_for_2026():
    # The published England & Wales set for 2026.
    assert holidays.is_bank_holiday("2026-01-01")   # New Year's Day, a Thursday
    assert holidays.is_bank_holiday("2026-04-03")   # Good Friday
    assert holidays.is_bank_holiday("2026-04-06")   # Easter Monday
    assert holidays.is_bank_holiday("2026-05-04")   # Early May, first Monday
    assert holidays.is_bank_holiday("2026-05-25")   # Spring, last Monday in May
    assert holidays.is_bank_holiday("2026-08-31")   # Summer, last Monday in August
    assert holidays.is_bank_holiday("2026-12-25")   # Christmas Day, a Friday


def test_ordinary_weekdays_are_not_bank_holidays():
    assert not holidays.is_bank_holiday("2026-08-24")   # the Monday before the summer one
    assert not holidays.is_bank_holiday("2026-09-07")
    assert not holidays.is_bank_holiday("2026-04-02")   # Maundy Thursday is not one


def test_accepts_a_date_object_as_well_as_an_iso_string():
    assert holidays.is_bank_holiday(date(2026, 8, 31))


def test_weekend_christmas_moves_to_a_substitute_weekday():
    # 2026: Boxing Day falls on Saturday, so the substitute is Monday 28th.
    assert not holidays.is_bank_holiday("2026-12-26")
    assert holidays.is_bank_holiday("2026-12-28")
    # 2027: Christmas Saturday and Boxing Day Sunday push to Monday and Tuesday.
    assert holidays.is_bank_holiday("2027-12-27")
    assert holidays.is_bank_holiday("2027-12-28")
    # 2028: New Year's Day falls on a Saturday, so Monday the 3rd stands in.
    assert not holidays.is_bank_holiday("2028-01-01")
    assert holidays.is_bank_holiday("2028-01-03")


@pytest.mark.parametrize("year,easter_monday", [
    (2025, "2025-04-21"), (2026, "2026-04-06"), (2027, "2027-03-29"), (2028, "2028-04-17"),
])
def test_easter_monday_is_computed_correctly_across_years(year, easter_monday):
    assert holidays.is_bank_holiday(easter_monday)


def test_name_for_identifies_the_holiday_and_is_none_otherwise():
    assert holidays.name_for("2026-08-31") == "Summer bank holiday"
    assert holidays.name_for("2026-12-28") == "Boxing Day (substitute day)"
    assert holidays.name_for("2026-08-24") is None
