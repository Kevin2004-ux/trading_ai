from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_annotation_feedback(
    candidate: dict,
    annotations_summary: dict,
    config: dict | None = None,
) -> dict:
    summary = annotations_summary if isinstance(annotations_summary, dict) else {}
    positive_count = int(summary.get("positive_count") or 0)
    negative_count = int(summary.get("negative_count") or 0)
    blocking_count = int(summary.get("blocking_count") or 0)
    average_rating = _safe_float(summary.get("average_rating"))
    reasons: list[str] = []
    warnings: list[str] = []

    score_adjustment = 0.0
    risk_multiplier = 1.0
    feedback_status = "neutral"

    if not summary.get("ok") or int(summary.get("total_annotations") or 0) == 0:
        return {
            "ok": True,
            "feedback_status": "unknown",
            "score_adjustment": 0.0,
            "risk_multiplier": 1.0,
            "reasons": ["No human annotations matched this ticker/setup."],
            "warnings": [],
        }

    if blocking_count > 0:
        feedback_status = "blocking"
        score_adjustment = -10.0
        risk_multiplier = 0.0
        reasons.append("A matching human annotation explicitly marked this ticker/setup as blocking.")
    elif negative_count >= 3 or (average_rating is not None and average_rating <= -2):
        feedback_status = "caution"
        score_adjustment = -5.0
        risk_multiplier = 0.5
        reasons.append("Repeated negative human annotations reduce confidence and risk allocation.")
    elif negative_count > positive_count:
        feedback_status = "caution"
        score_adjustment = -2.0
        risk_multiplier = 0.75
        reasons.append("Human annotations are net negative for this ticker/setup.")
    elif positive_count >= 2 and positive_count > negative_count:
        feedback_status = "supportive"
        score_adjustment = 2.0
        risk_multiplier = 1.0
        reasons.append("Repeated positive human annotations provide small supportive context.")
    else:
        reasons.append("Human annotations are mixed or neutral.")

    if str((candidate or {}).get("recommendation_status", "")).lower() == "rejected":
        warnings.append("Human feedback cannot unblock a candidate rejected by deterministic hard gates.")

    return {
        "ok": True,
        "feedback_status": feedback_status,
        "score_adjustment": score_adjustment,
        "risk_multiplier": risk_multiplier,
        "reasons": reasons,
        "warnings": warnings,
    }
