from __future__ import annotations

from typing import Any


DEFAULT_CIRCUIT_CONFIG = {
    "caution_loss_streak": 3,
    "reduced_risk_loss_streak": 5,
    "blocked_loss_streak": 7,
    "recent_win_rate_window": 10,
    "recent_win_rate_reduced_threshold": 30.0,
    "expectancy_window": 20,
    "expectancy_reduced_threshold_r": -0.25,
    "drawdown_caution_percent": -5.0,
    "drawdown_reduced_percent": -8.0,
    "drawdown_blocked_percent": -12.0,
    "reduced_risk_multiplier": 0.50,
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _closed_trades(trade_history: list[dict]) -> list[dict]:
    return [
        trade for trade in trade_history or []
        if isinstance(trade, dict)
        and str(trade.get("outcome", "")).lower() in {"win", "loss", "expired", "manual_review"}
    ]


def _trade_r_multiple(trade: dict) -> float | None:
    raw_r = _safe_float(trade.get("r_multiple") or trade.get("realized_r"))
    if raw_r is not None:
        return raw_r
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


def _rolling_loss_streak(closed: list[dict]) -> int:
    streak = 0
    for trade in reversed(closed):
        if str(trade.get("outcome", "")).lower() == "loss":
            streak += 1
        else:
            break
    return streak


def _recent_win_rate(closed: list[dict], window: int) -> float | None:
    recent = closed[-window:]
    outcomes = [str(trade.get("outcome", "")).lower() for trade in recent if str(trade.get("outcome", "")).lower() in {"win", "loss"}]
    if not outcomes:
        return None
    wins = outcomes.count("win")
    return round((wins / len(outcomes)) * 100.0, 2)


def _recent_expectancy(closed: list[dict], window: int) -> float | None:
    values = [value for value in (_trade_r_multiple(trade) for trade in closed[-window:]) if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _realized_drawdown_percent(closed: list[dict]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in closed:
        realized_return = _safe_float(trade.get("realized_return") or trade.get("latest_realized_return"))
        if realized_return is None:
            r_value = _trade_r_multiple(trade)
            realized_return = (r_value or 0.0) * 1.0
        equity += realized_return
        peak = max(peak, equity)
        drawdown = equity - peak
        max_drawdown = min(max_drawdown, drawdown)
    return round(max_drawdown, 4)


def evaluate_drawdown_circuit_breaker(
    trade_history: list[dict],
    open_trades: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    del open_trades
    cfg = dict(DEFAULT_CIRCUIT_CONFIG)
    if isinstance(config, dict):
        cfg.update(config)

    closed = _closed_trades(trade_history)
    loss_streak = _rolling_loss_streak(closed)
    win_rate = _recent_win_rate(closed, int(cfg["recent_win_rate_window"]))
    expectancy = _recent_expectancy(closed, int(cfg["expectancy_window"]))
    drawdown = _realized_drawdown_percent(closed)
    reasons: list[str] = []
    warnings: list[str] = []
    status_rank = 0

    def raise_status(rank: int, reason: str) -> None:
        nonlocal status_rank
        status_rank = max(status_rank, rank)
        reasons.append(reason)

    if loss_streak >= cfg["blocked_loss_streak"]:
        raise_status(3, f"{loss_streak} consecutive closed losses reached the blocked threshold.")
    elif loss_streak >= cfg["reduced_risk_loss_streak"]:
        raise_status(2, f"{loss_streak} consecutive closed losses reached the reduced-risk threshold.")
    elif loss_streak >= cfg["caution_loss_streak"]:
        raise_status(1, f"{loss_streak} consecutive closed losses reached the caution threshold.")

    if win_rate is not None and len(closed) >= cfg["recent_win_rate_window"] and win_rate < cfg["recent_win_rate_reduced_threshold"]:
        raise_status(2, f"Rolling {cfg['recent_win_rate_window']}-trade win rate is below {cfg['recent_win_rate_reduced_threshold']}%.")

    if expectancy is not None and len(closed) >= cfg["expectancy_window"] and expectancy < cfg["expectancy_reduced_threshold_r"]:
        raise_status(2, f"Rolling {cfg['expectancy_window']}-trade expectancy is below {cfg['expectancy_reduced_threshold_r']}R.")

    if drawdown <= cfg["drawdown_blocked_percent"]:
        raise_status(3, f"Realized drawdown {drawdown}% breached blocked threshold.")
    elif drawdown <= cfg["drawdown_reduced_percent"]:
        raise_status(2, f"Realized drawdown {drawdown}% breached reduced-risk threshold.")
    elif drawdown <= cfg["drawdown_caution_percent"]:
        raise_status(1, f"Realized drawdown {drawdown}% breached caution threshold.")

    status_by_rank = {
        0: "normal",
        1: "caution",
        2: "reduced_risk",
        3: "blocked",
    }
    circuit_status = status_by_rank[status_rank]
    if circuit_status == "caution":
        warnings.append("Circuit breaker is in caution mode; new paper trades are allowed with warning.")
    elif circuit_status == "reduced_risk":
        warnings.append("Circuit breaker reduced risk; position sizing should use the risk multiplier.")
    elif circuit_status == "blocked":
        warnings.append("Circuit breaker blocked new paper trades.")

    return {
        "ok": True,
        "circuit_status": circuit_status,
        "realized_drawdown_percent": drawdown,
        "rolling_loss_streak": loss_streak,
        "recent_win_rate": win_rate,
        "recent_expectancy_r": expectancy,
        "max_allowed_risk_multiplier": 0.0 if circuit_status == "blocked" else cfg["reduced_risk_multiplier"] if circuit_status == "reduced_risk" else 1.0,
        "new_trades_allowed": circuit_status != "blocked",
        "reasons": reasons,
        "warnings": warnings,
    }

