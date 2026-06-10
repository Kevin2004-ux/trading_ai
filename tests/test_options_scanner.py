from scanner.options_scanner import (
    scan_options_for_stock_candidate,
    scan_options_for_weekly_selection,
)


def _stock_candidate(ticker: str, *, score: float = 90.0) -> dict:
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "current_price": 120.0,
        "entry_price": 120.0,
        "target_price": 145.0,
        "stop_loss": 114.0,
        "risk_reward": 2.0,
        "score": score,
        "passed": True,
        "recommendation_status": "recommendable",
        "setup_type": "momentum_breakout",
    }


def _chain_result(ticker: str) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "source": "mock",
        "timestamp": "2026-06-07T00:00:00+00:00",
        "data": {
            "contracts": [
                {
                    "option_contract": f"{ticker}C125",
                    "underlying_ticker": ticker,
                    "option_type": "call",
                    "strike": 125.0,
                    "expiration": "2026-07-03",
                    "days_to_expiration": 26,
                    "bid": 3.8,
                    "ask": 4.0,
                    "mid": 3.9,
                    "last": 3.9,
                    "volume": 450,
                    "open_interest": 1600,
                    "implied_volatility": 0.32,
                    "iv_rank": 18,
                    "delta": 0.51,
                    "gamma": 0.08,
                    "theta": -0.07,
                    "vega": 0.12,
                },
                {
                    "option_contract": f"{ticker}C130",
                    "underlying_ticker": ticker,
                    "option_type": "call",
                    "strike": 130.0,
                    "expiration": "2026-07-03",
                    "days_to_expiration": 26,
                    "bid": 1.2,
                    "ask": 1.7,
                    "mid": 1.45,
                    "last": 1.45,
                    "volume": 40,
                    "open_interest": 80,
                    "implied_volatility": 0.41,
                    "iv_rank": 76,
                    "delta": 0.24,
                    "gamma": 0.04,
                    "theta": -0.05,
                    "vega": 0.09,
                },
            ],
        },
        "error": None,
    }


def test_scan_options_for_stock_candidate_returns_best_and_rejected_contracts(monkeypatch):
    monkeypatch.setattr(
        "scanner.options_scanner.get_options_chain",
        lambda ticker: _chain_result(ticker),
    )

    result = scan_options_for_stock_candidate(_stock_candidate("AAPL"), max_contracts=3)

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert len(result["best_option_candidates"]) == 1
    assert len(result["rejected_option_candidates"]) == 1
    assert result["summary"]["contracts_evaluated"] == 2
    best = result["best_option_candidates"][0]
    assert "mispricing_label" in best
    assert "mispricing_score" in best
    assert "mispricing_context" in best


def test_scan_options_for_weekly_selection_handles_multiple_stock_candidates(monkeypatch):
    monkeypatch.setattr(
        "scanner.options_scanner.get_options_chain",
        lambda ticker: _chain_result(ticker),
    )

    result = scan_options_for_weekly_selection(
        [_stock_candidate("AAPL"), _stock_candidate("MSFT")],
        max_contracts_per_ticker=2,
    )

    assert result["ok"] is True
    assert result["summary"]["tickers_evaluated"] == 2
    assert len(result["results"]) == 2
    assert len(result["best_option_candidates"]) == 2


def test_scan_options_for_stock_candidate_handles_unavailable_chain(monkeypatch):
    monkeypatch.setattr(
        "scanner.options_scanner.get_options_chain",
        lambda ticker: {
            "ok": False,
            "ticker": ticker,
            "source": "unavailable",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": None,
            "error": "Options-chain data is unavailable.",
        },
    )

    result = scan_options_for_stock_candidate(_stock_candidate("AAPL"))

    assert result["ok"] is False
    assert result["best_option_candidates"] == []
    assert "unavailable" in result["errors"][0].lower()
