from engine.constraint_engine import evaluate_stock_constraints
from ideas import build_assistant_trade_response, build_best_available_ideas, score_stock_opportunity
from ideas.opportunity_ranker import DEFAULT_STOCK_OPPORTUNITY_WEIGHTS, STOCK_OPPORTUNITY_SCORE_VERSION


def _candidate(
    ticker="AAPL",
    relative_volume=1.35,
    risk_reward=2.4,
    technical_status="confirmed",
    relative_strength_label="outperforming",
    include_optional=True,
):
    candidate = {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "setup_type": "momentum_pullback",
        "current_price": 125.0,
        "sma_20": 120.0,
        "sma_50": 115.0,
        "sma_200": 105.0,
        "average_volume_20": 2_500_000,
        "relative_volume": relative_volume,
        "atr_percent": 0.04,
        "risk_reward": risk_reward,
        "days_until_earnings": 25,
        "data_freshness": {"ok": True, "freshness_label": "fresh"},
        "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
        "technical_confirmation_summary": {
            "status": technical_status,
            "score_adjustment": 4 if technical_status == "confirmed" else -4,
            "warnings": [] if technical_status == "confirmed" else ["Technical confirmation is weak."],
            "reasons": ["Multi-timeframe confirmation is constructive."] if technical_status == "confirmed" else [],
        },
        "relative_strength_context": {"relative_strength_label": relative_strength_label},
        "why_this_profile_matched": ["Momentum pullback profile matched."],
    }
    if include_optional:
        candidate["statistical_context"] = {
            "setup_performance": {"sample_size": 12, "expectancy": 0.18, "win_rate": 0.62}
        }
        candidate["catalyst_context"] = {"sentiment": "positive", "summary": "Positive catalyst context."}

    result = evaluate_stock_constraints(candidate)
    candidate.update(result)
    return candidate


