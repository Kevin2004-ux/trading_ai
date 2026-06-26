from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import sqlite3
import uuid

from db.schema_manager import apply_pending_migrations

from .policy_registry import (
    POLICY_PROPOSAL_VERSION,
    active_policy_defaults,
    get_shadow_policies,
    insert_shadow_policy,
    policy_fingerprint,
    validate_research_policy,
)
from .walk_forward import evaluate_policy_walk_forward, rescore_saved_components


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _load_json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    for key in (
        "candidate_policy_json",
        "walk_forward_config_json",
        "train_metrics_json",
        "validation_metrics_json",
        "test_metrics_json",
        "comparison_metrics_json",
        "sample_sizes_json",
        "warnings_json",
        "rejection_reasons_json",
        "promotion_eligibility_json",
    ):
        if key in payload:
            payload[key] = _load_json(payload[key], {})
    return payload


def _store_evaluation(
    conn: sqlite3.Connection,
    *,
    proposal_id: int | None,
    baseline_policy_version: str,
    evaluation: dict,
) -> str:
    now = _now_iso()
    evaluation_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO policy_evaluations (
            evaluation_id, proposal_id, baseline_policy_version, candidate_policy_json,
            candidate_fingerprint, evaluation_status, walk_forward_config_json,
            train_metrics_json, validation_metrics_json, test_metrics_json,
            comparison_metrics_json, sample_sizes_json, warnings_json,
            rejection_reasons_json, promotion_eligibility_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evaluation_id,
            proposal_id,
            baseline_policy_version,
            _json(evaluation.get("candidate_policy")),
            evaluation.get("candidate_fingerprint"),
            evaluation.get("status"),
            _json(evaluation.get("configuration")),
            _json(evaluation.get("aggregate_train_metrics")),
            _json(evaluation.get("aggregate_validation_metrics")),
            _json(evaluation.get("aggregate_test_metrics")),
            _json(evaluation.get("baseline_comparison")),
            _json(
                {
                    "train": evaluation.get("aggregate_train_metrics", {}).get("sample_count", 0),
                    "validation": evaluation.get("aggregate_validation_metrics", {}).get("sample_count", 0),
                    "test": evaluation.get("aggregate_test_metrics", {}).get("sample_count", 0),
                }
            ),
            _json(evaluation.get("warnings")),
            _json(evaluation.get("promotion_eligibility", {}).get("blocking_reasons", [])),
            _json(evaluation.get("promotion_eligibility")),
            now,
            now,
        ),
    )
    return evaluation_id


