from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from paper.paper_trader import (
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)


PAPER_MODE = "paper_trading"
PAPER_WARNING = "Paper trading is simulated only. No live brokerage orders were placed."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_job_response(
    job_name: str,
    result_key: str,
    result: dict | None,
) -> dict:
    payload = result if isinstance(result, dict) else {}
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        errors = [str(errors)]
    error = payload.get("error")
    if error and not errors:
        errors = [str(error)]

    return {
        "ok": bool(payload.get("ok")),
        "job": job_name,
        "mode": PAPER_MODE,
        "timestamp": _now_iso(),
        result_key: payload,
        "warning": payload.get("warning") or PAPER_WARNING,
        "errors": errors,
    }


def _job_failure(job_name: str, result_key: str, message: str) -> dict:
    return {
        "ok": False,
        "job": job_name,
        "mode": PAPER_MODE,
        "timestamp": _now_iso(),
        result_key: None,
        "warning": PAPER_WARNING,
        "errors": [message],
    }


def run_weekly_paper_cycle_job(
    universe: str = "large_cap",
    max_tickers: int = 500,
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
    try:
        result = run_paper_trade_cycle(
            universe=universe,
            max_tickers=max_tickers,
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
            db_path=db_path,
        )
        return _build_job_response("weekly_paper_cycle", "paper_cycle", result)
    except Exception as exc:
        return _job_failure("weekly_paper_cycle", "paper_cycle", f"Weekly paper cycle job failed: {exc}")


def run_daily_paper_review_job(
    update_outcomes: bool = True,
    include_trade_reviews: bool = True,
    store_review_memory: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = review_paper_portfolio(
            update_outcomes=update_outcomes,
            include_trade_reviews=include_trade_reviews,
            store_review_memory=store_review_memory,
            db_path=db_path,
        )
        return _build_job_response("daily_paper_review", "paper_review", result)
    except Exception as exc:
        return _job_failure("daily_paper_review", "paper_review", f"Daily paper review job failed: {exc}")


def run_paper_summary_job(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_paper_trading_summary(db_path=db_path)
        return _build_job_response("paper_summary", "paper_summary", result)
    except Exception as exc:
        return _job_failure("paper_summary", "paper_summary", f"Paper summary job failed: {exc}")
