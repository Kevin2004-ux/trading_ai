from ideas import build_assistant_trade_response, build_best_available_ideas


TOP_LEVEL_KEYS = {
    "ok",
    "response_type",
    "paper_trading_only",
    "ranking_status",
    "research_status",
    "research_sources",
    "research_warnings",
    "requested_instrument",
    "market_state",
    "top_stocks",
    "top_options",
    "option_underlying_watchlist",
    "option_discovery_status",
    "option_data_missing",
    "paper_eligible",
    "research_only",
    "blocked",
    "why_no_final_trades",
    "data_missing",
    "system_issues",
    "next_steps",
    "scan_summary",
    "refinement",
}


STOCK_KEYS = {
    "ticker",
    "asset_type",
    "status",
    "rank",
    "opportunity_score",
    "engine_score",
    "setup",
    "direction",
    "entry_price",
    "target_price",
    "stop_loss",
    "risk_reward",
    "why_ranked",
    "key_risks",
    "failed_constraints",
    "confirmation_needed",
    "data_quality",
    "research_status",
    "research_summary",
    "current_catalysts",
    "current_risks",
    "research_uncertainties",
    "research_source_ids",
}


OPTION_KEYS = {
    "ticker",
    "asset_type",
    "status",
    "rank",
    "opportunity_score",
    "engine_score",
    "strategy",
    "option_contract",
    "option_type",
    "strike",
    "expiration",
    "days_to_expiration",
    "bid",
    "ask",
    "mid",
    "spread_percent",
    "open_interest",
    "volume",
    "implied_volatility",
    "iv_rank",
    "delta",
    "breakeven_price",
    "why_ranked",
    "key_risks",
    "missing_requirements",
    "underlying_status",
    "underlying_opportunity_score",
    "research_status",
    "research_summary",
    "current_catalysts",
    "current_risks",
    "research_uncertainties",
    "research_source_ids",
}


def _stock(
    ticker,
    status="watchlist",
    score=80,
    risk_reward=2.2,
    failed_constraints=None,
    rejection_reason=None,
):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "strategy": "swing_trade",
        "setup_type": "momentum_pullback",
        "recommendation_status": status,
        "current_price": 100.0,
        "entry_price": 101.0,
        "target_price": 115.0,
        "stop_loss": 95.0,
        "risk_reward": risk_reward,
        "score": score,
        "why_this_profile_matched": ["Momentum profile matched."],
        "relative_strength_context": {"relative_strength_label": "outperforming"},
        "technical_confirmation_summary": {"status": "confirmed"},
        "failed_constraints": failed_constraints or [],
        "rejection_reason": rejection_reason,
        "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
    }


def _option(status="research_only", missing=None):
    return {
        "underlying_ticker": "AAPL",
        "asset_type": "option",
        "strategy_type": "long_call",
        "option_contract": "AAPL260717C00100000",
        "expiration": "2026-07-17",
        "days_to_expiration": 26,
        "option_type": "call",
        "strike": 100.0,
        "recommendation_status": status,
        "score": 77,
        "bid": 4.0 if not missing else None,
        "ask": 4.2 if not missing else None,
        "mid": 4.1 if not missing else None,
        "spread_percent": 0.0488 if not missing else None,
        "volume": 500,
        "open_interest": 2000,
        "implied_volatility": 0.3 if not missing else None,
        "iv_context": {"implied_volatility": 0.3, "iv_rank": 42} if not missing else {},
        "greeks_monitoring": {"delta": 0.55, "greeks_quality": "usable"} if not missing else {},
        "delta": 0.55 if not missing else None,
        "breakeven_price": 104.1 if not missing else None,
        "underlying_status": "watchlist",
        "underlying_opportunity_score": 82,
        "option_trade_risk": {"status": status, "fill_quality": "acceptable" if not missing else None},
        "reason": "Call structure is useful for research.",
    }


def _scanner_failure(ticker="BAD"):
    reason = "IBKR historical bars unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "recommendation_status": "rejected",
        "current_price": None,
        "entry_price": None,
        "target_price": None,
        "stop_loss": None,
        "score": 0,
        "technical_snapshot": {},
        "failed_constraints": ["scanner_error"],
        "rejection_reason": reason,
        "data_quality": {"ok": False, "quality_label": "unavailable", "errors": [reason], "warnings": []},
    }


