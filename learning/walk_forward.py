from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import math
import sqlite3

from db.schema_manager import apply_pending_migrations

from .performance_evaluator import DEFAULT_MIN_SAMPLE_SIZE, compute_metrics
from .policy_registry import active_policy_defaults, policy_fingerprint, validate_research_policy


WALK_FORWARD_VERSION = "policy_walk_forward_v1"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _load_json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _default_config(config: dict | None = None) -> dict:
    raw = config if isinstance(config, dict) else {}
    return {
        "horizon_sessions": int(raw.get("horizon_sessions", 10)),
        "minimum_overall_sample_size": int(raw.get("minimum_overall_sample_size", DEFAULT_MIN_SAMPLE_SIZE)),
        "minimum_train_sample_size": int(raw.get("minimum_train_sample_size", DEFAULT_MIN_SAMPLE_SIZE)),
        "minimum_validation_sample_size": int(raw.get("minimum_validation_sample_size", DEFAULT_MIN_SAMPLE_SIZE)),
        "minimum_test_sample_size": int(raw.get("minimum_test_sample_size", DEFAULT_MIN_SAMPLE_SIZE)),
        "validation_fraction": float(raw.get("validation_fraction", 0.2)),
        "test_fraction": float(raw.get("test_fraction", 0.2)),
        "purge_embargo_sessions": int(raw.get("purge_embargo_sessions", 0)),
        "window_mode": str(raw.get("window_mode", "expanding")),
        "objective": str(raw.get("objective", "average_forward_return")),
        "top_k": int(raw.get("top_k", 5)),
    }


