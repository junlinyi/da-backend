"""Unit tests for the age-verification service (AGE_VERIFICATION_SPEC.md Test Plan).

Pure functions — no DB. Uses a fixed `today` so the assertions are stable
regardless of when the suite runs.
"""
from datetime import date

import pytest

from app.services.age_service import (
    compute_age,
    validate_birthdate,
    birthdate_bounds_for_age_range,
    BirthdateValidationError,
)

TODAY = date(2026, 6, 17)

# These are pure-function tests with no DB. `nodb` tells the legacy autouse
# SQLite fixture (tests/conftest.py) to skip; async defs let pytest-asyncio
# (asyncio_mode=auto) drive them on the shared loop without an event-loop clash.
pytestmark = pytest.mark.nodb


# --- compute_age -----------------------------------------------------------
async def test_compute_age_basic():
    assert compute_age(date(2000, 6, 15), TODAY) == 26


async def test_compute_age_birthday_today():
    # Born exactly 18 years ago today → 18.
    assert compute_age(date(2008, 6, 17), TODAY) == 18


async def test_compute_age_birthday_tomorrow():
    # Birthday is tomorrow → not yet ticked over.
    assert compute_age(date(2008, 6, 18), TODAY) == 17


async def test_compute_age_leap_day():
    # Feb 29 birthday, non-leap year today.
    assert compute_age(date(2004, 2, 29), date(2026, 3, 1)) == 22
    assert compute_age(date(2004, 2, 29), date(2026, 2, 28)) == 21


# --- validate_birthdate ----------------------------------------------------
async def test_validate_rejects_future():
    with pytest.raises(BirthdateValidationError):
        validate_birthdate(date(2030, 1, 1), TODAY)


async def test_validate_rejects_over_120():
    with pytest.raises(BirthdateValidationError):
        validate_birthdate(date(1900, 1, 1), TODAY)


async def test_validate_rejects_just_under_18():
    # 17 years, 364 days old — turns 18 tomorrow relative to TODAY.
    with pytest.raises(BirthdateValidationError):
        validate_birthdate(date(2008, 6, 18), TODAY)


async def test_validate_accepts_exactly_18():
    validate_birthdate(date(2008, 6, 17), TODAY)  # no raise


async def test_validate_accepts_reasonable_adult():
    validate_birthdate(date(1990, 3, 10), TODAY)  # no raise


# --- birthdate_bounds_for_age_range ---------------------------------------
async def test_bounds_18_to_120():
    lower, upper = birthdate_bounds_for_age_range(18, 120, TODAY)
    # Upper bound: someone born exactly 18y ago is included.
    assert upper == date(2008, 6, 17)
    assert compute_age(upper, TODAY) == 18
    # Lower bound: someone at this DOB is at most 120.
    assert compute_age(lower, TODAY) == 120


async def test_bounds_edges_are_inclusive():
    lower, upper = birthdate_bounds_for_age_range(25, 30, TODAY)
    assert compute_age(upper, TODAY) == 25   # youngest allowed
    assert compute_age(lower, TODAY) == 30   # oldest allowed
