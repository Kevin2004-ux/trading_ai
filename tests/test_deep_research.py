from research.deep_research import (
    build_evidence_table,
    build_research_brief,
    score_research_conviction,
    summarize_bear_case,
    summarize_bull_case,
)


def _candidate(
    *,
    ticker: str = "AAPL",
    recommendation_status: str = "recommendable",
    passed: bool = True,
    score: float = 91.0,
    risk_reward: float = 2.6,
) -> dict:
    return {
        "ticker": ticker,
        "direction": "long",
        "setup_type": "momentum_breakout",
        "selected_profile": "momentum_breakout",
        "recommendation_status": recommendation_status,
        "passed": passed,
        "score": score,
        "risk_reward": risk_reward,
        "entry_price": 120.0,
        "target_price": 135.0,
        "stop_loss": 112.5,
        "failed_constraints": [] if passed else ["minimum_relative_volume"],
        "rejection_reason": "" if passed else "Failed liquidity.",
        "statistical_context": {
            "setup_performance": {
                "expectancy": 0.08,
                "sample_size": 9,
                "confidence_label": "medium",
                "meets_min_sample_size": True,
            },
            "ticker_history": {
                "historical_edge": "positive",
                "closed_trades": 6,
                "wins": 4,
                "losses": 2,
            },
            "warnings": [],
        },
    }


def _market_snapshot(ticker: str = "AAPL") -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "source": "polygon",
        "timestamp": "2026-06-07T00:00:00+00:00",
        "data": {
            "quote": {"last_price": 120.0},
            "technical_snapshot": {
                "current_price": 120.0,
                "sma_20": 118.0,
                "sma_50": 114.0,
                "high_20": 121.0,
                "atr_14": 2.5,
                "relative_volume": 1.7,
            },
            "data_freshness": {
                "latest_bar_timestamp": "2026-06-06T00:00:00+00:00",
                "age_days": 1,
                "is_stale": False,
                "freshness_label": "fresh",
            },
        },
        "error": None,
    }


