from scanner.universe_builder import (
    build_custom_universe,
    get_default_universe,
)


def test_default_universe_returns_tickers():
    result = get_default_universe("large_cap", max_tickers=10)

    assert result["ok"] is True
    assert result["universe"] == "large_cap"
    assert result["count"] == 10
    assert "AAPL" in result["tickers"]


def test_custom_universe_dedupes_and_validates():
    result = build_custom_universe(["aapl", "AAPL", " msft ", "", "$bad", "nvda"], max_tickers=10)

    assert result["ok"] is True
    assert result["tickers"] == ["AAPL", "MSFT", "NVDA"]
    assert any("Ignored invalid ticker symbol" in error for error in result["errors"])


def test_unknown_universe_returns_clean_error():
    result = get_default_universe("unknown_bucket")

    assert result["ok"] is False
    assert result["count"] == 0
    assert any("Unknown universe" in error for error in result["errors"])
