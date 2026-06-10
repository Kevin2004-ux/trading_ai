import sqlite3

from scanner.scan_profiles import get_default_scan_profiles, get_scan_profile
from scanner.swing_scanner import scan_multi_strategy_candidates
from tools.agent_tools import scan_candidates_tool


def _market_snapshot(
    ticker: str,
    *,
    current_price: float = 120.0,
    sma_20: float = 119.0,
    sma_50: float = 110.0,
    sma_200: float = 100.0,
    high_20: float = 121.0,
    low_20: float = 108.0,
    atr_14: float = 2.0,
    atr_percent: float = 2.5,
    average_volume_20: float = 2_000_000,
    relative_volume: float = 1.8,
    daily_return: float = 1.2,
    rsi_14: float = 58.0,
    freshness_label: str = "fresh",
) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "source": "polygon",
        "timestamp": "2026-06-05T12:00:00+00:00",
        "error": None,
        "data": {
            "quote": {
                "last_price": current_price,
                "previous_close": current_price - 1.0,
                "day_volume": average_volume_20,
                "last_trade_timestamp": "2026-06-05T12:00:00+00:00",
            },
            "quote_error": None,
            "bars": [],
            "row_count": 180,
            "technical_snapshot": {
                "ok": True,
                "error": None,
                "current_price": current_price,
                "previous_close": current_price - 1.0,
                "daily_return": daily_return,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
                "rsi_14": rsi_14,
                "macd": 1.5,
                "average_volume_20": average_volume_20,
                "relative_volume": relative_volume,
                "atr_14": atr_14,
                "atr_percent": atr_percent,
                "high_20": high_20,
                "low_20": low_20,
                "distance_from_20_sma": 0.8,
                "distance_from_50_sma": 5.0,
            },
            "data_freshness": {
                "ok": True,
                "error": None,
                "latest_bar_timestamp": "2026-06-05T00:00:00+00:00",
                "age_days": 0.0,
                "is_stale": False,
                "freshness_label": freshness_label,
            },
        },
    }


def test_default_scan_profiles_load_correctly():
    profiles = get_default_scan_profiles()

    assert "momentum_breakout" in profiles
    assert "trend_pullback" in profiles
    assert "oversold_reversal" in profiles
    assert "relative_strength" in profiles
    assert "catalyst_watch" in profiles
    assert profiles["momentum_breakout"]["minimum_score_to_recommend"] >= 80


def test_unknown_scan_profile_returns_clean_error():
    result = get_scan_profile("does_not_exist")

    assert result["ok"] is False
    assert "Unknown scan profile" in result["error"]
    assert "momentum_breakout" in result["available_profiles"]


def test_multi_strategy_scan_runs_multiple_profiles(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: _market_snapshot(ticker),
    )

    result = scan_multi_strategy_candidates(
        ["AAPL"],
        profiles=["momentum_breakout", "relative_strength"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["ok"] is True
    assert result["profiles_run"] == ["momentum_breakout", "relative_strength"]
    assert result["total_profile_evaluations"] == 2
    assert "momentum_breakout" in result["candidates_by_profile"]
    assert "relative_strength" in result["candidates_by_profile"]


def test_same_ticker_matching_multiple_profiles_is_deduplicated(monkeypatch, tmp_path):
    snapshot = _market_snapshot(
        "AAPL",
        high_20=130.0,
        daily_return=2.5,
        relative_volume=2.1,
    )
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: snapshot,
    )

    result = scan_multi_strategy_candidates(
        ["AAPL"],
        profiles=["momentum_breakout", "relative_strength"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert len(result["best_candidates"]) == 1
    assert result["best_candidates"][0]["ticker"] == "AAPL"
    assert result["best_candidates"][0]["duplicate_reason"] is not None


def test_no_recommendable_candidates_returns_watchlist_candidates(monkeypatch, tmp_path):
    snapshot = _market_snapshot(
        "CAT",
        current_price=60.0,
        sma_20=60.2,
        sma_50=61.0,
        high_20=61.5,
        atr_14=1.0,
        atr_percent=1.8,
        relative_volume=0.95,
        daily_return=0.4,
        rsi_14=49.0,
    )
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: snapshot,
    )

    result = scan_multi_strategy_candidates(
        ["CAT"],
        profiles=["catalyst_watch"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["total_recommendable"] == 0
    assert result["total_watchlist"] >= 1
    assert result["best_candidates"]
    assert "watchlist names came closest" in result["message"]


def test_hard_safety_failures_still_reject_candidates(monkeypatch, tmp_path):
    weak_snapshot = _market_snapshot("PENNY", current_price=4.0)
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: weak_snapshot,
    )

    result = scan_multi_strategy_candidates(
        ["PENNY"],
        profiles=["momentum_breakout", "catalyst_watch"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["total_recommendable"] == 0
    assert result["total_watchlist"] == 0
    assert result["total_rejected"] == 1
    assert "minimum_price" in result["rejected_candidates"][0]["failed_constraints"]


def test_profile_specific_scoring_changes_the_winning_setup_type(monkeypatch, tmp_path):
    snapshot = _market_snapshot(
        "LEADER",
        high_20=130.0,
        daily_return=3.0,
        relative_volume=2.2,
    )
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: snapshot,
    )

    result = scan_multi_strategy_candidates(
        ["LEADER"],
        profiles=["momentum_breakout", "relative_strength"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["best_candidates"][0]["selected_profile"] == "relative_strength"
    assert result["best_candidates"][0]["scan_profile"] == "relative_strength"


def test_scanner_logs_candidate_evaluations_for_profile_runs(monkeypatch, tmp_path):
    db_path = str(tmp_path / "scanner.db")
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: _market_snapshot(ticker),
    )

    result = scan_multi_strategy_candidates(
        ["AAPL"],
        profiles=["momentum_breakout", "trend_pullback"],
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        candidate_count = conn.execute("SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0]
        scanner_run_count = conn.execute("SELECT COUNT(*) FROM scanner_runs").fetchone()[0]

    assert result["scanner_run_id"] is not None
    assert scanner_run_count == 1
    assert candidate_count == 2


def test_scan_candidates_tool_can_use_multi_strategy(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.scan_multi_strategy_candidates",
        lambda **kwargs: {
            "ok": True,
            "universe": "custom",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "profiles_run": ["momentum_breakout"],
            "total_tickers_scanned": 1,
            "total_profile_evaluations": 1,
            "total_recommendable": 1,
            "total_watchlist": 0,
            "total_rejected": 0,
            "best_candidates": [{"ticker": "AAPL"}],
            "candidates_by_profile": {"momentum_breakout": [{"ticker": "AAPL"}]},
            "watchlist_candidates": [],
            "rejected_candidates": [],
            "errors": [],
            "message": "Found 1 recommendable candidates.",
        },
    )

    result = scan_candidates_tool(["AAPL"], multi_strategy=True)

    assert result["ok"] is True
    assert result["data"]["profiles_run"] == ["momentum_breakout"]