def test_build_research_brief_combines_available_context(monkeypatch):
    monkeypatch.setattr(
        "research.deep_research._candidate_details",
        lambda ticker, db_path: {
            "market_snapshot": _market_snapshot(ticker),
            "candidate": _candidate(ticker=ticker),
            "constraint_result": {
                "passed": True,
                "recommendation_status": "recommendable",
                "score": 91.0,
                "constraint_results": {},
                "failed_constraints": [],
                "rejection_reason": "",
            },
            "trade_levels": {"ok": True, "entry_price": 120.0, "target_price": 135.0, "stop_loss": 112.5, "risk_reward": 2.6},
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_catalyst_snapshot",
        lambda ticker, lookback_days=7: {
            "ok": True,
            "ticker": ticker,
            "source": "fmp",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "earnings_snapshot": {"is_earnings_risk": False},
                "catalyst_score": {
                    "catalyst_score": 68.0,
                    "catalyst_label": "positive",
                    "summary": "Recent analyst upgrade is supportive.",
                    "negative_catalysts": [],
                    "risk_flags": [],
                },
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_market_regime_snapshot",
        lambda include_breadth=True, db_path="strategy_library.db": {
            "ok": True,
            "regime": "risk_on_uptrend",
            "summary": "Broad market trend remains constructive.",
            "risk_flags": [],
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_relative_strength_snapshot",
        lambda ticker, sector=None, include_sector=True, db_path="strategy_library.db": {
            "ok": True,
            "ticker": ticker,
            "relative_strength_label": "outperforming",
            "relative_strength_score": 75.0,
            "risk_flags": [],
            "summary": "Outperforming SPY and sector peers.",
        },
    )
    monkeypatch.setattr(
        "research.deep_research.scan_options_for_stock_candidate",
        lambda candidate, max_contracts=3: {
            "ok": True,
            "best_option_candidates": [
                {
                    "option_contract": "AAPL260703C00125000",
                    "mispricing_label": "fair_value",
                    "mispricing_context": {"explanation": "Valuation looks fair with acceptable liquidity."},
                }
            ],
            "summary": {"message": "One contract qualifies."},
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_sec_filing_snapshot",
        lambda ticker, lookback_days=120: {
            "ok": True,
            "ticker": ticker,
            "source": "mock",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "filings": [],
                "filing_analysis": {
                    "ok": True,
                    "ticker": ticker,
                    "filings_analyzed": 2,
                    "filing_risk_label": "low",
                    "filing_risk_score": 24.0,
                    "positive_filing_signals": ["Share repurchase activity was disclosed."],
                    "negative_filing_signals": [],
                    "risk_flags": [],
                    "recent_material_events": ["8-K: Strategic partnership"],
                    "summary": "Recent SEC filing risk is low.",
                    "sources": ["mock"],
                    "error": None,
                },
                "filing_summary": {"ticker": ticker, "summary": "Recent SEC filing risk is low."},
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_earnings_transcript_snapshot",
        lambda ticker, lookback_quarters=2: {
            "ok": True,
            "ticker": ticker,
            "source": "mock",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "transcripts": [],
                "earnings_quality": {
                    "ok": True,
                    "ticker": ticker,
                    "source": "mock",
                    "timestamp": "2026-06-07T00:00:00+00:00",
                    "quarters_analyzed": 2,
                    "earnings_quality_label": "strong",
                    "earnings_quality_score": 74.0,
                    "management_tone": "positive",
                    "guidance_label": "raised",
                    "positive_signals": ["Management discussed raised guidance."],
                    "negative_signals": [],
                    "risk_flags": [],
                    "summary": "Positive guidance and management tone.",
                    "sources": ["mock"],
                    "error": None,
                },
            },
            "error": None,
        },
    )

    result = build_research_brief("AAPL", include_options=True)

    assert result["ok"] is True
    assert result["brief_type"] == "deep_research"
    assert result["research_conviction"]["label"] in {"medium", "high"}
    assert result["bull_case"]["points"]
    assert result["trade_thesis"]["thesis"]
    categories = {row["category"] for row in result["evidence_table"]}
    assert {"technical", "statistical", "catalyst", "regime", "relative_strength", "options", "sec_filings", "earnings_transcript"}.issubset(categories)
    assert result["raw_context"]["filing_context"]["data"]["filing_analysis"]["filing_risk_label"] == "low"
    assert result["raw_context"]["earnings_transcript_context"]["data"]["earnings_quality"]["earnings_quality_label"] == "strong"


def test_build_research_brief_includes_memory_context_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "research.deep_research._candidate_details",
        lambda ticker, db_path: {
            "market_snapshot": _market_snapshot(ticker),
            "candidate": _candidate(ticker=ticker),
            "constraint_result": {"passed": True, "recommendation_status": "recommendable"},
            "trade_levels": {"ok": True},
        },
    )
    monkeypatch.setattr(
        "research.deep_research.find_similar_setups",
        lambda candidate_or_trade, top_k=5: {
            "ok": True,
            "source": "mock",
            "query": "AAPL momentum breakout",
            "matches": [{"memory_id": "m1", "score": 0.9, "metadata": {"ticker": "AAPL"}, "text": "Similar AAPL setup."}],
            "warnings": ["Semantic memory is qualitative context only."],
            "label": "qualitative_context_only",
            "error": None,
        },
    )

    result = build_research_brief(
        "AAPL",
        include_catalysts=False,
        include_market_regime=False,
        include_relative_strength=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_memory_context=True,
    )

    assert result["ok"] is True
    assert result["raw_context"]["memory_context"]["ok"] is True
    assert result["raw_context"]["memory_context"]["matches"][0]["memory_id"] == "m1"


def test_build_research_brief_handles_missing_sections_without_crashing(monkeypatch):
    monkeypatch.setattr("research.deep_research._candidate_details", lambda ticker, db_path: None)
    monkeypatch.setattr(
        "research.deep_research.get_market_snapshot",
        lambda ticker, lookback_days=180: {"ok": False, "ticker": ticker, "source": "polygon", "timestamp": "x", "data": None, "error": "No market data."},
    )
    monkeypatch.setattr(
        "research.deep_research.analyze_ticker_history",
        lambda ticker, db_path="strategy_library.db": {
            "ok": True,
            "ticker": ticker,
            "total_recommendations": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "historical_edge": "neutral",
            "message": "No history.",
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_catalyst_snapshot",
        lambda ticker, lookback_days=7: {"ok": False, "ticker": ticker, "source": "unavailable", "timestamp": "x", "data": {"catalyst_score": {}}, "error": "No catalyst data."},
    )
    monkeypatch.setattr(
        "research.deep_research.get_market_regime_snapshot",
        lambda include_breadth=True, db_path="strategy_library.db": {"ok": False, "regime": "unknown", "summary": "Unavailable.", "risk_flags": [], "error": "No regime."},
    )
    monkeypatch.setattr(
        "research.deep_research.get_relative_strength_snapshot",
        lambda ticker, sector=None, include_sector=True, db_path="strategy_library.db": {
            "ok": False,
            "ticker": ticker,
            "relative_strength_label": "unknown",
            "risk_flags": [],
            "summary": "Unavailable.",
            "error": "No relative strength data.",
        },
    )
    monkeypatch.setattr(
        "research.deep_research.get_sec_filing_snapshot",
        lambda ticker, lookback_days=120: {"ok": False, "ticker": ticker, "source": "unavailable", "timestamp": "x", "data": None, "error": "No filing data."},
    )
    monkeypatch.setattr(
        "research.deep_research.get_earnings_transcript_snapshot",
        lambda ticker, lookback_quarters=2: {"ok": False, "ticker": ticker, "source": "unavailable", "timestamp": "x", "data": None, "error": "No transcript data."},
    )

    result = build_research_brief("AAPL", include_options=True)

    assert result["ok"] is True
    assert "market_snapshot" in result["data_quality"]["missing_sections"]
    assert "options_context" in result["data_quality"]["missing_sections"]
    assert "filing_context" in result["data_quality"]["missing_sections"]
    assert "earnings_transcript_context" in result["data_quality"]["missing_sections"]
    assert any(row["source"] == "unavailable" for row in result["evidence_table"])


def test_score_research_conviction_penalizes_rejected_and_missing_data():
    result = score_research_conviction(
        {
            "candidate": _candidate(recommendation_status="rejected", passed=False, score=38.0, risk_reward=1.1),
            "statistical_context": {
                "setup_performance": {
                    "expectancy": -0.06,
                    "sample_size": 10,
                    "meets_min_sample_size": True,
                }
            },
            "catalyst_context": {
                "data": {
                    "catalyst_score": {
                        "catalyst_score": 28.0,
                        "catalyst_label": "negative",
                    }
                }
            },
            "market_regime": {"regime": "risk_off_downtrend"},
            "relative_strength": {"relative_strength_label": "market_laggard"},
            "filing_context": {"data": {"filing_analysis": {"filing_risk_label": "high", "filing_risk_score": 85.0}}},
            "earnings_transcript_context": {"data": {"earnings_quality": {"earnings_quality_label": "weak", "guidance_label": "lowered", "management_tone": "cautious"}}},
            "options_context": {
                "ok": True,
                "best_option_candidates": [{"mispricing_label": "high_iv_risky"}],
            },
            "data_quality": {
                "missing_sections": ["market_snapshot", "options_context"],
                "stale_data_flags": ["Market data freshness is stale."],
            },
        }
    )

    assert result["label"] == "low"
    assert result["score"] < 50
    assert result["penalties"]


def test_bull_and_bear_cases_reflect_deterministic_evidence():
    bullish_inputs = {
        "candidate": _candidate(),
        "constraint_result": {"passed": True},
        "technical_snapshot": {"current_price": 120.0, "sma_20": 118.0, "sma_50": 114.0},
        "statistical_context": _candidate()["statistical_context"],
        "catalyst_context": {"data": {"earnings_snapshot": {"is_earnings_risk": False}, "catalyst_score": {"catalyst_label": "positive"}}},
        "market_regime": {"regime": "risk_on_uptrend"},
        "relative_strength": {"relative_strength_label": "outperforming"},
        "filing_context": {"data": {"filing_analysis": {"filing_risk_label": "low", "positive_filing_signals": ["Share repurchase activity was disclosed."]}}},
        "earnings_transcript_context": {"data": {"earnings_quality": {"earnings_quality_label": "strong", "management_tone": "positive", "guidance_label": "raised"}}},
        "options_context": {"ok": True, "best_option_candidates": [{"mispricing_label": "fair_value"}]},
        "data_quality": {"missing_sections": [], "stale_data_flags": []},
    }
    bearish_inputs = {
        "candidate": _candidate(recommendation_status="watchlist", passed=True, score=68.0, risk_reward=1.8),
        "constraint_result": {"passed": True},
        "statistical_context": {"ticker_history": {"historical_edge": "negative"}},
        "catalyst_context": {"data": {"catalyst_score": {"catalyst_label": "high_risk"}}},
        "market_regime": {"regime": "high_volatility"},
        "relative_strength": {"relative_strength_label": "underperforming"},
        "filing_context": {"data": {"filing_analysis": {"filing_risk_label": "high", "negative_filing_signals": ["Potential dilution or offering activity."]}}},
        "earnings_transcript_context": {"data": {"earnings_quality": {"earnings_quality_label": "weak", "management_tone": "cautious", "guidance_label": "lowered"}}},
        "options_context": {"ok": True, "best_option_candidates": [{"mispricing_label": "cheap_but_low_probability"}]},
        "data_quality": {"missing_sections": ["market_snapshot"], "stale_data_flags": ["Stale bars."]},
    }

    bull_case = summarize_bull_case(bullish_inputs)
    bear_case = summarize_bear_case(bearish_inputs)

    assert any("passed objective constraints" in point.lower() for point in bull_case["points"])
    assert any("risk/reward is favorable" in point.lower() for point in bull_case["points"])
    assert any("filing risk is low" in point.lower() for point in bull_case["points"])
    assert any("earnings transcript quality is strong" in point.lower() for point in bull_case["points"])
    assert any("watchlist-only" in point.lower() for point in bear_case["points"])
    assert any("high volatility" in point.lower() for point in bear_case["points"])
    assert any("filing risk is high" in point.lower() for point in bear_case["points"])
    assert any("lowered guidance" in point.lower() for point in bear_case["points"])


def test_build_evidence_table_marks_unavailable_data():
    result = build_evidence_table(
        {
            "candidate": {},
            "constraint_result": {},
            "statistical_context": {},
            "catalyst_context": {},
            "market_regime": {},
            "relative_strength": {},
            "options_context": {},
            "requested_sections": [
                "market_snapshot",
                "candidate_details",
                "statistical_context",
                "catalyst_context",
            "market_regime",
            "relative_strength",
            "options_context",
            "filing_context",
            "earnings_transcript_context",
        ],
    }
    )

    by_category = {row["category"]: row for row in result["evidence_table"]}
    assert by_category["catalyst"]["source"] == "unavailable"
    assert by_category["regime"]["source"] == "unavailable"
    assert by_category["relative_strength"]["source"] == "unavailable"
    assert by_category["options"]["source"] == "unavailable"
    assert by_category["sec_filings"]["source"] == "unavailable"
    assert by_category["earnings_transcript"]["source"] == "unavailable"
