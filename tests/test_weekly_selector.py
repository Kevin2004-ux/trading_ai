from selector.weekly_selector import (
    apply_portfolio_limits,
    score_weekly_candidate,
    select_weekly_trades,
)


def _candidate(
    ticker: str,
    *,
    recommendation_status: str = "recommendable",
    score: float = 90.0,
    risk_reward: float = 2.5,
    relative_volume: float = 1.8,
    quality_bucket: str = "A",
    setup_type: str = "momentum_breakout",
    scan_profile: str = "momentum_breakout",
    sector: str | None = None,
) -> dict:
    candidate = {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "setup_type": setup_type,
        "scan_profile": scan_profile,
        "selected_profile": scan_profile,
        "score": score,
        "risk_reward": risk_reward,
        "relative_volume": relative_volume,
        "quality_bucket": quality_bucket,
        "recommendation_status": recommendation_status,
        "why_this_profile_matched": ["trend", "volume"],
        "technical_snapshot": {},
    }
    if sector:
        candidate["sector"] = sector
    return candidate


def test_weekly_selector_chooses_at_most_five_trades(monkeypatch):
    monkeypatch.setattr(
        "selector.weekly_selector.enrich_candidate_with_statistics",
        lambda candidate, db_path="strategy_library.db": {
            **candidate,
            "statistical_context": {
                "setup_performance": None,
                "ticker_history": {"closed_trades": 0, "historical_edge": "neutral"},
                "profile_performance": None,
                "statistical_score": 0.0,
                "confidence_label": "low",
                "warnings": [],
            },
        },
    )

    scan_result = {
        "ok": True,
        "best_candidates": [_candidate(f"T{i}") for i in range(6)],
        "watchlist_candidates": [],
    }

    result = select_weekly_trades(scan_result, max_trades=5, min_trades=2)

    assert result["ok"] is True
    assert len(result["selected_trades"]) == 5


def test_weekly_selector_does_not_force_weak_watchlist_candidates(monkeypatch):
    monkeypatch.setattr(
        "selector.weekly_selector.enrich_candidate_with_statistics",
        lambda candidate, db_path="strategy_library.db": {
            **candidate,
            "statistical_context": {
                "setup_performance": None,
                "ticker_history": {"closed_trades": 0, "historical_edge": "neutral"},
                "profile_performance": None,
                "statistical_score": 0.0,
                "confidence_label": "low",
                "warnings": [],
            },
        },
    )

    scan_result = {
        "ok": True,
        "best_candidates": [
            _candidate("AAPL", recommendation_status="watchlist", quality_bucket="watchlist", score=68.0),
            _candidate("MSFT", recommendation_status="watchlist", quality_bucket="watchlist", score=67.0),
        ],
        "watchlist_candidates": [],
    }

    result = select_weekly_trades(scan_result, max_trades=5, min_trades=2)

    assert result["ok"] is True
    assert result["selected_trades"] == []
    assert "no final trade should be taken yet" in result["selection_summary"]["message"].lower()


def test_weekly_selector_returns_watchlist_alternatives_when_no_recommendable_exist(monkeypatch):
    monkeypatch.setattr(
        "selector.weekly_selector.enrich_candidate_with_statistics",
        lambda candidate, db_path="strategy_library.db": {
            **candidate,
            "statistical_context": {
                "setup_performance": None,
                "ticker_history": {"closed_trades": 0, "historical_edge": "neutral"},
                "profile_performance": None,
                "statistical_score": 12.0,
                "confidence_label": "low",
                "warnings": [],
            },
        },
    )

    scan_result = {
        "ok": True,
        "best_candidates": [],
        "watchlist_candidates": [
            _candidate("AAPL", recommendation_status="watchlist", quality_bucket="watchlist", score=82.0),
            _candidate("MSFT", recommendation_status="watchlist", quality_bucket="watchlist", score=80.0),
        ],
    }

    result = select_weekly_trades(scan_result, max_trades=5, min_trades=2)

    assert result["ok"] is True
    assert result["selected_trades"] == []
    assert len(result["watchlist_alternatives"]) == 2


