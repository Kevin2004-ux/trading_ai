from datetime import date, datetime
from zoneinfo import ZoneInfo

from market.calendar import (
    get_latest_expected_completed_session,
    get_previous_market_day,
    is_latest_completed_session,
    is_market_day,
)


NY = ZoneInfo("America/New_York")


def test_friday_bar_is_latest_completed_session_on_weekend():
    now = datetime(2026, 1, 10, 12, 0, tzinfo=NY)
    result = is_latest_completed_session("2026-01-09T00:00:00+00:00", now=now)

    assert result["ok"] is True
    assert result["latest_expected_completed_session"] == "2026-01-09"
    assert result["is_latest_completed_session"] is True
    assert result["is_stale_by_session"] is False


def test_thursday_bar_is_latest_after_juneteenth_holiday_weekend():
    now = datetime(2026, 6, 21, 12, 0, tzinfo=NY)
    result = is_latest_completed_session("2026-06-18T00:00:00+00:00", now=now)

    assert is_market_day(date(2026, 6, 18)) is True
    assert is_market_day(date(2026, 6, 19)) is False
    assert result["latest_expected_completed_session"] == "2026-06-18"
    assert result["is_latest_completed_session"] is True
    assert result["is_stale_by_session"] is False


def test_common_us_market_holidays_are_closed():
    closed_days = [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ]

    assert all(not is_market_day(day) for day in closed_days)


def test_genuinely_old_bar_is_stale_by_market_session():
    now = datetime(2026, 6, 22, 12, 0, tzinfo=NY)
    result = is_latest_completed_session("2026-06-17T00:00:00+00:00", now=now)

    assert result["latest_expected_completed_session"] == "2026-06-18"
    assert result["is_latest_completed_session"] is False
    assert result["is_stale_by_session"] is True
    assert result["market_session_lag"] == 1


def test_latest_expected_completed_session_uses_previous_day_before_close():
    now = datetime(2026, 6, 22, 10, 0, tzinfo=NY)

    assert get_latest_expected_completed_session(now=now) == date(2026, 6, 18)
    assert get_previous_market_day(date(2026, 6, 22)) == date(2026, 6, 18)
