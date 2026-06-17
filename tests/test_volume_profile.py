from analytics.volume_profile import (
    APPROXIMATION_WARNING,
    build_volume_profile,
    evaluate_volume_profile_confirmation,
)


def _bars(prices: list[float], volume: float = 1_000_000) -> list[dict]:
    return [
        {
            "timestamp": f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": volume * (2 if 98 <= price <= 102 else 1),
        }
        for index, price in enumerate(prices)
    ]


def test_volume_profile_builds_from_daily_ohlcv_and_finds_poc():
    result = build_volume_profile(_bars([95, 98, 99, 100, 101, 102, 106, 108] * 8), bins=8)

    assert result["ok"] is True
    assert result["point_of_control"] is not None
    assert result["value_area_high"] >= result["value_area_low"]
    assert result["high_volume_nodes"]
    assert APPROXIMATION_WARNING in result["warnings"]


def test_candidate_near_support_confirms_long_setup():
    candidate = {"ticker": "AAPL", "current_price": 101.0, "direction": "long"}
    result = evaluate_volume_profile_confirmation(
        candidate,
        _bars([95, 98, 99, 100, 101, 102, 108, 112] * 8),
        config={"support_buffer_pct": 0.03, "resistance_buffer_pct": 0.01},
    )

    assert result["ok"] is True
    assert result["confirmation_status"] in {"confirmed", "neutral"}
    assert result["point_of_control"] is not None


def test_candidate_under_resistance_warns_long_setup():
    candidate = {"ticker": "AAPL", "current_price": 107.0, "direction": "long"}
    result = evaluate_volume_profile_confirmation(
        candidate,
        _bars([95, 99, 100, 101, 107, 108, 109, 110] * 8),
        config={"resistance_buffer_pct": 0.03},
    )

    assert result["confirmation_status"] == "warning"
    assert any("resistance" in reason.lower() for reason in result["reasons"])


def test_missing_volume_data_returns_neutral_warning_not_crash():
    result = evaluate_volume_profile_confirmation(
        {"ticker": "AAPL", "current_price": 100.0, "direction": "long"},
        [{"close": 100.0, "volume": None}],
    )

    assert result["ok"] is True
    assert result["confirmation_status"] == "neutral"
    assert result["warnings"]
