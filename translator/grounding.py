from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _trade_key_facts(trade: dict) -> dict:
    return {
        "ticker": _ticker(trade.get("ticker")),
        "entry_price": _safe_float(trade.get("entry_price")),
        "target_price": _safe_float(trade.get("target_price")),
        "stop_loss": _safe_float(trade.get("stop_loss")),
        "risk_reward": _safe_float(trade.get("risk_reward")),
        "estimated_fill_price": _safe_float((trade.get("paper_fill") or {}).get("estimated_fill_price")) if isinstance(trade.get("paper_fill"), dict) else None,
        "preferred_option_contract": trade.get("preferred_option_contract"),
        "preferred_instrument": trade.get("preferred_instrument", "stock"),
        "option_strategy_status": (trade.get("selected_option_strategy") or {}).get("status") if isinstance(trade.get("selected_option_strategy"), dict) else None,
    }


def extract_grounding_facts(trading_brain_result: dict) -> dict:
    result = trading_brain_result if isinstance(trading_brain_result, dict) else {}
    decision = result.get("decision_result") if isinstance(result.get("decision_result"), dict) else {}
    selection = result.get("selection_result") if isinstance(result.get("selection_result"), dict) else {}
    scan = result.get("scan_result") if isinstance(result.get("scan_result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}

    final_trades = _as_list(decision.get("final_recommendations"))
    logged_entries = _as_list(decision.get("logged_recommendations"))
    watchlist = _as_list(selection.get("watchlist_alternatives")) + _as_list(scan.get("watchlist_candidates"))
    rejected = _as_list(selection.get("rejected_candidates")) + _as_list(scan.get("rejected_candidates")) + _as_list(decision.get("not_selected"))

    selected_tickers = {_ticker(trade.get("ticker")) for trade in final_trades if isinstance(trade, dict)}
    logged_tickers = {
        _ticker(((entry.get("data") or {}).get("recommendation") or {}).get("ticker"))
        for entry in logged_entries
        if isinstance(entry, dict)
    }
    watchlist_tickers = {_ticker(item.get("ticker")) for item in watchlist if isinstance(item, dict)}
    rejected_tickers = {
        _ticker(item.get("ticker") or ((item.get("candidate") or {}).get("ticker") if isinstance(item.get("candidate"), dict) else None))
        for item in rejected
        if isinstance(item, dict)
    }
    allowed_tickers = {ticker for ticker in selected_tickers | logged_tickers | watchlist_tickers | rejected_tickers if ticker}

    data_quality = (scan.get("data_quality_summary") or summary.get("data_quality") or {}) if isinstance(scan.get("data_quality_summary") or summary.get("data_quality"), dict) else {}
    scan_execution = result.get("scan_execution_summary") or summary.get("scan_execution_summary") or scan.get("scan_execution_summary") or {}
    risk_warnings: list[str] = []
    for source in (
        result.get("macro_risk"),
        result.get("market_regime"),
        result.get("concentration_summary"),
        result.get("technical_confirmation_summary"),
        result.get("filing_sentiment_summary"),
        result.get("research_risk_summary"),
        result.get("startup_readiness"),
        summary,
    ):
        if isinstance(source, dict):
            risk_warnings.extend(str(item) for item in source.get("warnings", []) if item)
            risk_warnings.extend(str(item) for item in source.get("errors", []) if item)

    data_quality_warnings = []
    if isinstance(data_quality, dict):
        data_quality_warnings.extend(str(item) for item in data_quality.get("warnings", []) if item)
        data_quality_warnings.extend(str(item) for item in data_quality.get("errors", []) if item)
    if isinstance(scan_execution, dict):
        data_quality_warnings.extend(str(item) for item in scan_execution.get("warnings", []) if item)

    trade_facts = {
        _ticker(trade.get("ticker")): _trade_key_facts(trade)
        for trade in final_trades
        if isinstance(trade, dict) and _ticker(trade.get("ticker"))
    }
    option_risk_summary = result.get("option_risk_summary") or summary.get("option_risk_summary")
    option_strategy_summary = result.get("option_strategy_summary") or summary.get("option_strategy_summary")
    options_included = bool(result.get("option_research") or option_risk_summary or option_strategy_summary)
    blocked_or_research_only = False
    for option_summary in (option_risk_summary, option_strategy_summary):
        if isinstance(option_summary, dict) and (
            int(option_summary.get("blocked_count") or 0) > 0
            or int(option_summary.get("research_only_count") or 0) > 0
        ):
            blocked_or_research_only = True
    options_status = {
        "options_included": options_included,
        "option_risk_summary": option_risk_summary,
        "option_strategy_summary": option_strategy_summary,
        "blocked_or_research_only": blocked_or_research_only,
    }
    for trade in final_trades:
        if isinstance(trade, dict) and str(trade.get("preferred_instrument", "")).lower() == "option":
            status = ((trade.get("selected_option_strategy") or {}).get("status") if isinstance(trade.get("selected_option_strategy"), dict) else None)
            options_status["blocked_or_research_only"] = status != "paper_eligible"

    return {
        "allowed_tickers": sorted(allowed_tickers),
        "selected_tickers": sorted(ticker for ticker in selected_tickers if ticker),
        "logged_tickers": sorted(ticker for ticker in logged_tickers if ticker),
        "watchlist_tickers": sorted(ticker for ticker in watchlist_tickers if ticker),
        "rejected_tickers": sorted(ticker for ticker in rejected_tickers if ticker),
        "trade_facts": trade_facts,
        "selected_count": int(summary.get("selected_count", len(selected_tickers)) or 0),
        "logged_count": int(summary.get("logged_count", len(logged_tickers)) or 0),
        "options_status": options_status,
        "data_quality_warnings": data_quality_warnings,
        "risk_warnings": risk_warnings,
        "scan_execution": scan_execution,
        "market_context": {
            "macro_risk": result.get("macro_risk"),
            "market_regime": result.get("market_regime"),
            "circuit_breaker": summary.get("circuit_breaker"),
            "concentration_summary": result.get("concentration_summary"),
        },
    }


def build_allowed_fact_index(trading_brain_result: dict) -> dict:
    facts = extract_grounding_facts(trading_brain_result)
    return {
        "tickers": set(facts["allowed_tickers"]),
        "selected_tickers": set(facts["selected_tickers"]),
        "logged_tickers": set(facts["logged_tickers"]),
        "trade_facts": facts["trade_facts"],
        "facts": facts,
    }


def check_claim_against_grounding(
    claim: dict,
    grounding_facts: dict,
    config: dict | None = None,
) -> dict:
    ticker = _ticker(claim.get("ticker"))
    if ticker and ticker not in set(grounding_facts.get("allowed_tickers", [])):
        return {"ok": False, "code": "fabricated_ticker", "message": f"{ticker} is not present in deterministic results."}
    facts = (grounding_facts.get("trade_facts") or {}).get(ticker, {}) if ticker else {}
    tolerance = _safe_float((config or {}).get("price_tolerance")) or 0.01
    for field in ("entry_price", "target_price", "stop_loss", "risk_reward"):
        claimed = _safe_float(claim.get(field))
        expected = _safe_float(facts.get(field))
        if claimed is not None and expected is not None and abs(claimed - expected) > tolerance:
            return {"ok": False, "code": f"mismatched_{field}", "message": f"{field} for {ticker} does not match deterministic result."}
    return {"ok": True, "code": "pass", "message": "Claim is grounded."}
