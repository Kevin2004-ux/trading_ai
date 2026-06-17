from __future__ import annotations

from datetime import datetime, timezone

from options.strategy_builder import build_option_strategy_candidates
from realtime.options_chain import get_options_chain
from realtime.options_eval import evaluate_option_chain_for_trade


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def scan_options_for_stock_candidate(
    stock_candidate: dict,
    max_contracts: int = 5,
) -> dict:
    ticker = str(stock_candidate.get("ticker", "")).upper()
    if not ticker:
        return {
            "ok": False,
            "ticker": "",
            "underlying_candidate": stock_candidate,
            "best_option_candidates": [],
            "rejected_option_candidates": [],
            "option_strategy_candidates": [],
            "selected_option_strategy": None,
            "option_strategy_summary": {"strategy_count": 0, "paper_eligible_count": 0, "research_only_count": 0, "blocked_count": 0},
            "summary": {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": "Ticker is required for option-chain research.",
            },
            "errors": ["Ticker is required for option-chain research."],
        }

    chain_result = get_options_chain(ticker)
    if not chain_result.get("ok"):
        return {
            "ok": False,
            "ticker": ticker,
            "underlying_candidate": stock_candidate,
            "best_option_candidates": [],
            "rejected_option_candidates": [],
            "option_strategy_candidates": [],
            "selected_option_strategy": None,
            "option_strategy_summary": {"strategy_count": 0, "paper_eligible_count": 0, "research_only_count": 0, "blocked_count": 0},
            "summary": {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": chain_result.get("error", "Options-chain data is unavailable."),
            },
            "errors": [chain_result.get("error", "Options-chain data is unavailable.")],
        }

    option_chain = chain_result.get("data", {}).get("contracts", [])
    evaluation = evaluate_option_chain_for_trade(
        stock_candidate,
        option_chain,
        strategy="long_call",
        max_contracts=max_contracts,
    )
    strategy_build = build_option_strategy_candidates(
        ticker,
        {
            **stock_candidate,
            "ticker": ticker,
            "option_bias": "bullish" if str(stock_candidate.get("direction", "long")).lower() == "long" else "bearish",
        },
        option_chain,
    )

    return {
        "ok": bool(evaluation.get("ok")),
        "ticker": ticker,
        "underlying_candidate": stock_candidate,
        "best_option_candidates": evaluation.get("best_option_candidates", []),
        "rejected_option_candidates": evaluation.get("rejected_option_candidates", []),
        "watchlist_option_candidates": evaluation.get("watchlist_option_candidates", []),
        "option_risk_summary": evaluation.get("option_risk_summary", {}),
        "option_strategy_candidates": strategy_build.get("strategies", []),
        "selected_option_strategy": strategy_build.get("selected_strategy"),
        "option_strategy_summary": strategy_build.get("summary", {}),
        "summary": evaluation.get(
            "summary",
            {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": "Option research did not return a summary.",
            },
        ),
        "errors": evaluation.get("errors", []),
    }


def scan_options_for_weekly_selection(
    selected_stock_candidates: list[dict],
    max_contracts_per_ticker: int = 3,
) -> dict:
    results = []
    best_option_candidates = []
    rejected_option_candidates = []
    watchlist_option_candidates = []
    option_strategy_candidates = []
    selected_option_strategies = []
    errors = []

    for stock_candidate in selected_stock_candidates or []:
        result = scan_options_for_stock_candidate(
            stock_candidate,
            max_contracts=max_contracts_per_ticker,
        )
        results.append(result)
        best_option_candidates.extend(result.get("best_option_candidates", []))
        rejected_option_candidates.extend(result.get("rejected_option_candidates", []))
        watchlist_option_candidates.extend(result.get("watchlist_option_candidates", []))
        option_strategy_candidates.extend(result.get("option_strategy_candidates", []))
        if result.get("selected_option_strategy"):
            selected_option_strategies.append(result.get("selected_option_strategy"))
        errors.extend(result.get("errors", []))
    risk_summaries = [result.get("option_risk_summary", {}) for result in results if isinstance(result.get("option_risk_summary"), dict)]
    strategy_summaries = [result.get("option_strategy_summary", {}) for result in results if isinstance(result.get("option_strategy_summary"), dict)]

    return {
        "ok": len(selected_stock_candidates or []) > 0 and any(result.get("ok") for result in results),
        "timestamp": _now_iso(),
        "results": results,
        "best_option_candidates": best_option_candidates,
        "watchlist_option_candidates": watchlist_option_candidates,
        "rejected_option_candidates": rejected_option_candidates,
        "option_strategy_candidates": option_strategy_candidates,
        "selected_option_strategies": selected_option_strategies,
        "summary": {
            "tickers_evaluated": len(selected_stock_candidates or []),
            "contracts_passed": len(best_option_candidates),
            "option_risk_summary": {
                "evaluated_count": sum(int(item.get("evaluated_count", 0) or 0) for item in risk_summaries),
                "approved_count": sum(int(item.get("approved_count", 0) or 0) for item in risk_summaries),
                "research_only_count": sum(int(item.get("research_only_count", 0) or 0) for item in risk_summaries),
                "blocked_count": sum(int(item.get("blocked_count", 0) or 0) for item in risk_summaries),
            },
            "option_strategy_summary": {
                "strategy_count": sum(int(item.get("strategy_count", 0) or 0) for item in strategy_summaries),
                "paper_eligible_count": sum(int(item.get("paper_eligible_count", 0) or 0) for item in strategy_summaries),
                "research_only_count": sum(int(item.get("research_only_count", 0) or 0) for item in strategy_summaries),
                "blocked_count": sum(int(item.get("blocked_count", 0) or 0) for item in strategy_summaries),
            },
            "message": "Weekly option research completed." if results else "No stock candidates were provided for option research.",
        },
        "errors": errors,
    }
