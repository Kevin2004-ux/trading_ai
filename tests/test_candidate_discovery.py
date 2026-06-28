import sqlite3

from discovery import discover_candidates
from discovery.candidate_discovery import (
    discover_database_recent_candidates,
    discover_liquid_fallback_candidates,
    discover_manual_hotlist_candidates,
)


def test_manual_hotlist_validates_dedupes_and_ranks_tickers():
    candidates, warnings = discover_manual_hotlist_candidates(
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
        env_value="aapl, msft, AAPL, bad!, nvda",
    )

    assert [row["ticker"] for row in candidates] == ["AAPL", "MSFT", "NVDA"]
    assert candidates[0]["discovery_score"] > candidates[1]["discovery_score"]
    assert candidates[0]["source_type"] == "manual_hotlist"
    assert candidates[0]["requires_live_validation"] is True
    assert any("BAD!" in warning for warning in warnings)


def test_fallback_universe_returns_deduped_discovery_metadata():
    candidates, warnings = discover_liquid_fallback_candidates(
        max_tickers=10,
        discovered_at="2026-06-28T12:00:00+00:00",
        universes=["active", "large_cap", "tech"],
    )

    tickers = [row["ticker"] for row in candidates]
    assert warnings == []
    assert len(tickers) == len(set(tickers))
    assert candidates
    assert all(row["source_type"] == "liquid_fallback" for row in candidates)
    assert all(row["discovery_score"] is not None for row in candidates)
    assert all(row["requires_live_validation"] is True for row in candidates)


def test_database_discovery_missing_schema_warns_without_failing(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    result = discover_candidates(
        db_path=str(db_path),
        requested_sources=["database_recent"],
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
    )

    assert result["ok"] is True
    assert result["discovered_count"] == 0
    assert result["tickers"] == []
    assert any("candidate_evaluations table is missing" in warning for warning in result["warnings"])


def test_database_discovery_uses_recent_local_candidate_rows(tmp_path):
    db_path = tmp_path / "candidates.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE candidate_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanner_run_id INTEGER,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                asset_type TEXT,
                direction TEXT,
                setup_type TEXT,
                passed_constraints INTEGER,
                score REAL,
                rank INTEGER,
                rejection_reason TEXT,
                failed_constraints_json TEXT,
                metrics_json TEXT,
                constraint_results_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO candidate_evaluations (
                scanner_run_id, created_at, ticker, asset_type, direction, setup_type,
                passed_constraints, score, rank, rejection_reason, metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "2026-06-28T11:00:00+00:00",
                "AAPL",
                "stock",
                "long",
                "momentum_breakout",
                1,
                82,
                2,
                "",
                '{"relative_volume": 1.8, "risk_reward": 2.4}',
            ),
        )

    candidates, warnings = discover_database_recent_candidates(
        db_path=str(db_path),
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
    )

    assert warnings == []
    assert candidates[0]["ticker"] == "AAPL"
    assert candidates[0]["source_type"] == "database_recent"
    assert candidates[0]["discovery_score"] > 0
    assert "opportunity_score" not in candidates[0]
    assert "score" not in candidates[0]
