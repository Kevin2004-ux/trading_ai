from risk.position_sizing import (
    apply_position_sizing_to_trades,
    calculate_option_position_size,
    calculate_position_size,
    calculate_stock_position_size,
    get_position_sizing_config,
)


def _stock_trade(entry_price: float = 100.0, stop_loss: float = 95.0) -> dict:
    return {
        "ticker": "AAPL",
        "asset_type": "stock",
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_price": 110.0,
    }


def _option_trade(premium: float | None = 1.5) -> dict:
    trade = {
        "ticker": "AAPL260703C00125000",
        "underlying_ticker": "AAPL",
        "asset_type": "option",
        "option_contract": "AAPL260703C00125000",
    }
    if premium is not None:
        trade["entry_price"] = premium
    return trade


def test_risk_modes_return_expected_defaults():
    conservative = get_position_sizing_config(risk_mode="conservative")
    normal = get_position_sizing_config(risk_mode="normal")
    aggressive = get_position_sizing_config(risk_mode="aggressive")

    assert conservative["risk_per_trade_percent"] == 0.005
    assert normal["risk_per_trade_percent"] == 0.01
    assert aggressive["risk_per_trade_percent"] == 0.015
    assert conservative["max_option_premium_percent"] == 0.005
    assert normal["max_option_premium_percent"] == 0.01
    assert aggressive["max_option_premium_percent"] == 0.015


def test_unknown_risk_mode_defaults_to_normal_with_warning():
    config = get_position_sizing_config(risk_mode="wildcard")

    assert config["risk_mode"] == "normal"
    assert config["risk_per_trade_percent"] == 0.01
    assert config["warnings"]


def test_stock_position_size_calculates_shares_correctly():
    result = calculate_stock_position_size(_stock_trade(), account_size=10000.0, risk_mode="normal")

    assert result["ok"] is True
    assert result["shares"] == 20
    assert result["estimated_max_loss"] == 100.0
    assert result["notional_exposure"] == 2000.0


def test_stock_position_size_missing_stop_returns_clean_error():
    result = calculate_stock_position_size({"ticker": "AAPL", "entry_price": 100.0}, account_size=10000.0)

    assert result["ok"] is False
    assert "stop_loss" in result["error"]


def test_stock_position_size_zero_size_warning_when_stop_distance_too_large():
    result = calculate_stock_position_size(_stock_trade(entry_price=100.0, stop_loss=-20000.0), account_size=10000.0)

    assert result["ok"] is True
    assert result["shares"] == 0
    assert result["warnings"]


def test_option_position_size_calculates_contracts_correctly():
    result = calculate_option_position_size(_option_trade(1.5), account_size=10000.0, risk_mode="normal")

    assert result["ok"] is True
    assert result["contracts"] == 0
    assert result["warnings"]

    bigger_account = calculate_option_position_size(_option_trade(1.5), account_size=20000.0, risk_mode="aggressive")
    assert bigger_account["ok"] is True
    assert bigger_account["contracts"] == 2


def test_option_position_size_missing_premium_returns_clean_error():
    result = calculate_option_position_size(_option_trade(None), account_size=10000.0)

    assert result["ok"] is False
    assert "premium" in result["error"].lower()


def test_option_position_size_zero_size_warning_when_too_expensive():
    result = calculate_option_position_size(_option_trade(9.0), account_size=10000.0, risk_mode="conservative")

    assert result["ok"] is True
    assert result["contracts"] == 0
    assert result["warnings"]


def test_apply_position_sizing_to_trades_handles_mixed_trade_list():
    result = apply_position_sizing_to_trades([_stock_trade(), _option_trade(0.5)], account_size=10000.0)

    assert result["ok"] is True
    assert len(result["trades"]) == 2
    assert result["trades"][0]["position_sizing"]["asset_type"] == "stock"
    assert result["trades"][1]["position_sizing"]["asset_type"] == "option"


def test_calculate_position_size_dispatches_by_asset_type():
    stock = calculate_position_size(_stock_trade())
    option = calculate_position_size(_option_trade(0.8))

    assert stock["asset_type"] == "stock"
    assert option["asset_type"] == "option"


def test_combined_risk_multipliers_adjust_stock_position_size():
    result = calculate_stock_position_size(
        _stock_trade(),
        account_size=10000.0,
        risk_mode="normal",
        config={
            "risk_multipliers": {
                "circuit_breaker": 0.5,
                "macro": 0.75,
                "market_regime": 0.5,
                "concentration": 0.5,
            },
            "risk_multiplier_reasons": ["Reduced risk test."],
        },
    )

    assert result["ok"] is True
    assert result["original_position_sizing"]["shares"] == 20
    assert result["shares"] == 1
    assert result["combined_risk_multiplier"] == 0.09375
    assert result["estimated_max_loss"] == 5.0
    assert "Reduced risk test." in result["warnings"]


def test_technical_confirmation_multiplier_is_preserved_in_breakdown():
    result = calculate_stock_position_size(
        _stock_trade(),
        account_size=10000.0,
        risk_mode="normal",
        config={
            "risk_multipliers": {
                "technical_confirmation": 0.5,
            },
            "risk_multiplier_reasons": ["Technical confirmation warning."],
        },
    )

    assert result["original_position_sizing"]["shares"] == 20
    assert result["shares"] == 10
    assert result["risk_multipliers"]["technical_confirmation"] == 0.5