def test_available_stock_result_normalizes_all_stock_statuses_in_order():
    trading_result = {
        "ok": True,
        "universe": "mega_cap",
        "decision_result": {"final_recommendations": [_stock("NVDA", status="recommendable", score=95, risk_reward=3.0)]},
        "selection_result": {
            "watchlist_alternatives": [_stock("MSFT", status="watchlist", score=84, risk_reward=2.3)],
            "rejected_candidates": [
                _stock(
                    "TSLA",
                    status="rejected",
                    score=72,
                    risk_reward=1.8,
                    failed_constraints=["minimum_relative_volume"],
                    rejection_reason="Relative volume too low for final recommendation.",
                )
            ],
        },
        "summary": {"tickers_scanned": 3, "profiles_run": ["momentum"]},
    }
    best_ideas = build_best_available_ideas(trading_result, config={"include_options": False})

    response = build_assistant_trade_response(best_ideas, trading_result, requested_instrument="stocks")

    assert set(response) == TOP_LEVEL_KEYS
    assert response["ranking_status"] == "available"
    assert [row["ticker"] for row in response["top_stocks"]] == ["NVDA", "MSFT", "TSLA"]
    assert [row["status"] for row in response["top_stocks"]] == ["paper_eligible", "watchlist", "blocked"]
    assert set(response["top_stocks"][0]) == STOCK_KEYS
    assert isinstance(response["top_stocks"][0]["why_ranked"], list)
    assert isinstance(response["top_stocks"][2]["confirmation_needed"], list)
    assert "Relative volume must improve to the required threshold." in response["top_stocks"][2]["confirmation_needed"]


def test_available_option_result_preserves_research_only_and_blocked_requirements():
    trading_result = {
        "ok": True,
        "option_research": {
            "best_option_candidates": [_option(status="research_only")],
            "rejected_option_candidates": [{**_option(status="blocked", missing=True), "option_contract": "AAPL260717P00095000"}],
        },
        "decision_result": {"final_recommendations": []},
    }
    best_ideas = build_best_available_ideas(trading_result, config={"include_options": True})

    response = build_assistant_trade_response(best_ideas, trading_result, requested_instrument="options")

    assert response["ranking_status"] == "available"
    assert response["top_stocks"] == []
    assert len(response["top_options"]) == 2
    assert set(response["top_options"][0]) == OPTION_KEYS
    assert response["top_options"][0]["status"] == "research_only"
    blocked = [row for row in response["top_options"] if row["status"] == "blocked"][0]
    assert blocked["missing_requirements"]
    assert "bid/ask" in blocked["missing_requirements"]


def test_option_underlying_watchlist_is_returned_when_exact_contracts_unavailable():
    best_ideas = build_best_available_ideas(
        {
            "ok": True,
            "option_discovery": {
                "status": "partial",
                "options_final_eligibility": False,
                "underlying_watchlist": [
                    {
                        "ticker": "AAPL",
                        "option_bias": "bullish",
                        "underlying_opportunity_score": 82,
                        "underlying_status": "watchlist",
                        "why_watch": ["AAPL is a strong underlying near-miss."],
                        "required_before_contract_ranking": ["bid/ask", "IV", "Greeks"],
                    }
                ],
                "missing_requirements": ["bid/ask", "IV", "Greeks"],
            },
            "decision_result": {"final_recommendations": []},
        },
        config={"include_options": True},
    )

    response = build_assistant_trade_response(best_ideas, {}, requested_instrument="options")

    assert response["top_options"] == []
    assert response["option_underlying_watchlist"][0]["ticker"] == "AAPL"
    assert response["option_discovery_status"] == "partial"
    assert "bid/ask" in response["option_data_missing"]


def test_ranking_unavailable_has_empty_top_lists_and_provider_state():
    trading_result = {
        "ok": True,
        "scan_result": {"rejected_candidates": [_scanner_failure("AAPL"), _scanner_failure("MSFT")]},
        "decision_result": {"final_recommendations": []},
    }
    best_ideas = build_best_available_ideas(trading_result, config={"include_options": False})

    response = build_assistant_trade_response(best_ideas, trading_result, requested_instrument="stocks")

    assert response["ranking_status"] == "unavailable"
    assert response["top_stocks"] == []
    assert response["top_options"] == []
    assert response["market_state"]["provider_status"] == "unavailable"
    assert any("IBKR/TWS is not reachable" in item for item in response["system_issues"])


def test_mixed_result_excludes_provider_failure_and_keeps_legitimate_rows():
    trading_result = {
        "ok": True,
        "scan_result": {
            "rejected_candidates": [
                _scanner_failure("BAD"),
                _stock("AMD", status="rejected", score=74, failed_constraints=["price_above_sma_20"], rejection_reason="Price below SMA 20."),
            ]
        },
        "decision_result": {"final_recommendations": []},
    }
    best_ideas = build_best_available_ideas(trading_result, config={"include_options": False})

    response = build_assistant_trade_response(best_ideas, trading_result, requested_instrument="stocks")

    assert response["ranking_status"] == "available"
    assert [row["ticker"] for row in response["top_stocks"]] == ["AMD"]
    assert "Price must reclaim SMA 20." in response["top_stocks"][0]["confirmation_needed"]
    assert any("IBKR/TWS is not reachable" in item for item in response["system_issues"])


def test_stable_contract_exists_for_empty_best_ideas():
    response = build_assistant_trade_response({}, {}, requested_instrument="auto")

    assert set(response) == TOP_LEVEL_KEYS
    assert response["response_type"] == "trade_ideas"
    assert response["top_stocks"] == []
    assert response["top_options"] == []
    assert response["scan_summary"]["profiles_run"] == []
