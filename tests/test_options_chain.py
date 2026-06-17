import config
from realtime.options_chain import calculate_option_metrics, get_options_chain, normalize_options_chain
from realtime.options_eval import evaluate_option_chain_for_trade


def _strong_stock_candidate() -> dict:
    return {
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "setup_type": "momentum_breakout",
        "current_price": 120.0,
        "entry_price": 120.0,
        "target_price": 145.0,
        "stop_loss": 114.0,
        "risk_reward": 2.0,
        "score": 92.0,
        "passed": True,
        "recommendation_status": "recommendable",
    }


def _raw_option_chain() -> list[dict]:
    return [
        {
            "details": {
                "ticker": "O:AAPL260703C00125000",
                "underlying_ticker": "AAPL",
                "contract_type": "call",
                "strike_price": 125.0,
                "expiration_date": "2026-07-03",
            },
            "last_quote": {"bid": 3.8, "ask": 4.0},
            "day": {"close": 3.9, "volume": 450},
            "open_interest": 1600,
            "implied_volatility": 0.32,
            "iv_rank": 18,
            "greeks": {"delta": 0.51, "gamma": 0.08, "theta": -0.07, "vega": 0.12},
            "underlying_price": 120.0,
            "expected_target_price": 145.0,
        },
        {
            "details": {
                "ticker": "O:AAPL260703C00130000",
                "underlying_ticker": "AAPL",
                "contract_type": "call",
                "strike_price": 130.0,
                "expiration_date": "2026-07-03",
            },
            "last_quote": {"bid": 1.2, "ask": 1.7},
            "day": {"close": 1.45, "volume": 80},
            "open_interest": 90,
            "implied_volatility": 0.41,
            "iv_rank": 76,
            "greeks": {"delta": 0.24, "gamma": 0.04, "theta": -0.05, "vega": 0.09},
            "underlying_price": 120.0,
            "expected_target_price": 145.0,
        },
    ]


def test_normalize_options_chain_creates_expected_schema():
    normalized = normalize_options_chain(_raw_option_chain())

    assert len(normalized) == 2
    first = normalized[0]
    expected_keys = {
        "ticker",
        "underlying_ticker",
        "option_contract",
        "option_type",
        "strike",
        "expiration",
        "days_to_expiration",
        "bid",
        "ask",
        "mid",
        "last",
        "volume",
        "open_interest",
        "implied_volatility",
        "iv_rank",
        "iv_percentile",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "spread_percent",
        "breakeven_price",
        "breakeven_move_percent",
    }

    assert expected_keys.issubset(first.keys())
    assert first["option_type"] == "call"
    assert first["underlying_ticker"] == "AAPL"


def test_calculate_option_metrics_computes_mid_spread_and_breakeven():
    metrics = calculate_option_metrics(
        {
            "option_type": "call",
            "strike": 125.0,
            "bid": 4.8,
            "ask": 5.0,
        },
        underlying_price=120.0,
        expected_target_price=132.0,
    )

    assert metrics["mid"] == 4.9
    assert round(metrics["spread_percent"], 4) == round((5.0 - 4.8) / 4.9, 4)
    assert metrics["breakeven_price"] == 129.9
    assert round(metrics["breakeven_move_percent"], 4) == round((129.9 - 120.0) / 120.0, 4)


def test_strong_long_call_candidate_passes_and_weak_contract_is_rejected():
    result = evaluate_option_chain_for_trade(
        _strong_stock_candidate(),
        _raw_option_chain(),
        strategy="long_call",
        max_contracts=5,
    )

    assert result["ok"] is True
    assert result["summary"]["contracts_evaluated"] == 2
    assert len(result["best_option_candidates"]) == 1
    assert result["best_option_candidates"][0]["option_contract"] == "O:AAPL260703C00125000"
    rejected = {candidate["option_contract"]: candidate for candidate in result["rejected_option_candidates"]}
    assert "O:AAPL260703C00130000" in rejected
    assert "minimum_open_interest" in rejected["O:AAPL260703C00130000"]["failed_constraints"]
    assert "minimum_volume" in rejected["O:AAPL260703C00130000"]["failed_constraints"]
    assert "maximum_iv_rank" in rejected["O:AAPL260703C00130000"]["failed_constraints"]
    best = result["best_option_candidates"][0]
    assert best["iv_context"]["iv_context"] == "cheap"
    assert best["greeks_monitoring"]["greeks_quality"] in {"good", "usable"}
    assert best["option_trade_risk"]["approved"] is True
    assert best["options_research_status"] == "paper_eligible"


