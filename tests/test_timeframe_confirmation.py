from analytics.timeframe_confirmation import (
    build_timeframe_features,
    evaluate_timeframe_confirmation,
)


def _trend_bars(start: float = 100.0, step: float = 1.0, count: int = 220) -> list[dict]:
    rows = []
    for index in range(count):
        close = start + (step * index)
        rows.append(
            {
                "timestamp": f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1_000_000 + (index * 1000),
            }
        )
    return rows


def test_daily_weekly_uptrend_confirms_long_candidate():
    daily = _trend_bars(step=1.0)
    weekly = _trend_bars(start=90.0, step=2.0, count=60)

    result = evaluate_timeframe_confirmation({"ticker": "AAPL", "direction": "long"}, daily, weekly)

    assert result["ok"] is True
    assert result["confirmation_status"] == "confirmed"
    assert result["daily_trend"] == "uptrend"
    assert result["weekly_trend"] == "uptrend"
    assert result["score_adjustment"] > 0


def test_daily_weekly_downtrend_rejects_long_candidate():
    daily = _trend_bars(start=300.0, step=-1.0)
    weekly = _trend_bars(start=250.0, step=-2.0, count=60)

    result = evaluate_timeframe_confirmation({"ticker": "AAPL", "direction": "long"}, daily, weekly)

    assert result["confirmation_status"] == "rejected"
    assert result["risk_multiplier"] == 0.0


def test_daily_aligns_but_weekly_missing_returns_neutral_warning():
    daily = _trend_bars(step=1.0)

    result = evaluate_timeframe_confirmation({"ticker": "AAPL", "direction": "long"}, daily, weekly_history=None)

    assert result["confirmation_status"] == "neutral"
    assert result["daily_alignment"] is True
    assert result["weekly_trend"] == "unknown"
    assert result["warnings"]


def test_strong_timeframe_conflict_rejects_when_configured():
    daily = _trend_bars(start=300.0, step=-1.0)
    weekly = _trend_bars(start=250.0, step=-2.0, count=60)

    result = evaluate_timeframe_confirmation(
        {"ticker": "AAPL", "direction": "long"},
        daily,
        weekly,
        config={"reject_strong_conflict": True},
    )

    assert result["confirmation_status"] == "rejected"


def test_build_timeframe_features_handles_missing_history_cleanly():
    features = build_timeframe_features([])

    assert features["ok"] is False
    assert features["daily_trend"] == "unknown"
    assert features["errors"]
