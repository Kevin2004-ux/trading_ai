from __future__ import annotations

from datetime import datetime, timezone

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

    return {
        "ok": bool(evaluation.get("ok")),
        "ticker": ticker,
        "underlying_candidate": stock_candidate,
        "best_option_candidates": evaluation.get("best_option_candidates", []),
        "rejected_option_candidates": evaluation.get("rejected_option_candidates", []),
        "watchlist_option_candidates": evaluation.get("watchlist_option_candidates", []),
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
        errors.extend(result.get("errors", []))

    return {
        "ok": len(selected_stock_candidates or []) > 0 and any(result.get("ok") for result in results),
        "timestamp": _now_iso(),
        "results": results,
        "best_option_candidates": best_option_candidates,
        "watchlist_option_candidates": watchlist_option_candidates,
        "rejected_option_candidates": rejected_option_candidates,
        "summary": {
            "tickers_evaluated": len(selected_stock_candidates or []),
            "contracts_passed": len(best_option_candidates),
            "message": "Weekly option research completed." if results else "No stock candidates were provided for option research.",
        },
        "errors": errors,
    }
