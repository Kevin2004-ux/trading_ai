from risk.portfolio_manager import (
    analyze_portfolio_exposure,
    apply_portfolio_risk_limits,
    build_portfolio_risk_summary,
    calculate_trade_risk,
    score_portfolio_fit,
)


def _stock_trade(
    ticker: str,
    *,
    sector: str = "technology",
    setup_type: str = "momentum_breakout",
    entry_price: float = 100.0,
    target_price: float = 110.0,
    stop_loss: float = 95.0,
    score: float = 92.0,
) -> dict:
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "risk_reward": 2.0,
        "score": score,
        "quality_bucket": "A",
        "confidence_label": "high",
        "sector": sector,
        "setup_type": setup_type,
        "recommendation_status": "recommendable",
        "passed": True,
    }


def _option_trade(
    ticker: str = "AAPL",
    *,
    premium: float = 1.2,
    score: float = 88.0,
) -> dict:
    return {
        "ticker": ticker,
        "underlying_ticker": ticker,
        "asset_type": "option",
        "option_contract": f"{ticker}260703C00125000",
        "direction": "long",
        "entry_price": premium,
        "target_price": 2.5,
        "stop_loss": 0.0,
        "risk_reward": 2.2,
        "score": score,
        "quality_bucket": "A",
        "confidence_label": "medium",
        "sector": "technology",
        "setup_type": "momentum_breakout",
        "recommendation_status": "recommendable",
        "passed": True,
    }


def test_calculate_trade_risk_for_stock_estimates_quantity():
    result = calculate_trade_risk(_stock_trade("AAPL"), account_size=10000.0)

    assert result["ok"] is True
    assert result["asset_type"] == "stock"
    assert result["risk_known"] is True
    assert result["quantity"] == 20
    assert round(result["estimated_dollar_risk"], 2) == 100.0
    assert round(result["risk_percent_of_account"], 4) == 0.01


def test_calculate_trade_risk_for_option_uses_one_contract_when_missing_contracts():
    result = calculate_trade_risk(_option_trade(), account_size=10000.0)

    assert result["ok"] is True
    assert result["asset_type"] == "option"
    assert result["contracts"] == 1
    assert round(result["premium_at_risk"], 2) == 120.0
    assert round(result["premium_percent_of_account"], 4) == 0.012


def test_analyze_portfolio_exposure_returns_expected_rollup():
    exposure = analyze_portfolio_exposure(
        proposed_trades=[_stock_trade("AAPL"), _stock_trade("MSFT", sector="technology", setup_type="trend_pullback")],
        existing_open_trades=[_stock_trade("NVDA", sector="technology", setup_type="momentum_breakout")],
    )

    assert exposure["ok"] is True
    assert exposure["existing_open_trades_count"] == 1
    assert exposure["proposed_trades_count"] == 2
    assert exposure["existing_open_risk_percent"] > 0
    assert exposure["proposed_risk_percent"] > 0
    assert exposure["sector_counts_existing"]["technology"] == 1


def test_score_portfolio_fit_penalizes_duplicate_and_concentration():
    result = score_portfolio_fit(
        _stock_trade("AAPL", sector="technology"),
        existing_open_trades=[_stock_trade("AAPL", sector="technology")],
        selected_trades=[_stock_trade("MSFT", sector="technology")],
    )

    assert result["ok"] is True
    assert result["score"] < 75
    assert "duplicate_ticker" in result["flags"]
    assert "sector_concentration" in result["flags"]


def test_apply_portfolio_risk_limits_rejects_duplicates_and_excess_weekly_risk():
    result = apply_portfolio_risk_limits(
        proposed_trades=[
            _stock_trade("AAPL", score=96.0),
            _stock_trade("MSFT", score=90.0, sector="healthcare", setup_type="trend_pullback"),
            _stock_trade("AAPL", score=89.0),
        ],
        existing_open_trades=[_stock_trade("NVDA", score=87.0, sector="technology")],
        account_size=10000.0,
        config={"max_same_sector_trades": 2, "max_new_weekly_risk_percent": 0.02},
    )

    assert result["ok"] is True
    assert [trade["ticker"] for trade in result["approved_trades"]] == ["AAPL", "MSFT"]
    assert len(result["rejected_trades"]) == 1
    assert result["rejected_trades"][0]["ticker"] == "AAPL"
    assert "Duplicate underlying ticker" in result["rejected_trades"][0]["rejection_reason"]


def test_apply_portfolio_risk_limits_rejects_option_premium_above_cap():
    result = apply_portfolio_risk_limits(
        proposed_trades=[_option_trade(premium=2.0)],
        account_size=10000.0,
        config={"max_option_premium_percent": 0.01},
    )

    assert result["ok"] is True
    assert result["approved_trades"] == []
    assert len(result["rejected_trades"]) == 1
    assert "Option premium exposure exceeds max_option_premium_percent." in result["rejected_trades"][0]["rejection_reason"]


def test_build_portfolio_risk_summary_returns_clean_rollup():
    approved = [_stock_trade("AAPL")]
    approved[0]["portfolio_risk_context"] = {
        "trade_risk": {"risk_percent_of_account": 0.01, "premium_percent_of_account": 0.0}
    }
    rejected = [{"ticker": "MSFT", "trade": _stock_trade("MSFT"), "rejection_reason": "Trade would exceed max_new_weekly_risk_percent."}]
    exposure = {"existing_open_risk_percent": 0.01, "existing_option_premium_percent": 0.0}

    summary = build_portfolio_risk_summary(approved, rejected, exposure)

    assert summary["approved_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["approved_tickers"] == ["AAPL"]
    assert summary["message"]
