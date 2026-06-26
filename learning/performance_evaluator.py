from __future__ import annotations

from statistics import median
from typing import Any
import json
import math
import sqlite3

from db.schema_manager import apply_pending_migrations


PERFORMANCE_EVALUATION_VERSION = "learning_performance_v1"
DEFAULT_MIN_SAMPLE_SIZE = 30


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


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        avg_rank = (index + end + 2) / 2.0
        for offset in range(index, end + 1):
            ranks[indexed[offset][0]] = avg_rank
        index = end + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    if mean_x is None or mean_y is None:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


def _spearman_score_return(rows: list[dict]) -> float | None:
    pairs = [
        (_safe_float(row.get("opportunity_score")), _safe_float(row.get("forward_return")))
        for row in rows
    ]
    pairs = [(score, ret) for score, ret in pairs if score is not None and ret is not None]
    if len(pairs) < 3:
        return None
    scores, returns = zip(*pairs)
    return _pearson(_rank(list(scores)), _rank(list(returns)))


def _confidence(sample_size: int, minimum: int) -> tuple[str, list[str]]:
    if sample_size < minimum:
        return "insufficient", [f"Sample size {sample_size} is below minimum required sample {minimum}."]
    if sample_size < minimum * 2:
        return "low", ["Sample size meets minimum but remains limited."]
    return "usable", []