def _fetch_rows(db_path: str, horizon_sessions: int) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.*, o.outcome_status, o.forward_return, o.maximum_favorable_excursion,
                o.maximum_adverse_excursion, o.target_hit, o.stop_hit, o.r_multiple,
                o.ambiguous, o.underlying_only, o.option_price_history_available
            FROM candidate_snapshots s
            JOIN candidate_forward_outcomes o ON o.candidate_snapshot_id = s.id
            WHERE o.horizon_sessions = ?
            ORDER BY s.snapshot_at ASC, s.id ASC
            """,
            (horizon_sessions,),
        ).fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        payload["opportunity_components"] = _load_json(payload.get("opportunity_components_json"), {})
        result.append(payload)
    return result


def _rescore_from_components(row: dict, weights: dict[str, float]) -> tuple[float | None, bool]:
    components = row.get("opportunity_components") or {}
    if not isinstance(components, dict) or not components:
        return None, False
    weighted = 0.0
    available_weight = 0.0
    for key, weight in weights.items():
        component = components.get(key)
        if not isinstance(component, dict):
            continue
        if not component.get("available"):
            continue
        score = _safe_float(component.get("score"))
        numeric_weight = _safe_float(weight)
        if score is None or numeric_weight is None:
            continue
        weighted += score * numeric_weight
        available_weight += numeric_weight
    if available_weight <= 0:
        return None, False
    return max(0.0, min(100.0, weighted / available_weight)), True


def rescore_saved_components(rows: list[dict], candidate_policy: dict) -> tuple[list[dict], dict]:
    stock_weights = candidate_policy.get("stock_opportunity_weights", {})
    option_weights = candidate_policy.get("option_opportunity_weights", {})
    rescored: list[dict] = []
    unsupported = 0
    for row in rows:
        updated = dict(row)
        weights = option_weights if str(row.get("asset_type")) == "option" else stock_weights
        score, supported = _rescore_from_components(row, weights)
        if supported:
            updated["shadow_opportunity_score"] = score
        else:
            unsupported += 1
            updated["shadow_opportunity_score"] = row.get("opportunity_score")
        updated["original_opportunity_score"] = row.get("opportunity_score")
        updated["opportunity_score"] = updated.get("shadow_opportunity_score")
        updated["original_actionability_status"] = row.get("actionability_status")
        updated["actionability_status"] = row.get("actionability_status")
        rescored.append(updated)
    return rescored, {"unsupported_rescore_count": unsupported, "coverage": 1 - unsupported / len(rows) if rows else 0}


def _split_rows(rows: list[dict], config: dict) -> tuple[list[dict], list[dict], list[dict], dict]:
    total = len(rows)
    test_size = max(1, int(total * config["test_fraction"])) if total else 0
    validation_size = max(1, int(total * config["validation_fraction"])) if total - test_size > 1 else 0
    train_end = max(0, total - validation_size - test_size)
    validation_start = train_end + config["purge_embargo_sessions"]
    validation_end = max(validation_start, total - test_size)
    test_start = validation_end + config["purge_embargo_sessions"]
    train = rows[:train_end]
    validation = rows[validation_start:validation_end]
    test = rows[test_start:]
    diagnostics = {
        "ordered": all(str(rows[index].get("snapshot_at")) <= str(rows[index + 1].get("snapshot_at")) for index in range(max(0, len(rows) - 1))),
        "train_end_index": train_end,
        "validation_start_index": validation_start,
        "validation_end_index": validation_end,
        "test_start_index": test_start,
        "purge_embargo_sessions": config["purge_embargo_sessions"],
    }
    return train, validation, test, diagnostics


def _comparison(candidate: dict, baseline: dict) -> dict:
    candidate_return = _safe_float(candidate.get("average_forward_return"))
    baseline_return = _safe_float(baseline.get("average_forward_return"))
    candidate_r = _safe_float(candidate.get("average_r_multiple"))
    baseline_r = _safe_float(baseline.get("average_r_multiple"))
    return {
        "average_forward_return_delta": (candidate_return - baseline_return) if candidate_return is not None and baseline_return is not None else None,
        "average_r_multiple_delta": (candidate_r - baseline_r) if candidate_r is not None and baseline_r is not None else None,
        "candidate_sample_count": candidate.get("sample_count", 0),
        "baseline_sample_count": baseline.get("sample_count", 0),
    }


def _eligibility(
    *,
    train_metrics: dict,
    validation_metrics: dict,
    test_metrics: dict,
    comparison: dict,
    coverage: dict,
    config: dict,
) -> dict:
    blocking: list[str] = []
    if train_metrics.get("sample_count", 0) < config["minimum_train_sample_size"]:
        blocking.append("Training sample size is insufficient.")
    if validation_metrics.get("sample_count", 0) < config["minimum_validation_sample_size"]:
        blocking.append("Validation sample size is insufficient.")
    if test_metrics.get("sample_count", 0) < config["minimum_test_sample_size"]:
        blocking.append("Untouched test sample size is insufficient.")
    if coverage.get("coverage", 0) < 0.8:
        blocking.append("Stored component coverage is inadequate for this policy proposal.")
    if comparison.get("average_forward_return_delta") is not None and comparison["average_forward_return_delta"] < -0.001:
        blocking.append("Candidate policy underperforms baseline on average forward return.")
    if test_metrics.get("ambiguity_count", 0) > max(1, test_metrics.get("sample_count", 0) * 0.2):
        blocking.append("Too many ambiguous test outcomes.")
    return {
        "promotion_eligible": not blocking,
        "blocking_reasons": blocking,
        "minimum_sample_requirements": {
            "overall": config["minimum_overall_sample_size"],
            "train": config["minimum_train_sample_size"],
            "validation": config["minimum_validation_sample_size"],
            "test": config["minimum_test_sample_size"],
        },
        "coverage": coverage,
        "manual_promotion_required": True,
        "automatic_promotion_allowed": False,
    }


def evaluate_policy_walk_forward(
    candidate_policy: dict,
    baseline_policy_version: str | None = None,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
) -> dict:
    configuration = _default_config(config)
    validation = validate_research_policy(candidate_policy)
    active = active_policy_defaults(db_path)
    response = {
        "ok": True,
        "evaluation_version": WALK_FORWARD_VERSION,
        "status": "failed",
        "baseline_policy_version": baseline_policy_version or active.get("active_policy_version", ""),
        "candidate_policy": validation.get("policy", {}),
        "candidate_fingerprint": validation.get("fingerprint", ""),
        "configuration": configuration,
        "folds": [],
        "aggregate_train_metrics": {},
        "aggregate_validation_metrics": {},
        "aggregate_test_metrics": {},
        "baseline_comparison": {},
        "promotion_eligibility": {"promotion_eligible": False, "blocking_reasons": []},
        "warnings": [],
        "errors": [],
    }
    if not validation.get("ok"):
        response["errors"].extend(validation.get("errors", []))
        return response
    try:
        apply_pending_migrations(db_path)
        rows = _fetch_rows(db_path, configuration["horizon_sessions"])
        total_min = configuration["minimum_train_sample_size"] + configuration["minimum_validation_sample_size"] + configuration["minimum_test_sample_size"]
        if len(rows) < max(configuration["minimum_overall_sample_size"], total_min):
            response["status"] = "insufficient_data"
            response["promotion_eligibility"] = {
                "promotion_eligible": False,
                "blocking_reasons": ["Insufficient point-in-time outcome history for walk-forward evaluation."],
                "minimum_sample_requirements": {
                    "overall": configuration["minimum_overall_sample_size"],
                    "train": configuration["minimum_train_sample_size"],
                    "validation": configuration["minimum_validation_sample_size"],
                    "test": configuration["minimum_test_sample_size"],
                },
            }
            return response
        train, validation_rows, test, diagnostics = _split_rows(rows, configuration)
        if not diagnostics["ordered"]:
            response["status"] = "failed"
            response["errors"].append("Chronological ordering failed; refusing walk-forward evaluation.")
            return response
        rescored_train, train_coverage = rescore_saved_components(train, response["candidate_policy"])
        rescored_validation, validation_coverage = rescore_saved_components(validation_rows, response["candidate_policy"])
        rescored_test, test_coverage = rescore_saved_components(test, response["candidate_policy"])
        baseline_train = compute_metrics(train, minimum_sample_size=configuration["minimum_train_sample_size"], top_k=configuration["top_k"])
        baseline_validation = compute_metrics(validation_rows, minimum_sample_size=configuration["minimum_validation_sample_size"], top_k=configuration["top_k"])
        baseline_test = compute_metrics(test, minimum_sample_size=configuration["minimum_test_sample_size"], top_k=configuration["top_k"])
        train_metrics = compute_metrics(rescored_train, minimum_sample_size=configuration["minimum_train_sample_size"], top_k=configuration["top_k"])
        validation_metrics = compute_metrics(rescored_validation, minimum_sample_size=configuration["minimum_validation_sample_size"], top_k=configuration["top_k"])
        test_metrics = compute_metrics(rescored_test, minimum_sample_size=configuration["minimum_test_sample_size"], top_k=configuration["top_k"])
        comparison = {
            "train": _comparison(train_metrics, baseline_train),
            "validation": _comparison(validation_metrics, baseline_validation),
            "test": _comparison(test_metrics, baseline_test),
        }
        coverage = {
            "train": train_coverage,
            "validation": validation_coverage,
            "test": test_coverage,
            "coverage": min(train_coverage.get("coverage", 0), validation_coverage.get("coverage", 0), test_coverage.get("coverage", 0)),
        }
        eligibility = _eligibility(
            train_metrics=train_metrics,
            validation_metrics=validation_metrics,
            test_metrics=test_metrics,
            comparison=comparison["test"],
            coverage=coverage,
            config=configuration,
        )
        response.update(
            {
                "status": "completed",
                "folds": [
                    {
                        "fold_number": 1,
                        "window_mode": configuration["window_mode"],
                        "train_start": train[0].get("snapshot_at") if train else None,
                        "train_end": train[-1].get("snapshot_at") if train else None,
                        "validation_start": validation_rows[0].get("snapshot_at") if validation_rows else None,
                        "validation_end": validation_rows[-1].get("snapshot_at") if validation_rows else None,
                        "test_start": test[0].get("snapshot_at") if test else None,
                        "test_end": test[-1].get("snapshot_at") if test else None,
                        "purge_embargo_sessions": configuration["purge_embargo_sessions"],
                    }
                ],
                "aggregate_train_metrics": train_metrics,
                "aggregate_validation_metrics": validation_metrics,
                "aggregate_test_metrics": test_metrics,
                "baseline_comparison": comparison,
                "promotion_eligibility": eligibility,
            }
        )
        if not eligibility.get("promotion_eligible"):
            response["warnings"].extend(eligibility.get("blocking_reasons", []))
        return response
    except sqlite3.Error as exc:
        response["errors"].append(str(exc))
        return response
