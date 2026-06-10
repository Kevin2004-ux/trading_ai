from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from realtime.market_data import get_historical_bars, normalize_ohlcv
from tracking.trade_logger import (
    get_open_recommendations,
    log_trade_outcome,
    update_recommendation_status,
)


DEFAULT_STOCK_HOLDING_PERIOD_DAYS = 14
TERMINAL_OUTCOMES = {"win", "loss", "expired", "manual_review"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any, fallback: datetime | None = None) -> datetime | None:
    if value is None:
        return fallback
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return fallback

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _result(
    ok: bool,
    recommendation: dict,
    *,
    status: str,
    outcome: str,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    closed_at: str | None = None,
    realized_return: float | None = None,
    max_gain: float | None = None,
    max_drawdown: float | None = None,
    grading_data: dict | None = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": ok,
        "recommendation_id": recommendation.get("id"),
        "ticker": recommendation.get("ticker"),
        "status": status,
        "outcome": outcome,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "closed_at": closed_at,
        "realized_return": realized_return,
        "max_gain": max_gain,
        "max_drawdown": max_drawdown,
        "grading_data": grading_data or {},
        "error": error,
    }


def _filter_bars_since_entry(bars: list[dict], created_at: datetime, as_of_dt: datetime) -> pd.DataFrame:
    normalized = normalize_ohlcv(bars)
    if normalized.empty:
        return normalized

    filtered = normalized[
        (normalized["timestamp"] >= pd.Timestamp(created_at))
        & (normalized["timestamp"] <= pd.Timestamp(as_of_dt))
    ].copy()
    return filtered.sort_values("timestamp").reset_index(drop=True)


def _last_known_price(recommendation: dict, bars_df: pd.DataFrame, current_snapshot: dict | None = None) -> float | None:
    if not bars_df.empty:
        close_value = _safe_float(bars_df.iloc[-1]["close"])
        if close_value is not None:
            return close_value

    snapshot_data = current_snapshot.get("data", {}) if isinstance(current_snapshot, dict) else {}
    if isinstance(snapshot_data, dict):
        quote = snapshot_data.get("quote", {})
        technical_snapshot = snapshot_data.get("technical_snapshot", {})
        last_price = _safe_float(quote.get("last_price")) if isinstance(quote, dict) else None
        if last_price is not None:
            return last_price
        current_price = _safe_float(technical_snapshot.get("current_price")) if isinstance(technical_snapshot, dict) else None
        if current_price is not None:
            return current_price
    return None


def _compute_path_metrics(recommendation: dict, bars_df: pd.DataFrame) -> tuple[float | None, float | None]:
    if bars_df.empty:
        return None, None

    entry_price = _safe_float(recommendation.get("entry_price"))
    if entry_price in (None, 0):
        return None, None

    direction = str(recommendation.get("direction", "")).lower()
    highs = bars_df["high"].astype(float)
    lows = bars_df["low"].astype(float)

    if direction == "long":
        max_gain = ((highs.max() - entry_price) / entry_price)
        max_drawdown = ((lows.min() - entry_price) / entry_price)
        return max_gain, max_drawdown
    if direction == "short":
        max_gain = ((entry_price - lows.min()) / entry_price)
        max_drawdown = ((entry_price - highs.max()) / entry_price)
        return max_gain, max_drawdown
    return None, None


