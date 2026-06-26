from ideas import build_best_available_ideas, format_best_ideas_response


def _scanner_failure_candidate(ticker="AAPL", reason=None):
    reason = reason or "IBKR historical bars unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "recommendation_status": "rejected",
        "current_price": None,
        "entry_price": None,
        "target_price": None,
        "stop_loss": None,
        "score": 0,
        "technical_snapshot": {},
        "failed_constraints": ["scanner_error"],
        "rejection_reason": reason,
        "data_quality": {
            "ok": False,
            "quality_label": "unavailable",
            "errors": [reason],
            "warnings": [],
        },
    }


def _legitimate_rejected_stock(ticker="TSLA"):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "recommendation_status": "rejected",
        "current_price": 180.0,
        "entry_price": 181.0,
        "target_price": 195.0,
        "stop_loss": 174.0,
        "risk_reward": 2.0,
        "score": 72,
        "technical_snapshot": {
            "current_price": 180.0,
            "sma_20": 178.0,
            "sma_50": 170.0,
            "rsi_14": 58.0,
            "relative_volume": 0.8,
        },
        "failed_constraints": ["relative_volume_too_low"],
        "rejection_reason": "Relative volume too low for final recommendation.",
        "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
    }


def _sample_result():
    return {
        "ok": True,
        "decision_result": {
            "final_recommendations": [],
            "not_selected": [
                {
                    "ticker": "MSFT",
                    "reason": "Exceeded max_trades.",
                    "candidate": {
                        "ticker": "MSFT",
                        "asset_type": "stock",
                        "recommendation_status": "watchlist",
                        "score": 82,
                        "risk_reward": 2.4,
                        "rejection_reason": "Not selected by final portfolio constraints.",
                        "relative_strength_context": {"relative_strength_label": "outperforming"},
                    },
                }
            ],
        },
        "selection_result": {
            "watchlist_alternatives": [
                {
                    "ticker": "AAPL",
                    "asset_type": "stock",
                    "recommendation_status": "watchlist",
                    "score": 78,
                    "risk_reward": 2.1,
                    "why_this_profile_matched": ["Momentum profile matched."],
                    "relative_strength_context": {"relative_strength_label": "market_leader"},
                }
            ],
            "rejected_candidates": [
                {
                    "ticker": "TSLA",
                    "asset_type": "stock",
                    "recommendation_status": "rejected",
                    "score": 74,
                    "risk_reward": 2.8,
                    "rejection_reason": "Macro risk block.",
                }
            ],
        },
        "option_research": {
            "best_option_candidates": [
                {
                    "underlying_ticker": "AAPL",
                    "asset_type": "option",
                    "option_contract": "AAPL260717C00100000",
                    "option_type": "call",
                    "strike": 100.0,
                    "expiration": "2026-07-17",
                    "days_to_expiration": 25,
                    "recommendation_status": "watchlist",
                    "score": 76,
                    "bid": 4.0,
                    "ask": 4.2,
                    "mid": 4.1,
                    "spread_percent": 0.0488,
                    "volume": 500,
                    "open_interest": 2000,
                    "underlying_price": 98.0,
                    "risk_reward": 2.1,
                    "breakeven_price": 104.1,
                    "target_reaches_breakeven": True,
                    "iv_context": {"implied_volatility": 0.3, "iv_rank": 42},
                    "implied_volatility": 0.3,
                    "iv_rank": 42,
                    "greeks_monitoring": {"delta": 0.55, "greeks_quality": "usable"},
                    "delta": 0.55,
                    "option_trade_risk": {"status": "research_only", "fill_quality": "acceptable"},
                    "reason": "Call has clean structure but remains research-only.",
                }
            ],
            "rejected_option_candidates": [
                {
                    "underlying_ticker": "SPY",
                    "asset_type": "option",
                    "recommendation_status": "blocked",
                    "score": 70,
                    "option_trade_risk": {"status": "blocked", "block_reason": "Missing bid/ask."},
                }
            ],
        },
    }


def test_best_ideas_returns_useful_response_when_selected_count_zero():
    result = build_best_available_ideas(_sample_result())

    assert result["ok"] is True
    assert result["paper_eligible"] == []
    assert result["stock_watchlist"]
    assert result["why_no_final_trades"]
    assert "No final paper trades" in format_best_ideas_response(result)