def test_bad_spread_contract_is_rejected():
    chain = _raw_option_chain()
    chain[0]["last_quote"] = {"bid": 4.0, "ask": 5.2}

    result = evaluate_option_chain_for_trade(_strong_stock_candidate(), chain)

    rejected = {candidate["option_contract"]: candidate for candidate in result["rejected_option_candidates"]}
    assert "maximum_bid_ask_spread_percent" in rejected["O:AAPL260703C00125000"]["failed_constraints"]
    assert "option_trade_risk_approved" in rejected["O:AAPL260703C00125000"]["failed_constraints"]


def test_expiration_outside_range_is_rejected():
    chain = [
        {
            "option_contract": "AAPL_NEAR",
            "underlying_ticker": "AAPL",
            "option_type": "call",
            "strike": 125.0,
            "expiration": "2026-06-10",
            "days_to_expiration": 3,
            "bid": 4.8,
            "ask": 5.0,
            "mid": 4.9,
            "last": 4.95,
            "volume": 450,
            "open_interest": 1600,
            "implied_volatility": 0.32,
            "iv_rank": 42,
            "delta": 0.51,
            "gamma": 0.08,
            "theta": -0.07,
            "vega": 0.12,
        }
    ]

    result = evaluate_option_chain_for_trade(_strong_stock_candidate(), chain)

    assert result["best_option_candidates"] == []
    assert "expiration_window" in result["rejected_option_candidates"][0]["failed_constraints"]


def test_ibkr_options_chain_returns_clean_unavailable_when_selected(monkeypatch):
    monkeypatch.setenv("OPTIONS_DATA_PROVIDER", "ibkr")
    monkeypatch.setattr(config, "OPTIONS_DATA_PROVIDER", "ibkr", raising=False)
    monkeypatch.setattr(
        "providers.ibkr_provider.get_ibkr_options_chain",
        lambda ticker, expiration=None, min_days_to_expiration=14, max_days_to_expiration=56: {
            "ok": False,
            "ticker": ticker,
            "source": "ibkr",
            "data": {"contracts": [], "row_count": 0},
            "error": "IBKR option chain metadata is reachable, but full option quote chains are not enabled yet.",
        },
    )

    result = get_options_chain("AAPL")

    assert result["ok"] is False
    assert result["source"] == "ibkr"
    assert result["data"]["contracts"] == []


def test_ibkr_options_unavailable_keeps_option_recommendations_blocked(monkeypatch):
    monkeypatch.setenv("OPTIONS_DATA_PROVIDER", "ibkr")
    monkeypatch.setattr(config, "OPTIONS_DATA_PROVIDER", "ibkr", raising=False)
    monkeypatch.setattr(
        "providers.ibkr_provider.get_ibkr_options_chain",
        lambda ticker, expiration=None, min_days_to_expiration=14, max_days_to_expiration=56: {
            "ok": False,
            "ticker": ticker,
            "source": "ibkr",
            "data": {
                "contracts": [],
                "row_count": 0,
                "diagnostic": {
                    "permissions_summary": {
                        "option_metadata_available": True,
                        "option_quotes_available": False,
                        "likely_missing_opra": True,
                    }
                },
            },
            "error": "IBKR option quote snapshots are unavailable. OPRA/options market data permissions may be missing.",
        },
    )

    result = get_options_chain("AAPL")

    assert result["ok"] is False
    assert result["data"]["contracts"] == []
    assert result["data"]["diagnostic"]["permissions_summary"]["likely_missing_opra"] is True
    assert "unavailable" in result["error"].lower()
