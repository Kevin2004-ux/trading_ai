from execution.fill_model import apply_fill_model_to_trades, estimate_paper_fill


def test_stock_paper_fill_preserves_intended_entry():
    trade = {
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "entry_price": 100.0,
        "average_volume_20": 50_000_000,
        "relative_volume": 1.0,
    }

    result = estimate_paper_fill(trade)

    assert result["ok"] is True
    assert result["intended_entry_price"] == 100.0
    assert result["estimated_fill_price"] > 100.0
    assert result["fill_quality"] == "good"


def test_option_paper_fill_uses_bid_ask_quote():
    trade = {"ticker": "AAPL", "asset_type": "option", "option_contract": "AAPL_CALL", "entry_price": 5.0}
    quote = {"option_contract": "AAPL_CALL", "bid": 4.9, "ask": 5.1}

    result = estimate_paper_fill(trade, option_quote=quote)

    assert result["ok"] is True
    assert result["asset_type"] == "option"
    assert result["estimated_fill_price"] == 5.05
    assert result["intended_entry_price"] == 5.0


def test_option_without_bid_ask_cannot_estimate_fill():
    trade = {"ticker": "AAPL", "asset_type": "option", "option_contract": "AAPL_CALL", "entry_price": 5.0}

    result = estimate_paper_fill(trade)

    assert result["ok"] is False
    assert result["fill_quality"] == "unavailable"


def test_apply_fill_model_updates_entry_and_attaches_context():
    result = apply_fill_model_to_trades(
        [
            {
                "ticker": "AAPL",
                "asset_type": "stock",
                "entry_price": 100.0,
                "average_volume_20": 50_000_000,
            }
        ]
    )

    assert result["ok"] is True
    filled = result["trades"][0]
    assert filled["intended_entry_price"] == 100.0
    assert filled["entry_price"] == filled["paper_fill"]["estimated_fill_price"]