def test_best_ideas_ranks_watchlist_and_rejected_candidates():
    result = build_best_available_ideas(_sample_result())

    assert result["stock_watchlist"][0]["ticker"] == "AAPL"
    assert any(item["ticker"] == "TSLA" for item in result["blocked_but_interesting"])


def test_option_blocked_chain_unavailable_appears_in_data_missing_and_system_issues():
    result = build_best_available_ideas(
        {
            "ok": False,
            "market_snapshot": {"error": "IBKR historical bars unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"},
            "options_chain": {"error": "IBKR options chain unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"},
            "strategy_result": {"errors": ["Option chain is empty or malformed."]},
        }
    )

    assert any("Option chain" in item for item in result["data_missing"])
    assert any("IBKR/TWS is not reachable" in item for item in result["system_issues"])


def test_option_research_only_stays_research_only():
    result = build_best_available_ideas(_sample_result())

    assert result["option_research_only"]
    assert result["option_research_only"][0]["bucket"] == "research_only"
    assert result["option_research_only"][0]["asset_type"] == "option"
    assert result["option_research_only"][0]["option_opportunity_score"] is not None


def test_stock_only_best_ideas_suppresses_option_buckets_and_option_issues():
    result = build_best_available_ideas(
        {
            **_sample_result(),
            "options_chain": {"error": "Option chain is empty or malformed."},
        },
        config={"include_options": False},
    )

    assert result["stock_watchlist"]
    assert result["option_research_only"] == []
    assert not any("option" in item.lower() for item in result["data_missing"])


def test_best_ideas_explains_startup_validation_block_when_scan_never_runs():
    result = build_best_available_ideas(
        {
            "ok": False,
            "startup_readiness": {
                "ok": False,
                "errors": ["IBKR_READ_ONLY must be true when IBKR is configured."],
                "warnings": [],
            },
            "trade_hunt": None,
            "summary": {"message": "Paper trading cycle blocked by startup validation."},
        }
    )

    assert result["stock_watchlist"] == []
    assert result["blocked_but_interesting"] == []
    assert any("IBKR_READ_ONLY" in item for item in result["system_issues"])
    assert any("did not return enough usable candidate data" in item for item in result["why_no_final_trades"])


def test_best_ideas_does_not_treat_latest_completed_session_age_as_stale_block():
    result = build_best_available_ideas(
        {
            "ok": True,
            "trade_hunt": {
                "selection_result": {
                    "watchlist_alternatives": [
                        {
                            "ticker": "AAPL",
                            "asset_type": "stock",
                            "recommendation_status": "watchlist",
                            "score": 78,
                            "risk_reward": 2.1,
                            "data_freshness": {
                                "age_days": 4.1,
                                "is_stale": False,
                                "freshness_label": "latest_completed_session",
                                "market_session": {
                                    "is_latest_completed_session": True,
                                    "is_stale_by_session": False,
                                },
                            },
                            "data_quality": {"quality_label": "good", "errors": [], "warnings": []},
                        }
                    ],
                    "rejected_candidates": [],
                },
                "decision_result": {"final_recommendations": []},
            },
        },
        config={"include_options": False},
    )

    assert result["stock_watchlist"][0]["ticker"] == "AAPL"
    assert result["blocked_but_interesting"] == []
    assert not any("stale" in item.lower() for item in result["data_missing"])


def test_provider_failures_are_not_ranked_as_trade_ideas():
    result = build_best_available_ideas(
        {
            "ok": True,
            "scan_result": {
                "rejected_candidates": [
                    _scanner_failure_candidate("AAPL"),
                    _scanner_failure_candidate("MSFT"),
                ]
            },
            "decision_result": {"final_recommendations": []},
        },
        config={"include_options": False},
    )
    formatted = format_best_ideas_response(result)

    assert result["ranking_status"] == "unavailable"
    assert result["paper_eligible"] == []
    assert result["stock_watchlist"] == []
    assert result["option_research_only"] == []
    assert result["blocked_but_interesting"] == []
    assert sum("IBKR/TWS is not reachable" in item for item in result["system_issues"]) == 1
    assert "Market ranking is unavailable" in formatted
    assert "AAPL" not in formatted
    assert "MSFT" not in formatted
    assert "interesting attributes" not in formatted


