from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Any

from macro.calendar import classify_macro_event_importance, get_macro_calendar


LEVEL_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _bool_env(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _config(config: dict | None = None) -> dict:
    cfg = {
        "enabled": _bool_env("MACRO_RISK_ENABLED", True),
        "block_critical_events": _bool_env("MACRO_BLOCK_CRITICAL_EVENTS", True),
        "high_risk_multiplier": _float_env("MACRO_HIGH_RISK_MULTIPLIER", 0.50),
        "medium_risk_multiplier": _float_env("MACRO_MEDIUM_RISK_MULTIPLIER", 0.75),
        "critical_risk_multiplier": _float_env("MACRO_CRITICAL_RISK_MULTIPLIER", 0.25),
        "upcoming_window_days": 7,
    }
    if isinstance(config, dict):
        cfg.update(config)
    return cfg


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _event_window(event: dict) -> tuple[datetime | None, datetime | None]:
    window = event.get("risk_window", {}) if isinstance(event, dict) else {}
    if not isinstance(window, dict):
        return None, None
    return _parse_dt(window.get("start")), _parse_dt(window.get("end"))


def _max_level(events: list[dict]) -> str:
    level = "low"
    for event in events:
        importance = classify_macro_event_importance(event).get("importance", "low")
        if LEVEL_RANK.get(importance, 1) > LEVEL_RANK.get(level, 1):
            level = importance
    return level


def _multiplier(level: str, cfg: dict) -> float:
    if level == "critical":
        return float(cfg["critical_risk_multiplier"])
    if level == "high":
        return float(cfg["high_risk_multiplier"])
    if level == "medium":
        return float(cfg["medium_risk_multiplier"])
    return 1.0


def evaluate_macro_risk(
    as_of: str | None = None,
    calendar: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    now = _parse_dt(as_of) or datetime.now()
    if not cfg["enabled"]:
        return {
            "ok": True,
            "macro_risk_level": "low",
            "risk_multiplier": 1.0,
            "new_trades_allowed": True,
            "event_window_active": False,
            "active_events": [],
            "upcoming_events": [],
            "warnings": ["Macro risk controls are disabled."],
            "reasons": [],
        }

    if calendar is None:
        cal = get_macro_calendar(now.date().isoformat(), (now.date() + timedelta(days=int(cfg["upcoming_window_days"]))).isoformat())
        calendar = cal.get("events", []) if cal.get("ok") else []

    active_events: list[dict] = []
    upcoming_events: list[dict] = []
    for event in calendar or []:
        if not isinstance(event, dict):
            continue
        start, end = _event_window(event)
        event_date = _parse_dt(event.get("date"))
        if start and end and start <= now <= end:
            active_events.append(event)
        elif event_date and now <= event_date <= now + timedelta(days=int(cfg["upcoming_window_days"])):
            upcoming_events.append(event)

    if active_events:
        risk_level = _max_level(active_events)
    elif upcoming_events:
        upcoming_level = _max_level(upcoming_events)
        risk_level = "medium" if upcoming_level in {"high", "critical"} else upcoming_level
    else:
        risk_level = "low"

    if any(event.get("event_type") == "OPEX" for event in active_events + upcoming_events) and LEVEL_RANK[risk_level] < LEVEL_RANK["medium"]:
        risk_level = "medium"
    if any(event.get("event_type") == "EARNINGS_CLUSTER" for event in active_events) and LEVEL_RANK[risk_level] < LEVEL_RANK["medium"]:
        risk_level = "medium"

    risk_multiplier = _multiplier(risk_level, cfg)
    new_trades_allowed = not (risk_level == "critical" and bool(cfg["block_critical_events"]))
    reasons = []
    warnings = []
    if active_events:
        reasons.append(f"{len(active_events)} macro risk window(s) active.")
    if upcoming_events:
        reasons.append(f"{len(upcoming_events)} macro event(s) upcoming.")
    if not new_trades_allowed:
        warnings.append("Critical macro event window blocks new trades.")
    elif risk_multiplier < 1.0:
        warnings.append(f"Macro risk reduced position sizing multiplier to {risk_multiplier}.")

    return {
        "ok": True,
        "macro_risk_level": risk_level,
        "risk_multiplier": risk_multiplier,
        "new_trades_allowed": new_trades_allowed,
        "event_window_active": bool(active_events),
        "active_events": active_events,
        "upcoming_events": upcoming_events,
        "warnings": warnings,
        "reasons": reasons,
    }

