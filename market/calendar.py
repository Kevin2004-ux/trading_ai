from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo


US_EASTERN = ZoneInfo("America/New_York")
MARKET_CLOSE_BUFFER = time(16, 15)


def _as_date(value: Any) -> date:
    if value is None:
        return datetime.now(US_EASTERN).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(US_EASTERN).date()
    if isinstance(value, date):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(US_EASTERN).date()


def _as_bar_session_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return _as_date(value)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    offset = (current.weekday() - weekday) % 7
    return current - timedelta(days=offset)


def _easter_date(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def _us_market_holidays(year: int) -> frozenset[date]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1),  # New Year's Day
        _observed_fixed_holiday(year + 1, 1, 1),  # Next New Year's Day can be observed in December.
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _easter_date(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed_holiday(year, 6, 19),  # Juneteenth
        _observed_fixed_holiday(year, 7, 4),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed_holiday(year, 12, 25),  # Christmas
    }
    return frozenset(holidays)


def is_market_day(value: Any, market: str = "US") -> bool:
    if market.upper() != "US":
        raise ValueError(f"Unsupported market calendar: {market}")
    day = _as_date(value)
    return day.weekday() < 5 and day not in _us_market_holidays(day.year)


def get_previous_market_day(value: Any, market: str = "US") -> date:
    current = _as_date(value) - timedelta(days=1)
    while not is_market_day(current, market=market):
        current -= timedelta(days=1)
    return current


def get_latest_expected_completed_session(now: Any = None, market: str = "US") -> date:
    if now is None:
        current = datetime.now(US_EASTERN)
    elif isinstance(now, datetime):
        current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        current = current.astimezone(US_EASTERN)
    else:
        current = datetime.combine(_as_date(now), time(23, 59), tzinfo=US_EASTERN)

    current_day = current.date()
    if is_market_day(current_day, market=market) and current.time() >= MARKET_CLOSE_BUFFER:
        return current_day
    return get_previous_market_day(current_day, market=market)


def _market_session_lag(bar_day: date, expected_day: date, market: str = "US") -> int:
    if bar_day >= expected_day:
        return 0
    lag = 0
    current = expected_day
    while current > bar_day:
        lag += 1
        current = get_previous_market_day(current, market=market)
    return lag


def is_latest_completed_session(bar_timestamp: Any, now: Any = None, market: str = "US") -> dict:
    try:
        bar_day = _as_bar_session_date(bar_timestamp)
        expected_day = get_latest_expected_completed_session(now=now, market=market)
        session_lag = _market_session_lag(bar_day, expected_day, market=market)
        return {
            "ok": True,
            "market": market.upper(),
            "bar_date": bar_day.isoformat(),
            "latest_expected_completed_session": expected_day.isoformat(),
            "is_latest_completed_session": bar_day == expected_day,
            "is_stale_by_session": bar_day < expected_day,
            "market_session_lag": session_lag,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "market": market.upper(),
            "bar_date": None,
            "latest_expected_completed_session": None,
            "is_latest_completed_session": False,
            "is_stale_by_session": True,
            "market_session_lag": None,
            "error": str(exc),
        }
