from __future__ import annotations

from collections import Counter, defaultdict
import json
import sqlite3
from typing import Any


TERMINAL_OUTCOMES = {"win", "loss", "expired", "manual_review"}


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _deserialize_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _extract_scan_profile(payloads: list[Any]) -> str | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("scan_profile", "selected_profile"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _load_recommendations(db_path: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            WITH latest_outcomes AS (
                SELECT t1.*
                FROM trade_outcomes t1
                INNER JOIN (
                    SELECT recommendation_id, MAX(id) AS max_id
                    FROM trade_outcomes
                    GROUP BY recommendation_id
                ) t2
                ON t1.recommendation_id = t2.recommendation_id
                AND t1.id = t2.max_id
            )
            SELECT
                tr.*,
                lo.realized_return AS latest_realized_return,
                lo.max_gain AS latest_max_gain,
                lo.max_drawdown AS latest_max_drawdown,
                lo.exit_reason AS latest_exit_reason,
                lo.grading_data_json AS latest_grading_data_json
            FROM trade_recommendations tr
            LEFT JOIN latest_outcomes lo
                ON lo.recommendation_id = tr.id
            ORDER BY tr.created_at ASC, tr.id ASC
            """
        ).fetchall()

    recommendations = []
    for row in rows:
        item = dict(row)
        for key in ("data_snapshot_json", "constraint_results_json", "model_outputs_json", "latest_grading_data_json"):
            if key in item:
                item[key] = _deserialize_json(item[key])
        item["scan_profile"] = _extract_scan_profile(
            [
                item.get("model_outputs_json"),
                item.get("data_snapshot_json"),
                item.get("constraint_results_json"),
                item.get("latest_grading_data_json"),
            ]
        )
        item["realized_return_value"] = _safe_float(item.get("latest_realized_return"))
        item["max_gain_value"] = _safe_float(item.get("latest_max_gain"))
        item["max_drawdown_value"] = _safe_float(item.get("latest_max_drawdown"))
        recommendations.append(item)
    return recommendations


def _load_candidate_evaluations(db_path: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM candidate_evaluations
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()

    evaluations = []
    for row in rows:
        item = dict(row)
        for key in ("failed_constraints_json", "metrics_json", "constraint_results_json"):
            item[key] = _deserialize_json(item.get(key))
        constraint_payload = item.get("constraint_results_json") if isinstance(item.get("constraint_results_json"), dict) else {}
        metrics_payload = item.get("metrics_json") if isinstance(item.get("metrics_json"), dict) else {}
        item["scan_profile"] = _extract_scan_profile([constraint_payload, metrics_payload])
        item["recommendation_status"] = constraint_payload.get("recommendation_status")
        item["risk_reward_value"] = _safe_float(metrics_payload.get("risk_reward"))
        item["score_value"] = _safe_float(item.get("score"))
        evaluations.append(item)
    return evaluations


def calculate_expectancy(
    wins: int,
    losses: int,
    avg_win_return: float,
    avg_loss_return: float,
) -> float:
    total = wins + losses
    if total <= 0:
        return 0.0
    win_rate = wins / total
    loss_rate = losses / total
    return (win_rate * avg_win_return) + (loss_rate * avg_loss_return)


def score_statistical_confidence(
    sample_size: int,
    win_rate: float | None,
    expectancy: float | None,
) -> dict:
    sample_component = min(max(sample_size, 0), 40) / 40.0 * 70.0
    win_component = 0.0 if win_rate is None else min(abs(win_rate - 0.5) * 200.0, 15.0)
    expectancy_component = 0.0 if expectancy is None else min(abs(expectancy) * 100.0, 15.0)
    statistical_score = round(min(100.0, sample_component + win_component + expectancy_component), 2)

    if sample_size < 5 or statistical_score < 40:
        confidence_label = "low"
    elif sample_size < 15 or statistical_score < 75:
        confidence_label = "medium"
    else:
        confidence_label = "high"

    return {
        "sample_size": sample_size,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "statistical_score": statistical_score,
        "confidence_label": confidence_label,
    }


def analyze_setup_performance(
    db_path: str = "strategy_library.db",
    min_sample_size: int = 5,
) -> dict:
    try:
        recommendations = _load_recommendations(db_path)
        closed = [
            recommendation
            for recommendation in recommendations
            if str(recommendation.get("outcome", "")).lower() in TERMINAL_OUTCOMES
        ]

        grouped: dict[tuple, list[dict]] = defaultdict(list)
        for recommendation in closed:
            key = (
                recommendation.get("strategy"),
                recommendation.get("setup_type"),
                recommendation.get("direction"),
                recommendation.get("asset_type"),
            )
            grouped[key].append(recommendation)

        groups = []
        for (strategy, setup_type, direction, asset_type), rows in grouped.items():
            wins = sum(1 for row in rows if str(row.get("outcome", "")).lower() == "win")
            losses = sum(1 for row in rows if str(row.get("outcome", "")).lower() == "loss")
            expired = sum(1 for row in rows if str(row.get("outcome", "")).lower() == "expired")
            manual_review = sum(1 for row in rows if str(row.get("outcome", "")).lower() == "manual_review")
            closed_sample = wins + losses
            win_rate = (wins / closed_sample) if closed_sample else None

            win_returns = [row["realized_return_value"] for row in rows if str(row.get("outcome", "")).lower() == "win"]
            loss_returns = [row["realized_return_value"] for row in rows if str(row.get("outcome", "")).lower() == "loss"]
            avg_realized_return = _mean([row["realized_return_value"] for row in rows])
            avg_win_return = _mean(win_returns)
            avg_loss_return = _mean(loss_returns)
            expectancy = None
            if closed_sample:
                expectancy = calculate_expectancy(
                    wins,
                    losses,
                    avg_win_return or 0.0,
                    avg_loss_return or 0.0,
                )
            confidence = score_statistical_confidence(len(rows), win_rate, expectancy)

            groups.append(
                {
                    "strategy": strategy,
                    "setup_type": setup_type,
                    "direction": direction,
                    "asset_type": asset_type,
                    "sample_size": len(rows),
                    "wins": wins,
                    "losses": losses,
                    "expired": expired,
                    "manual_review": manual_review,
                    "win_rate": win_rate,
                    "avg_realized_return": avg_realized_return,
                    "avg_win_return": avg_win_return,
                    "avg_loss_return": avg_loss_return,
                    "expectancy": expectancy,
                    "avg_max_gain": _mean([row["max_gain_value"] for row in rows]),
                    "avg_max_drawdown": _mean([row["max_drawdown_value"] for row in rows]),
                    "confidence_label": confidence["confidence_label"],
                    "statistical_score": confidence["statistical_score"],
                    "meets_min_sample_size": len(rows) >= min_sample_size,
                }
            )

        groups.sort(key=lambda item: (item["statistical_score"], item["sample_size"]), reverse=True)
        return {
            "ok": True,
            "groups": groups,
            "min_sample_size": min_sample_size,
            "message": "No closed recommendations found." if not groups else None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "groups": [], "error": str(exc)}


def analyze_ticker_history(
    ticker: str,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        normalized_ticker = str(ticker or "").strip().upper()
        recommendations = [row for row in _load_recommendations(db_path) if str(row.get("ticker", "")).upper() == normalized_ticker]
        if not recommendations:
            return {
                "ok": True,
                "ticker": normalized_ticker,
                "total_recommendations": 0,
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": None,
                "avg_realized_return": None,
                "best_trade": None,
                "worst_trade": None,
                "most_common_setup_type": None,
                "recent_outcomes": [],
                "historical_edge": "neutral",
                "message": "No historical recommendations found for ticker.",
            }

        closed = [row for row in recommendations if str(row.get("outcome", "")).lower() in TERMINAL_OUTCOMES]
        wins = sum(1 for row in closed if str(row.get("outcome", "")).lower() == "win")
        losses = sum(1 for row in closed if str(row.get("outcome", "")).lower() == "loss")
        closed_sample = wins + losses
        win_rate = (wins / closed_sample) if closed_sample else None
        avg_realized_return = _mean([row["realized_return_value"] for row in closed])
        setup_counts = Counter(row.get("setup_type") for row in recommendations if row.get("setup_type"))
        most_common_setup_type = setup_counts.most_common(1)[0][0] if setup_counts else None

        closed_with_returns = [row for row in closed if row["realized_return_value"] is not None]
        best_trade = None
        worst_trade = None
        if closed_with_returns:
            best_row = max(closed_with_returns, key=lambda row: row["realized_return_value"])
            worst_row = min(closed_with_returns, key=lambda row: row["realized_return_value"])
            best_trade = {
                "recommendation_id": best_row.get("id"),
                "outcome": best_row.get("outcome"),
                "realized_return": best_row.get("realized_return_value"),
                "setup_type": best_row.get("setup_type"),
            }
            worst_trade = {
                "recommendation_id": worst_row.get("id"),
                "outcome": worst_row.get("outcome"),
                "realized_return": worst_row.get("realized_return_value"),
                "setup_type": worst_row.get("setup_type"),
            }

        if win_rate is not None and avg_realized_return is not None:
            if win_rate > 0.55 and avg_realized_return > 0:
                historical_edge = "positive"
            elif win_rate < 0.45 and avg_realized_return < 0:
                historical_edge = "negative"
            else:
                historical_edge = "neutral"
        else:
            historical_edge = "neutral"

        recent_outcomes = [
            {
                "recommendation_id": row.get("id"),
                "outcome": row.get("outcome"),
                "realized_return": row.get("realized_return_value"),
                "setup_type": row.get("setup_type"),
            }
            for row in sorted(closed, key=lambda row: (row.get("closed_at") or "", row.get("id") or 0), reverse=True)[:5]
        ]

        return {
            "ok": True,
            "ticker": normalized_ticker,
            "total_recommendations": len(recommendations),
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_realized_return": avg_realized_return,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "most_common_setup_type": most_common_setup_type,
            "recent_outcomes": recent_outcomes,
            "historical_edge": historical_edge,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "ticker": ticker, "error": str(exc)}


def analyze_profile_performance(
    scan_profile: str | None = None,
    db_path: str = "strategy_library.db",
    min_sample_size: int = 5,
) -> dict:
    try:
        evaluations = _load_candidate_evaluations(db_path)
        recommendations = _load_recommendations(db_path)

        grouped_evaluations: dict[str, list[dict]] = defaultdict(list)
        for evaluation in evaluations:
            profile_name = evaluation.get("scan_profile") or "unknown"
            grouped_evaluations[profile_name].append(evaluation)

        grouped_recommendations: dict[str, list[dict]] = defaultdict(list)
        for recommendation in recommendations:
            if recommendation.get("scan_profile"):
                grouped_recommendations[recommendation["scan_profile"]].append(recommendation)

        if scan_profile is not None:
            target_profiles = [scan_profile]
        else:
            target_profiles = sorted(set(grouped_evaluations.keys()) | set(grouped_recommendations.keys()))

        profiles_output = []
        for profile_name in target_profiles:
            eval_rows = grouped_evaluations.get(profile_name, [])
            rec_rows = grouped_recommendations.get(profile_name, [])
            recommendable = sum(1 for row in eval_rows if str(row.get("recommendation_status", "")).lower() == "recommendable")
            watchlist = sum(1 for row in eval_rows if str(row.get("recommendation_status", "")).lower() == "watchlist")
            rejected = sum(1 for row in eval_rows if str(row.get("recommendation_status", "")).lower() == "rejected")
            recommendation_count = len(rec_rows)
            evaluated_count = len(eval_rows)
            conversion_rate = (recommendation_count / evaluated_count) if evaluated_count else None

            closed_rec_rows = [row for row in rec_rows if str(row.get("outcome", "")).lower() in TERMINAL_OUTCOMES]
            wins = sum(1 for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "win")
            losses = sum(1 for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "loss")
            closed_sample = wins + losses
            win_rate = (wins / closed_sample) if closed_sample else None
            avg_realized_return = _mean([row["realized_return_value"] for row in closed_rec_rows])
            avg_win_return = _mean([row["realized_return_value"] for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "win"])
            avg_loss_return = _mean([row["realized_return_value"] for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "loss"])
            expectancy = None
            if closed_sample:
                expectancy = calculate_expectancy(wins, losses, avg_win_return or 0.0, avg_loss_return or 0.0)

            confidence = score_statistical_confidence(len(closed_rec_rows), win_rate, expectancy)

            profiles_output.append(
                {
                    "scan_profile": profile_name,
                    "number_evaluated": evaluated_count,
                    "number_recommendable": recommendable,
                    "number_watchlist": watchlist,
                    "number_rejected": rejected,
                    "number_recommendations": recommendation_count,
                    "conversion_rate": conversion_rate,
                    "wins": wins,
                    "losses": losses,
                    "expired": sum(1 for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "expired"),
                    "manual_review": sum(1 for row in closed_rec_rows if str(row.get("outcome", "")).lower() == "manual_review"),
                    "win_rate": win_rate,
                    "avg_realized_return": avg_realized_return,
                    "average_score": _mean([row.get("score_value") for row in eval_rows]),
                    "average_risk_reward": _mean([row.get("risk_reward_value") for row in eval_rows]),
                    "confidence_label": confidence["confidence_label"],
                    "statistical_score": confidence["statistical_score"],
                    "meets_min_sample_size": len(closed_rec_rows) >= min_sample_size,
                }
            )

        if scan_profile is not None and not profiles_output:
            return {
                "ok": False,
                "profiles": [],
                "error": f"No statistical profile data found for scan_profile '{scan_profile}'.",
            }

        profiles_output.sort(key=lambda item: (item["statistical_score"], item["number_evaluated"]), reverse=True)
        return {
            "ok": True,
            "profiles": profiles_output,
            "min_sample_size": min_sample_size,
            "message": "No profile evaluation history found." if not profiles_output else None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "profiles": [], "error": str(exc)}


def enrich_candidate_with_statistics(
    candidate: dict,
    db_path: str = "strategy_library.db",
) -> dict:
    candidate_copy = dict(candidate)
    setup_analysis = analyze_setup_performance(db_path=db_path)
    ticker_history = analyze_ticker_history(candidate_copy.get("ticker", ""), db_path=db_path)
    profile_analysis = analyze_profile_performance(
        scan_profile=candidate_copy.get("scan_profile") or candidate_copy.get("selected_profile"),
        db_path=db_path,
    ) if candidate_copy.get("scan_profile") or candidate_copy.get("selected_profile") else {"ok": True, "profiles": []}

    setup_match = None
    if setup_analysis.get("ok"):
        for group in setup_analysis.get("groups", []):
            if group.get("setup_type") == candidate_copy.get("setup_type") and group.get("direction") == candidate_copy.get("direction") and group.get("asset_type") in {candidate_copy.get("asset_type"), "equity" if candidate_copy.get("asset_type") == "stock" else candidate_copy.get("asset_type")}:
                setup_match = group
                break

    profile_match = None
    if profile_analysis.get("ok") and profile_analysis.get("profiles"):
        profile_match = profile_analysis["profiles"][0]

    scores = []
    warnings = []
    if setup_match:
        scores.append(setup_match.get("statistical_score"))
        if not setup_match.get("meets_min_sample_size"):
            warnings.append("Setup history has a limited sample size.")
    else:
        warnings.append("No matching setup history found.")

    if profile_match:
        scores.append(profile_match.get("statistical_score"))
        if not profile_match.get("meets_min_sample_size"):
            warnings.append("Profile history has a limited sample size.")
    elif candidate_copy.get("scan_profile") or candidate_copy.get("selected_profile"):
        warnings.append("No matching scan profile history found.")

    edge = ticker_history.get("historical_edge") if isinstance(ticker_history, dict) else None
    if edge == "negative":
        warnings.append("Ticker has a negative historical edge.")
    elif edge == "neutral":
        warnings.append("Ticker edge is not yet statistically strong.")

    valid_scores = [score for score in scores if score is not None]
    if valid_scores:
        statistical_score = round(sum(valid_scores) / len(valid_scores), 2)
    else:
        statistical_score = 0.0

    if statistical_score < 40:
        confidence_label = "low"
    elif statistical_score < 75:
        confidence_label = "medium"
    else:
        confidence_label = "high"

    candidate_copy["statistical_context"] = {
        "setup_performance": setup_match,
        "ticker_history": ticker_history,
        "profile_performance": profile_match,
        "statistical_score": statistical_score,
        "confidence_label": confidence_label,
        "warnings": warnings,
    }
    return candidate_copy
