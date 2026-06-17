from providers.ticker_normalizer import normalize_ticker_for_provider


def test_brk_dot_b_normalizes_for_ibkr():
    result = normalize_ticker_for_provider("BRK.B", "ibkr")

    assert result["ok"] is True
    assert result["original_ticker"] == "BRK.B"
    assert result["normalized_ticker"] == "BRK B"
    assert result["warnings"]


def test_brk_dash_and_space_forms_normalize_for_ibkr():
    assert normalize_ticker_for_provider("BRK-B", "ibkr")["normalized_ticker"] == "BRK B"
    assert normalize_ticker_for_provider("BRK B", "ibkr")["normalized_ticker"] == "BRK B"


def test_bf_class_share_normalizes_for_ibkr():
    assert normalize_ticker_for_provider("BF.B", "ibkr")["normalized_ticker"] == "BF B"
    assert normalize_ticker_for_provider("BF-B", "ibkr")["normalized_ticker"] == "BF B"


def test_empty_ticker_fails_cleanly():
    result = normalize_ticker_for_provider("", "ibkr")

    assert result["ok"] is False
    assert result["error"]

