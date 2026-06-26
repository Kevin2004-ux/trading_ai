import sqlite3
from datetime import date, timedelta

from db.schema_manager import apply_pending_migrations
from learning import build_baseline_policy, evaluate_policy_walk_forward, rescore_saved_components


def _seed_outcomes(db_path, count=12):
    apply_pending_migrations(db_path)
    start = date(2026, 1, 2)
    with sqlite3.connect(db_path) as conn:
        for index in range(count):
            snapshot_at = (start + timedelta(days=index)).isoformat()
            components = {
                "engine_core": {"score": 50 + index, "weight": 0.5, "available": True},
                "relative_strength": {"score": 100 - index, "weight": 0.5, "available": True},
            }
            cursor = conn.execute(
                """
                INSERT INTO candidate_snapshots (
                    root_run_id, ticker, asset_type, direction, actionability_status,
                    opportunity_score, opportunity_components_json, snapshot_at,
                    created_at, policy_version, plan_fingerprint
                ) VALUES (?, ?, 'stock', 'long', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "run",
                    f"T{index}",
                    "watchlist" if index % 2 else "blocked",
                    50 + index,
                    __import__("json").dumps(components),
                    snapshot_at,
                    snapshot_at,
                    "research_policy_v1_baseline",
                    "plan",
                ),
            )
            conn.execute(
                """
                INSERT INTO candidate_forward_outcomes (
                    candidate_snapshot_id, horizon_sessions, horizon_maturity_date,
                    graded_at, outcome_status, starting_price, ending_price,
                    forward_return, maximum_favorable_excursion, maximum_adverse_excursion,
                    target_hit, stop_hit, r_multiple, warnings_json, errors_json
                ) VALUES (?, 5, ?, ?, 'graded', 100, ?, ?, ?, ?, 0, 0, ?, '[]', '[]')
                """,
                (
                    cursor.lastrowid,
                    snapshot_at,
                    snapshot_at,
                    100 + index,
                    index / 100,
                    index / 90,
                    -index / 200,
                    index / 10,
                ),
            )


def test_walk_forward_returns_insufficient_data_without_relaxing_thresholds(tmp_path):
    db_path = str(tmp_path / "insufficient.db")
    _seed_outcomes(db_path, count=4)

    result = evaluate_policy_walk_forward(build_baseline_policy(), db_path=db_path, config={"horizon_sessions": 5})

    assert result["status"] == "insufficient_data"
    assert result["promotion_eligibility"]["promotion_eligible"] is False
    assert "Insufficient" in result["promotion_eligibility"]["blocking_reasons"][0]


def test_walk_forward_splits_are_chronological_and_embargoed(tmp_path):
    db_path = str(tmp_path / "walk.db")
    _seed_outcomes(db_path, count=12)
    policy = build_baseline_policy()
    policy["stock_opportunity_weights"] = {
        **policy["stock_opportunity_weights"],
        "engine_core": 0.9,
        "relative_strength": 0.1,
    }

    result = evaluate_policy_walk_forward(
        policy,
        db_path=db_path,
        config={
            "horizon_sessions": 5,
            "minimum_overall_sample_size": 6,
            "minimum_train_sample_size": 2,
            "minimum_validation_sample_size": 2,
            "minimum_test_sample_size": 2,
            "purge_embargo_sessions": 1,
        },
    )

    fold = result["folds"][0]
    assert result["status"] == "completed"
    assert fold["train_end"] < fold["validation_start"]
    assert fold["validation_end"] < fold["test_start"]
    assert fold["purge_embargo_sessions"] == 1
    assert result["promotion_eligibility"]["automatic_promotion_allowed"] is False


def test_weight_rescoring_changes_research_score_without_status_or_eligibility_change():
    rows = [
        {
            "id": 1,
            "asset_type": "stock",
            "actionability_status": "blocked",
            "opportunity_score": 50,
            "opportunity_components": {
                "engine_core": {"score": 40, "available": True},
                "relative_strength": {"score": 90, "available": True},
            },
        }
    ]
    policy = build_baseline_policy()
    policy["stock_opportunity_weights"] = {
        **policy["stock_opportunity_weights"],
        "engine_core": 0.0,
        "relative_strength": 1.0,
    }

    rescored, coverage = rescore_saved_components(rows, policy)

    assert rescored[0]["shadow_opportunity_score"] == 90
    assert rescored[0]["actionability_status"] == "blocked"
    assert rescored[0]["original_actionability_status"] == "blocked"
    assert coverage["coverage"] == 1