def create_policy_proposal(
    proposed_policy: dict,
    baseline_policy_version: str | None = None,
    created_by: str = "user",
    db_path: str = "strategy_library.db",
) -> dict:
    validation = validate_research_policy(proposed_policy)
    if not validation.get("ok"):
        return {"ok": False, "proposal": None, "evaluation": {}, "errors": validation.get("errors", []), "warnings": []}
    try:
        apply_pending_migrations(db_path)
        active = active_policy_defaults(db_path)
        baseline = baseline_policy_version or active.get("active_policy_version", "")
        fingerprint = validation["fingerprint"]
        evaluation = evaluate_policy_walk_forward(validation["policy"], baseline_policy_version=baseline, db_path=db_path)
        now = _now_iso()
        with _connect(db_path) as conn:
            existing = conn.execute("SELECT * FROM policy_proposals WHERE candidate_fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return {"ok": True, "proposal": _row_to_dict(existing), "evaluation": evaluation, "duplicate": True, "errors": [], "warnings": ["Duplicate proposal fingerprint returned existing proposal."]}
            cursor = conn.execute(
                """
                INSERT INTO policy_proposals (
                    proposal_version, baseline_policy_version, candidate_policy_json,
                    candidate_fingerprint, status, walk_forward_config_json,
                    train_metrics_json, validation_metrics_json, test_metrics_json,
                    comparison_metrics_json, sample_sizes_json, warnings_json,
                    rejection_reasons_json, promotion_eligibility_json,
                    created_at, updated_at, created_by
                ) VALUES (?, ?, ?, ?, 'shadow', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    POLICY_PROPOSAL_VERSION,
                    baseline,
                    _json(validation["policy"]),
                    fingerprint,
                    _json(evaluation.get("configuration")),
                    _json(evaluation.get("aggregate_train_metrics")),
                    _json(evaluation.get("aggregate_validation_metrics")),
                    _json(evaluation.get("aggregate_test_metrics")),
                    _json(evaluation.get("baseline_comparison")),
                    _json(
                        {
                            "train": evaluation.get("aggregate_train_metrics", {}).get("sample_count", 0),
                            "validation": evaluation.get("aggregate_validation_metrics", {}).get("sample_count", 0),
                            "test": evaluation.get("aggregate_test_metrics", {}).get("sample_count", 0),
                        }
                    ),
                    _json(evaluation.get("warnings")),
                    _json(evaluation.get("promotion_eligibility", {}).get("blocking_reasons", [])),
                    _json(evaluation.get("promotion_eligibility")),
                    now,
                    now,
                    created_by,
                ),
            )
            proposal_id = int(cursor.lastrowid)
            evaluation_id = _store_evaluation(conn, proposal_id=proposal_id, baseline_policy_version=baseline, evaluation=evaluation)
            conn.execute("UPDATE policy_proposals SET evaluation_id = ?, updated_at = ? WHERE id = ?", (evaluation_id, _now_iso(), proposal_id))
            row = conn.execute("SELECT * FROM policy_proposals WHERE id = ?", (proposal_id,)).fetchone()
        shadow = insert_shadow_policy(validation["policy"], baseline_policy_version=baseline, created_by=created_by, db_path=db_path)
        warnings = list(evaluation.get("warnings", []))
        if not shadow.get("ok"):
            warnings.extend(shadow.get("errors", []))
        return {"ok": True, "proposal": _row_to_dict(row), "evaluation": evaluation, "duplicate": False, "shadow_policy": shadow.get("policy"), "errors": [], "warnings": warnings}
    except sqlite3.Error as exc:
        return {"ok": False, "proposal": None, "evaluation": {}, "duplicate": False, "errors": [str(exc)], "warnings": []}


def list_policy_proposals(db_path: str = "strategy_library.db", limit: int = 50) -> dict:
    try:
        apply_pending_migrations(db_path)
        safe_limit = max(1, min(int(limit), 200))
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM policy_proposals ORDER BY id DESC LIMIT ?", (safe_limit,)).fetchall()
        return {"ok": True, "proposals": [_row_to_dict(row) for row in rows], "count": len(rows), "errors": []}
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"ok": False, "proposals": [], "count": 0, "errors": [str(exc)]}


def legacy_optimizer_diagnostics() -> dict:
    return {
        "ok": True,
        "diagnostics_version": "legacy_optimizer_safety_v1",
        "paths": {
            "backtest.py": {
                "status": "legacy_unsafe",
                "reason": "Not proven point-in-time safe for active policy promotion.",
            },
            "meta_controller/optimizer.py": {
                "status": "legacy_unsafe",
                "reason": "Legacy optimizer is isolated from production promotion governance.",
            },
            "meta_controller/main_controller.py": {
                "status": "research_only",
                "reason": "SQLite strategy experiments remain separate from active research policies.",
            },
            "meta_controller/automl.py": {
                "status": "legacy_unsafe",
                "reason": "AutoML is not connected to active scans or manual promotion.",
            },
        },
        "production_promotion_allowed": False,
        "warnings": ["Legacy optimizers are not used by active scans or policy promotion unless separately proven point-in-time safe."],
        "errors": [],
    }


def record_shadow_policy_scores(db_path: str = "strategy_library.db", limit_policies: int = 5) -> dict:
    response = {
        "ok": True,
        "shadow_scoring_version": "shadow_policy_scores_v1",
        "policies_evaluated": 0,
        "snapshots_considered": 0,
        "scores_recorded": 0,
        "visible_ranking_changed": False,
        "provider_calls_made": 0,
        "trade_logs_created": 0,
        "warnings": [],
        "errors": [],
    }
    try:
        apply_pending_migrations(db_path)
        shadows = get_shadow_policies(db_path, limit=limit_policies)
        policies = shadows.get("policies", [])
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM candidate_snapshots ORDER BY snapshot_at ASC, id ASC").fetchall()
            snapshots = []
            for row in rows:
                payload = dict(row)
                payload["opportunity_components"] = _load_json(payload.get("opportunity_components_json"), {})
                snapshots.append(payload)
            response["snapshots_considered"] = len(snapshots)
            active_ranked = sorted(
                snapshots,
                key=lambda item: item.get("opportunity_score") if item.get("opportunity_score") is not None else -1,
                reverse=True,
            )
            active_ranks = {int(row["id"]): index for index, row in enumerate(active_ranked, start=1)}
            for policy_row in policies:
                policy = policy_row.get("policy_json") or {}
                rescored, coverage = rescore_saved_components(snapshots, policy)
                response["policies_evaluated"] += 1
                ranked = sorted(
                    rescored,
                    key=lambda item: item.get("shadow_opportunity_score") if item.get("shadow_opportunity_score") is not None else -1,
                    reverse=True,
                )
                shadow_ranks = {int(row["id"]): index for index, row in enumerate(ranked, start=1)}
                for row in snapshots:
                    snapshot_id = int(row["id"])
                    shadow_score = next((item.get("shadow_opportunity_score") for item in rescored if int(item["id"]) == snapshot_id), None)
                    shadow_rank = shadow_ranks.get(snapshot_id)
                    active_rank = active_ranks.get(snapshot_id)
                    rank_change = (active_rank - shadow_rank) if active_rank is not None and shadow_rank is not None else None
                    conn.execute(
                        """
                        INSERT INTO shadow_policy_scores (
                            candidate_snapshot_id, policy_version, policy_fingerprint,
                            shadow_opportunity_score, shadow_rank, active_rank, rank_change,
                            created_at, score_components_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(candidate_snapshot_id, policy_fingerprint) DO UPDATE SET
                            shadow_opportunity_score = excluded.shadow_opportunity_score,
                            shadow_rank = excluded.shadow_rank,
                            active_rank = excluded.active_rank,
                            rank_change = excluded.rank_change,
                            created_at = excluded.created_at,
                            score_components_json = excluded.score_components_json
                        """,
                        (
                            snapshot_id,
                            policy_row.get("policy_version"),
                            policy_row.get("fingerprint"),
                            shadow_score,
                            shadow_rank,
                            active_rank,
                            rank_change,
                            _now_iso(),
                            _json({"coverage": coverage}),
                        ),
                    )
                    response["scores_recorded"] += 1
        return response
    except sqlite3.Error as exc:
        response["ok"] = False
        response["errors"].append(str(exc))
        return response