def determine_stock_outcome(
    recommendation: dict,
    bars: list[dict],
    as_of: str | None = None,
) -> dict:
    if not recommendation.get("id"):
        return _result(False, recommendation, status="open", outcome="open", error="Recommendation id is missing.")
    if not recommendation.get("ticker"):
        return _result(False, recommendation, status="open", outcome="open", error="Ticker is missing.")

    entry_price = _safe_float(recommendation.get("entry_price"))
    target_price = _safe_float(recommendation.get("target_price"))
    stop_loss = _safe_float(recommendation.get("stop_loss"))
    if entry_price is None or target_price is None or stop_loss is None:
        return _result(
            False,
            recommendation,
            status="open",
            outcome="open",
            error="Recommendation must include entry_price, target_price, and stop_loss.",
        )

    direction = str(recommendation.get("direction", "")).lower()
    if direction not in {"long", "short"}:
        return _result(False, recommendation, status="open", outcome="open", error="Unsupported trade direction.")

    created_at = _parse_timestamp(recommendation.get("created_at"))
    if created_at is None:
        return _result(False, recommendation, status="open", outcome="open", error="Recommendation created_at is missing or invalid.")

    as_of_dt = _parse_timestamp(as_of, fallback=_now_utc())
    if as_of_dt is None:
        as_of_dt = _now_utc()

    bars_df = _filter_bars_since_entry(bars, created_at, as_of_dt)
    if bars_df.empty:
        return _result(False, recommendation, status="open", outcome="open", error="No valid bars available after recommendation timestamp.")

    max_gain, max_drawdown = _compute_path_metrics(recommendation, bars_df)
    holding_period_days = recommendation.get("holding_period_days")
    holding_period_days = int(holding_period_days) if holding_period_days is not None else DEFAULT_STOCK_HOLDING_PERIOD_DAYS
    expiry_dt = created_at + timedelta(days=holding_period_days)

    for _, row in bars_df.iterrows():
        high = _safe_float(row["high"])
        low = _safe_float(row["low"])
        close = _safe_float(row["close"])
        bar_ts = _parse_timestamp(row["timestamp"])
        if high is None or low is None or close is None or bar_ts is None:
            continue

        if direction == "long":
            target_hit = high >= target_price
            stop_hit = low <= stop_loss
            exit_price = target_price if target_hit else stop_loss if stop_hit else None
        else:
            target_hit = low <= target_price
            stop_hit = high >= stop_loss
            exit_price = target_price if target_hit else stop_loss if stop_hit else None

        if target_hit and stop_hit:
            return _result(
                True,
                recommendation,
                status="manual_review",
                outcome="manual_review",
                exit_price=close,
                exit_reason="target_and_stop_hit_same_bar",
                closed_at=bar_ts.isoformat(),
                realized_return=None,
                max_gain=max_gain,
                max_drawdown=max_drawdown,
                grading_data={
                    "grading_method": "stock_bar_path",
                    "bar_timestamp": bar_ts.isoformat(),
                    "same_bar_ambiguity": True,
                    "holding_period_days": holding_period_days,
                },
            )

        if target_hit or stop_hit:
            outcome = "win" if target_hit else "loss"
            if direction == "long":
                realized_return = ((exit_price - entry_price) / entry_price) if exit_price is not None else None
            else:
                realized_return = ((entry_price - exit_price) / entry_price) if exit_price is not None else None

            return _result(
                True,
                recommendation,
                status="closed",
                outcome=outcome,
                exit_price=exit_price,
                exit_reason="target_hit" if target_hit else "stop_loss_hit",
                closed_at=bar_ts.isoformat(),
                realized_return=realized_return,
                max_gain=max_gain,
                max_drawdown=max_drawdown,
                grading_data={
                    "grading_method": "stock_bar_path",
                    "bar_timestamp": bar_ts.isoformat(),
                    "holding_period_days": holding_period_days,
                },
            )

    latest_close = _safe_float(bars_df.iloc[-1]["close"])
    if as_of_dt >= expiry_dt:
        realized_return = None
        if latest_close is not None:
            if direction == "long":
                realized_return = ((latest_close - entry_price) / entry_price)
            else:
                realized_return = ((entry_price - latest_close) / entry_price)

        return _result(
            True,
            recommendation,
            status="closed",
            outcome="expired",
            exit_price=latest_close,
            exit_reason="holding_period_expired",
            closed_at=as_of_dt.isoformat(),
            realized_return=realized_return,
            max_gain=max_gain,
            max_drawdown=max_drawdown,
            grading_data={
                "grading_method": "stock_bar_path",
                "holding_period_days": holding_period_days,
                "expiry_timestamp": expiry_dt.isoformat(),
            },
        )

    current_realized_return = None
    if latest_close is not None:
        if direction == "long":
            current_realized_return = ((latest_close - entry_price) / entry_price)
        else:
            current_realized_return = ((entry_price - latest_close) / entry_price)

    return _result(
        True,
        recommendation,
        status="open",
        outcome="open",
        exit_price=latest_close,
        exit_reason="still_open_within_holding_period",
        closed_at=None,
        realized_return=current_realized_return,
        max_gain=max_gain,
        max_drawdown=max_drawdown,
        grading_data={
            "grading_method": "stock_bar_path",
            "holding_period_days": holding_period_days,
            "expiry_timestamp": expiry_dt.isoformat(),
        },
    )


