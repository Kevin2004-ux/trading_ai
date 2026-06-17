from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any


CLOSED_OUTCOMES = {"win", "loss", "expired", "manual_review", "closed"}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _direction(trade: dict) -> str:
    return str(trade.get("direction") or "long").lower()


def calculate_r_multiple(trade: dict) -> float | None:
    for key in ("r_multiple", "realized_r", "outcome_r"):
        value = _safe_float(trade.get(key))
        if value is not None:
            return value

    outcome = str(trade.get("outcome") or trade.get("latest_outcome") or "").lower()
    entry = _safe_float(trade.get("entry_price"))
    stop = _safe_float(trade.get("stop_loss"))
    exit_price = _safe_float(trade.get("exit_price") or trade.get("latest_exit_price"))
    if entry is not None and stop is not None and exit_price is not None:
        risk = abs(entry - stop)
        if risk > 0:
            pnl = exit_price - entry if _direction(trade) != "short" else entry - exit_price
            return pnl / risk

    realized_return = _safe_float(trade.get("realized_return") or trade.get("latest_realized_return"))
    risk_pct = None
    if entry is not None and stop is not None and entry:
        risk_pct = abs(entry - stop) / abs(entry) * 100.0
    if realized_return is not None and risk_pct and risk_pct > 0:
        return realized_return / risk_pct

    if outcome == "win":
        return _safe_float(trade.get("risk_reward")) or 1.0
    if outcome == "loss":
        return -1.0
    if outcome == "expired":
        return 0.0
    return None


def _hold_days(trade: dict) -> float | None:
    explicit = _safe_float(trade.get("holding_period_days") or trade.get("hold_days"))
    if explicit is not None:
        return explicit
    created = _parse_dt(trade.get("created_at"))
    closed = _parse_dt(trade.get("closed_at") or trade.get("latest_outcome_created_at"))
    if created and closed:
        return max((closed - created).total_seconds() / 86400.0, 0.0)
    return None


def _drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _sharpe_like(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = _mean(values)
    if avg is None:
        return None
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    std = variance ** 0.5
    if std == 0:
        return None
    return avg / std * (len(values) ** 0.5)


def analyze_paper_trade_performance(
    trades: list[dict],
    config: dict | None = None,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    rows = [trade for trade in trades or [] if isinstance(trade, dict)]
    closed = [
        trade for trade in rows
        if str(trade.get("outcome") or trade.get("latest_outcome") or trade.get("status") or "").lower() in CLOSED_OUTCOMES
    ]
    open_trades = [trade for trade in rows if trade not in closed]
    r_pairs = [(trade, calculate_r_multiple(trade)) for trade in closed]
    r_pairs = [(trade, value) for trade, value in r_pairs if value is not None]
    r_values = [value for _, value in r_pairs]
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    closed_decided = len(wins) + len(losses)
    win_rate = (len(wins) / closed_decided * 100.0) if closed_decided else None
    expectancy = _mean(r_values)
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = None
    if gross_losses > 0:
        profit_factor = gross_wins / gross_losses
    elif gross_wins > 0:
        profit_factor = gross_wins

    min_sample = int((config or {}).get("min_closed_trades", 5))
    if len(r_values) < min_sample:
        warnings.append(f"Insufficient closed paper-trade sample: {len(r_values)} closed trades with R data; minimum suggested sample is {min_sample}.")
    if open_trades:
        warnings.append(f"{len(open_trades)} open paper trade(s) are summarized separately and excluded from win-rate/expectancy.")

    best_pair = max(r_pairs, key=lambda pair: pair[1], default=(None, None))
    worst_pair = min(r_pairs, key=lambda pair: pair[1], default=(None, None))
    hold_values = [value for value in (_hold_days(trade) for trade in closed) if value is not None]

    return {
        "ok": True,
        "trade_count": len(rows),
        "closed_trade_count": len(closed),
        "open_trade_count": len(open_trades),
        "win_rate": _round(win_rate, 2),
        "avg_win_r": _round(_mean(wins)),
        "avg_loss_r": _round(_mean(losses)),
        "expectancy_r": _round(expectancy),
        "profit_factor": _round(profit_factor),
        "max_drawdown_r": _round(_drawdown(r_values)),
        "sharpe_like_score": _round(_sharpe_like(r_values)),
        "median_hold_days": _round(float(median(hold_values)), 2) if hold_values else None,
        "best_trade": {**best_pair[0], "r_multiple": _round(best_pair[1])} if isinstance(best_pair[0], dict) else None,
        "worst_trade": {**worst_pair[0], "r_multiple": _round(worst_pair[1])} if isinstance(worst_pair[0], dict) else None,
        "open_trade_summary": {
            "count": len(open_trades),
            "tickers": [trade.get("ticker") for trade in open_trades if trade.get("ticker")],
        },
        "warnings": warnings,
        "errors": errors,
    }
