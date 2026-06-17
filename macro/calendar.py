from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


EVENT_IMPORTANCE = {
    "FOMC": "critical",
    "CPI": "critical",
    "PCE": "high",
    "JOBS": "high",
    "PPI": "high",
    "GDP": "medium",
    "TREASURY_AUCTION": "medium",
    "OPEX": "medium",
    "EARNINGS_CLUSTER": "medium",
    "OTHER": "low",
}


def _parse_date(value: str | None, default: date) -> date:
    if not value:
        return default
    return datetime.fromisoformat(str(value)).date()


def _event(event_id: str, event_date: date, event_type: str, title: str, time: str | None = "08:30", notes: str = "") -> dict:
    importance = EVENT_IMPORTANCE.get(event_type, "low")
    start = datetime.combine(event_date, datetime.min.time()).replace(hour=0, minute=0)
    end = start + timedelta(days=1, hours=23, minutes=59)
    if event_type in {"FOMC", "CPI", "PCE", "JOBS", "PPI"}:
        start = start - timedelta(days=1)
        end = end + timedelta(days=1)
    return {
        "event_id": event_id,
        "date": event_date.isoformat(),
        "time": time,
        "timezone": "America/New_York",
        "event_type": event_type,
        "title": title,
        "importance": importance,
        "risk_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "notes": notes,
    }


def _third_friday(year: int, month: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != 4:
        current += timedelta(days=1)
    return current + timedelta(days=14)


def _static_events(start: date, end: date) -> list[dict]:
    events: list[dict] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        year = current.year
        month = current.month
        events.extend(
            [
                _event(f"cpi-{year}-{month:02d}", date(year, month, min(12, 28)), "CPI", "Consumer Price Index", "08:30", "Static CPI placeholder for risk controls."),
                _event(f"fomc-{year}-{month:02d}", date(year, month, min(18, 28)), "FOMC", "FOMC Rate Decision", "14:00", "Static FOMC placeholder for risk controls."),
                _event(f"jobs-{year}-{month:02d}", date(year, month, min(5, 28)), "JOBS", "Employment Situation", "08:30", "Static jobs report placeholder."),
                _event(f"opex-{year}-{month:02d}", _third_friday(year, month), "OPEX", "Monthly Options Expiration", None, "Static monthly OPEX marker."),
            ]
        )
        if month in {1, 4, 7, 10}:
            events.append(_event(f"earnings-cluster-{year}-{month:02d}", date(year, month, min(20, 28)), "EARNINGS_CLUSTER", "Earnings Cluster", None, "Static earnings season risk marker."))
        if month == 12:
            current = date(year + 1, 1, 1)
        else:
            current = date(year, month + 1, 1)
    return [event for event in events if start <= date.fromisoformat(event["date"]) <= end]


def classify_macro_event_importance(event: dict) -> dict:
    event_type = str((event or {}).get("event_type", "OTHER")).upper()
    importance = str((event or {}).get("importance") or EVENT_IMPORTANCE.get(event_type, "low")).lower()
    if event_type in {"FOMC", "CPI"}:
        importance = "critical"
    elif event_type in {"PCE", "JOBS", "PPI"} and importance not in {"critical", "high"}:
        importance = "high"
    elif event_type in {"OPEX", "EARNINGS_CLUSTER", "GDP", "TREASURY_AUCTION"} and importance == "low":
        importance = "medium"
    risk_score = {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(importance, 1)
    return {
        "ok": True,
        "event_id": event.get("event_id") if isinstance(event, dict) else None,
        "event_type": event_type,
        "importance": importance,
        "risk_score": risk_score,
    }


def get_macro_calendar(
    start_date: str | None = None,
    end_date: str | None = None,
    source: str = "static",
) -> dict:
    today = date.today()
    start = _parse_date(start_date, today)
    end = _parse_date(end_date, start + timedelta(days=14))
    if end < start:
        return {
            "ok": False,
            "source": source,
            "events": [],
            "error": "end_date must be on or after start_date.",
        }
    if source != "static":
        return {
            "ok": False,
            "source": source,
            "events": [],
            "error": "Only the offline static macro calendar source is implemented.",
        }
    events = _static_events(start, end)
    return {
        "ok": True,
        "source": source,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "events": events,
        "count": len(events),
        "error": None,
    }

