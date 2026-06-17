from options.iv_rank import calculate_iv_percentile, calculate_iv_rank, evaluate_iv_context


def test_iv_rank_calculates_correctly():
    result = calculate_iv_rank(0.3, [0.1, 0.2, 0.3, 0.4, 0.5])

    assert result["ok"] is True
    assert result["iv_rank"] == 50.0


def test_iv_percentile_calculates_correctly():
    result = calculate_iv_percentile(0.3, [0.1, 0.2, 0.3, 0.4, 0.5])

    assert result["ok"] is True
    assert result["iv_percentile"] == 60.0


def test_missing_iv_returns_unknown_and_blocks():
    result = evaluate_iv_context(None, [0.1, 0.2, 0.3])

    assert result["ok"] is False
    assert result["iv_context"] == "unknown"
    assert result["trade_bias"] == "unknown"


def test_cheap_iv_favors_long_premium():
    result = evaluate_iv_context(0.2, config={"iv_rank": 12})

    assert result["ok"] is True
    assert result["iv_context"] == "cheap"
    assert result["trade_bias"] == "long_premium_favorable"


def test_expensive_iv_favors_short_premium_and_warns_long_premium_layer():
    result = evaluate_iv_context(0.8, config={"iv_rank": 91})

    assert result["ok"] is True
    assert result["iv_context"] == "expensive"
    assert result["trade_bias"] == "short_premium_favorable"

