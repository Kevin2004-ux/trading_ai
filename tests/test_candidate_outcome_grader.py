import sqlite3

from db.schema_manager import apply_pending_migrations
from learning import grade_mature_candidate_outcomes


def _insert_snapshot(db_path, **overrides):
    apply_pending_migrations(db_path)
    payload = {
        "root_run_id": "run-1",
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "actionability_status": "watchlist",
        "entry_price": 100.0,
        "target_price": 110.0,
        "stop_loss": 95.0,
        "snapshot_at": "2026-06-15T20:30:00+00:00",
        "created_at": "2026-06-15T20:30:00+00:00",
        "policy_version": "research_policy_v1_baseline",
        "plan_fingerprint": "plan",
    }
    payload.update(overrides)
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(f"INSERT INTO candidate_snapshots ({columns}) VALUES ({placeholders})", tuple(payload.values()))
        return cursor.lastrowid


def _bars(*rows):
    return {"ok": True, "bars": [dict(row) for row in rows]}


def test_horizon_not_graded_before_trading_session_matures(tmp_path):
    db_path = str(tmp_path / "pending.db")
    _insert_snapshot(db_path)

    result = grade_mature_candidate_outcomes(db_path=db_path, as_of="2026-06-15", horizons=[1], price_loader=lambda *_: _bars())

    assert result["ok"] is True
    assert result["pending_count"] == 1
    assert result["outcomes_created"] == 1


def test_stock_long_outcome_grading_calculates_return_mfe_mae_and_hits(tmp_path):
    db_path = str(tmp_path / "long.db")
    _insert_snapshot(db_path)

    result = grade_mature_candidate_outcomes(
        db_path=db_path,
        as_of="2026-06-22",
        horizons=[3],
        price_loader=lambda *_: _bars(
            {"date": "2026-06-16", "high": 106, "low": 99, "close": 104},
            {"date": "2026-06-17", "high": 111, "low": 103, "close": 110},
            {"date": "2026-06-18", "high": 112, "low": 105, "close": 111},
        ),
    )

    assert result["stock_outcome_count"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT forward_return, maximum_favorable_excursion, maximum_adverse_excursion, target_hit, first_hit_result FROM candidate_forward_outcomes").fetchone()
    assert round(row[0], 4) == 0.11
    assert round(row[1], 4) == 0.12
    assert round(row[2], 4) == -0.01
    assert row[3] == 1
    assert row[4] == "target"


def test_stock_short_outcome_grading_uses_short_direction(tmp_path):
    db_path = str(tmp_path / "short.db")
    _insert_snapshot(db_path, ticker="TSLA", direction="short", entry_price=100, target_price=90, stop_loss=105)

    grade_mature_candidate_outcomes(
        db_path=db_path,
        as_of="2026-06-22",
        horizons=[3],
        price_loader=lambda *_: _bars(
            {"date": "2026-06-16", "high": 101, "low": 96, "close": 97},
            {"date": "2026-06-17", "high": 98, "low": 89, "close": 91},
        ),
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT forward_return, target_hit, first_hit_result FROM candidate_forward_outcomes").fetchone()
    assert round(row[0], 4) == 0.09
    assert row[1] == 1
    assert row[2] == "target"


def test_same_bar_target_and_stop_marks_ambiguous(tmp_path):
    db_path = str(tmp_path / "ambiguous.db")
    _insert_snapshot(db_path)

    result = grade_mature_candidate_outcomes(
        db_path=db_path,
        as_of="2026-06-22",
        horizons=[1],
        price_loader=lambda *_: _bars({"date": "2026-06-16", "high": 111, "low": 94, "close": 100}),
    )

    assert result["ambiguous_count"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT ambiguous, first_hit_result FROM candidate_forward_outcomes").fetchone()
    assert row == (1, "ambiguous")


def test_option_without_price_history_is_underlying_only_not_exact_option_performance(tmp_path):
    db_path = str(tmp_path / "option_underlying.db")
    _insert_snapshot(db_path, asset_type="option", option_contract="AAPL260717C00100000", mid=4.0, underlying_price=100)

    result = grade_mature_candidate_outcomes(
        db_path=db_path,
        as_of="2026-06-22",
        horizons=[1],
        price_loader=lambda *_: {"ok": True, "option_price_history_available": False, "bars": [{"date": "2026-06-16", "high": 105, "low": 99, "close": 103}]},
    )

    assert result["underlying_only_option_count"] == 1
    assert result["exact_option_outcome_count"] == 0


def test_option_with_price_history_allows_exact_option_grading(tmp_path):
    db_path = str(tmp_path / "option_exact.db")
    _insert_snapshot(db_path, asset_type="option", option_contract="AAPL260717C00100000", mid=4.0, underlying_price=100)

    result = grade_mature_candidate_outcomes(
        db_path=db_path,
        as_of="2026-06-22",
        horizons=[1],
        price_loader=lambda *_: {"ok": True, "option_price_history_available": True, "bars": [{"date": "2026-06-16", "high": 5, "low": 3.5, "close": 4.5}]},
    )

    assert result["exact_option_outcome_count"] == 1
    assert result["underlying_only_option_count"] == 0


def test_outcome_grading_is_idempotent(tmp_path):
    db_path = str(tmp_path / "idempotent.db")
    _insert_snapshot(db_path)
    loader = lambda *_: _bars({"date": "2026-06-16", "high": 105, "low": 99, "close": 102})

    first = grade_mature_candidate_outcomes(db_path=db_path, as_of="2026-06-22", horizons=[1], price_loader=loader)
    second = grade_mature_candidate_outcomes(db_path=db_path, as_of="2026-06-22", horizons=[1], price_loader=loader)

    assert first["outcomes_created"] == 1
    assert second["outcomes_created"] == 0
    assert second["outcomes_updated"] == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_forward_outcomes").fetchone()[0] == 1