def test_portfolio_limits_avoid_duplicate_tickers():
    candidates = [_candidate("AAPL"), _candidate("AAPL"), _candidate("MSFT")]
    for candidate in candidates:
        candidate["weekly_score"] = 90.0

    selected = apply_portfolio_limits(candidates)

    assert len(selected) == 2
    assert [candidate["ticker"] for candidate in selected] == ["AAPL", "MSFT"]
    assert candidates[1]["portfolio_limit_reason"] is not None


def test_statistical_enrichment_affects_candidate_scoring(monkeypatch):
    def fake_enrich(candidate, db_path="strategy_library.db"):
        positive = candidate["ticker"] == "AAPL"
        return {
            **candidate,
            "statistical_context": {
                "setup_performance": {"meets_min_sample_size": positive, "expectancy": 0.08 if positive else -0.03},
                "ticker_history": {"closed_trades": 8 if positive else 8, "historical_edge": "positive" if positive else "negative"},
                "profile_performance": {"meets_min_sample_size": positive, "avg_realized_return": 0.04 if positive else -0.02},
                "statistical_score": 82.0 if positive else 30.0,
                "confidence_label": "high" if positive else "low",
                "warnings": [],
            },
        }

    monkeypatch.setattr("selector.weekly_selector.enrich_candidate_with_statistics", fake_enrich)

    strong = fake_enrich(_candidate("AAPL"))
    weak = fake_enrich(_candidate("TSLA"))

    strong_score = score_weekly_candidate(strong)
    weak_score = score_weekly_candidate(weak)

    assert strong_score > weak_score


def test_low_or_no_statistical_sample_is_treated_neutrally(monkeypatch):
    monkeypatch.setattr(
        "selector.weekly_selector.enrich_candidate_with_statistics",
        lambda candidate, db_path="strategy_library.db": {
            **candidate,
            "statistical_context": {
                "setup_performance": {"meets_min_sample_size": False, "expectancy": None},
                "ticker_history": {"closed_trades": 1, "historical_edge": "neutral"},
                "profile_performance": {"meets_min_sample_size": False, "avg_realized_return": None},
                "statistical_score": 18.0,
                "confidence_label": "low",
                "warnings": ["Limited history."],
            },
        },
    )

    scan_result = {
        "ok": True,
        "best_candidates": [_candidate("AAPL", score=92.0, quality_bucket="A+")],
        "watchlist_candidates": [],
    }

    result = select_weekly_trades(scan_result, max_trades=5, min_trades=2)

    assert result["ok"] is True
    assert len(result["selected_trades"]) == 1
    assert result["selected_trades"][0]["weekly_score"] > 0


def test_weekly_selector_boosts_positive_catalyst_modestly():
    base_candidate = _candidate("AAPL", score=85.0)
    base_candidate["statistical_context"] = {
        "setup_performance": None,
        "ticker_history": {"closed_trades": 0, "historical_edge": "neutral"},
        "profile_performance": None,
        "statistical_score": 0.0,
        "confidence_label": "low",
        "warnings": [],
    }
    positive_candidate = dict(base_candidate)
    positive_candidate["catalyst_context"] = {
        "catalyst_label": "strong_positive",
        "catalyst_bias": 6.0,
        "risk_flags": [],
    }

    assert score_weekly_candidate(positive_candidate) > score_weekly_candidate(base_candidate)


def test_weekly_selector_penalizes_earnings_risk_and_high_risk_catalyst():
    candidate = _candidate("AAPL", score=90.0)
    candidate["statistical_context"] = {
        "setup_performance": None,
        "ticker_history": {"closed_trades": 0, "historical_edge": "neutral"},
        "profile_performance": None,
        "statistical_score": 0.0,
        "confidence_label": "low",
        "warnings": [],
    }
    safe_candidate = dict(candidate)
    risky_candidate = dict(candidate)
    risky_candidate["catalyst_context"] = {
        "catalyst_label": "high_risk",
        "catalyst_bias": -4.0,
        "risk_flags": ["Earnings are within 7 days."],
    }

    assert score_weekly_candidate(risky_candidate) < score_weekly_candidate(safe_candidate)
