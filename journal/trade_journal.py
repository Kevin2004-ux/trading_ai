from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from memory.vector_memory import store_memory_item
from tracking.trade_logger import get_recommendation, init_trade_tracking_db


DEFAULT_DB_PATH = "strategy_library.db"
TERMINAL_OUTCOMES = {"win", "loss", "expired", "manual_review", "closed"}
JSON_COLUMNS = {
    "lessons_json",
    "mistakes_json",
    "strengths_json",
    "rule_adjustments_json",
    "review_json",
    "memory_status_json",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _serialize_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _deserialize_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _review_row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for column in JSON_COLUMNS:
        if column in result:
            result[column] = _deserialize_json(result[column])
    return result


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _contains_text(payload: Any, needles: list[str]) -> bool:
    text = json.dumps(payload, default=str).lower() if isinstance(payload, (dict, list)) else str(payload or "").lower()
    return any(needle.lower() in text for needle in needles)


def _normalize_outcome(recommendation: dict, outcome: dict | None = None) -> str | None:
    payload = _as_dict(outcome)
    for key in ("outcome", "status"):
        if payload.get(key):
            value = str(payload[key]).lower()
            return "manual_review" if value == "closed" else value
    for key in ("outcome", "status", "recommendation_status"):
        if recommendation.get(key):
            value = str(recommendation[key]).lower()
            return "manual_review" if value == "closed" else value
    return None


def _latest_outcome_for_recommendation(recommendation_id: int, db_path: str) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM trade_outcomes
            WHERE recommendation_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (recommendation_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["grading_data_json"] = _deserialize_json(result.get("grading_data_json"))
    return result


def _latest_outcome_by_recommendation_ids(db_path: str) -> dict[int, dict]:
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
            SELECT *
            FROM latest_outcomes
            """
        ).fetchall()

    outcomes: dict[int, dict] = {}
    for row in rows:
        item = dict(row)
        item["grading_data_json"] = _deserialize_json(item.get("grading_data_json"))
        outcomes[int(item["recommendation_id"])] = item
    return outcomes


def _json_payloads(recommendation: dict) -> tuple[dict, dict, dict]:
    data_snapshot = _deserialize_json(recommendation.get("data_snapshot_json"))
    constraint_results = _deserialize_json(recommendation.get("constraint_results_json"))
    model_outputs = _deserialize_json(recommendation.get("model_outputs_json"))
    return _as_dict(data_snapshot), _as_dict(constraint_results), _as_dict(model_outputs)


def _constraints_passed(recommendation: dict) -> bool | None:
    _, constraint_results, _ = _json_payloads(recommendation)
    if "passed" in constraint_results:
        return bool(constraint_results.get("passed"))
    nested = constraint_results.get("constraint_results")
    if isinstance(nested, dict) and "passed" in nested:
        return bool(nested.get("passed"))
    status = str(constraint_results.get("recommendation_status") or recommendation.get("recommendation_status") or "").lower()
    if status == "recommendable":
        return True
    if status in {"rejected", "watchlist"}:
        return False
    return None


def _position_sizing_available(recommendation: dict) -> bool:
    data_snapshot, _, model_outputs = _json_payloads(recommendation)
    return _contains_text(
        [data_snapshot, model_outputs],
        ["position_size", "position_sizing", "shares", "contracts", "risk_amount"],
    )


def _portfolio_risk_approved(recommendation: dict) -> bool | None:
    data_snapshot, _, model_outputs = _json_payloads(recommendation)
    payload = [data_snapshot, model_outputs]
    if _contains_text(payload, ["portfolio_risk_rejected", "portfolio rejected", "not approved", "exceeds portfolio"]):
        return False
    if _contains_text(payload, ["portfolio_risk", "portfolio approved", "approved_trades", "risk_approved"]):
        return True
    return None


def _option_liquidity_context_available(recommendation: dict) -> bool:
    data_snapshot, _, model_outputs = _json_payloads(recommendation)
    payload = [data_snapshot, model_outputs, recommendation]
    return _contains_text(payload, ["bid", "ask", "spread", "volume", "open_interest", "liquidity"])


def _risk_flags(recommendation: dict, market_context: dict | None = None) -> list[str]:
    data_snapshot, _, model_outputs = _json_payloads(recommendation)
    payloads = [data_snapshot, model_outputs, _as_dict(market_context)]
    flags: list[str] = []
    if _contains_text(payloads, ["risk_off", "high-volatility", "high volatility", "market_regime_risk"]):
        flags.append("market_regime")
    if _contains_text(payloads, ["earnings_risk", "earnings within", "upcoming earnings"]):
        flags.append("earnings")
    if _contains_text(payloads, ["weak_relative_strength", "underperforming", "relative strength weak"]):
        flags.append("weak_relative_strength")
    if _contains_text(payloads, ["liquidity_risk", "wide spread", "low open interest", "low volume"]):
        flags.append("liquidity")
    return flags


def _exit_reason(recommendation: dict, outcome: dict | None = None) -> str:
    payload = _as_dict(outcome)
    return str(payload.get("exit_reason") or recommendation.get("exit_reason") or "").lower()


def _max_gain(recommendation: dict, outcome: dict | None = None) -> float | None:
    payload = _as_dict(outcome)
    return _safe_float(payload.get("max_gain") if payload.get("max_gain") is not None else recommendation.get("max_gain"))


def _max_drawdown(recommendation: dict, outcome: dict | None = None) -> float | None:
    payload = _as_dict(outcome)
    return _safe_float(payload.get("max_drawdown") if payload.get("max_drawdown") is not None else recommendation.get("max_drawdown"))


def _realized_return(outcome: dict | None = None) -> float | None:
    payload = _as_dict(outcome)
    return _safe_float(payload.get("realized_return"))


def _review_summary(
    recommendation: dict,
    outcome_name: str | None,
    quality: dict,
    thesis_analysis: dict,
    lessons: list[dict],
) -> str:
    ticker = recommendation.get("ticker") or "Unknown ticker"
    quality_label = quality.get("label", "unreviewable")
    thesis_validity = thesis_analysis.get("thesis_validity", "unknown")
    lesson_tags = [lesson.get("tag") for lesson in lessons if isinstance(lesson, dict) and lesson.get("tag")]
    lesson_text = f" Key lessons: {', '.join(lesson_tags[:3])}." if lesson_tags else ""
    return (
        f"{ticker} closed as {outcome_name or 'unknown'} with {quality_label} process "
        f"and {thesis_validity} thesis follow-through.{lesson_text}"
    )


def init_trade_journal_db(db_path: str = DEFAULT_DB_PATH) -> dict:
    try:
        tracking_init = init_trade_tracking_db(db_path=db_path)
        if not tracking_init.get("ok"):
            return {
                "ok": False,
                "db_path": db_path,
                "tables_created": [],
                "error": tracking_init.get("error", "Failed to initialize trade tracking database."),
            }

        with _connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trade_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id INTEGER NOT NULL,
                    ticker TEXT,
                    created_at TEXT NOT NULL,
                    outcome TEXT,
                    trade_quality_label TEXT,
                    trade_quality_score REAL,
                    thesis_validity TEXT,
                    review_summary TEXT,
                    lessons_json TEXT,
                    mistakes_json TEXT,
                    strengths_json TEXT,
                    rule_adjustments_json TEXT,
                    review_json TEXT,
                    memory_status_json TEXT,
                    FOREIGN KEY(recommendation_id) REFERENCES trade_recommendations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_trade_reviews_recommendation_id
                ON trade_reviews(recommendation_id);

                CREATE INDEX IF NOT EXISTS idx_trade_reviews_ticker_created_at
                ON trade_reviews(ticker, created_at);
                """
            )
        return {
            "ok": True,
            "db_path": db_path,
            "tables_created": ["trade_reviews"],
            "error": None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "db_path": db_path, "tables_created": [], "error": str(exc)}


def analyze_thesis_followthrough(
    recommendation: dict,
    outcome: dict | None = None,
    research_brief: dict | None = None,
) -> dict:
    if not isinstance(recommendation, dict):
        return {
            "thesis_validity": "unknown",
            "followthrough_summary": "Recommendation data is unavailable.",
            "supporting_evidence": [],
            "contradicting_evidence": ["Recommendation payload missing."],
        }

    thesis = recommendation.get("thesis")
    invalidation = recommendation.get("invalidation")
    outcome_name = _normalize_outcome(recommendation, outcome)
    exit_reason = _exit_reason(recommendation, outcome)
    max_gain = _max_gain(recommendation, outcome)
    max_drawdown = _max_drawdown(recommendation, outcome)

    supporting: list[str] = []
    contradicting: list[str] = []

    if not _has_text(thesis):
        contradicting.append("Original thesis is missing.")
    else:
        supporting.append("Original thesis was recorded.")

    if not _has_text(invalidation):
        contradicting.append("Invalidation condition is missing.")
    else:
        supporting.append("Invalidation condition was recorded.")

    if isinstance(research_brief, dict):
        conviction = research_brief.get("research_conviction")
        if conviction:
            supporting.append(f"Research context was available: {conviction}.")

    if max_gain is not None and max_gain > 0:
        supporting.append(f"Trade moved favorably by {round(max_gain * 100, 2)}% at best.")
    if max_drawdown is not None and max_drawdown < 0:
        contradicting.append(f"Trade drew down by {round(abs(max_drawdown) * 100, 2)}% at worst.")

    if outcome_name == "win":
        supporting.append("Trade reached a winning outcome.")
        if "target" in exit_reason:
            supporting.append("Target logic appears to have worked.")
        thesis_validity = "valid" if _has_text(thesis) else "unknown"
        summary = "The trade outcome supported the recorded thesis." if _has_text(thesis) else "The trade won, but the original thesis was not recorded."
    elif outcome_name == "loss":
        if "stop" in exit_reason:
            contradicting.append("Stop loss was hit, invalidating or pausing the setup.")
        thesis_validity = "partially_valid" if max_gain is not None and max_gain > 0 else "invalid"
        if not _has_text(thesis):
            thesis_validity = "unknown"
        summary = "The trade lost; review focuses on whether the loss followed the original plan rather than treating the loss as automatic bad process."
    elif outcome_name == "expired":
        thesis_validity = "partially_valid" if max_gain is not None and max_gain > 0 else "unknown"
        summary = "The trade expired without a decisive target or stop outcome."
    elif outcome_name == "manual_review":
        thesis_validity = "unknown"
        contradicting.append("Outcome grading required manual review.")
        summary = "The thesis cannot be judged cleanly because outcome data was ambiguous."
    elif outcome_name == "open":
        thesis_validity = "unknown"
        summary = "The trade is still open and should not receive a final post-trade thesis judgment."
    else:
        thesis_validity = "unknown"
        summary = "Outcome data is missing, so thesis follow-through cannot be determined."

    if not _has_text(thesis):
        thesis_validity = "unknown"

    return {
        "thesis_validity": thesis_validity,
        "followthrough_summary": summary,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
    }


def score_trade_quality(
    recommendation: dict,
    outcome: dict | None = None,
    thesis_analysis: dict | None = None,
) -> dict:
    if not isinstance(recommendation, dict):
        return {
            "label": "unreviewable",
            "score": 0,
            "drivers": [],
            "penalties": ["Recommendation payload missing."],
        }

    outcome_name = _normalize_outcome(recommendation, outcome)
    if outcome_name in {None, "open"}:
        return {
            "label": "unreviewable",
            "score": 0,
            "drivers": [],
            "penalties": ["Trade is not closed yet."],
        }

    score = 50.0
    drivers: list[str] = []
    penalties: list[str] = []

    if _has_text(recommendation.get("thesis")):
        score += 10
        drivers.append("Clear thesis was recorded.")
    else:
        score -= 12
        penalties.append("Missing thesis.")

    if _has_text(recommendation.get("invalidation")):
        score += 10
        drivers.append("Clear invalidation was recorded.")
    else:
        score -= 12
        penalties.append("Missing invalidation condition.")

    stop_loss = _safe_float(recommendation.get("stop_loss"))
    if stop_loss is not None:
        score += 8
        drivers.append("Stop loss was defined.")
    else:
        score -= 20
        penalties.append("Missing stop loss.")

    risk_reward = _safe_float(recommendation.get("risk_reward"))
    if risk_reward is not None and risk_reward >= 2.0:
        score += 8
        drivers.append("Risk/reward met the minimum process threshold.")
    elif risk_reward is None:
        score -= 8
        penalties.append("Risk/reward was not recorded.")
    else:
        score -= 14
        penalties.append("Risk/reward was below 2.0.")

    constraints_passed = _constraints_passed(recommendation)
    if constraints_passed is True:
        score += 10
        drivers.append("Objective constraints passed when logged.")
    elif constraints_passed is False:
        score -= 30
        penalties.append("Failed or watchlist constraints were present.")

    if _position_sizing_available(recommendation):
        score += 5
        drivers.append("Position sizing context was available.")
    else:
        penalties.append("Position sizing context was not available.")

    portfolio_approval = _portfolio_risk_approved(recommendation)
    if portfolio_approval is True:
        score += 5
        drivers.append("Portfolio risk context approved or addressed the trade.")
    elif portfolio_approval is False:
        score -= 15
        penalties.append("Portfolio risk context rejected or warned on the trade.")

    exit_reason = _exit_reason(recommendation, outcome)
    if outcome_name == "win" and "target" in exit_reason:
        score += 8
        drivers.append("Target logic worked as intended.")
    if outcome_name == "loss" and "stop" in exit_reason:
        score += 6
        drivers.append("Loss appears to have stayed within the planned stop process.")
    if outcome_name == "manual_review":
        score -= 15
        penalties.append("Outcome required manual review due to ambiguous data.")

    if str(recommendation.get("asset_type", "")).lower() == "option" and not _option_liquidity_context_available(recommendation):
        score -= 12
        penalties.append("Option trade is missing liquidity context.")

    if outcome_name == "loss" and _risk_flags(recommendation):
        score -= 8
        penalties.append("Loss occurred with known risk flags present.")

    thesis_validity = _as_dict(thesis_analysis).get("thesis_validity")
    if thesis_validity == "valid":
        score += 5
        drivers.append("Thesis follow-through was valid.")
    elif thesis_validity == "invalid":
        score -= 5
        penalties.append("Thesis follow-through was invalid.")

    bounded_score = max(0, min(100, round(score, 2)))
    if bounded_score >= 75:
        label = "good_process"
    elif bounded_score >= 50:
        label = "mixed_process"
    else:
        label = "poor_process"

    return {
        "label": label,
        "score": bounded_score,
        "drivers": drivers,
        "penalties": penalties,
    }


def identify_trade_lessons(
    recommendation: dict,
    outcome: dict | None = None,
    thesis_analysis: dict | None = None,
    market_context: dict | None = None,
) -> dict:
    lessons: list[dict] = []
    mistakes: list[str] = []
    strengths: list[str] = []
    rule_adjustments: list[str] = []

    if not isinstance(recommendation, dict):
        return {
            "lessons": [{"tag": "insufficient_data_to_review", "summary": "Recommendation data was unavailable."}],
            "mistakes": ["Recommendation payload missing."],
            "strengths": [],
            "rule_adjustments": ["Do not attempt post-trade process review without the original recommendation record."],
        }

    outcome_name = _normalize_outcome(recommendation, outcome)
    thesis_validity = _as_dict(thesis_analysis).get("thesis_validity")
    exit_reason = _exit_reason(recommendation, outcome)
    max_gain = _max_gain(recommendation, outcome)
    risk_reward = _safe_float(recommendation.get("risk_reward"))

    if not _has_text(recommendation.get("thesis")) or not _has_text(recommendation.get("invalidation")):
        lessons.append({"tag": "insufficient_data_to_review", "summary": "Original thesis or invalidation data was incomplete."})
        mistakes.append("The original trade plan was missing thesis or invalidation detail.")
        rule_adjustments.append("Require thesis and invalidation before logging future recommendations.")

    if outcome_name == "win" and thesis_validity == "valid":
        lessons.append({"tag": "winner_followed_thesis", "summary": "The winning trade aligned with the recorded thesis."})
        strengths.append("The thesis and target process were aligned.")

    if outcome_name == "loss" and "stop" in exit_reason and _has_text(recommendation.get("invalidation")):
        lessons.append({"tag": "valid_loss_with_plan", "summary": "The trade lost, but the stop/invalidation process appears to have contained the risk."})
        strengths.append("The loss appears to have respected the planned invalidation.")

    if outcome_name == "loss" and max_gain is not None and max_gain > 0.02 and "stop" in exit_reason:
        lessons.append({"tag": "stop_too_tight_possible", "summary": "The trade moved favorably before failing, so stop placement may deserve review."})
        rule_adjustments.append("Review whether stop distance matches normal ATR/noise for this setup.")

    if outcome_name in {"loss", "expired"} and max_gain is not None and max_gain > 0 and risk_reward is not None and risk_reward > 3.0:
        lessons.append({"tag": "target_too_aggressive_possible", "summary": "The trade had favorable movement but may have had an aggressive target."})
        rule_adjustments.append("Review target placement for high risk/reward setups that frequently expire or reverse.")

    flags = _risk_flags(recommendation, market_context)
    if "market_regime" in flags:
        lessons.append({"tag": "ignored_market_regime_risk", "summary": "Market regime risk was present and should be reviewed against the result."})
        mistakes.append("Market regime risk may not have been weighted enough.")
    if "earnings" in flags:
        lessons.append({"tag": "ignored_earnings_risk", "summary": "Earnings risk was present near the trade window."})
        mistakes.append("Earnings timing risk may not have been weighted enough.")
    if "weak_relative_strength" in flags:
        lessons.append({"tag": "weak_relative_strength_warning", "summary": "Weak relative strength was present and should remain a warning, not an automatic override."})
    if str(recommendation.get("asset_type", "")).lower() == "option" and not _option_liquidity_context_available(recommendation):
        lessons.append({"tag": "option_liquidity_risk", "summary": "Option liquidity context was missing or insufficient."})
        mistakes.append("Option liquidity was not documented.")
        rule_adjustments.append("Require bid/ask spread, volume, and open interest before logging option recommendations.")

    seen: set[str] = set()
    unique_lessons = []
    for lesson in lessons:
        tag = lesson.get("tag")
        if tag and tag not in seen:
            unique_lessons.append(lesson)
            seen.add(tag)

    if not unique_lessons:
        unique_lessons.append({"tag": "no_major_process_lesson", "summary": "No deterministic process lesson stood out from available data."})

    return {
        "lessons": unique_lessons,
        "mistakes": mistakes,
        "strengths": strengths,
        "rule_adjustments": rule_adjustments,
    }


def build_trade_review(
    recommendation: dict,
    outcome: dict | None = None,
    market_context: dict | None = None,
    research_brief: dict | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    timestamp = _now_iso()
    if not isinstance(recommendation, dict):
        return {
            "ok": False,
            "timestamp": timestamp,
            "recommendation_id": None,
            "ticker": None,
            "outcome": None,
            "trade_quality": {"label": "unreviewable", "score": 0, "drivers": [], "penalties": ["Recommendation payload missing."]},
            "thesis_analysis": {"thesis_validity": "unknown", "followthrough_summary": "Recommendation payload missing.", "supporting_evidence": [], "contradicting_evidence": []},
            "lessons": [{"tag": "insufficient_data_to_review", "summary": "Recommendation payload missing."}],
            "mistakes": ["Recommendation payload missing."],
            "strengths": [],
            "rule_adjustments": [],
            "review_summary": "Trade review could not be completed because recommendation data was missing.",
            "data_quality": {"missing_sections": ["recommendation"], "confidence_warning": "Insufficient data to review this trade."},
            "error": "Recommendation payload missing.",
        }

    recommendation_id = recommendation.get("id")
    loaded_outcome = outcome
    if loaded_outcome is None and recommendation_id is not None:
        try:
            loaded_outcome = _latest_outcome_for_recommendation(int(recommendation_id), db_path=db_path)
        except (sqlite3.Error, TypeError, ValueError):
            loaded_outcome = None

    outcome_name = _normalize_outcome(recommendation, loaded_outcome)
    thesis_analysis = analyze_thesis_followthrough(recommendation, outcome=loaded_outcome, research_brief=research_brief)
    quality = score_trade_quality(recommendation, outcome=loaded_outcome, thesis_analysis=thesis_analysis)
    lesson_result = identify_trade_lessons(
        recommendation,
        outcome=loaded_outcome,
        thesis_analysis=thesis_analysis,
        market_context=market_context,
    )

    missing_sections = []
    if not _has_text(recommendation.get("thesis")):
        missing_sections.append("thesis")
    if not _has_text(recommendation.get("invalidation")):
        missing_sections.append("invalidation")
    if loaded_outcome is None and outcome_name in {None, "open"}:
        missing_sections.append("outcome")
    if _constraints_passed(recommendation) is None:
        missing_sections.append("constraint_results")
    if market_context is None:
        missing_sections.append("market_context")
    if research_brief is None:
        missing_sections.append("research_brief")

    confidence_warning = ""
    if missing_sections:
        confidence_warning = "Review is limited by missing sections: " + ", ".join(missing_sections) + "."
    if quality.get("label") == "unreviewable":
        confidence_warning = "Trade is not ready for final post-trade review."

    review_summary = _review_summary(
        recommendation,
        outcome_name,
        quality,
        thesis_analysis,
        lesson_result["lessons"],
    )

    return {
        "ok": True,
        "timestamp": timestamp,
        "recommendation_id": recommendation_id,
        "ticker": recommendation.get("ticker"),
        "outcome": outcome_name,
        "trade_quality": quality,
        "thesis_analysis": thesis_analysis,
        "lessons": lesson_result["lessons"],
        "mistakes": lesson_result["mistakes"],
        "strengths": lesson_result["strengths"],
        "rule_adjustments": lesson_result["rule_adjustments"],
        "review_summary": review_summary,
        "data_quality": {
            "missing_sections": missing_sections,
            "confidence_warning": confidence_warning,
        },
        "error": None,
    }


def log_trade_review(
    recommendation_id: int,
    review: dict,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    try:
        init_result = init_trade_journal_db(db_path=db_path)
        if not init_result.get("ok"):
            return {"ok": False, "error": init_result.get("error", "Failed to initialize trade journal database.")}

        if not isinstance(review, dict):
            return {"ok": False, "error": "Review payload must be a dictionary."}

        recommendation = get_recommendation(recommendation_id, db_path=db_path)
        if recommendation is None or (isinstance(recommendation, dict) and recommendation.get("ok") is False):
            return {"ok": False, "error": f"Recommendation {recommendation_id} not found."}

        created_at = review.get("timestamp") or _now_iso()
        trade_quality = _as_dict(review.get("trade_quality"))
        thesis_analysis = _as_dict(review.get("thesis_analysis"))

        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO trade_reviews (
                    recommendation_id, ticker, created_at, outcome,
                    trade_quality_label, trade_quality_score, thesis_validity,
                    review_summary, lessons_json, mistakes_json, strengths_json,
                    rule_adjustments_json, review_json, memory_status_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    review.get("ticker") or recommendation.get("ticker"),
                    created_at,
                    review.get("outcome"),
                    trade_quality.get("label"),
                    trade_quality.get("score"),
                    thesis_analysis.get("thesis_validity"),
                    review.get("review_summary"),
                    _serialize_json(review.get("lessons")),
                    _serialize_json(review.get("mistakes")),
                    _serialize_json(review.get("strengths")),
                    _serialize_json(review.get("rule_adjustments")),
                    _serialize_json(review),
                    _serialize_json(review.get("memory_status")),
                ),
            )
            review_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM trade_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()

        inserted = _review_row_to_dict(row)
        return {
            "ok": True,
            "review": inserted,
            "review_id": review_id,
            "error": None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "recommendation_id": recommendation_id}


def get_trade_reviews(
    recommendation_id: int | None = None,
    ticker: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    try:
        init_result = init_trade_journal_db(db_path=db_path)
        if not init_result.get("ok"):
            return {"ok": False, "reviews": [], "count": 0, "error": init_result.get("error")}

        clauses = []
        params: list[Any] = []
        if recommendation_id is not None:
            clauses.append("recommendation_id = ?")
            params.append(recommendation_id)
        if ticker is not None:
            clauses.append("upper(ticker) = ?")
            params.append(str(ticker).upper())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM trade_reviews
                {where}
                ORDER BY created_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()

        reviews = [_review_row_to_dict(row) for row in rows]
        return {
            "ok": True,
            "reviews": reviews,
            "count": len(reviews),
            "error": None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "reviews": [], "count": 0, "error": str(exc)}


def _closed_unreviewed_recommendations(db_path: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tr.*
            FROM trade_recommendations tr
            LEFT JOIN trade_reviews review
                ON review.recommendation_id = tr.id
            WHERE review.id IS NULL
              AND (
                lower(COALESCE(tr.outcome, '')) IN ('win', 'loss', 'expired', 'manual_review')
                OR lower(COALESCE(tr.status, '')) IN ('win', 'loss', 'expired', 'manual_review', 'closed')
                OR tr.closed_at IS NOT NULL
              )
            ORDER BY tr.closed_at ASC, tr.created_at ASC, tr.id ASC
            """
        ).fetchall()

    recommendations = []
    for row in rows:
        item = dict(row)
        for key in ("data_snapshot_json", "constraint_results_json", "model_outputs_json"):
            item[key] = _deserialize_json(item.get(key))
        recommendations.append(item)
    return recommendations


def review_closed_trades(
    db_path: str = DEFAULT_DB_PATH,
    store_memory: bool = False,
) -> dict:
    reviewed_count = 0
    skipped_count = 0
    reviews: list[dict] = []
    errors: list[str] = []

    try:
        init_result = init_trade_journal_db(db_path=db_path)
        if not init_result.get("ok"):
            return {
                "ok": False,
                "reviewed_count": 0,
                "skipped_count": 0,
                "reviews": [],
                "errors": [init_result.get("error", "Failed to initialize trade journal database.")],
            }

        recommendations = _closed_unreviewed_recommendations(db_path)
        outcomes = _latest_outcome_by_recommendation_ids(db_path)
        if not recommendations:
            return {
                "ok": True,
                "reviewed_count": 0,
                "skipped_count": 0,
                "reviews": [],
                "errors": [],
            }

        for recommendation in recommendations:
            recommendation_id = recommendation.get("id")
            if recommendation_id is None:
                skipped_count += 1
                errors.append("Skipped closed recommendation without id.")
                continue

            outcome = outcomes.get(int(recommendation_id))
            review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)
            if not review.get("ok"):
                skipped_count += 1
                errors.append(review.get("error") or f"Failed to review recommendation {recommendation_id}.")
                continue

            if store_memory:
                try:
                    memory_status = store_memory_item(
                        review,
                        item_type="post_trade_review",
                        extra_metadata={
                            "ticker": review.get("ticker"),
                            "recommendation_id": recommendation_id,
                            "source_db_path": db_path,
                        },
                    )
                except Exception as exc:
                    memory_status = {
                        "ok": False,
                        "source": "unavailable",
                        "error": f"Failed to store trade review memory: {exc}",
                    }
                review["memory_status"] = memory_status
            else:
                review["memory_status"] = {
                    "ok": False,
                    "source": "disabled",
                    "error": "store_memory is False.",
                }

            logged = log_trade_review(int(recommendation_id), review, db_path=db_path)
            if not logged.get("ok"):
                skipped_count += 1
                errors.append(logged.get("error") or f"Failed to log review for recommendation {recommendation_id}.")
                continue

            reviewed_count += 1
            reviews.append(logged["review"])

        return {
            "ok": len(errors) == 0,
            "reviewed_count": reviewed_count,
            "skipped_count": skipped_count,
            "reviews": reviews,
            "errors": errors,
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "reviewed_count": reviewed_count,
            "skipped_count": skipped_count,
            "reviews": reviews,
            "errors": [str(exc)],
        }
