from risk.concentration_controls import (
    evaluate_concentration_risk,
    evaluate_portfolio_concentration,
)


def _trade(ticker: str, sector: str = "tech", direction: str = "long", entry: float = 100.0, stop: float = 95.0) -> dict:
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": direction,
        "sector": sector,
        "entry_price": entry,
        "target_price": entry + 10,
        "stop_loss": stop,
        "quantity": 20,
    }


def test_high_correlation_to_open_trade_reduces_risk():
    result = evaluate_concentration_risk(
        _trade("AAPL"),
        open_trades=[_trade("MSFT")],
        correlation_matrix={"correlations": {"AAPL": {"MSFT": 0.9}, "MSFT": {"AAPL": 0.9}}},
        config={"account_size": 10000.0},
    )

    assert result["approved"] is True
    assert result["risk_level"] == "high"
    assert result["risk_multiplier"] == 0.5
    assert result["correlated_exposure"]["high_correlations"][0]["ticker"] == "MSFT"


def test_multiple_moderate_correlations_reduce_risk():
    result = evaluate_concentration_risk(
        _trade("AAPL"),
        open_trades=[_trade("MSFT"), _trade("NVDA")],
        correlation_matrix={
            "correlations": {
                "AAPL": {"MSFT": 0.8, "NVDA": 0.78},
                "MSFT": {"AAPL": 0.8},
                "NVDA": {"AAPL": 0.78},
            }
        },
        config={"account_size": 10000.0},
    )

    assert result["approved"] is True
    assert result["risk_multiplier"] == 0.5
    assert len(result["correlated_exposure"]["moderate_correlations"]) == 2


def test_excessive_same_sector_exposure_reduces_risk():
    result = evaluate_concentration_risk(
        _trade("AAPL"),
        open_trades=[_trade("MSFT"), _trade("NVDA")],
        correlation_matrix={"correlations": {}},
        config={"account_size": 10000.0, "max_sector_exposure": 0.02},
    )

    assert result["approved"] is True
    assert result["risk_level"] == "high"
    assert result["risk_multiplier"] == 0.5


def test_single_ticker_overexposure_blocks():
    result = evaluate_concentration_risk(
        _trade("AAPL"),
        open_trades=[_trade("AAPL", entry=100.0, stop=90.0)],
        correlation_matrix={"correlations": {"AAPL": {"AAPL": 1.0}}},
        config={"account_size": 10000.0, "max_single_ticker_exposure": 0.01},
    )

    assert result["approved"] is False
    assert result["risk_level"] == "blocked"
    assert result["risk_multiplier"] == 0.0
    assert result["ticker_overlap"] == ["AAPL"]


def test_unavailable_correlation_data_allows_with_conservative_warning():
    result = evaluate_concentration_risk(
        _trade("AAPL"),
        open_trades=[_trade("MSFT")],
        correlation_matrix=None,
        config={"account_size": 10000.0},
    )

    assert result["approved"] is True
    assert result["risk_level"] == "medium"
    assert result["risk_multiplier"] == 0.75
    assert result["warnings"]


def test_portfolio_concentration_summary_handles_open_trades_without_matrix():
    result = evaluate_portfolio_concentration(
        [_trade("AAPL"), _trade("MSFT")],
        correlation_matrix=None,
        config={"account_size": 10000.0},
    )

    assert result["ok"] is True
    assert result["approved"] is True
    assert result["risk_level"] == "medium"
    assert result["sector_exposure"]["tech"] > 0
