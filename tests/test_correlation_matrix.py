import sqlite3
from datetime import datetime, timedelta, timezone

from risk.correlation_matrix import (
    build_correlation_matrix,
    get_latest_correlation_snapshot,
    refresh_correlation_snapshot,
    save_correlation_snapshot,
)


def _bars(start: float, moves: list[float], offset: float = 0.0) -> list[dict]:
    price = start
    rows = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, move in enumerate(moves):
        price = price * (1 + move + offset)
        rows.append(
            {
                "timestamp": (base + timedelta(days=index)).isoformat(),
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": round(price, 4),
                "volume": 1_000_000,
            }
        )
    return rows


def test_correlation_matrix_builds_from_price_history():
    moves = [0.01, -0.005, 0.012, -0.004, 0.006] * 15
    result = build_correlation_matrix(
        {
            "AAPL": _bars(100, moves),
            "MSFT": _bars(200, moves),
            "SPY": _bars(400, [-move for move in moves]),
        },
        lookback_days=60,
    )

    assert result["ok"] is True
    assert result["correlations"]["AAPL"]["MSFT"] > 0.99
    assert result["correlations"]["AAPL"]["SPY"] < -0.99


def test_missing_or_constant_history_warns_without_crashing():
    result = build_correlation_matrix(
        {
            "AAPL": [],
            "MSFT": _bars(100, [0.0] * 70),
        }
    )

    assert result["ok"] is False
    assert result["warnings"]
    assert result["errors"]


def test_correlation_snapshot_saves_and_loads(tmp_path):
    db_path = str(tmp_path / "correlation.db")
    matrix = {
        "ok": True,
        "lookback_days": 60,
        "tickers": ["AAPL", "MSFT"],
        "correlations": {"AAPL": {"AAPL": 1.0, "MSFT": 0.9}, "MSFT": {"AAPL": 0.9, "MSFT": 1.0}},
        "warnings": [],
        "errors": [],
    }

    saved = save_correlation_snapshot(db_path, matrix)
    loaded = get_latest_correlation_snapshot(db_path, max_age_hours=36)

    assert saved["ok"] is True
    assert loaded["ok"] is True
    assert loaded["snapshot"]["snapshot_id"] == saved["snapshot_id"]
    assert loaded["snapshot"]["matrix_json"]["AAPL"]["MSFT"] == 0.9


def test_stale_snapshot_is_detected(tmp_path):
    db_path = str(tmp_path / "stale.db")
    save_correlation_snapshot(
        db_path,
        {
            "ok": True,
            "lookback_days": 60,
            "tickers": ["AAPL"],
            "correlations": {"AAPL": {"AAPL": 1.0}},
            "warnings": [],
            "errors": [],
        },
    )
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE correlation_snapshots SET created_at = ?", (stale_time,))

    result = get_latest_correlation_snapshot(db_path, max_age_hours=36)

    assert result["ok"] is False
    assert result["is_stale"] is True


def test_refresh_correlation_snapshot_uses_provider_and_temp_db(tmp_path):
    db_path = str(tmp_path / "refresh.db")
    moves = [0.01, -0.005, 0.012, -0.004, 0.006] * 15

    def provider(ticker: str, lookback_days: int):
        return {"ok": True, "data": {"bars": _bars(100 if ticker == "AAPL" else 200, moves)}}

    result = refresh_correlation_snapshot(
        db_path=db_path,
        tickers=["AAPL", "MSFT"],
        price_history_provider=provider,
        lookback_days=60,
    )

    assert result["ok"] is True
    assert result["save_result"]["ok"] is True
    assert result["matrix"]["correlations"]["AAPL"]["MSFT"] > 0.99
