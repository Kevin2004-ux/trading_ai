from __future__ import annotations

from typing import Any

from .memory_feedback import evaluate_annotation_feedback
from .retrieval_quality import evaluate_retrieval_quality


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata(match: dict) -> dict:
    metadata = match.get("metadata") if isinstance(match, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def build_memory_query_context(
    candidate: dict,
    market_context: dict | None = None,
    config: dict | None = None,
) -> dict:
    if not isinstance(candidate, dict):
        return {"ok": False, "ticker": "", "setup_type": None, "query_text": "", "structured_context": {}, "errors": ["Candidate is required."]}
    ticker = _ticker(candidate.get("ticker") or candidate.get("underlying_ticker"))
    setup_type = candidate.get("setup_type") or candidate.get("scan_profile") or candidate.get("selected_profile")
    direction = candidate.get("direction", "long")
    market = market_context if isinstance(market_context, dict) else {}
    query_text = " | ".join(
        str(item)
        for item in (
            f"Ticker {ticker}" if ticker else "",
            f"setup {setup_type}" if setup_type else "",
            f"direction {direction}" if direction else "",
            f"market regime {market.get('regime')}" if market.get("regime") else "",
            f"relative strength {(candidate.get('relative_strength_context') or {}).get('relative_strength_label')}" if isinstance(candidate.get("relative_strength_context"), dict) else "",
            f"thesis {candidate.get('thesis')}" if candidate.get("thesis") else "",
        )
        if item
    )
    return {
        "ok": bool(ticker),
        "ticker": ticker,
        "setup_type": setup_type,
        "query_text": query_text,
        "structured_context": {
            "ticker": ticker,
            "setup_type": setup_type,
            "direction": direction,
            "asset_type": candidate.get("asset_type", "stock"),
            "score": candidate.get("score"),
            "risk_reward": candidate.get("risk_reward"),
            "recommendation_status": candidate.get("recommendation_status"),
            "market_context": market,
        },
        "errors": [] if ticker else ["Ticker is required for memory query context."],
    }


def _memory_impact(candidate: dict, matches: list[dict], retrieval_quality: dict, feedback: dict | None = None) -> dict:
    quality = retrieval_quality if isinstance(retrieval_quality, dict) else {}
    if not quality.get("usable_for_decision_support"):
        return {
            "score_adjustment": 0.0,
            "risk_multiplier": 1.0,
            "trade_impact": "ignored" if quality.get("quality_status") == "fail" else "neutral",
        }

    verified_positive = 0
    verified_negative = 0
    for match in matches:
        metadata = _metadata(match)
        outcome = str(metadata.get("outcome") or match.get("outcome") or "").lower()
        verified = str(metadata.get("outcome_verified", "true")).lower() in {"1", "true", "yes", "y", "on"}
        if not verified:
            continue
        if outcome in {"win", "positive"}:
            verified_positive += 1
        elif outcome in {"loss", "negative", "failed"}:
            verified_negative += 1

    score_adjustment = 0.0
    risk_multiplier = 1.0
    trade_impact = "neutral"
    if verified_negative > verified_positive:
        score_adjustment = -3.0
        risk_multiplier = 0.75
        trade_impact = "caution"
    elif verified_positive > verified_negative and verified_positive >= 1:
        score_adjustment = 2.0
        risk_multiplier = 1.0
        trade_impact = "supportive"

    if isinstance(feedback, dict):
        score_adjustment += _safe_float(feedback.get("score_adjustment")) or 0.0
        risk_multiplier = min(risk_multiplier, _safe_float(feedback.get("risk_multiplier")) if _safe_float(feedback.get("risk_multiplier")) is not None else risk_multiplier)
        feedback_status = str(feedback.get("feedback_status") or "").lower()
        if feedback_status == "blocking":
            trade_impact = "blocking"
        elif feedback_status == "caution" and trade_impact != "blocking":
            trade_impact = "caution"
        elif feedback_status == "supportive" and trade_impact == "neutral":
            trade_impact = "supportive"

    if str(candidate.get("recommendation_status", "")).lower() == "rejected":
        trade_impact = "ignored"
        score_adjustment = min(score_adjustment, 0.0)

    return {
        "score_adjustment": round(score_adjustment, 4),
        "risk_multiplier": round(risk_multiplier, 4),
        "trade_impact": trade_impact,
    }


def build_memory_decision_context(
    candidate: dict,
    retrieval_result: dict | None = None,
    retrieval_quality: dict | None = None,
    config: dict | None = None,
) -> dict:
    query_context = build_memory_query_context(candidate, market_context=(candidate or {}).get("market_regime_context") if isinstance(candidate, dict) else None)
    retrieval = retrieval_result if isinstance(retrieval_result, dict) else {"ok": False, "matches": [], "error": "Memory retrieval was not run."}
    quality = retrieval_quality if isinstance(retrieval_quality, dict) else evaluate_retrieval_quality(retrieval, query_context=query_context.get("structured_context"), config=config)
    matches = _as_list(retrieval.get("matches"))
    annotations_summary = (candidate or {}).get("annotations_summary") if isinstance(candidate, dict) else None
    feedback = evaluate_annotation_feedback(candidate or {}, annotations_summary, config=config) if isinstance(annotations_summary, dict) else None
    impact = _memory_impact(candidate or {}, matches, quality, feedback)
    warnings = list(quality.get("warnings", [])) if isinstance(quality, dict) else []
    if feedback and feedback.get("warnings"):
        warnings.extend(str(item) for item in feedback.get("warnings", []))
    if impact["trade_impact"] == "blocking":
        warnings.append("Human feedback marked this setup as blocking; deterministic hard gates still control final eligibility.")

    return {
        "ok": True,
        "ticker": query_context.get("ticker"),
        "setup_type": query_context.get("setup_type"),
        "query_text": query_context.get("query_text"),
        "structured_context": query_context.get("structured_context"),
        "retrieved_memories": matches,
        "retrieval_quality": quality,
        "human_feedback": feedback,
        "memory_impact": impact,
        "warnings": warnings,
        "errors": list(quality.get("errors", [])) if isinstance(quality, dict) else [],
    }