def test_legitimate_rejected_stock_with_usable_data_stays_blocked_but_interesting():
    result = build_best_available_ideas(
        {
            "ok": True,
            "scan_result": {"rejected_candidates": [_legitimate_rejected_stock("TSLA")]},
            "decision_result": {"final_recommendations": []},
        },
        config={"include_options": False},
    )

    assert result["ranking_status"] == "available"
    assert result["blocked_but_interesting"][0]["ticker"] == "TSLA"
    assert result["blocked_but_interesting"][0]["reason"] == "Relative volume too low for final recommendation."


def test_mixed_legitimate_rejection_and_provider_failure_excludes_failed_row():
    result = build_best_available_ideas(
        {
            "ok": True,
            "scan_result": {
                "rejected_candidates": [
                    _scanner_failure_candidate("AAPL"),
                    _legitimate_rejected_stock("NVDA"),
                ]
            },
            "decision_result": {"final_recommendations": []},
        },
        config={"include_options": False},
    )

    assert result["ranking_status"] == "available"
    assert [item["ticker"] for item in result["blocked_but_interesting"]] == ["NVDA"]
    assert all(item["ticker"] != "AAPL" for item in result["blocked_but_interesting"])
    assert any("IBKR/TWS is not reachable" in item for item in result["system_issues"])


def test_option_discovery_contracts_are_collected_and_sorted_by_option_opportunity_score():
    result = build_best_available_ideas(
        {
            "ok": True,
            "decision_result": {"final_recommendations": []},
            "option_discovery": {
                "status": "available",
                "options_final_eligibility": False,
                "research_only_contracts": [
                    {
                        "ticker": "AAPL",
                        "underlying_ticker": "AAPL",
                        "asset_type": "option",
                        "recommendation_status": "research_only",
                        "strategy": "long_call",
                        "option_contract": "AAPL260717C00125000",
                        "option_type": "call",
                        "strike": 125,
                        "expiration": "2026-07-17",
                        "days_to_expiration": 25,
                        "bid": 3.8,
                        "ask": 4.0,
                        "mid": 3.9,
                        "spread_percent": 0.05,
                        "volume": 500,
                        "open_interest": 2000,
                        "implied_volatility": 0.3,
                        "iv_rank": 35,
                        "delta": 0.52,
                        "breakeven_price": 128.9,
                        "underlying_price": 120,
                        "option_opportunity_score": 80,
                        "score": 65,
                    },
                    {
                        "ticker": "MSFT",
                        "underlying_ticker": "MSFT",
                        "asset_type": "option",
                        "recommendation_status": "research_only",
                        "strategy": "long_call",
                        "option_contract": "MSFT260717C00125000",
                        "option_type": "call",
                        "strike": 125,
                        "expiration": "2026-07-17",
                        "days_to_expiration": 25,
                        "bid": 3.8,
                        "ask": 4.2,
                        "mid": 4.0,
                        "spread_percent": 0.1,
                        "volume": 500,
                        "open_interest": 2000,
                        "implied_volatility": 0.3,
                        "iv_rank": 35,
                        "delta": 0.52,
                        "breakeven_price": 129,
                        "underlying_price": 120,
                        "option_opportunity_score": 70,
                        "score": 95,
                    },
                ],
                "missing_requirements": [],
                "warnings": [],
                "errors": [],
            },
        },
        config={"include_options": True},
    )

    assert [item["option_contract"] for item in result["option_research_only"]] == [
        "AAPL260717C00125000",
        "MSFT260717C00125000",
    ]
    assert result["option_discovery_status"] == "available"


def test_option_discovery_underlying_watchlist_is_preserved_without_exact_contracts():
    result = build_best_available_ideas(
        {
            "ok": True,
            "decision_result": {"final_recommendations": []},
            "option_discovery": {
                "status": "partial",
                "options_final_eligibility": False,
                "underlying_watchlist": [
                    {
                        "ticker": "AAPL",
                        "option_bias": "bullish",
                        "underlying_opportunity_score": 82,
                        "underlying_status": "watchlist",
                        "why_watch": ["AAPL ranked as an underlying near-miss."],
                        "required_before_contract_ranking": ["bid/ask", "IV", "Greeks"],
                    }
                ],
                "missing_requirements": ["bid/ask", "IV", "Greeks"],
                "warnings": [],
                "errors": [],
            },
        },
        config={"include_options": True},
    )

    assert result["option_research_only"] == []
    assert result["option_underlying_watchlist"][0]["ticker"] == "AAPL"
    assert result["ranking_status"] == "available"
    formatted = format_best_ideas_response(result)
    assert "Option-underlying watchlist" in formatted
