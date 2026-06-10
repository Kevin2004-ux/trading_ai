from analytics.relative_strength import (
    analyze_sector_strength,
    analyze_stock_relative_strength,
    apply_relative_strength_to_candidate,
)
from selector.weekly_selector import score_weekly_candidate


def _snapshot(
    ticker: str,
    *,
    current_price: float,
    sma_20: float,
    sma_50: float,
    daily_return: float,
    relative_volume: float,
    high_20: float,
) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "data": {
            "technical_snapshot": {
                "current_price": current_price,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "daily_return": daily_return,
                "relative_volume": relative_volume,
                "high_20": high_20,
                "distance_from_20_sma": ((current_price - sma_20) / sma_20) * 100.0 if sma_20 else None,
                "distance_from_50_sma": ((current_price - sma_50) / sma_50) * 100.0 if sma_50 else None,
            }
        },
    }


def _candidate() -> dict:
    return {
        "ticker": "AAPL",
        "score": 85.0,
        "risk_reward": 2.4,
        "relative_volume": 1.6,
        "why_this_profile_matched": ["Momentum and volume are aligned."],
        "quality_bucket": "A",
        "recommendation_status": "recommendable",
        "statistical_context": {"statistical_score": 70.0, "confidence_label": "medium"},
    }


def test_stock_outperforming_spy_and_qqq_returns_outperforming_or_market_leader():
    result = analyze_stock_relative_strength(
        "AAPL",
        _snapshot("AAPL", current_price=120, sma_20=116, sma_50=112, daily_return=2.1, relative_volume=1.8, high_20=121),
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=598, sma_50=595, daily_return=0.6, relative_volume=1.0, high_20=603),
        qqq_snapshot=_snapshot("QQQ", current_price=500, sma_20=497, sma_50=492, daily_return=0.8, relative_volume=1.1, high_20=504),
        sector_snapshot=_snapshot("XLK", current_price=220, sma_20=218, sma_50=215, daily_return=1.0, relative_volume=1.0, high_20=223),
        sector="Technology",
    )

    assert result["ok"] is True
    assert result["relative_strength_label"] in {"outperforming", "market_leader"}


def test_stock_underperforming_spy_and_qqq_returns_underperforming_or_laggard():
    result = analyze_stock_relative_strength(
        "AAPL",
        _snapshot("AAPL", current_price=120, sma_20=123, sma_50=125, daily_return=-1.8, relative_volume=0.8, high_20=127),
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=595, sma_50=590, daily_return=0.9, relative_volume=1.1, high_20=604),
        qqq_snapshot=_snapshot("QQQ", current_price=500, sma_20=496, sma_50=492, daily_return=1.1, relative_volume=1.2, high_20=503),
        sector_snapshot=_snapshot("XLK", current_price=220, sma_20=218, sma_50=215, daily_return=0.7, relative_volume=1.0, high_20=223),
        sector="Technology",
    )

    assert result["ok"] is True
    assert result["relative_strength_label"] in {"underperforming", "market_laggard"}


def test_missing_benchmark_data_returns_unknown_cleanly():
    result = analyze_stock_relative_strength("AAPL", _snapshot("AAPL", current_price=120, sma_20=118, sma_50=115, daily_return=1.0, relative_volume=1.4, high_20=122))

    assert result["ok"] is True
    assert result["relative_strength_label"] == "unknown"


def test_sector_strength_calculation_works():
    result = analyze_sector_strength(
        {
            "Technology": _snapshot("XLK", current_price=220, sma_20=218, sma_50=215, daily_return=1.2, relative_volume=1.1, high_20=223),
            "Energy": _snapshot("XLE", current_price=90, sma_20=92, sma_50=95, daily_return=-1.0, relative_volume=0.9, high_20=96),
        },
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=598, sma_50=595, daily_return=0.4, relative_volume=1.0, high_20=603),
    )

    assert result["ok"] is True
    assert result["strongest_sector"] == "Technology"
    assert result["weakest_sector"] == "Energy"


def test_apply_relative_strength_to_candidate_adds_context_and_risk_flags():
    weak_result = {
        "ok": True,
        "relative_strength_label": "market_laggard",
        "relative_strength_score": 20.0,
        "risk_flags": ["Stock is lagging the market on the day."],
    }

    enriched = apply_relative_strength_to_candidate(_candidate(), weak_result)

    assert enriched["relative_strength_context"]["relative_strength_label"] == "market_laggard"
    assert enriched["relative_strength_adjustment"] < 0
    assert enriched["relative_strength_risk_flags"]


def test_weekly_selector_boosts_strong_relative_strength_modestly():
    candidate = _candidate()
    candidate["relative_strength_context"] = {
        "relative_strength_label": "market_leader",
        "relative_strength_score": 88.0,
        "risk_flags": [],
    }

    boosted = score_weekly_candidate(candidate)
    candidate["relative_strength_context"] = {
        "relative_strength_label": "unknown",
        "relative_strength_score": 50.0,
        "risk_flags": [],
    }
    neutral = score_weekly_candidate(candidate)

    assert boosted > neutral


def test_weekly_selector_penalizes_weak_relative_strength_modestly():
    candidate = _candidate()
    candidate["relative_strength_context"] = {
        "relative_strength_label": "market_laggard",
        "relative_strength_score": 22.0,
        "risk_flags": ["Weak relative strength."],
    }
    weak = score_weekly_candidate(candidate)

    candidate["relative_strength_context"] = {
        "relative_strength_label": "unknown",
        "relative_strength_score": 50.0,
        "risk_flags": [],
    }
    neutral = score_weekly_candidate(candidate)

    assert weak < neutral