def compute_metrics(rows: list[dict], minimum_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE, top_k: int = 5) -> dict:
    graded = [row for row in rows if row.get("outcome_status") == "graded"]
    returns = [_safe_float(row.get("forward_return")) for row in graded]
    returns = [value for value in returns if value is not None]
    mfe = [_safe_float(row.get("maximum_favorable_excursion")) for row in graded]
    mae = [_safe_float(row.get("maximum_adverse_excursion")) for row in graded]
    r_values = [_safe_float(row.get("r_multiple")) for row in graded]
    mfe = [value for value in mfe if value is not None]
    mae = [value for value in mae if value is not None]
    r_values = [value for value in r_values if value is not None]
    sample_size = len(graded)
    confidence, warnings = _confidence(sample_size, minimum_sample_size)
    ranked = sorted(graded, key=lambda row: _safe_float(row.get("opportunity_score")) or -1.0, reverse=True)
    top = ranked[: max(1, min(top_k, len(ranked)))]
    top_returns = [_safe_float(row.get("forward_return")) for row in top]
    top_returns = [value for value in top_returns if value is not None]
    quintile_size = max(1, len(ranked) // 5) if ranked else 0
    top_quintile = ranked[:quintile_size] if quintile_size else []
    bottom_quintile = ranked[-quintile_size:] if quintile_size else []
    top_quintile_returns = [_safe_float(row.get("forward_return")) for row in top_quintile]
    bottom_quintile_returns = [_safe_float(row.get("forward_return")) for row in bottom_quintile]
    top_quintile_returns = [value for value in top_quintile_returns if value is not None]
    bottom_quintile_returns = [value for value in bottom_quintile_returns if value is not None]
    by_status = {}
    for status in ("paper_eligible", "watchlist", "blocked", "research_only", "option_underlying_watchlist"):
        status_rows = [row for row in graded if str(row.get("actionability_status")) == status]
        values = [_safe_float(row.get("forward_return")) for row in status_rows]
        values = [value for value in values if value is not None]
        by_status[status] = {"sample_count": len(status_rows), "average_forward_return": _mean(values)}
    return {
        "sample_count": sample_size,
        "coverage": sample_size / len(rows) if rows else 0,
        "average_forward_return": _mean(returns),
        "median_forward_return": median(returns) if returns else None,
        "positive_return_rate": sum(1 for value in returns if value > 0) / len(returns) if returns else None,
        "average_mfe": _mean(mfe),
        "average_mae": _mean(mae),
        "target_hit_rate": sum(1 for row in graded if row.get("target_hit")) / sample_size if sample_size else None,
        "stop_hit_rate": sum(1 for row in graded if row.get("stop_hit")) / sample_size if sample_size else None,
        "average_r_multiple": _mean(r_values),
        "score_return_rank_correlation": _spearman_score_return(graded),
        "top_k_mean_return": _mean(top_returns),
        "top_k_positive_return_rate": sum(1 for value in top_returns if value > 0) / len(top_returns) if top_returns else None,
        "top_quintile_vs_bottom_quintile_spread": (
            (_mean(top_quintile_returns) or 0) - (_mean(bottom_quintile_returns) or 0)
            if top_quintile_returns and bottom_quintile_returns
            else None
        ),
        "actionability_status_comparison": by_status,
        "ambiguity_count": sum(1 for row in rows if row.get("ambiguous")),
        "unavailable_count": sum(1 for row in rows if row.get("outcome_status") == "unavailable"),
        "minimum_required_sample": minimum_sample_size,
        "confidence_status": confidence,
        "warnings": warnings,
    }


def _query_rows(db_path: str, horizon_sessions: int, start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    clauses = ["o.horizon_sessions = ?"]
    params: list[Any] = [horizon_sessions]
    if start_date:
        clauses.append("s.snapshot_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("s.snapshot_at <= ?")
        params.append(end_date)
    query = f"""
        SELECT
            s.*, o.outcome_status, o.forward_return, o.maximum_favorable_excursion,
            o.maximum_adverse_excursion, o.target_hit, o.stop_hit, o.r_multiple,
            o.ambiguous, o.underlying_only, o.option_price_history_available
        FROM candidate_snapshots s
        JOIN candidate_forward_outcomes o ON o.candidate_snapshot_id = s.id
        WHERE {' AND '.join(clauses)}
        ORDER BY s.snapshot_at ASC, s.id ASC
    """
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        payload = dict(row)
        payload["opportunity_components_json"] = _load_json(payload.get("opportunity_components_json"), {})
        payload["failed_constraints_json"] = _load_json(payload.get("failed_constraints_json"), [])
        payload["qualification_gaps_json"] = _load_json(payload.get("qualification_gaps_json"), [])
        result.append(payload)
    return result


def evaluate_performance(
    db_path: str = "strategy_library.db",
    horizon_sessions: int = 10,
    group_by: str = "policy_version",
    start_date: str | None = None,
    end_date: str | None = None,
    minimum_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> dict:
    allowed_groups = {
        "policy_version",
        "opportunity_score_version",
        "scan_profile",
        "setup_type",
        "market_regime",
        "actionability_status",
        "asset_type",
        "score_decile",
    }
    response = {
        "ok": True,
        "evaluation_version": PERFORMANCE_EVALUATION_VERSION,
        "horizon_sessions": horizon_sessions,
        "group_by": group_by,
        "start_date": start_date,
        "end_date": end_date,
        "groups": {},
        "overall": {},
        "warnings": [],
        "errors": [],
    }
    try:
        apply_pending_migrations(db_path)
        rows = _query_rows(db_path, horizon_sessions, start_date=start_date, end_date=end_date)
        response["overall"] = compute_metrics(rows, minimum_sample_size=minimum_sample_size)
        if group_by not in allowed_groups:
            response["warnings"].append(f"Unsupported group_by '{group_by}', using policy_version.")
            group_by = "policy_version"
            response["group_by"] = group_by
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            if group_by == "market_regime":
                context = _load_json(row.get("market_regime_context_json"), {})
                key = context.get("label") or context.get("regime") or "unknown"
            elif group_by == "score_decile":
                score = _safe_float(row.get("opportunity_score"))
                key = "unknown" if score is None else f"decile_{min(10, max(1, int(score // 10) + 1))}"
            else:
                key = str(row.get(group_by) or "unknown")
            grouped.setdefault(key, []).append(row)
        response["groups"] = {
            key: compute_metrics(group_rows, minimum_sample_size=minimum_sample_size)
            for key, group_rows in sorted(grouped.items())
        }
        return response
    except sqlite3.Error as exc:
        response["ok"] = False
        response["errors"].append(str(exc))
        return response
