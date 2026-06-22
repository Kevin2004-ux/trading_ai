from ideas import build_best_available_ideas, format_best_ideas_response


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
                    "recommendation_status": "watchlist",
                    "score": 76,
                    "bid": 4.0,
                    "ask": 4.2,
                    "iv_context": {"implied_volatility": 0.3, "iv_rank": 42},
                    "greeks_monitoring": {"delta": 0.55, "greeks_quality": "usable"},
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