def determine_option_outcome(
    recommendation: dict,
    bars: list[dict] | None = None,
    as_of: str | None = None,
) -> dict:
    as_of_dt = _parse_timestamp(as_of, fallback=_now_utc()) or _now_utc()
    expiration = _parse_timestamp(recommendation.get("expiration"))

    if bars:
        stock_like = determine_stock_outcome(recommendation, bars, as_of=as_of)
        stock_like["grading_data"] = {
            **stock_like.get("grading_data", {}),
            "grading_method": "option_underlying_proxy",
            "option_pricing_used": False,
        }
        return stock_like

    if expiration is not None and as_of_dt > expiration:
        return _result(
            True,
            recommendation,
            status="manual_review",
            outcome="manual_review",
            exit_price=None,
            exit_reason="option_expired_without_option_price_history",
            closed_at=as_of_dt.isoformat(),
            realized_return=None,
            max_gain=None,
            max_drawdown=None,
            grading_data={
                "grading_method": "option_placeholder",
                "option_pricing_used": False,
                "expiration_timestamp": expiration.isoformat(),
            },
        )

    return _result(
        True,
        recommendation,
        status="open",
        outcome="open",
        exit_price=None,
        exit_reason="option_requires_additional_pricing_history",
        closed_at=None,
        realized_return=None,
        max_gain=None,
        max_drawdown=None,
        grading_data={
            "grading_method": "option_placeholder",
            "option_pricing_used": False,
        },
    )


def grade_recommendation(
    recommendation: dict,
    historical_bars: list[dict] | None = None,
    current_snapshot: dict | None = None,
    as_of: str | None = None,
    db_path: str = "strategy_library.db",
) -> dict:
    if not isinstance(recommendation, dict):
        return {
            "ok": False,
            "recommendation_id": None,
            "ticker": None,
            "status": "open",
            "outcome": "open",
            "exit_price": None,
            "exit_reason": None,
            "closed_at": None,
            "realized_return": None,
            "max_gain": None,
            "max_drawdown": None,
            "grading_data": {},
            "error": "Recommendation must be a dictionary.",
        }

    ticker = recommendation.get("ticker")
    if not ticker:
        return _result(False, recommendation, status="open", outcome="open", error="Recommendation ticker is missing.")

    asset_type = str(recommendation.get("asset_type", "stock")).lower()
    if historical_bars is None:
        bars_result = get_historical_bars(ticker, lookback_days=180)
        if bars_result.get("ok"):
            historical_bars = bars_result.get("data", {}).get("bars", [])
        else:
            return _result(False, recommendation, status="open", outcome="open", error=bars_result.get("error", "Failed to load historical bars."))

    if asset_type in {"stock", "equity"}:
        result = determine_stock_outcome(recommendation, historical_bars or [], as_of=as_of)
    elif asset_type == "option":
        result = determine_option_outcome(recommendation, bars=historical_bars, as_of=as_of)
    else:
        return _result(False, recommendation, status="open", outcome="open", error="Unsupported asset_type for outcome grading.")

    if result["ok"] and result["exit_price"] is None and current_snapshot is not None:
        fallback_exit = _last_known_price(recommendation, _filter_bars_since_entry(historical_bars or [], _parse_timestamp(recommendation.get("created_at")) or _now_utc(), _parse_timestamp(as_of, fallback=_now_utc()) or _now_utc()), current_snapshot)
        if fallback_exit is not None:
            result["exit_price"] = fallback_exit

    return result


