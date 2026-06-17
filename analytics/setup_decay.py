from __future__ import annotations

from collections import defaultdict
from typing import Any


DEFAULT_SETUP_DECAY_CONFIG = {
    "minimum_sample_size": 8,
    "decay_sample_size": 10,
    "disabled_sample_size": 15,
    "decay_expectancy_threshold_r": 0.0,
    "disabled_expectancy_threshold_r": -0.35,
    "low_win_rate_threshold": 30.0,
    "recent_window": 20,
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _setup_name(trade: dict) -> str:
    return str(trade.get("setup_type") or trade.get("strategy") or "unknown")


def _closed_for_setup(setup_name: str, trade_history: list[dict]) -> list[dict]:
    return [
        trade for trade in trade_history or []
        if isinstance(trade, dict)
        and _setup_name(trade) == setup_name
        and str(trade.get("outcome", "")).lower() in {"win", "loss", "expired", "manual_review"}
    ]


def _r_multiple(trade: dict) -> float | None:
    raw = _safe_float(trade.get("r_multiple") or trade.get("realized_r"))
    if raw is not None:
        return raw
    outcome = str(trade.get("outcome", "")).lower()
    if outcome == "win":
        risk_reward = _safe_float(trade.get("risk_reward"))
        return risk_reward if risk_reward is not None else 1.0
    if outcome == "loss":
        return -1.0
    if outcome == "expired":
        return 0.0
    realized_return = _safe_float(trade.get("realized_return") or trade.get("latest_realized_return"))
    if realized_return is not None:
        return realized_return / 100.0
    return None


def _avg_hold_days(trades: list[dict]) -> float | None:
    values = [_safe_float(trade.get("holding_period_days")) for trade in trades]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def evaluate_setup_decay(
    setup_name: str,
    trade_history: list[dict],
    config: dict | None = None,
) -> dict:
    cfg = dict(DEFAULT_SETUP_DECAY_CONFIG)
    if isinstance(config, dict):
        cfg.update(config)

    name = str(setup_name or "unknown")
    closed = _closed_for_setup(name, trade_history)
    recent = closed[-int(cfg["recent_window"]):]
    sample_size = len(recent)
    outcomes = [str(trade.get("outcome", "")).lower() for trade in recent if str(trade.get("outcome", "")).lower() in {"win", "loss"}]
    wins = outcomes.count("win")
    win_rate = round((wins / len(outcomes)) * 100.0, 2) if outcomes else None
    r_values = [value for value in (_r_multiple(trade) for trade in recent) if value is not None]
    expectancy = round(sum(r_values) / len(r_values), 4) if r_values else None
    reasons: list[str] = []
    warnings: list[str] = []
    status = "healthy"

    if sample_size < cfg["minimum_sample_size"]:
        status = "watch"
        reasons.append("Not enough closed trades to judge setup health.")
    elif sample_size >= cfg["disabled_sample_size"] and expectancy is not None and expectancy < cfg["disabled_expectancy_threshold_r"]:
        status = "disabled"
        reasons.append(f"Recent expectancy {expectancy}R is below disabled threshold.")
    elif sample_size >= cfg["decay_sample_size"] and expectancy is not None and expectancy < cfg["decay_expectancy_threshold_r"]:
        status = "decaying"
        reasons.append(f"Recent expectancy {expectancy}R is below break-even.")

    if win_rate is not None and win_rate < cfg["low_win_rate_threshold"] and expectancy is not None and expectancy < 0:
        if sample_size >= cfg["disabled_sample_size"] and expectancy < cfg["disabled_expectancy_threshold_r"]:
            status = "disabled"
        elif status == "healthy":
            status = "decaying"
        reasons.append(f"Recent win rate {win_rate}% is weak with negative expectancy.")

    if status in {"watch", "decaying", "disabled"}:
        warnings.append(f"Setup {name} status is {status}.")

    return {
        "ok": True,
        "setup_name": name,
        "status": status,
        "sample_size": sample_size,
        "recent_win_rate": win_rate,
        "recent_expectancy_r": expectancy,
        "avg_hold_days": _avg_hold_days(recent),
        "reasons": reasons,
        "warnings": warnings,
    }


def evaluate_all_setup_decay(
    trade_history: list[dict],
    config: dict | None = None,
) -> dict:
    setup_names: set[str] = set()
    for trade in trade_history or []:
        if isinstance(trade, dict):
            setup_names.add(_setup_name(trade))
    results = {
        setup: evaluate_setup_decay(setup, trade_history, config=config)
        for setup in sorted(setup_names)
    }
    counts = defaultdict(int)
    for result in results.values():
        counts[result["status"]] += 1
    return {
        "ok": True,
        "setups": results,
        "counts": dict(counts),
        "warnings": [
            warning
            for result in results.values()
            for warning in result.get("warnings", [])
        ],
    }

