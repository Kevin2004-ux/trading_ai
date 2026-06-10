import sqlite3

from tracking.outcome_grader import (
    determine_stock_outcome,
    grade_recommendation,
    update_open_recommendations,
)
from tracking.trade_logger import get_recommendation, init_trade_tracking_db, log_recommendation


def _recommendation(**overrides):
    recommendation = {
        "id": 1,
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "entry_price": 100.0,
        "target_price": 110.0,
        "stop_loss": 95.0,
        "created_at": "2026-06-01T00:00:00+00:00",
        "holding_period_days": 5,
    }
    recommendation.update(overrides)
    return recommendation


def _bars(rows):
    return [
        {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        for timestamp, open_, high, low, close, volume in rows
    ]


def test_long_stock_hits_target_before_stop_is_win():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 106, 99, 105, 1000),
            ("2026-06-03T00:00:00+00:00", 105, 111, 104, 110, 1000),
        ]
    )

    result = determine_stock_outcome(_recommendation(), bars)

    assert result["ok"] is True
    assert result["outcome"] == "win"
    assert result["exit_price"] == 110.0
    assert result["exit_reason"] == "target_hit"


def test_long_stock_hits_stop_before_target_is_loss():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 102, 94, 95, 1000),
            ("2026-06-03T00:00:00+00:00", 95, 111, 95, 110, 1000),
        ]
    )

    result = determine_stock_outcome(_recommendation(), bars)

    assert result["ok"] is True
    assert result["outcome"] == "loss"
    assert result["exit_price"] == 95.0
    assert result["exit_reason"] == "stop_loss_hit"


def test_same_bar_touches_target_and_stop_is_manual_review():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 112, 94, 103, 1000),
        ]
    )

    result = determine_stock_outcome(_recommendation(), bars)

    assert result["ok"] is True
    assert result["outcome"] == "manual_review"
    assert result["status"] == "manual_review"
    assert result["exit_reason"] == "target_and_stop_hit_same_bar"


def test_short_stock_hits_target_is_win():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 101, 88, 90, 1000),
        ]
    )

    result = determine_stock_outcome(
        _recommendation(direction="short", target_price=90.0, stop_loss=105.0),
        bars,
    )

    assert result["ok"] is True
    assert result["outcome"] == "win"
    assert result["exit_price"] == 90.0


def test_holding_period_passes_without_hit_is_expired():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 104, 97, 102, 1000),
            ("2026-06-04T00:00:00+00:00", 102, 103, 98, 101, 1000),
        ]
    )

    result = determine_stock_outcome(
        _recommendation(holding_period_days=2),
        bars,
        as_of="2026-06-04T00:00:00+00:00",
    )

    assert result["ok"] is True
    assert result["outcome"] == "expired"
    assert result["exit_reason"] == "holding_period_expired"


def test_still_inside_holding_period_without_hit_is_open():
    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 104, 97, 102, 1000),
        ]
    )

    result = determine_stock_outcome(
        _recommendation(holding_period_days=5),
        bars,
        as_of="2026-06-03T00:00:00+00:00",
    )

    assert result["ok"] is True
    assert result["outcome"] == "open"
    assert result["status"] == "open"


def test_malformed_recommendation_gives_clean_error():
    result = grade_recommendation({"id": 1, "ticker": "AAPL"}, historical_bars=[])

    assert result["ok"] is False
    assert "entry_price" in result["error"]


def test_update_open_recommendations_updates_terminal_outcomes_in_temp_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "trade_tracking.db")
    init_trade_tracking_db(db_path)

    recommendation = log_recommendation(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test_strategy",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        holding_period_days=5,
        created_at="2026-06-01T00:00:00+00:00",
        db_path=db_path,
    )

    bars = _bars(
        [
            ("2026-06-02T00:00:00+00:00", 100, 106, 99, 105, 1000),
            ("2026-06-03T00:00:00+00:00", 105, 111, 104, 110, 1000),
        ]
    )

    monkeypatch.setattr(
        "tracking.outcome_grader.get_historical_bars",
        lambda ticker, lookback_days=180: {
            "ok": True,
            "ticker": ticker,
            "source": "polygon",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "data": {"bars": bars},
            "error": None,
        },
    )

    summary = update_open_recommendations(db_path=db_path, as_of="2026-06-05T00:00:00+00:00")

    assert summary["ok"] is True
    assert summary["checked"] == 1
    assert summary["updated"] == 1
    assert summary["still_open"] == 0
    assert summary["manual_review"] == 0
    assert summary["results"][0]["outcome"] == "win"

    updated_recommendation = get_recommendation(recommendation["id"], db_path=db_path)
    assert updated_recommendation["status"] == "win"
    assert updated_recommendation["outcome"] == "win"

    with sqlite3.connect(db_path) as conn:
        trade_outcome_count = conn.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]
    assert trade_outcome_count == 1