def _scanner_failure():
    reason = "IBKR historical bars unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"
    return {
        "ticker": "BAD",
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


def test_stock_opportunity_ranker_is_deterministic():
    candidate = _candidate()

    first = score_stock_opportunity(candidate)
    second = score_stock_opportunity(candidate)

    assert first == second
    assert first["score_version"] == STOCK_OPPORTUNITY_SCORE_VERSION


def test_stock_opportunity_scores_are_bounded():
    result = score_stock_opportunity(_candidate())

    assert 0 <= result["opportunity_score"] <= 100
    assert 0 <= result["data_confidence"] <= 100
    assert set(result["components"]) == set(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)
    for component in result["components"].values():
        assert 0 <= component["score"] <= 100
        assert 0 <= component["weight"] <= 1
        assert isinstance(component["available"], bool)
        assert isinstance(component["evidence"], list)


def test_near_miss_relative_volume_is_rankable_but_not_upgraded():
    candidate = _candidate(relative_volume=1.08)
    result = score_stock_opportunity(candidate)

    assert result["rankable"] is True
    assert result["opportunity_score"] > 0
    assert result["actionability_status"] == "blocked"
    assert candidate["recommendation_status"] == "rejected"
    assert any(gap["constraint"] == "minimum_relative_volume" for gap in result["qualification_gaps"])
    assert "Relative volume must improve to the required threshold." in result["confirmation_needed"]


def test_relative_volume_monotonicity():
    far = score_stock_opportunity(_candidate(relative_volume=0.8))
    near = score_stock_opportunity(_candidate(relative_volume=1.15))
    passed = score_stock_opportunity(_candidate(relative_volume=1.35))

    assert near["components"]["qualification_fit"]["score"] >= far["components"]["qualification_fit"]["score"]
    assert passed["components"]["qualification_fit"]["score"] >= near["components"]["qualification_fit"]["score"]
    assert near["opportunity_score"] >= far["opportunity_score"]
    assert passed["opportunity_score"] >= near["opportunity_score"]


def test_risk_reward_monotonicity():
    weak = score_stock_opportunity(_candidate(risk_reward=1.2))
    near = score_stock_opportunity(_candidate(risk_reward=1.9))
    passed = score_stock_opportunity(_candidate(risk_reward=2.6))

    assert near["components"]["risk_reward"]["score"] >= weak["components"]["risk_reward"]["score"]
    assert passed["components"]["risk_reward"]["score"] >= near["components"]["risk_reward"]["score"]
    assert near["opportunity_score"] >= weak["opportunity_score"]
    assert passed["opportunity_score"] >= near["opportunity_score"]


def test_stronger_structured_evidence_scores_higher():
    strong = score_stock_opportunity(
        _candidate(technical_status="confirmed", relative_strength_label="market_leader")
    )
    weak = score_stock_opportunity(
        _candidate(technical_status="warning", relative_strength_label="underperforming")
    )

    assert strong["opportunity_score"] > weak["opportunity_score"]
    assert strong["components"]["technical_confirmation"]["score"] > weak["components"]["technical_confirmation"]["score"]
    assert strong["components"]["relative_strength"]["score"] > weak["components"]["relative_strength"]["score"]


def test_missing_optional_research_does_not_make_candidate_unrankable_or_zero():
    result = score_stock_opportunity(_candidate(include_optional=False))

    assert result["rankable"] is True
    assert result["opportunity_score"] > 0
    assert result["components"]["statistical_edge"]["available"] is False
    assert result["components"]["catalyst_context"]["available"] is False


def test_provider_data_failure_is_unrankable_and_excluded_from_best_ideas():
    failure = _scanner_failure()
    result = score_stock_opportunity(failure)
    best_ideas = build_best_available_ideas(
        {"ok": True, "scan_result": {"rejected_candidates": [failure]}, "decision_result": {"final_recommendations": []}},
        config={"include_options": False},
    )

    assert result["rankable"] is False
    assert result["opportunity_score"] is None
    assert best_ideas["ranking_status"] == "unavailable"
    assert best_ideas["paper_eligible"] == []
    assert best_ideas["stock_watchlist"] == []
    assert best_ideas["blocked_but_interesting"] == []


def test_status_separation_is_preserved():
    rejected = _candidate(relative_volume=1.05)
    watchlist = _candidate(relative_volume=1.21, risk_reward=2.02)
    watchlist["recommendation_status"] = "watchlist"
    paper = _candidate(relative_volume=1.7, risk_reward=3.4)
    paper["recommendation_status"] = "recommendable"

    rejected_result = score_stock_opportunity(rejected)
    watchlist_result = score_stock_opportunity(watchlist)
    paper_result = score_stock_opportunity(paper)

    assert rejected_result["actionability_status"] == "blocked"
    assert watchlist_result["actionability_status"] == "watchlist"
    assert paper_result["actionability_status"] == "paper_eligible"
    assert rejected["recommendation_status"] == "rejected"
    assert watchlist["recommendation_status"] == "watchlist"
    assert paper["recommendation_status"] == "recommendable"


def test_assistant_response_uses_opportunity_score_and_confirmation_needed():
    near_miss = _candidate(ticker="NVDA", relative_volume=1.08)
    best_ideas = build_best_available_ideas(
        {"ok": True, "scan_result": {"rejected_candidates": [near_miss]}, "decision_result": {"final_recommendations": []}},
        config={"include_options": False},
    )
    response = build_assistant_trade_response(best_ideas, requested_instrument="stocks")

    assert response["top_stocks"][0]["ticker"] == "NVDA"
    assert response["top_stocks"][0]["status"] == "blocked"
    assert response["top_stocks"][0]["opportunity_score"] == best_ideas["blocked_but_interesting"][0]["opportunity_score"]
    assert response["top_stocks"][0]["why_ranked"]
    assert "Relative volume must improve to the required threshold." in response["top_stocks"][0]["confirmation_needed"]
