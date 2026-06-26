from ideas.option_opportunity_ranker import score_option_opportunity


def _underlying(**overrides):
    row = {
        "ticker": "AAPL",
        "opportunity_score": 82.0,
        "score": 78.0,
        "risk_reward": 2.4,
        "current_price": 120.0,
        "recommendation_status": "watchlist",
    }
    row.update(overrides)
    return row


def _contract(**overrides):
    row = {
        "underlying_ticker": "AAPL",
        "option_contract": "AAPL260717C00125000",
        "option_type": "call",
        "strike": 125.0,
        "expiration": "2026-07-17",
        "days_to_expiration": 25,
        "bid": 3.8,
        "ask": 4.0,
        "mid": 3.9,
        "volume": 350,
        "open_interest": 1600,
        "implied_volatility": 0.32,
        "iv_rank": 35,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
        "spread_percent": 0.0513,
        "breakeven_price": 128.9,
        "target_reaches_breakeven": True,
        "risk_reward": 2.2,
        "recommendation_status": "research_only",
        "option_trade_risk": {"status": "research_only", "fill_quality": "usable", "warnings": [], "errors": []},
    }
    row.update(overrides)
    return row


def test_exact_rankable_contract_returns_bounded_score_and_components():
    result = score_option_opportunity(_contract(), _underlying())

    assert result["rankable"] is True
    assert 0 < result["opportunity_score"] <= 100
    assert result["score_version"] == "option_opportunity_v1"
    assert result["actionability_status"] == "research_only"
    assert set(result["components"]) == {
        "underlying_quality",
        "contract_liquidity",
        "spread_and_fill",
        "expiration_fit",
        "breakeven_realism",
        "risk_reward",
        "volatility_context",
        "greeks_quality",
    }
    assert result["why_ranked"]


def test_metadata_only_contract_missing_bid_ask_is_not_rankable():
    result = score_option_opportunity(_contract(bid=None, ask=None, mid=None), _underlying())

    assert result["rankable"] is False
    assert result["opportunity_score"] is None
    assert "bid" in result["missing_requirements"]
    assert "ask" in result["missing_requirements"]


def test_missing_iv_and_greeks_remains_research_rankable_with_lower_confidence():
    complete = score_option_opportunity(_contract(), _underlying())
    sparse = score_option_opportunity(
        _contract(
            implied_volatility=None,
            iv_rank=None,
            delta=None,
            gamma=None,
            theta=None,
            vega=None,
            option_trade_risk={"status": "blocked", "fill_quality": "usable", "errors": ["Usable Greeks are unavailable."]},
            recommendation_status="blocked",
        ),
        _underlying(),
    )

    assert sparse["rankable"] is True
    assert sparse["actionability_status"] == "blocked"
    assert "greeks" in sparse["missing_requirements"]
    assert sparse["data_confidence"] < complete["data_confidence"]


def test_blocked_high_scoring_contract_remains_blocked():
    result = score_option_opportunity(
        _contract(recommendation_status="blocked", option_trade_risk={"status": "blocked", "fill_quality": "good", "errors": []}),
        _underlying(),
    )

    assert result["rankable"] is True
    assert result["actionability_status"] == "blocked"
    assert result["opportunity_score"] is not None


def test_liquidity_and_spread_monotonicity():
    low_liquidity = score_option_opportunity(_contract(volume=20, open_interest=50), _underlying())
    high_liquidity = score_option_opportunity(_contract(volume=800, open_interest=4000), _underlying())
    wide_spread = score_option_opportunity(_contract(bid=3.0, ask=4.8, mid=3.9, spread_percent=0.4615), _underlying())
    tight_spread = score_option_opportunity(_contract(bid=3.85, ask=3.95, mid=3.9, spread_percent=0.0256), _underlying())

    assert high_liquidity["components"]["contract_liquidity"]["score"] >= low_liquidity["components"]["contract_liquidity"]["score"]
    assert high_liquidity["opportunity_score"] >= low_liquidity["opportunity_score"]
    assert tight_spread["components"]["spread_and_fill"]["score"] >= wide_spread["components"]["spread_and_fill"]["score"]
    assert tight_spread["opportunity_score"] >= wide_spread["opportunity_score"]


def test_dte_preference_affects_research_score_without_status_change():
    preferred = score_option_opportunity(_contract(days_to_expiration=30), _underlying(), config={"option_preferences": {"min_dte": 20, "max_dte": 40}})
    far = score_option_opportunity(_contract(days_to_expiration=80), _underlying(), config={"option_preferences": {"min_dte": 20, "max_dte": 40}})

    assert preferred["components"]["expiration_fit"]["score"] >= far["components"]["expiration_fit"]["score"]
    assert preferred["actionability_status"] == far["actionability_status"] == "research_only"
