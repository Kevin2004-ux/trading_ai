from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agent.trading_brain import monitor_open_trades, run_weekly_trade_hunt
from journal.trade_journal import review_closed_trades
from tracking.trade_logger import init_trade_tracking_db


PAPER_MODE = "paper_trading"
TERMINAL_OUTCOMES = {"win", "loss", "expired", "manual_review"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deserialize_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_paper_trade(recommendation: dict) -> bool:
    if not isinstance(recommendation, dict):
        return False

    for payload_name in ("model_outputs_json", "data_snapshot_json"):
        payload = recommendation.get(payload_name)
        if isinstance(payload, dict):
            if payload.get("paper_trading") is True:
                return True
            if str(payload.get("execution_mode", "")).lower() == PAPER_MODE:
                return True
            if str(payload.get("mode", "")).lower() == PAPER_MODE:
                return True
    return False


def _load_paper_recommendations(db_path: str) -> list[dict]:
    init_result = init_trade_tracking_db(db_path=db_path)
    if not init_result.get("ok"):
        raise sqlite3.Error(init_result.get("error", "Failed to initialize trade tracking database."))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            WITH latest_outcomes AS (
                SELECT t1.*
                FROM trade_outcomes t1
                INNER JOIN (
                    SELECT recommendation_id, MAX(id) AS max_id
                    FROM trade_outcomes
                    GROUP BY recommendation_id
                ) t2
                ON t1.recommendation_id = t2.recommendation_id
                AND t1.id = t2.max_id
            )
            SELECT
                tr.*,
                lo.realized_return AS latest_realized_return
            FROM trade_recommendations tr
            LEFT JOIN latest_outcomes lo
                ON lo.recommendation_id = tr.id
            ORDER BY tr.created_at ASC, tr.id ASC
            """
        ).fetchall()

    recommendations: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("data_snapshot_json", "constraint_results_json", "model_outputs_json"):
            item[key] = _deserialize_json(item.get(key))
        if _is_paper_trade(item):
            recommendations.append(item)
    return recommendations


def _paper_open_trades(recommendations: list[dict]) -> list[dict]:
    return [
        recommendation
        for recommendation in recommendations
        if recommendation.get("closed_at") is None
        and str(recommendation.get("status", "open")).lower() not in TERMINAL_OUTCOMES
    ]


def _paper_closed_trades(recommendations: list[dict]) -> list[dict]:
    return [
        recommendation
        for recommendation in recommendations
        if str(recommendation.get("outcome", "")).lower() in TERMINAL_OUTCOMES
    ]


def _paper_win_loss_record(recommendations: list[dict]) -> dict:
    wins = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "win")
    losses = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "loss")
    expired = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "expired")
    open_count = sum(1 for recommendation in recommendations if recommendation.get("closed_at") is None and str(recommendation.get("status", "open")).lower() not in TERMINAL_OUTCOMES)
    closed = wins + losses
    return {
        "total_recommendations": len(recommendations),
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "open": open_count,
        "closed_trades": closed,
        "win_rate": round((wins / closed) * 100.0, 2) if closed else 0.0,
    }


def _realized_return(recommendation: dict) -> float | None:
    latest_realized_return = _safe_float(recommendation.get("latest_realized_return"))
    if latest_realized_return is not None:
        return latest_realized_return

    entry_price = _safe_float(recommendation.get("entry_price"))
    exit_price = _safe_float(recommendation.get("exit_price"))
    if entry_price in (None, 0) or exit_price is None:
        return None
    realized_return = ((exit_price - entry_price) / entry_price) * 100.0
    if str(recommendation.get("direction", "")).lower() == "short":
        realized_return = ((entry_price - exit_price) / entry_price) * 100.0
    return realized_return


def _paper_strategy_performance(recommendations: list[dict]) -> dict:
    overall = {
        "total_recommendations": len(recommendations),
        "average_score": None,
        "average_confidence": None,
        "average_risk_reward": None,
    }
    if recommendations:
        score_values = [_safe_float(item.get("score")) for item in recommendations if _safe_float(item.get("score")) is not None]
        confidence_values = [_safe_float(item.get("confidence")) for item in recommendations if _safe_float(item.get("confidence")) is not None]
        rr_values = [_safe_float(item.get("risk_reward")) for item in recommendations if _safe_float(item.get("risk_reward")) is not None]
        if score_values:
            overall["average_score"] = sum(score_values) / len(score_values)
        if confidence_values:
            overall["average_confidence"] = sum(confidence_values) / len(confidence_values)
        if rr_values:
            overall["average_risk_reward"] = sum(rr_values) / len(rr_values)

    def grouped(rows: list[dict], field_name: str, default: str) -> list[dict]:
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            key = row.get(field_name) or default
            buckets.setdefault(str(key), []).append(row)

        output: list[dict] = []
        for key, bucket in buckets.items():
            return_values = [value for value in (_realized_return(item) for item in bucket) if value is not None]
            wins = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "win")
            losses = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "loss")
            expired = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "expired")
            output.append(
                {
                    field_name: key,
                    "total_recommendations": len(bucket),
                    "wins": wins,
                    "losses": losses,
                    "expired": expired,
                    "average_score": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("score")) for item in bucket) if value is not None]) else None,
                    "average_confidence": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("confidence")) for item in bucket) if value is not None]) else None,
                    "average_risk_reward": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("risk_reward")) for item in bucket) if value is not None]) else None,
                    "average_realized_return": (sum(return_values) / len(return_values)) if return_values else None,
                }
            )
        output.sort(key=lambda item: item["total_recommendations"], reverse=True)
        return output

    return {
        "overall": overall,
        "by_strategy": grouped(recommendations, "strategy", "unknown"),
        "by_setup_type": grouped(recommendations, "setup_type", "unspecified"),
    }


def run_paper_trade_cycle(
    universe: str = "large_cap",
    max_tickers: int = 500,
    profiles: list[str] | None = None,
    max_trades: int = 5,
    min_trades: int = 2,
    include_catalysts: bool = True,
    include_market_regime: bool = True,
    include_relative_strength: bool = True,
    include_options: bool = False,
    prefer_options: bool = False,
    max_option_contracts_per_trade: int = 3,
    include_portfolio_risk: bool = True,
    include_position_sizing: bool = True,
    include_memory_context: bool = True,
    store_memory: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    db_path: str = "strategy_library.db",
) -> dict:
    trade_hunt = run_weekly_trade_hunt(
        universe=universe,
        max_tickers=max_tickers,
        profiles=profiles,
        max_trades=max_trades,
        min_trades=min_trades,
        include_catalysts=include_catalysts,
        include_market_regime=include_market_regime,
        include_relative_strength=include_relative_strength,
        include_options=include_options,
        prefer_options=prefer_options,
        max_option_contracts_per_trade=max_option_contracts_per_trade,
        include_portfolio_risk=include_portfolio_risk,
        include_position_sizing=include_position_sizing,
        include_memory_context=include_memory_context,
        store_memory=store_memory,
        account_size=account_size,
        risk_mode=risk_mode,
        auto_log=True,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": PAPER_MODE, "mode": PAPER_MODE},
    )

    decision_result = trade_hunt.get("decision_result", {}) if isinstance(trade_hunt, dict) else {}
    logged_entries = decision_result.get("logged_recommendations", []) if isinstance(decision_result, dict) else []
    paper_trades_logged = [
        entry.get("data", {}).get("recommendation")
        for entry in logged_entries
        if isinstance(entry, dict) and isinstance(entry.get("data"), dict) and entry.get("data", {}).get("recommendation")
    ]

    selected_count = len(decision_result.get("final_recommendations", [])) if isinstance(decision_result, dict) else 0
    logged_count = len(paper_trades_logged)
    message = (
        "Paper trading cycle completed. Recommendations were logged as simulated trades only."
        if trade_hunt.get("ok")
        else "Paper trading cycle failed before simulated trades could be logged."
    )

    return {
        "ok": bool(trade_hunt.get("ok")),
        "mode": PAPER_MODE,
        "timestamp": _now_iso(),
        "trade_hunt": trade_hunt,
        "paper_trades_logged": paper_trades_logged,
        "summary": {
            "selected_count": selected_count,
            "logged_count": logged_count,
            "message": message,
        },
        "warning": "Paper trading is simulated only. No live brokerage orders were placed.",
        "errors": trade_hunt.get("errors", []) if isinstance(trade_hunt, dict) else ["Paper trading cycle failed."],
    }


def review_paper_portfolio(
    update_outcomes: bool = True,
    include_trade_reviews: bool = True,
    store_review_memory: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        monitoring_result = monitor_open_trades(update_outcomes=update_outcomes, db_path=db_path)
        trade_review_summary = None
        if include_trade_reviews:
            trade_review_summary = review_closed_trades(
                db_path=db_path,
                store_memory=store_review_memory,
            )

        paper_recommendations = _load_paper_recommendations(db_path)
        paper_ids = {recommendation["id"] for recommendation in paper_recommendations}
        update_result = monitoring_result.get("update_result") if isinstance(monitoring_result, dict) else None
        recent_results = update_result.get("results", []) if isinstance(update_result, dict) else []
        recently_closed_paper_trades = [
            result
            for result in recent_results
            if isinstance(result, dict) and result.get("recommendation_id") in paper_ids and str(result.get("outcome", "")).lower() in TERMINAL_OUTCOMES
        ]

        summary = get_paper_trading_summary(db_path=db_path)
        return {
            "ok": bool(monitoring_result.get("ok")) and bool(summary.get("ok")),
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "monitoring_result": monitoring_result,
            "open_paper_trades": summary.get("open_paper_trades", []),
            "recently_closed_paper_trades": recently_closed_paper_trades,
            "win_loss_record": summary.get("win_loss_record"),
            "strategy_performance": summary.get("strategy_performance"),
            "trade_review_summary": trade_review_summary,
            "warning": "Paper trading performance is simulated only and is not live brokerage P/L.",
            "errors": list(monitoring_result.get("errors", []))
            + list(summary.get("errors", []))
            + list(trade_review_summary.get("errors", []) if isinstance(trade_review_summary, dict) else []),
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "monitoring_result": None,
            "open_paper_trades": [],
            "recently_closed_paper_trades": [],
            "win_loss_record": None,
            "strategy_performance": None,
            "trade_review_summary": None,
            "warning": "Paper trading performance is simulated only and is not live brokerage P/L.",
            "errors": [str(exc)],
        }


def get_paper_trading_summary(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        recommendations = _load_paper_recommendations(db_path)
        open_paper_trades = _paper_open_trades(recommendations)
        closed_paper_trades = _paper_closed_trades(recommendations)
        win_loss_record = _paper_win_loss_record(recommendations)
        strategy_performance = _paper_strategy_performance(recommendations)
        setup_types = strategy_performance.get("by_setup_type", [])
        ranked_setups = [setup for setup in setup_types if setup.get("average_realized_return") is not None]
        ranked_setups.sort(key=lambda item: item["average_realized_return"], reverse=True)
        best_setup_type = ranked_setups[0]["setup_type"] if ranked_setups else None
        worst_setup_type = ranked_setups[-1]["setup_type"] if ranked_setups else None

        return {
            "ok": True,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "open_paper_trades": open_paper_trades,
            "closed_paper_trades_count": len(closed_paper_trades),
            "win_loss_record": win_loss_record,
            "strategy_performance": strategy_performance,
            "best_setup_type": best_setup_type,
            "worst_setup_type": worst_setup_type,
            "warning": "This is simulated paper-trading performance, not live brokerage P/L.",
            "errors": [],
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "open_paper_trades": [],
            "closed_paper_trades_count": 0,
            "win_loss_record": None,
            "strategy_performance": None,
            "best_setup_type": None,
            "worst_setup_type": None,
            "warning": "This is simulated paper-trading performance, not live brokerage P/L.",
            "errors": [str(exc)],
        }