def update_open_recommendations(
    db_path: str = "strategy_library.db",
    lookback_days: int = 180,
    as_of: str | None = None,
) -> dict:
    open_recommendations = get_open_recommendations(db_path=db_path)
    if isinstance(open_recommendations, dict) and open_recommendations.get("ok") is False:
        return {
            "ok": False,
            "checked": 0,
            "updated": 0,
            "still_open": 0,
            "manual_review": 0,
            "errors": [open_recommendations],
            "results": [],
        }

    recommendations = open_recommendations if isinstance(open_recommendations, list) else []
    results = []
    errors = []
    updated = 0
    still_open = 0
    manual_review = 0

    for recommendation in recommendations:
        ticker = recommendation.get("ticker")
        if not ticker:
            error = {"recommendation_id": recommendation.get("id"), "error": "Open recommendation is missing ticker."}
            errors.append(error)
            continue

        bars_result = get_historical_bars(ticker, lookback_days=lookback_days)
        if not bars_result.get("ok"):
            errors.append(
                {
                    "recommendation_id": recommendation.get("id"),
                    "ticker": ticker,
                    "error": bars_result.get("error", "Failed to fetch historical bars."),
                }
            )
            continue

        historical_bars = bars_result.get("data", {}).get("bars", [])
        current_snapshot = None
        grade_result = grade_recommendation(
            recommendation,
            historical_bars=historical_bars,
            current_snapshot=current_snapshot,
            as_of=as_of,
            db_path=db_path,
        )
        results.append(grade_result)

        if not grade_result.get("ok"):
            errors.append(
                {
                    "recommendation_id": recommendation.get("id"),
                    "ticker": ticker,
                    "error": grade_result.get("error", "Grading failed."),
                }
            )
            continue

        outcome = grade_result.get("outcome")
        if outcome == "open":
            still_open += 1
            continue

        log_outcome = log_trade_outcome(
            recommendation_id=recommendation.get("id"),
            outcome=outcome,
            exit_price=grade_result.get("exit_price"),
            exit_reason=grade_result.get("exit_reason"),
            realized_return=grade_result.get("realized_return"),
            max_gain=grade_result.get("max_gain"),
            max_drawdown=grade_result.get("max_drawdown"),
            grading_data_json=grade_result.get("grading_data"),
            created_at=grade_result.get("closed_at"),
            db_path=db_path,
        )
        if log_outcome.get("ok") is False:
            errors.append(
                {
                    "recommendation_id": recommendation.get("id"),
                    "ticker": ticker,
                    "error": log_outcome.get("error", "Failed to log trade outcome."),
                }
            )
            continue

        status_to_store = "closed" if outcome == "manual_review" else outcome
        status_update = update_recommendation_status(
            recommendation.get("id"),
            status=status_to_store,
            outcome=outcome,
            exit_price=grade_result.get("exit_price"),
            notes=grade_result.get("exit_reason"),
            db_path=db_path,
        )
        if status_update.get("ok") is False:
            errors.append(
                {
                    "recommendation_id": recommendation.get("id"),
                    "ticker": ticker,
                    "error": status_update.get("error", "Failed to update recommendation status."),
                }
            )
            continue

        updated += 1
        if outcome == "manual_review":
            manual_review += 1

    return {
        "ok": len(errors) == 0,
        "checked": len(recommendations),
        "updated": updated,
        "still_open": still_open,
        "manual_review": manual_review,
        "errors": errors,
        "results": results,
    }
