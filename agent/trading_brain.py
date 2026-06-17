from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import sqlite3
from typing import Any

from analytics.market_regime import (
    apply_regime_to_trade_selection,
    get_market_regime_snapshot,
)
from execution.fill_model import estimate_paper_fill
from analytics.setup_decay import evaluate_all_setup_decay
from analytics.relative_strength import get_relative_strength_snapshot
from analytics.statistical_brain import enrich_candidate_with_statistics
from db.audit_log import append_audit_event
from engine.constraint_engine import evaluate_stock_constraints
from memory.vector_memory import (
    find_similar_setups,
    store_research_brief_memory,
    store_trade_decision_memory,
)
from memory.annotation_store import record_memory_retrieval_event, summarize_annotations
from memory.memory_context import build_memory_decision_context, build_memory_query_context
from memory.memory_feedback import evaluate_annotation_feedback
from memory.retrieval_quality import evaluate_retrieval_quality
from macro.macro_risk import evaluate_macro_risk
from realtime.catalyst_enrichment import enrich_candidate_with_catalysts
from realtime.market_data import get_market_snapshot
from risk.portfolio_manager import apply_portfolio_risk_limits
from risk.circuit_breaker import evaluate_drawdown_circuit_breaker
from risk.concentration_controls import evaluate_concentration_risk
from risk.correlation_matrix import get_latest_correlation_snapshot, refresh_correlation_snapshot
from risk.position_sizing import calculate_position_size
from scanner.options_scanner import scan_options_for_weekly_selection
from scanner.swing_scanner import (
    build_stock_candidate,
    calculate_trade_levels,
    scan_multi_strategy_candidates,
)
from scanner.universe_builder import get_default_universe
from selector.weekly_selector import select_weekly_trades
from tracking.outcome_grader import update_open_recommendations
from tracking.trade_logger import (
    get_open_recommendations,
    get_strategy_performance,
    get_win_loss_record,
)


DEFAULT_HOLDING_PERIOD_DAYS = 7
DEFAULT_MINIMUM_RISK_REWARD = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _deserialize_json(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _is_paper_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("paper_trading") is True
        or str(payload.get("execution_mode", "")).lower() == "paper_trading"
        or str(payload.get("mode", "")).lower() == "paper_trading"
    )


def _is_paper_logging_metadata(logging_metadata: dict | None) -> bool:
    return _is_paper_payload(logging_metadata)


def _memory_enabled() -> bool:
    return str(os.getenv("MEMORY_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "y", "on"} or str(os.getenv("PINECONE_MEMORY_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "y", "on"} or str(os.getenv("ENABLE_PINECONE_MEMORY", "false")).strip().lower() in {"1", "true", "yes", "y", "on"}


def _memory_summary_from_decisions(decision_result: dict | None) -> dict:
    decisions = []
    if isinstance(decision_result, dict):
        decisions = decision_result.get("final_recommendations", [])
    if not isinstance(decisions, list):
        decisions = []
    contexts = [decision.get("memory_context") for decision in decisions if isinstance(decision, dict) and isinstance(decision.get("memory_context"), dict)]
    qualities = [context.get("retrieval_quality") for context in contexts if isinstance(context.get("retrieval_quality"), dict)]
    impacts = [context.get("memory_impact") for context in contexts if isinstance(context.get("memory_impact"), dict)]
    return {
        "enabled": _memory_enabled(),
        "evaluated_count": len(contexts),
        "decision_support_count": sum(1 for quality in qualities if quality.get("usable_for_decision_support")),
        "explanation_only_count": sum(1 for quality in qualities if quality.get("usable_for_explanation") and not quality.get("usable_for_decision_support")),
        "ignored_count": sum(1 for impact in impacts if impact.get("trade_impact") == "ignored"),
        "warnings": [
            warning
            for context in contexts
            for warning in context.get("warnings", [])
            if isinstance(context.get("warnings"), list)
        ][:10],
    }


def _load_paper_trade_history(db_path: str) -> list[dict]:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
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
                SELECT tr.*, lo.realized_return AS latest_realized_return
                FROM trade_recommendations tr
                LEFT JOIN latest_outcomes lo ON lo.recommendation_id = tr.id
                ORDER BY tr.created_at ASC, tr.id ASC
                """
            ).fetchall()
    except sqlite3.Error:
        return []

    trades = []
    for row in rows:
        trade = dict(row)
        for key in ("data_snapshot_json", "model_outputs_json", "constraint_results_json"):
            trade[key] = _deserialize_json(trade.get(key))
        if _is_paper_payload(trade.get("data_snapshot_json")) or _is_paper_payload(trade.get("model_outputs_json")):
            trades.append(trade)
    return trades


def _constraint_payload(candidate: dict) -> dict:
    constraint_results = candidate.get("constraint_results")
    if isinstance(constraint_results, dict) and "constraint_results" in constraint_results and "passed" in constraint_results:
        return constraint_results

    passed = bool(candidate.get("passed"))
    status = str(candidate.get("recommendation_status", "rejected")).lower()
    return {
        "passed": passed,
        "recommendation_status": status,
        "score": candidate.get("score"),
        "constraint_results": constraint_results if isinstance(constraint_results, dict) else {},
        "failed_constraints": candidate.get("failed_constraints", []),
        "rejection_reason": candidate.get("rejection_reason", ""),
        "config": {"minimum_risk_reward": DEFAULT_MINIMUM_RISK_REWARD},
    }


def _candidate_status(candidate: dict) -> str:
    return str(candidate.get("recommendation_status", "rejected")).lower()


def _constraint_passed(candidate: dict) -> bool:
    payload = _constraint_payload(candidate)
    return bool(payload.get("passed"))


def _holding_period(candidate: dict) -> int:
    raw = candidate.get("holding_period_days")
    try:
        if raw is None:
            return DEFAULT_HOLDING_PERIOD_DAYS
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return DEFAULT_HOLDING_PERIOD_DAYS


def _confidence_label(candidate: dict) -> str:
    statistical_context = candidate.get("statistical_context", {})
    if isinstance(statistical_context, dict):
        label = statistical_context.get("confidence_label")
        if isinstance(label, str) and label:
            relative_strength = candidate.get("relative_strength_context", {})
            rs_label = str(relative_strength.get("relative_strength_label", "unknown")).lower() if isinstance(relative_strength, dict) else "unknown"
            if label == "medium" and rs_label in {"market_leader", "outperforming"}:
                return "high"
            if label == "high" and rs_label in {"underperforming", "market_laggard"}:
                return "medium"
            return label

    quality_bucket = str(candidate.get("quality_bucket", "")).upper()
    if quality_bucket == "A+":
        return "high"
    if quality_bucket in {"A", "B"}:
        return "medium"
    return "low"


def _build_why_selected(candidate: dict) -> list[str]:
    reasons: list[str] = []

    matched = candidate.get("why_this_profile_matched")
    if isinstance(matched, list):
        reasons.extend(str(reason) for reason in matched if reason)

    risk_reward = _safe_float(candidate.get("risk_reward"))
    if risk_reward is not None and risk_reward >= DEFAULT_MINIMUM_RISK_REWARD:
        reasons.append(f"Risk/reward is {round(risk_reward, 2)} to 1, which meets the minimum threshold.")

    statistical_context = candidate.get("statistical_context", {})
    if isinstance(statistical_context, dict):
        setup = statistical_context.get("setup_performance")
        if isinstance(setup, dict):
            expectancy = _safe_float(setup.get("expectancy"))
            if expectancy is not None and expectancy > 0:
                reasons.append("Historical setup expectancy is positive.")
        ticker_history = statistical_context.get("ticker_history")
        if isinstance(ticker_history, dict) and str(ticker_history.get("historical_edge", "")).lower() == "positive":
            reasons.append("Ticker history shows a positive edge.")

    catalyst_context = candidate.get("catalyst_context", {})
    if isinstance(catalyst_context, dict):
        label = str(catalyst_context.get("catalyst_label", "")).lower()
        positive_catalysts = catalyst_context.get("positive_catalysts", [])
        if label in {"positive", "strong_positive"} and isinstance(positive_catalysts, list) and positive_catalysts:
            reasons.append(f"Catalyst support: {positive_catalysts[0]}")

    relative_strength_context = candidate.get("relative_strength_context", {})
    if isinstance(relative_strength_context, dict):
        rs_label = str(relative_strength_context.get("relative_strength_label", "")).lower()
        if rs_label in {"market_leader", "outperforming"}:
            reasons.append(
                f"Relative strength is {rs_label.replace('_', ' ')} versus market benchmarks."
            )

    seen: set[str] = set()
    deduped = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            deduped.append(reason)
    return deduped[:6]


def _build_risks(candidate: dict) -> list[str]:
    risks: list[str] = []

    failed_constraints = candidate.get("failed_constraints")
    if isinstance(failed_constraints, list):
        risks.extend(f"Constraint failed: {item}" for item in failed_constraints if item)

    statistical_context = candidate.get("statistical_context", {})
    if isinstance(statistical_context, dict):
        warnings = statistical_context.get("warnings", [])
        if isinstance(warnings, list):
            risks.extend(str(item) for item in warnings if item)

    catalyst_context = candidate.get("catalyst_context", {})
    if isinstance(catalyst_context, dict):
        for key in ("negative_catalysts", "risk_flags"):
            items = catalyst_context.get(key, [])
            if isinstance(items, list):
                risks.extend(str(item) for item in items if item)

    relative_strength_context = candidate.get("relative_strength_context", {})
    if isinstance(relative_strength_context, dict):
        rs_label = str(relative_strength_context.get("relative_strength_label", "")).lower()
        if rs_label in {"underperforming", "market_laggard"}:
            risks.append("Relative strength is weak versus SPY/QQQ or sector context.")
        rs_flags = relative_strength_context.get("risk_flags", [])
        if isinstance(rs_flags, list):
            risks.extend(str(item) for item in rs_flags if item)

    data_quality = candidate.get("data_quality", {})
    if isinstance(data_quality, dict):
        risks.extend(str(item) for item in data_quality.get("warnings", []) if item)
        risks.extend(str(item) for item in data_quality.get("errors", []) if item)

    filing_sentiment = candidate.get("filing_sentiment", {})
    if isinstance(filing_sentiment, dict):
        risks.extend(str(item) for item in filing_sentiment.get("warnings", []) if item)
        risk_level = str(filing_sentiment.get("filing_risk_level", "")).lower()
        trade_impact = str(filing_sentiment.get("trade_impact", "")).lower()
        if risk_level in {"medium", "high", "critical"} or trade_impact in {"caution", "blocking"}:
            risks.extend(str(item) for item in filing_sentiment.get("reasons", []) if item)

    short_interest = candidate.get("short_interest", {})
    if isinstance(short_interest, dict):
        risks.extend(str(item) for item in short_interest.get("warnings", []) if item)
        if str(short_interest.get("trade_impact", "")).lower() in {"caution", "blocking"}:
            risks.extend(str(item) for item in short_interest.get("reasons", []) if item)

    borrow_pressure = candidate.get("borrow_pressure", {})
    if isinstance(borrow_pressure, dict):
        risks.extend(str(item) for item in borrow_pressure.get("warnings", []) if item)
        if not borrow_pressure.get("short_trade_allowed", True):
            risks.append("Borrow pressure blocks short-style candidates.")

    news_sentiment = candidate.get("news_sentiment", {})
    if isinstance(news_sentiment, dict):
        risks.extend(str(item) for item in news_sentiment.get("warnings", []) if item)
        risk_level = str(news_sentiment.get("headline_risk_level", "")).lower()
        if risk_level in {"medium", "high", "critical"} or str(news_sentiment.get("trade_impact", "")).lower() in {"caution", "blocking"}:
            risks.extend(str(item) for item in news_sentiment.get("risk_flags", []) if item)

    concentration_context = candidate.get("concentration_risk_context", {})
    if isinstance(concentration_context, dict):
        risks.extend(str(item) for item in concentration_context.get("warnings", []) if item)
        risk_level = str(concentration_context.get("risk_level", "")).lower()
        if risk_level in {"high", "blocked"}:
            risks.extend(str(item) for item in concentration_context.get("reasons", []) if item)

    technical_summary = candidate.get("technical_confirmation_summary", {})
    if isinstance(technical_summary, dict):
        risks.extend(str(item) for item in technical_summary.get("warnings", []) if item)
        if str(technical_summary.get("status", "")).lower() in {"warning", "rejected"}:
            risks.extend(str(item) for item in technical_summary.get("reasons", []) if item)

    option_trade_risk = candidate.get("option_trade_risk", {})
    if isinstance(option_trade_risk, dict):
        risks.extend(str(item) for item in option_trade_risk.get("warnings", []) if item)
        risks.extend(str(item) for item in option_trade_risk.get("errors", []) if item)

    status = _candidate_status(candidate)
    if status == "watchlist":
        risks.append("Candidate is watchlist-only and not a final recommendation.")
    elif status == "rejected":
        rejection_reason = candidate.get("rejection_reason")
        if rejection_reason:
            risks.append(str(rejection_reason))

    seen: set[str] = set()
    deduped = []
    for risk in risks:
        if risk not in seen:
            seen.add(risk)
            deduped.append(risk)
    return deduped[:8]


def _data_used(candidate: dict) -> dict:
    return {
        "constraints": isinstance(_constraint_payload(candidate).get("constraint_results"), dict),
        "statistics": isinstance(candidate.get("statistical_context"), dict),
        "catalysts": isinstance(candidate.get("catalyst_context"), dict),
        "relative_strength": isinstance(candidate.get("relative_strength_context"), dict),
        "market_snapshot": isinstance(candidate.get("technical_snapshot"), dict) or candidate.get("current_price") is not None,
        "sec_filings": isinstance(candidate.get("filing_analysis"), dict) or isinstance(candidate.get("filing_sentiment"), dict),
        "short_interest": isinstance(candidate.get("short_interest"), dict),
        "borrow_pressure": isinstance(candidate.get("borrow_pressure"), dict),
        "news_sentiment": isinstance(candidate.get("news_sentiment"), dict),
    }


def _filing_sentiment_summary(selection_result: dict | None) -> dict:
    evaluations = []
    if not isinstance(selection_result, dict):
        return {"ok": True, "evaluated_count": 0, "blocking_count": 0, "high_risk_count": 0, "evaluations": []}
    for collection_name in ("selected_trades", "watchlist_alternatives", "rejected_candidates"):
        collection = selection_result.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for candidate in collection:
            if not isinstance(candidate, dict):
                continue
            filing_sentiment = candidate.get("filing_sentiment")
            filing_analysis = candidate.get("filing_analysis")
            earnings_analysis = candidate.get("earnings_8k_analysis")
            if not any(isinstance(item, dict) for item in (filing_sentiment, filing_analysis, earnings_analysis)):
                continue
            evaluations.append(
                {
                    "ticker": _normalize_ticker(candidate.get("ticker")),
                    "bucket": collection_name,
                    "filing_sentiment": filing_sentiment,
                    "filing_analysis": filing_analysis,
                    "earnings_8k_analysis": earnings_analysis,
                }
            )
    filings_loaded_count = 0
    for item in evaluations:
        analysis = item.get("filing_analysis")
        recent_filings = analysis.get("recent_filings") if isinstance(analysis, dict) else []
        if isinstance(recent_filings, list) and recent_filings:
            filings_loaded_count += 1
    return {
        "ok": True,
        "evaluated_count": len(evaluations),
        "filings_loaded_count": filings_loaded_count,
        "earnings_8k_count": sum(1 for item in evaluations if isinstance(item.get("earnings_8k_analysis"), dict)),
        "blocking_count": sum(1 for item in evaluations if str(((item.get("filing_sentiment") or {}).get("trade_impact", ""))).lower() == "blocking"),
        "high_risk_count": sum(1 for item in evaluations if str(((item.get("filing_sentiment") or {}).get("filing_risk_level", ""))).lower() == "high"),
        "evaluations": evaluations,
    }


def _research_risk_summary(selection_result: dict | None) -> dict:
    evaluations = []
    if not isinstance(selection_result, dict):
        return {"ok": True, "evaluated_count": 0, "blocking_count": 0, "reduced_count": 0, "evaluations": []}
    for collection_name in ("selected_trades", "watchlist_alternatives", "rejected_candidates"):
        collection = selection_result.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for candidate in collection:
            if not isinstance(candidate, dict):
                continue
            contexts = {
                "short_interest": candidate.get("short_interest"),
                "borrow_pressure": candidate.get("borrow_pressure"),
                "news_sentiment": candidate.get("news_sentiment"),
            }
            if not any(isinstance(value, dict) for value in contexts.values()):
                continue
            evaluations.append({"ticker": _normalize_ticker(candidate.get("ticker")), "bucket": collection_name, **contexts})
    return {
        "ok": True,
        "evaluated_count": len(evaluations),
        "blocking_count": sum(
            1
            for item in evaluations
            if str(((item.get("news_sentiment") or {}).get("trade_impact", ""))).lower() == "blocking"
            or str(((item.get("short_interest") or {}).get("trade_impact", ""))).lower() == "blocking"
            or ((item.get("borrow_pressure") or {}).get("short_trade_allowed") is False)
        ),
        "reduced_count": sum(
            1
            for item in evaluations
            if str(((item.get("news_sentiment") or {}).get("trade_impact", ""))).lower() == "caution"
            or str(((item.get("short_interest") or {}).get("trade_impact", ""))).lower() == "caution"
        ),
        "evaluations": evaluations,
    }


def _apply_setup_decay_to_selection(selection_result: dict, setup_decay: dict | None) -> dict:
    if not isinstance(selection_result, dict) or not isinstance(setup_decay, dict):
        return selection_result
    setup_table = setup_decay.get("setups", {}) if isinstance(setup_decay.get("setups"), dict) else {}
    if not setup_table:
        return selection_result

    adjusted = deepcopy(selection_result)
    selected = adjusted.get("selected_trades", [])
    if not isinstance(selected, list):
        return adjusted
    retained: list[dict] = []
    watchlist = list(adjusted.get("watchlist_alternatives", [])) if isinstance(adjusted.get("watchlist_alternatives"), list) else []
    rejected = list(adjusted.get("rejected_candidates", [])) if isinstance(adjusted.get("rejected_candidates"), list) else []

    for candidate in selected:
        if not isinstance(candidate, dict):
            continue
        setup_name = str(candidate.get("setup_type") or candidate.get("selected_profile") or candidate.get("scan_profile") or "unknown")
        decay = setup_table.get(setup_name)
        if not isinstance(decay, dict):
            retained.append(candidate)
            continue
        candidate = deepcopy(candidate)
        candidate["setup_decay_context"] = decay
        status = str(decay.get("status", "healthy")).lower()
        if status == "disabled":
            candidate["recommendation_status"] = "rejected"
            candidate["passed"] = False
            candidate["failed_constraints"] = list(candidate.get("failed_constraints", [])) + ["setup_decay_disabled"]
            candidate["rejection_reason"] = "; ".join(decay.get("reasons") or ["Setup is disabled by decay detection."])
            rejected.append(candidate)
        elif status == "decaying" and (_safe_float(candidate.get("score")) or 0.0) < 95.0:
            candidate["recommendation_status"] = "watchlist"
            candidate["passed"] = True
            candidate["downgrade_reason"] = "; ".join(decay.get("reasons") or ["Setup is decaying."])
            watchlist.append(candidate)
        else:
            retained.append(candidate)

    adjusted["selected_trades"] = retained
    adjusted["watchlist_alternatives"] = watchlist
    adjusted["rejected_candidates"] = rejected
    adjusted["setup_decay"] = setup_decay
    return adjusted


def _risk_multiplier_context(candidate: dict) -> tuple[dict[str, float], list[str]]:
    multipliers: dict[str, float] = {}
    reasons: list[str] = []
    circuit = candidate.get("circuit_breaker_context")
    if isinstance(circuit, dict):
        value = _safe_float(circuit.get("max_allowed_risk_multiplier"))
        if value is not None:
            multipliers["circuit_breaker"] = value
            if value < 1:
                reasons.append(f"Circuit breaker multiplier {value}.")
    macro = candidate.get("macro_risk_context")
    if isinstance(macro, dict):
        value = _safe_float(macro.get("risk_multiplier"))
        if value is not None:
            multipliers["macro_risk"] = value
            if value < 1:
                reasons.append(f"Macro risk multiplier {value}.")
    regime = candidate.get("market_regime_context") or candidate.get("market_regime")
    if isinstance(regime, dict):
        key = "option_risk_multiplier" if str(candidate.get("preferred_instrument", candidate.get("asset_type", "stock"))).lower() == "option" else "stock_risk_multiplier"
        value = _safe_float(regime.get(key))
        if value is not None:
            multipliers["market_regime"] = value
            if value < 1:
                reasons.append(f"Market regime multiplier {value}.")
    concentration = candidate.get("concentration_risk_context")
    if isinstance(concentration, dict):
        value = _safe_float(concentration.get("risk_multiplier"))
        if value is not None:
            multipliers["concentration"] = value
            if value < 1:
                reasons.extend(str(reason) for reason in concentration.get("reasons", []) if reason)
    technical = candidate.get("technical_confirmation_summary")
    if isinstance(technical, dict):
        value = _safe_float(technical.get("risk_multiplier"))
        if value is not None:
            multipliers["technical_confirmation"] = value
            if value < 1:
                reasons.extend(str(reason) for reason in technical.get("reasons", []) if reason)
    filing = candidate.get("filing_sentiment")
    if isinstance(filing, dict):
        value = _safe_float(filing.get("risk_multiplier"))
        if value is not None:
            multipliers["filing_sentiment"] = value
            if value < 1:
                reasons.extend(str(reason) for reason in filing.get("reasons", []) if reason)
    news = candidate.get("news_sentiment")
    if isinstance(news, dict):
        value = _safe_float(news.get("risk_multiplier"))
        if value is not None:
            multipliers["news_sentiment"] = value
            if value < 1:
                reasons.extend(str(reason) for reason in news.get("risk_flags", []) if reason)
    short_interest = candidate.get("short_interest")
    if isinstance(short_interest, dict):
        value = _safe_float(short_interest.get("risk_multiplier"))
        if value is not None:
            multipliers["short_interest"] = value
            if value < 1:
                reasons.extend(str(reason) for reason in short_interest.get("reasons", []) if reason)
    return multipliers, reasons


def _extract_matrix_from_snapshot(snapshot_result: dict | None) -> dict | None:
    if not isinstance(snapshot_result, dict):
        return None
    snapshot = snapshot_result.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    matrix = snapshot.get("matrix_json")
    if not isinstance(matrix, dict):
        return None
    return {
        "ok": snapshot_result.get("ok", False),
        "snapshot_id": snapshot.get("snapshot_id"),
        "created_at": snapshot.get("created_at"),
        "age_hours": snapshot.get("age_hours"),
        "is_stale": snapshot.get("is_stale"),
        "lookback_days": snapshot.get("lookback_days"),
        "tickers": snapshot.get("tickers_json") or [],
        "correlations": matrix,
    }


def _historical_price_provider(ticker: str, lookback_days: int) -> dict:
    from realtime.market_data import get_historical_bars

    return get_historical_bars(ticker, lookback_days=lookback_days + 10)


def _load_or_refresh_correlation_context(
    *,
    db_path: str,
    tickers: list[str],
    lookback_days: int = 60,
    max_age_hours: int = 36,
) -> tuple[dict | None, dict]:
    latest = get_latest_correlation_snapshot(db_path=db_path, max_age_hours=max_age_hours)
    if latest.get("ok"):
        return _extract_matrix_from_snapshot(latest), {
            "ok": True,
            "source": "latest_snapshot",
            "latest_snapshot": latest,
            "refresh_result": None,
            "warnings": [],
            "errors": [],
        }

    refresh_result = refresh_correlation_snapshot(
        db_path=db_path,
        tickers=sorted(set(ticker for ticker in tickers if ticker)),
        price_history_provider=_historical_price_provider,
        lookback_days=lookback_days,
    )
    refreshed = get_latest_correlation_snapshot(db_path=db_path, max_age_hours=max_age_hours)
    matrix = _extract_matrix_from_snapshot(refreshed)
    return matrix, {
        "ok": bool(matrix),
        "source": "refreshed_snapshot" if matrix else "unavailable",
        "latest_snapshot": refreshed,
        "refresh_result": refresh_result,
        "warnings": list(refresh_result.get("warnings", [])) if isinstance(refresh_result, dict) else [],
        "errors": list(refresh_result.get("errors", [])) if isinstance(refresh_result, dict) else [latest.get("error", "Correlation snapshot unavailable.")],
    }


def _audit_if_run_id(db_path: str, logging_metadata: dict | None, event_type: str, payload: dict) -> None:
    if not isinstance(logging_metadata, dict) or not logging_metadata.get("run_id"):
        return
    append_audit_event(
        db_path=db_path,
        run_id=str(logging_metadata["run_id"]),
        event_type=event_type,
        payload=payload if isinstance(payload, dict) else {},
    )


def _apply_research_brief_to_decision(decision: dict, research_brief: dict | None) -> dict:
    if not isinstance(decision, dict) or not isinstance(research_brief, dict):
        return decision

    enriched = deepcopy(decision)
    enriched["research_brief"] = research_brief
    enriched["research_summary"] = research_brief.get("research_summary")
    enriched["research_conviction"] = research_brief.get("research_conviction")
    enriched["bull_case"] = research_brief.get("bull_case")
    enriched["bear_case"] = research_brief.get("bear_case")
    enriched["key_risks"] = research_brief.get("key_risks")

    raw_context = research_brief.get("raw_context", {})
    if isinstance(raw_context, dict):
        source_candidate = enriched.get("source_candidate")
        if isinstance(source_candidate, dict):
            relative_strength = raw_context.get("relative_strength")
            if isinstance(relative_strength, dict) and not isinstance(source_candidate.get("relative_strength_context"), dict):
                source_candidate["relative_strength_context"] = relative_strength
                enriched["relative_strength_context"] = relative_strength
            market_regime = raw_context.get("market_regime")
            if isinstance(market_regime, dict):
                source_candidate.setdefault("market_regime_context", market_regime)
    return enriched


def _best_option_alternatives(candidate: dict, limit: int = 3) -> list[dict]:
    option_alternatives = candidate.get("option_alternatives", [])
    if not isinstance(option_alternatives, list):
        return []
    return [deepcopy(option) for option in option_alternatives[:limit] if isinstance(option, dict)]


def _option_strategy_context(candidate: dict) -> dict:
    selected = candidate.get("selected_option_strategy")
    strategies = candidate.get("option_strategy_candidates")
    return {
        "selected_option_strategy": selected if isinstance(selected, dict) else None,
        "option_strategy_candidates": strategies if isinstance(strategies, list) else [],
        "option_strategy_summary": candidate.get("option_strategy_summary") if isinstance(candidate.get("option_strategy_summary"), dict) else {},
    }


def _select_preferred_option(candidate: dict) -> tuple[dict | None, str | None]:
    option_alternatives = _best_option_alternatives(candidate, limit=3)
    if not option_alternatives:
        return None, "No option alternatives were available."

    preferred_option = option_alternatives[0]
    strategy_context = _option_strategy_context(candidate)
    selected_strategy = strategy_context.get("selected_option_strategy")
    if isinstance(selected_strategy, dict):
        strategy_status = str(selected_strategy.get("status", "")).lower()
        if strategy_status != "paper_eligible":
            return None, f"Selected option strategy is {strategy_status or 'unavailable'}, so options remain research-only."
        if str(selected_strategy.get("strategy_type", "")).lower() not in {"long_call", "long_put"}:
            return None, "Selected option strategy is multi-leg/research structure and cannot be logged as a single option trade yet."
    if not preferred_option.get("passed"):
        return None, "Best option alternative did not pass strict option constraints."
    if str(preferred_option.get("recommendation_status", "")).lower() != "recommendable":
        return None, "Best option alternative is not recommendable."
    if str(preferred_option.get("mispricing_label", "")).lower() == "cheap_but_low_probability":
        return None, "Best option alternative looks cheap, but probability context is too weak to prefer it."
    if not preferred_option.get("option_contract"):
        return None, "Best option alternative is missing option_contract."
    if not preferred_option.get("expiration"):
        return None, "Best option alternative is missing expiration."
    if not preferred_option.get("breakeven_realistic"):
        return None, "Best option alternative does not have a realistic breakeven relative to the target."
    risk_reward = _safe_float(preferred_option.get("risk_reward"))
    if risk_reward is None or risk_reward < DEFAULT_MINIMUM_RISK_REWARD:
        return None, "Best option alternative does not meet minimum risk/reward."
    if _safe_float(preferred_option.get("spread_percent")) is None:
        return None, "Best option alternative is missing spread data."
    option_trade_risk = preferred_option.get("option_trade_risk")
    if not isinstance(option_trade_risk, dict) or not option_trade_risk.get("approved"):
        risk_reason = ""
        if isinstance(option_trade_risk, dict):
            risk_reason = "; ".join(
                str(item)
                for item in (option_trade_risk.get("errors") or option_trade_risk.get("warnings") or [])
                if item
            )
        return None, risk_reason or "Best option alternative is not approved by IV/Greeks/spread risk checks."
    mispricing_score = _safe_float(preferred_option.get("mispricing_score"))
    if mispricing_score is not None and mispricing_score < 60:
        return None, "Best option alternative does not have strong enough valuation context to be preferred."
    return preferred_option, None


def build_trade_decision(
    candidate: dict,
    db_path: str = "strategy_library.db",
    prefer_options: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    include_position_sizing: bool = True,
    include_memory_context: bool = True,
    logging_metadata: dict | None = None,
) -> dict:
    candidate_copy = deepcopy(candidate)
    if not isinstance(candidate_copy.get("statistical_context"), dict):
        candidate_copy = enrich_candidate_with_statistics(candidate_copy, db_path=db_path)

    status = _candidate_status(candidate_copy)
    constraint_payload = _constraint_payload(candidate_copy)
    risk_reward = _safe_float(candidate_copy.get("risk_reward"))
    entry_price = _safe_float(candidate_copy.get("entry_price"))
    target_price = _safe_float(candidate_copy.get("target_price"))
    stop_loss = _safe_float(candidate_copy.get("stop_loss"))

    decision = "reject"
    if status == "recommendable" and constraint_payload.get("passed") and None not in (entry_price, target_price, stop_loss) and risk_reward is not None and risk_reward >= DEFAULT_MINIMUM_RISK_REWARD:
        decision = "recommend"
    elif status == "watchlist":
        decision = "watchlist"
    filing_sentiment = candidate_copy.get("filing_sentiment")
    if isinstance(filing_sentiment, dict) and str(filing_sentiment.get("trade_impact", "")).lower() == "blocking":
        decision = "reject"
    news_sentiment = candidate_copy.get("news_sentiment")
    if isinstance(news_sentiment, dict) and str(news_sentiment.get("trade_impact", "")).lower() == "blocking":
        decision = "reject"
    short_interest = candidate_copy.get("short_interest")
    if isinstance(short_interest, dict) and str(short_interest.get("trade_impact", "")).lower() == "blocking":
        decision = "reject"
    borrow_pressure = candidate_copy.get("borrow_pressure")
    if (
        str(candidate_copy.get("direction", "")).lower() == "short"
        and isinstance(borrow_pressure, dict)
        and not borrow_pressure.get("short_trade_allowed", True)
    ):
        decision = "reject"

    why_selected = _build_why_selected(candidate_copy)
    risks = _build_risks(candidate_copy)
    ticker = _normalize_ticker(candidate_copy.get("ticker"))
    holding_period_days = _holding_period(candidate_copy)
    confidence_label = _confidence_label(candidate_copy)
    option_alternatives = _best_option_alternatives(candidate_copy, limit=3)
    preferred_option_contract = None
    option_selection_reason = None
    option_risks: list[str] = []
    preferred_instrument = "stock"
    preferred_option_mispricing_context = None
    option_strategy_context = _option_strategy_context(candidate_copy)

    if option_alternatives:
        _, option_reason = _select_preferred_option(candidate_copy)
        if prefer_options:
            preferred_option, option_reason = _select_preferred_option(candidate_copy)
            if preferred_option is not None:
                preferred_instrument = "option"
                preferred_option_contract = preferred_option.get("option_contract")
                option_selection_reason = (
                    f"Preferred option {preferred_option_contract} passed strict option constraints with acceptable liquidity and realistic breakeven."
                )
                option_risks = _build_risks(preferred_option)
                preferred_option_mispricing_context = preferred_option.get("mispricing_context")
                candidate_copy["preferred_option_trade_risk"] = preferred_option.get("option_trade_risk")
            else:
                option_selection_reason = option_reason
                if option_reason:
                    option_risks.append(option_reason)
        else:
            option_selection_reason = "Option alternatives are available as research, but stock remains the default preferred instrument."

    position_sizing = None
    if include_position_sizing:
        risk_multipliers, risk_multiplier_reasons = _risk_multiplier_context(candidate_copy)
        sizing_trade = {
            "ticker": ticker,
            "underlying_ticker": candidate_copy.get("underlying_ticker") or ticker,
            "asset_type": "option" if preferred_instrument == "option" else candidate_copy.get("asset_type", "stock"),
            "preferred_instrument": preferred_instrument,
            "option_contract": preferred_option_contract,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss": stop_loss,
        }
        if preferred_instrument == "option":
            preferred_option = next(
                (
                    option for option in option_alternatives
                    if isinstance(option, dict) and option.get("option_contract") == preferred_option_contract
                ),
                None,
            )
            if isinstance(preferred_option, dict):
                sizing_trade.update(
                    {
                        "ticker": preferred_option.get("ticker") or ticker,
                        "underlying_ticker": preferred_option.get("underlying_ticker") or ticker,
                        "entry_price": _safe_float(preferred_option.get("mid")) or _safe_float(preferred_option.get("entry_price")),
                        "mid": preferred_option.get("mid"),
                        "premium": preferred_option.get("premium"),
                    }
                )
        position_sizing = calculate_position_size(
            sizing_trade,
            account_size=account_size,
            risk_mode=risk_mode,
            config={
                "risk_multipliers": risk_multipliers,
                "risk_multiplier_reasons": risk_multiplier_reasons,
            },
        )
        if isinstance(position_sizing, dict):
            circuit_context = candidate_copy.get("circuit_breaker_context")
            if isinstance(circuit_context, dict):
                position_sizing["circuit_breaker_context"] = circuit_context
            macro_context = candidate_copy.get("macro_risk_context")
            if isinstance(macro_context, dict):
                position_sizing["macro_risk_context"] = macro_context
            market_regime_context = candidate_copy.get("market_regime_context")
            if isinstance(market_regime_context, dict):
                position_sizing["market_regime_context"] = market_regime_context
            concentration_context = candidate_copy.get("concentration_risk_context")
            if isinstance(concentration_context, dict):
                position_sizing["concentration_risk_context"] = concentration_context
            technical_context = candidate_copy.get("technical_confirmation_summary")
            if isinstance(technical_context, dict):
                position_sizing["technical_confirmation_summary"] = technical_context
            filing_context = candidate_copy.get("filing_sentiment")
            if isinstance(filing_context, dict):
                position_sizing["filing_sentiment"] = filing_context
            news_context = candidate_copy.get("news_sentiment")
            if isinstance(news_context, dict):
                position_sizing["news_sentiment"] = news_context
            short_context = candidate_copy.get("short_interest")
            if isinstance(short_context, dict):
                position_sizing["short_interest"] = short_context
            warnings = position_sizing.get("warnings", [])
            if isinstance(warnings, list):
                for warning in warnings:
                    text = str(warning)
                    if text and text not in risks:
                        risks.append(text)
            if position_sizing.get("ok") and position_sizing.get("asset_type") == "stock" and position_sizing.get("shares", 0) < 1:
                if decision == "recommend":
                    decision = "watchlist"
            if position_sizing.get("ok") and position_sizing.get("asset_type") == "option" and position_sizing.get("contracts", 0) < 1:
                if decision == "recommend":
                    decision = "watchlist"

    similar_setup_context = None
    memory_context = None
    retrieval_quality = None
    human_feedback = None
    if include_memory_context:
        memory_candidate = {
            **candidate_copy,
            "ticker": ticker,
            "decision": decision,
        }
        query_context = build_memory_query_context(
            memory_candidate,
            market_context=candidate_copy.get("market_regime_context"),
        )
        annotations_summary = summarize_annotations(
            db_path=db_path,
            ticker=ticker,
            setup_type=candidate_copy.get("setup_type"),
        )
        if annotations_summary.get("ok"):
            memory_candidate["annotations_summary"] = annotations_summary
            human_feedback = evaluate_annotation_feedback(memory_candidate, annotations_summary)
        if _memory_enabled():
            similar_setup_context = find_similar_setups(memory_candidate, top_k=5)
            retrieval_quality = evaluate_retrieval_quality(
                similar_setup_context,
                query_context=query_context.get("structured_context"),
            )
            memory_context = build_memory_decision_context(
                memory_candidate,
                retrieval_result=similar_setup_context,
                retrieval_quality=retrieval_quality,
            )
            event_result = record_memory_retrieval_event(
                db_path=db_path,
                run_id=(logging_metadata or {}).get("run_id") if isinstance(logging_metadata, dict) else None,
                ticker=ticker,
                setup_type=candidate_copy.get("setup_type"),
                query=query_context,
                retrieval_result=similar_setup_context,
                retrieval_quality=retrieval_quality,
                used_for_decision=bool(retrieval_quality.get("usable_for_decision_support")) if isinstance(retrieval_quality, dict) else False,
                used_for_explanation=bool(retrieval_quality.get("usable_for_explanation")) if isinstance(retrieval_quality, dict) else False,
            )
            _audit_if_run_id(db_path, logging_metadata, "memory_retrieval_attempted", {"ticker": ticker, "setup_type": candidate_copy.get("setup_type"), "result": similar_setup_context})
            _audit_if_run_id(db_path, logging_metadata, "memory_retrieval_quality_evaluated", retrieval_quality or {})
            _audit_if_run_id(db_path, logging_metadata, "memory_context_applied", memory_context or {})
            if not event_result.get("ok"):
                risks.append(f"Memory retrieval event was not recorded: {event_result.get('error')}")
        else:
            retrieval_quality = evaluate_retrieval_quality(
                {"ok": False, "source": "disabled", "matches": [], "error": "Memory is disabled."},
                query_context=query_context.get("structured_context"),
            )
            memory_context = build_memory_decision_context(
                memory_candidate,
                retrieval_result={"ok": False, "source": "disabled", "matches": [], "error": "Memory is disabled."},
                retrieval_quality=retrieval_quality,
            )
            similar_setup_context = {
                "ok": False,
                "source": "disabled",
                "query": query_context.get("query_text"),
                "matches": [],
                "warnings": ["Memory is disabled; no Pinecone retrieval was attempted."],
                "label": "disabled",
                "error": "Memory is disabled.",
            }
        if human_feedback:
            memory_context = memory_context or {}
            memory_context["human_feedback"] = human_feedback
            _audit_if_run_id(db_path, logging_metadata, "human_feedback_evaluated", human_feedback)
            if str(human_feedback.get("feedback_status", "")).lower() in {"caution", "blocking"}:
                risks.extend(str(item) for item in human_feedback.get("reasons", []) if item)

    thesis_parts = []
    if decision == "recommend":
        thesis_parts.append(f"{ticker} passed objective constraints.")
    elif decision == "watchlist":
        thesis_parts.append(f"{ticker} is close to qualifying but remains watchlist-only.")
    else:
        thesis_parts.append(f"{ticker} does not qualify as a final trade.")
    if why_selected:
        thesis_parts.append(why_selected[0])
    thesis_parts.append(f"Planned holding period is {holding_period_days} days.")
    thesis = " ".join(thesis_parts)

    invalidation = "Trade invalidates if the stop loss is hit."
    if stop_loss is not None:
        invalidation = f"Trade invalidates if price hits or closes through the stop loss at {round(stop_loss, 4)}."

    return {
        "ticker": ticker,
        "decision": decision,
        "confidence_label": confidence_label,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "holding_period_days": holding_period_days,
        "thesis": thesis,
        "invalidation": invalidation,
        "why_selected": why_selected,
        "risks": risks,
        "relative_strength_context": candidate_copy.get("relative_strength_context"),
        "macro_risk_context": candidate_copy.get("macro_risk_context"),
        "market_regime_context": candidate_copy.get("market_regime_context"),
        "circuit_breaker_context": candidate_copy.get("circuit_breaker_context"),
        "concentration_risk_context": candidate_copy.get("concentration_risk_context"),
        "technical_confirmation_summary": candidate_copy.get("technical_confirmation_summary"),
        "volume_profile_confirmation": candidate_copy.get("volume_profile_confirmation"),
        "timeframe_confirmation": candidate_copy.get("timeframe_confirmation"),
        "filing_analysis": candidate_copy.get("filing_analysis"),
        "earnings_8k_analysis": candidate_copy.get("earnings_8k_analysis"),
        "filing_sentiment": candidate_copy.get("filing_sentiment"),
        "short_interest": candidate_copy.get("short_interest"),
        "borrow_pressure": candidate_copy.get("borrow_pressure"),
        "news_sentiment": candidate_copy.get("news_sentiment"),
        "option_alternatives": option_alternatives,
        "preferred_instrument": preferred_instrument,
        "preferred_option_contract": preferred_option_contract,
        "option_selection_reason": option_selection_reason,
        "option_risks": option_risks,
        "preferred_option_mispricing_context": preferred_option_mispricing_context,
        "preferred_option_trade_risk": candidate_copy.get("preferred_option_trade_risk"),
        "option_strategy_candidates": option_strategy_context.get("option_strategy_candidates"),
        "selected_option_strategy": option_strategy_context.get("selected_option_strategy"),
        "option_strategy_summary": option_strategy_context.get("option_strategy_summary"),
        "position_sizing": position_sizing,
        "similar_setup_context": similar_setup_context,
        "memory_context": memory_context,
        "retrieval_quality": retrieval_quality,
        "human_feedback": human_feedback,
        "data_used": _data_used(candidate_copy),
        "source_candidate": candidate_copy,
    }


def _can_recommend(candidate: dict, seen_tickers: set[str]) -> tuple[bool, str | None]:
    ticker = _normalize_ticker(candidate.get("ticker"))
    if not ticker:
        return False, "Ticker is missing."
    if ticker in seen_tickers:
        return False, "Duplicate ticker."
    if _candidate_status(candidate) != "recommendable":
        return False, "Candidate is not recommendable."
    if not _constraint_passed(candidate):
        return False, "Constraint checks did not pass."
    technical_summary = candidate.get("technical_confirmation_summary")
    if isinstance(technical_summary, dict) and str(technical_summary.get("status", "")).lower() == "rejected":
        return False, "Technical confirmation rejected candidate."
    filing_sentiment = candidate.get("filing_sentiment")
    if isinstance(filing_sentiment, dict) and str(filing_sentiment.get("trade_impact", "")).lower() == "blocking":
        return False, "Critical filing risk blocks candidate."
    news_sentiment = candidate.get("news_sentiment")
    if isinstance(news_sentiment, dict) and str(news_sentiment.get("trade_impact", "")).lower() == "blocking":
        return False, "Critical headline risk blocks candidate."
    short_interest = candidate.get("short_interest")
    if isinstance(short_interest, dict) and str(short_interest.get("trade_impact", "")).lower() == "blocking":
        return False, "Short-interest squeeze risk blocks candidate."
    borrow_pressure = candidate.get("borrow_pressure")
    if str(candidate.get("direction", "")).lower() == "short" and isinstance(borrow_pressure, dict) and not borrow_pressure.get("short_trade_allowed", True):
        return False, "Borrow pressure blocks short candidate."
    data_quality = candidate.get("data_quality")
    if isinstance(data_quality, dict) and not data_quality.get("final_recommendation_allowed", True):
        reason = "; ".join(data_quality.get("errors") or data_quality.get("warnings") or ["Market data quality blocks final recommendations."])
        return False, reason
    for field_name in ("entry_price", "target_price", "stop_loss"):
        if _safe_float(candidate.get(field_name)) is None:
            return False, f"{field_name} is missing."
    risk_reward = _safe_float(candidate.get("risk_reward"))
    if risk_reward is None or risk_reward < DEFAULT_MINIMUM_RISK_REWARD:
        return False, "risk_reward is below the minimum threshold."
    return True, None


def _log_final_recommendation(decision: dict, db_path: str) -> dict:
    from tools.agent_tools import log_recommendation_tool

    return _log_final_recommendation_with_metadata(decision, db_path=db_path, logging_metadata=None)


def _log_final_recommendation_with_metadata(
    decision: dict,
    db_path: str,
    logging_metadata: dict | None = None,
) -> dict:
    from tools.agent_tools import log_recommendation_tool

    source_candidate = decision.get("source_candidate", {})
    data_snapshot = {
        "selected_profile": source_candidate.get("selected_profile"),
        "scan_profile": source_candidate.get("scan_profile"),
        "data_quality": source_candidate.get("data_quality"),
        "price_source": source_candidate.get("price_source"),
        "quote_status": source_candidate.get("quote_status"),
        "circuit_breaker": source_candidate.get("circuit_breaker_context") or decision.get("circuit_breaker_context"),
        "macro_risk": source_candidate.get("macro_risk_context") or decision.get("macro_risk_context"),
        "market_regime": source_candidate.get("market_regime_context") or decision.get("market_regime_context"),
        "concentration_risk": source_candidate.get("concentration_risk_context") or decision.get("concentration_risk_context"),
        "technical_confirmation": source_candidate.get("technical_confirmation_summary") or decision.get("technical_confirmation_summary"),
        "volume_profile_confirmation": source_candidate.get("volume_profile_confirmation") or decision.get("volume_profile_confirmation"),
        "timeframe_confirmation": source_candidate.get("timeframe_confirmation") or decision.get("timeframe_confirmation"),
        "filing_analysis": source_candidate.get("filing_analysis") or decision.get("filing_analysis"),
        "earnings_8k_analysis": source_candidate.get("earnings_8k_analysis") or decision.get("earnings_8k_analysis"),
        "filing_sentiment": source_candidate.get("filing_sentiment") or decision.get("filing_sentiment"),
        "short_interest": source_candidate.get("short_interest") or decision.get("short_interest"),
        "borrow_pressure": source_candidate.get("borrow_pressure") or decision.get("borrow_pressure"),
        "news_sentiment": source_candidate.get("news_sentiment") or decision.get("news_sentiment"),
        "selected_option_strategy": source_candidate.get("selected_option_strategy") or decision.get("selected_option_strategy"),
        "option_strategy_summary": source_candidate.get("option_strategy_summary") or decision.get("option_strategy_summary"),
        "setup_decay": source_candidate.get("setup_decay_context"),
        "memory_context": source_candidate.get("memory_context") or decision.get("memory_context"),
        "retrieval_quality": source_candidate.get("retrieval_quality") or decision.get("retrieval_quality"),
        "human_feedback": source_candidate.get("human_feedback") or decision.get("human_feedback"),
    }
    model_outputs = {
        "scan_profile": source_candidate.get("scan_profile"),
        "selected_profile": source_candidate.get("selected_profile"),
        "circuit_breaker": source_candidate.get("circuit_breaker_context") or decision.get("circuit_breaker_context"),
        "macro_risk": source_candidate.get("macro_risk_context") or decision.get("macro_risk_context"),
        "market_regime": source_candidate.get("market_regime_context") or decision.get("market_regime_context"),
        "concentration_risk": source_candidate.get("concentration_risk_context") or decision.get("concentration_risk_context"),
        "technical_confirmation": source_candidate.get("technical_confirmation_summary") or decision.get("technical_confirmation_summary"),
        "volume_profile_confirmation": source_candidate.get("volume_profile_confirmation") or decision.get("volume_profile_confirmation"),
        "timeframe_confirmation": source_candidate.get("timeframe_confirmation") or decision.get("timeframe_confirmation"),
        "filing_analysis": source_candidate.get("filing_analysis") or decision.get("filing_analysis"),
        "earnings_8k_analysis": source_candidate.get("earnings_8k_analysis") or decision.get("earnings_8k_analysis"),
        "filing_sentiment": source_candidate.get("filing_sentiment") or decision.get("filing_sentiment"),
        "short_interest": source_candidate.get("short_interest") or decision.get("short_interest"),
        "borrow_pressure": source_candidate.get("borrow_pressure") or decision.get("borrow_pressure"),
        "news_sentiment": source_candidate.get("news_sentiment") or decision.get("news_sentiment"),
        "selected_option_strategy": source_candidate.get("selected_option_strategy") or decision.get("selected_option_strategy"),
        "option_strategy_summary": source_candidate.get("option_strategy_summary") or decision.get("option_strategy_summary"),
        "setup_decay": source_candidate.get("setup_decay_context"),
        "memory_context": source_candidate.get("memory_context") or decision.get("memory_context"),
        "retrieval_quality": source_candidate.get("retrieval_quality") or decision.get("retrieval_quality"),
        "human_feedback": source_candidate.get("human_feedback") or decision.get("human_feedback"),
    }
    if isinstance(logging_metadata, dict):
        data_snapshot.update(logging_metadata)
        model_outputs.update(logging_metadata)
    if isinstance(decision.get("position_sizing"), dict):
        data_snapshot["position_sizing"] = decision["position_sizing"]
        model_outputs["position_sizing"] = decision["position_sizing"]

    preferred_instrument = str(decision.get("preferred_instrument", "stock")).lower()
    option_contract = decision.get("preferred_option_contract")
    expiration = decision.get("expiration")
    entry_price = decision.get("entry_price")
    target_price = decision.get("target_price")
    stop_loss = decision.get("stop_loss")
    risk_reward = decision.get("risk_reward")
    asset_type = source_candidate.get("asset_type", "stock")
    thesis = decision.get("thesis")
    invalidation = decision.get("invalidation")
    score = source_candidate.get("score")
    constraint_results = _constraint_payload(source_candidate)

    if preferred_instrument == "option":
        preferred_option = next(
            (
                option for option in source_candidate.get("option_alternatives", [])
                if isinstance(option, dict) and option.get("option_contract") == option_contract
            ),
            None,
        )
        if not isinstance(preferred_option, dict):
            return {"ok": False, "error": "Preferred option details are missing."}
        if not option_contract:
            return {"ok": False, "error": "Preferred option is missing option_contract."}
        if not preferred_option.get("expiration"):
            return {"ok": False, "error": "Preferred option is missing expiration."}
        if not preferred_option.get("passed"):
            return {"ok": False, "error": "Preferred option failed strict option constraints."}
        if str(preferred_option.get("recommendation_status", "")).lower() != "recommendable":
            return {"ok": False, "error": "Preferred option is not recommendable."}
        option_trade_risk = preferred_option.get("option_trade_risk")
        if not isinstance(option_trade_risk, dict) or not option_trade_risk.get("approved"):
            return {"ok": False, "error": "Preferred option failed IV/Greeks/spread risk approval."}

        option_constraint_payload = {
            "passed": bool(preferred_option.get("passed")),
            "recommendation_status": str(preferred_option.get("recommendation_status", "rejected")).lower(),
            "score": preferred_option.get("score"),
            "constraint_results": preferred_option.get("constraint_results", {}),
            "failed_constraints": preferred_option.get("failed_constraints", []),
            "rejection_reason": preferred_option.get("rejection_reason", ""),
            "config": {"minimum_risk_reward": DEFAULT_MINIMUM_RISK_REWARD},
        }
        asset_type = "option"
        option_contract = preferred_option.get("option_contract")
        expiration = preferred_option.get("expiration")
        entry_price = _safe_float(preferred_option.get("mid"))
        if entry_price is None:
            return {"ok": False, "error": "Preferred option is missing entry premium."}
        target_price = _safe_float(preferred_option.get("expected_value_at_target")) or target_price
        stop_loss = _safe_float(preferred_option.get("expected_value_at_stop"))
        if stop_loss is None:
            stop_loss = 0.0
        risk_reward = _safe_float(preferred_option.get("risk_reward"))
        score = preferred_option.get("score")
        thesis = f"{thesis} Preferred option alternative: {option_contract}."
        invalidation = (
            f"Option thesis invalidates if the underlying setup fails or the option value deteriorates toward the expected stop value at {round(stop_loss, 4)}."
        )
        data_snapshot.update(
            {
                "option_contract": option_contract,
                "expiration": expiration,
                "preferred_instrument": "option",
                "iv_context": preferred_option.get("iv_context"),
                "greeks_monitoring": preferred_option.get("greeks_monitoring"),
                "option_trade_risk": preferred_option.get("option_trade_risk"),
                "options_research_status": preferred_option.get("options_research_status"),
            }
        )
        model_outputs.update(
            {
                "option_contract": option_contract,
                "expiration": expiration,
                "preferred_instrument": "option",
                "iv_context": preferred_option.get("iv_context"),
                "greeks_monitoring": preferred_option.get("greeks_monitoring"),
                "option_trade_risk": preferred_option.get("option_trade_risk"),
                "options_research_status": preferred_option.get("options_research_status"),
            }
        )
        constraint_results = option_constraint_payload

    is_paper_logging = isinstance(logging_metadata, dict) and (
        logging_metadata.get("paper_trading") is True
        or str(logging_metadata.get("execution_mode", "")).lower() == "paper_trading"
        or str(logging_metadata.get("mode", "")).lower() == "paper_trading"
    )
    intended_entry_price = entry_price
    if is_paper_logging:
        fill_trade = {
            **source_candidate,
            "ticker": decision.get("ticker"),
            "asset_type": asset_type,
            "preferred_instrument": preferred_instrument,
            "option_contract": option_contract,
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "direction": source_candidate.get("direction", "long"),
            "position_sizing": decision.get("position_sizing"),
        }
        option_quote = preferred_option if preferred_instrument == "option" and isinstance(locals().get("preferred_option"), dict) else None
        fill_result = estimate_paper_fill(
            fill_trade,
            market_snapshot={"ok": True, "data": {"technical_snapshot": source_candidate.get("technical_snapshot", {}), "quote": {"last_price": entry_price}}},
            option_quote=option_quote,
            position_sizing=decision.get("position_sizing") if isinstance(decision.get("position_sizing"), dict) else None,
        )
        data_snapshot["paper_fill"] = fill_result
        data_snapshot["intended_entry_price"] = intended_entry_price
        model_outputs["paper_fill"] = fill_result
        model_outputs["intended_entry_price"] = intended_entry_price
        if fill_result.get("ok") and fill_result.get("estimated_fill_price") is not None:
            entry_price = fill_result["estimated_fill_price"]
            if asset_type == "stock" and None not in (_safe_float(target_price), _safe_float(stop_loss), _safe_float(entry_price)):
                risk = _safe_float(entry_price) - _safe_float(stop_loss)
                reward = _safe_float(target_price) - _safe_float(entry_price)
                risk_reward = round(reward / risk, 4) if risk and risk > 0 else risk_reward
        elif asset_type == "option":
            return {"ok": False, "error": fill_result.get("error", "Option paper fill is unavailable.")}

    return log_recommendation_tool(
        ticker=decision.get("ticker"),
        asset_type=asset_type,
        direction=source_candidate.get("direction", "long"),
        strategy=source_candidate.get("selected_profile") or source_candidate.get("scan_profile") or source_candidate.get("setup_type") or "trading_brain",
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        setup_type=source_candidate.get("setup_type"),
        risk_reward=risk_reward,
        holding_period_days=decision.get("holding_period_days"),
        expiration=expiration,
        option_contract=option_contract,
        confidence=None,
        score=score,
        thesis=thesis,
        invalidation=invalidation,
        data_snapshot=data_snapshot,
        constraint_results=constraint_results,
        model_outputs=model_outputs,
        db_path=db_path,
    )


def decide_final_recommendations(
    selection_result: dict,
    max_trades: int = 5,
    auto_log: bool = False,
    db_path: str = "strategy_library.db",
    logging_metadata: dict | None = None,
    prefer_options: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    include_position_sizing: bool = True,
    include_memory_context: bool = True,
) -> dict:
    timestamp = _now_iso()
    if not isinstance(selection_result, dict):
        return {
            "ok": False,
            "timestamp": timestamp,
            "final_recommendations": [],
            "watchlist": [],
            "not_selected": [],
            "logged_recommendations": [],
            "message": "Selection result is missing or invalid.",
            "errors": ["Selection result is missing or invalid."],
        }

    final_recommendations: list[dict] = []
    watchlist = list(selection_result.get("watchlist_alternatives", [])) if isinstance(selection_result.get("watchlist_alternatives"), list) else []
    not_selected: list[dict] = []
    logged_recommendations: list[dict] = []
    errors: list[str] = []
    seen_tickers: set[str] = set()

    selected_trades = selection_result.get("selected_trades", [])
    if not isinstance(selected_trades, list):
        selected_trades = []

    for candidate in selected_trades:
        if len(final_recommendations) >= max_trades:
            not_selected.append({"ticker": _normalize_ticker(candidate.get("ticker")), "reason": "Exceeded max_trades.", "candidate": candidate})
            continue

        valid, reason = _can_recommend(candidate, seen_tickers)
        if not valid:
            not_selected.append({"ticker": _normalize_ticker(candidate.get("ticker")), "reason": reason, "candidate": candidate})
            continue

        decision = build_trade_decision(
            candidate,
            db_path=db_path,
            prefer_options=prefer_options,
            account_size=account_size,
            risk_mode=risk_mode,
            include_position_sizing=include_position_sizing,
            include_memory_context=include_memory_context,
            logging_metadata=logging_metadata,
        )
        if decision["decision"] != "recommend":
            not_selected.append({"ticker": decision["ticker"], "reason": f"Decision downgraded to {decision['decision']}.", "candidate": candidate})
            continue

        final_recommendations.append(decision)
        seen_tickers.add(decision["ticker"])

        if auto_log:
            logged = _log_final_recommendation_with_metadata(decision, db_path=db_path, logging_metadata=logging_metadata)
            if logged.get("ok"):
                logged_recommendations.append(logged)
            else:
                errors.append(logged.get("error", f"Failed to log {decision['ticker']}."))

    if final_recommendations:
        message = f"Built {len(final_recommendations)} final recommendations."
        if auto_log:
            message += f" Logged {len(logged_recommendations)} recommendations."
    else:
        message = "No final recommendations passed the trading brain guardrails."

    return {
        "ok": True,
        "timestamp": timestamp,
        "final_recommendations": final_recommendations,
        "watchlist": watchlist,
        "not_selected": not_selected,
        "logged_recommendations": logged_recommendations,
        "message": message,
        "errors": errors,
    }


def run_weekly_trade_hunt(
    universe: str = "large_cap",
    max_tickers: int = 500,
    profiles: list[str] | None = None,
    max_trades: int = 5,
    min_trades: int = 2,
    include_catalysts: bool = True,
    include_market_regime: bool = True,
    include_relative_strength: bool = True,
    include_research_briefs: bool = False,
    include_options: bool = False,
    prefer_options: bool = False,
    max_option_contracts_per_trade: int = 3,
    include_portfolio_risk: bool = True,
    include_position_sizing: bool = True,
    include_memory_context: bool = True,
    store_memory: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    auto_log: bool = False,
    db_path: str = "strategy_library.db",
    logging_metadata: dict | None = None,
    scan_max_concurrency: int = 5,
    scan_ticker_timeout_seconds: float = 15.0,
    scan_total_timeout_seconds: float = 180.0,
    use_async_scan: bool = True,
) -> dict:
    errors: list[str] = []
    concentration_summary = None
    universe_result = get_default_universe(universe=universe, max_tickers=max_tickers)
    if not universe_result.get("ok"):
        return {
            "ok": False,
            "mode": "weekly_trade_hunt",
            "timestamp": _now_iso(),
            "universe_result": universe_result,
            "scan_result": None,
            "selection_result": None,
            "decision_result": None,
            "market_regime": None,
            "portfolio_risk": None,
            "performance_context": None,
            "summary": {
                "tickers_scanned": 0,
                "profiles_run": profiles or [],
                "selected_count": 0,
                "logged_count": 0,
                "message": "Failed to build ticker universe.",
            },
            "errors": universe_result.get("errors", []) if isinstance(universe_result.get("errors"), list) else [universe_result.get("error", "Universe build failed.")],
        }

    scan_result = scan_multi_strategy_candidates(
        tickers=universe_result.get("tickers", []),
        profiles=profiles,
        universe=universe,
        db_path=db_path,
        use_async_scan=use_async_scan,
        scan_config={
            "max_concurrency": scan_max_concurrency,
            "ticker_timeout_seconds": scan_ticker_timeout_seconds,
            "total_timeout_seconds": scan_total_timeout_seconds,
        },
    )
    if not scan_result.get("ok"):
        return {
            "ok": False,
            "mode": "weekly_trade_hunt",
            "timestamp": _now_iso(),
            "universe_result": universe_result,
            "scan_result": scan_result,
            "scan_execution_summary": scan_result.get("scan_execution_summary") if isinstance(scan_result, dict) else None,
            "selection_result": None,
            "decision_result": None,
            "market_regime": None,
            "portfolio_risk": None,
            "performance_context": None,
            "summary": {
                "tickers_scanned": universe_result.get("count", 0),
                "profiles_run": profiles or [],
                "selected_count": 0,
                "logged_count": 0,
                "scan_execution_summary": scan_result.get("scan_execution_summary") if isinstance(scan_result, dict) else None,
                "message": "Scanner failed.",
            },
            "errors": [scan_result.get("error", "Scanner failed.")],
        }
    scan_execution_summary = scan_result.get("scan_execution_summary") if isinstance(scan_result, dict) else None
    if isinstance(scan_execution_summary, dict) and scan_execution_summary.get("partial_results_used"):
        errors.append("Scan completed with partial results due to timeout or provider failures.")

    existing_open_trades = get_open_recommendations(db_path=db_path)
    if isinstance(existing_open_trades, dict) and existing_open_trades.get("ok") is False:
        errors.append(existing_open_trades.get("error", "Failed to load open recommendations."))
        existing_open_trades = []

    paper_mode = _is_paper_logging_metadata(logging_metadata)
    paper_trade_history = _load_paper_trade_history(db_path) if paper_mode else []
    circuit_breaker = evaluate_drawdown_circuit_breaker(
        paper_trade_history,
        open_trades=existing_open_trades if isinstance(existing_open_trades, list) else [],
    ) if paper_mode else None
    setup_decay = evaluate_all_setup_decay(paper_trade_history) if paper_mode else None
    macro_risk = evaluate_macro_risk()

    if isinstance(circuit_breaker, dict) and not circuit_breaker.get("new_trades_allowed", True):
        performance_context = {
            "open_trade_count": len(existing_open_trades) if isinstance(existing_open_trades, list) else 0,
            "win_loss_record": get_win_loss_record(db_path=db_path),
            "strategy_performance": get_strategy_performance(db_path=db_path),
        }
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "timestamp": _now_iso(),
            "universe_result": universe_result,
            "scan_result": scan_result,
            "scan_execution_summary": scan_execution_summary,
            "selection_result": {
                "ok": True,
                "selected_trades": [],
                "watchlist_alternatives": [],
                "rejected_candidates": [],
                "selection_summary": {
                    "selected_count": 0,
                    "message": "Circuit breaker blocked new paper trades.",
                },
                "circuit_breaker": circuit_breaker,
                "macro_risk": macro_risk,
                "setup_decay": setup_decay,
            },
            "macro_risk": macro_risk,
            "market_regime": None,
            "concentration_summary": concentration_summary,
            "portfolio_risk": None,
            "option_research": None,
            "decision_result": {
                "ok": True,
                "timestamp": _now_iso(),
                "final_recommendations": [],
                "watchlist": [],
                "not_selected": [],
                "logged_recommendations": [],
                "message": "Circuit breaker blocked new paper trades.",
                "errors": [],
                "circuit_breaker": circuit_breaker,
                "macro_risk": macro_risk,
                "setup_decay": setup_decay,
            },
            "performance_context": performance_context,
            "summary": {
                "tickers_scanned": universe_result.get("count", 0),
                "profiles_run": scan_result.get("profiles_run", profiles or []),
                "selected_count": 0,
                "logged_count": 0,
                "circuit_breaker": circuit_breaker,
                "macro_risk": macro_risk,
                "setup_decay": setup_decay,
                "concentration_summary": concentration_summary,
                "data_quality": scan_result.get("data_quality_summary"),
                "scan_execution_summary": scan_execution_summary,
                "message": "Circuit breaker blocked new paper trades.",
            },
            "errors": errors,
        }

    market_regime = None
    if include_market_regime:
        market_regime = get_market_regime_snapshot(include_breadth=True, db_path=db_path)

    if isinstance(macro_risk, dict) and not macro_risk.get("new_trades_allowed", True):
        performance_context = {
            "open_trade_count": len(existing_open_trades) if isinstance(existing_open_trades, list) else 0,
            "win_loss_record": get_win_loss_record(db_path=db_path),
            "strategy_performance": get_strategy_performance(db_path=db_path),
        }
        blocked_message = "Critical macro event window blocked new trades."
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "timestamp": _now_iso(),
            "universe_result": universe_result,
            "scan_result": scan_result,
            "scan_execution_summary": scan_execution_summary,
            "selection_result": {
                "ok": True,
                "selected_trades": [],
                "watchlist_alternatives": [],
                "rejected_candidates": [],
                "selection_summary": {
                    "selected_count": 0,
                    "message": blocked_message,
                },
                "macro_risk": macro_risk,
                "market_regime": market_regime,
                "circuit_breaker": circuit_breaker,
                "setup_decay": setup_decay,
            },
            "macro_risk": macro_risk,
            "market_regime": market_regime,
            "concentration_summary": concentration_summary,
            "portfolio_risk": None,
            "option_research": None,
            "decision_result": {
                "ok": True,
                "timestamp": _now_iso(),
                "final_recommendations": [],
                "watchlist": [],
                "not_selected": [],
                "logged_recommendations": [],
                "message": blocked_message,
                "errors": [],
                "macro_risk": macro_risk,
                "market_regime": market_regime,
                "circuit_breaker": circuit_breaker,
                "setup_decay": setup_decay,
            },
            "performance_context": performance_context,
            "summary": {
                "tickers_scanned": universe_result.get("count", 0),
                "profiles_run": scan_result.get("profiles_run", profiles or []),
                "selected_count": 0,
                "logged_count": 0,
                "macro_risk": macro_risk,
                "market_regime": market_regime,
                "circuit_breaker": circuit_breaker,
                "setup_decay": setup_decay,
                "concentration_summary": concentration_summary,
                "data_quality": scan_result.get("data_quality_summary"),
                "scan_execution_summary": scan_execution_summary,
                "message": blocked_message,
            },
            "errors": errors,
        }

    selection_result = select_weekly_trades(
        scan_result=scan_result,
        max_trades=max_trades,
        min_trades=min_trades,
        existing_open_trades=existing_open_trades,
        db_path=db_path,
        config={
            "include_catalysts": include_catalysts,
            "include_relative_strength": include_relative_strength,
        },
    )
    if isinstance(selection_result, dict) and selection_result.get("ok"):
        if paper_mode:
            for collection_name in ("selected_trades", "watchlist_alternatives"):
                collection = selection_result.get(collection_name, [])
                if isinstance(collection, list):
                    for candidate in collection:
                        if isinstance(candidate, dict):
                            candidate["circuit_breaker_context"] = circuit_breaker
        selection_result = _apply_setup_decay_to_selection(selection_result, setup_decay)
    if include_relative_strength and isinstance(selection_result, dict) and selection_result.get("ok"):
        for collection_name in ("selected_trades", "watchlist_alternatives"):
            collection = selection_result.get(collection_name, [])
            if not isinstance(collection, list):
                continue
            for candidate in collection:
                if not isinstance(candidate, dict):
                    continue
                if isinstance(candidate.get("relative_strength_context"), dict):
                    continue
                sector = candidate.get("sector") or candidate.get("industry_sector")
                candidate["relative_strength_context"] = get_relative_strength_snapshot(
                    ticker=_normalize_ticker(candidate.get("ticker")),
                    sector=sector if isinstance(sector, str) else None,
                    include_sector=True,
                    db_path=db_path,
                )
    if include_market_regime and isinstance(market_regime, dict) and market_regime.get("ok") and isinstance(selection_result, dict) and selection_result.get("ok"):
        selection_result = apply_regime_to_trade_selection(selection_result, market_regime)
    if isinstance(selection_result, dict) and selection_result.get("ok"):
        for collection_name in ("selected_trades", "watchlist_alternatives", "rejected_candidates"):
            collection = selection_result.get(collection_name, [])
            if not isinstance(collection, list):
                continue
            for candidate in collection:
                if not isinstance(candidate, dict):
                    continue
                candidate["macro_risk_context"] = macro_risk
                if isinstance(market_regime, dict):
                    candidate["market_regime_context"] = market_regime

    if isinstance(selection_result, dict) and selection_result.get("ok"):
        selected_for_concentration = selection_result.get("selected_trades", [])
        open_for_concentration = existing_open_trades if isinstance(existing_open_trades, list) else []
        candidate_tickers = [
            _normalize_ticker(candidate.get("ticker"))
            for candidate in selected_for_concentration
            if isinstance(candidate, dict) and _normalize_ticker(candidate.get("ticker"))
        ]
        open_tickers = [
            _normalize_ticker(trade.get("underlying_ticker") or trade.get("ticker"))
            for trade in open_for_concentration
            if isinstance(trade, dict) and _normalize_ticker(trade.get("underlying_ticker") or trade.get("ticker"))
        ]
        lookback_days = int(os.getenv("CORRELATION_LOOKBACK_DAYS", "60") or 60)
        max_age_hours = int(os.getenv("CORRELATION_MAX_AGE_HOURS", "36") or 36)
        correlation_matrix, concentration_summary = _load_or_refresh_correlation_context(
            db_path=db_path,
            tickers=[*candidate_tickers, *open_tickers, "SPY"],
            lookback_days=lookback_days,
            max_age_hours=max_age_hours,
        )
        _audit_if_run_id(db_path, logging_metadata, "correlation_snapshot_loaded", concentration_summary or {})

        retained_selected: list[dict] = []
        concentration_rejected = list(selection_result.get("rejected_candidates", [])) if isinstance(selection_result.get("rejected_candidates"), list) else []
        accepted_context: list[dict] = list(open_for_concentration)
        evaluations: list[dict] = []
        for candidate in selected_for_concentration if isinstance(selected_for_concentration, list) else []:
            if not isinstance(candidate, dict):
                continue
            concentration = evaluate_concentration_risk(
                candidate,
                open_trades=accepted_context,
                correlation_matrix=correlation_matrix,
                config={"account_size": account_size, "max_total_open_risk_percent": 0.05},
            )
            candidate["concentration_risk_context"] = concentration
            evaluations.append({"ticker": _normalize_ticker(candidate.get("ticker")), "concentration_risk": concentration})
            if not concentration.get("approved", True):
                rejected_candidate = deepcopy(candidate)
                rejected_candidate["recommendation_status"] = "rejected"
                rejected_candidate["passed"] = False
                rejected_candidate["failed_constraints"] = list(rejected_candidate.get("failed_constraints", [])) + ["concentration_risk_blocked"]
                rejected_candidate["rejection_reason"] = "; ".join(concentration.get("reasons", []) or ["Blocked by concentration controls."])
                concentration_rejected.append(rejected_candidate)
                continue
            retained_selected.append(candidate)
            accepted_context.append(candidate)
        selection_result["selected_trades"] = retained_selected
        selection_result["rejected_candidates"] = concentration_rejected
        selection_result["concentration_summary"] = {
            "ok": True,
            "snapshot": concentration_summary,
            "evaluated_count": len(evaluations),
            "blocked_count": max(0, len(selected_for_concentration if isinstance(selected_for_concentration, list) else []) - len(retained_selected)),
            "reduced_count": sum(1 for item in evaluations if (item.get("concentration_risk") or {}).get("risk_multiplier", 1.0) < 1.0 and (item.get("concentration_risk") or {}).get("approved", True)),
            "evaluations": evaluations,
        }
        _audit_if_run_id(db_path, logging_metadata, "concentration_risk_evaluated", selection_result["concentration_summary"])

        technical_evaluations = []
        for collection_name in ("selected_trades", "watchlist_alternatives", "rejected_candidates"):
            collection = selection_result.get(collection_name, [])
            if not isinstance(collection, list):
                continue
            for candidate in collection:
                if isinstance(candidate, dict) and (
                    isinstance(candidate.get("technical_confirmation_summary"), dict)
                    or isinstance(candidate.get("volume_profile_confirmation"), dict)
                    or isinstance(candidate.get("timeframe_confirmation"), dict)
                ):
                    technical_evaluations.append(
                        {
                            "ticker": _normalize_ticker(candidate.get("ticker")),
                            "bucket": collection_name,
                            "technical_confirmation_summary": candidate.get("technical_confirmation_summary"),
                            "volume_profile_confirmation": candidate.get("volume_profile_confirmation"),
                            "timeframe_confirmation": candidate.get("timeframe_confirmation"),
                        }
                    )
        selection_result["technical_confirmation_summary"] = {
            "ok": True,
            "evaluated_count": len(technical_evaluations),
            "rejected_count": sum(1 for item in technical_evaluations if str((item.get("technical_confirmation_summary") or {}).get("status", "")).lower() == "rejected"),
            "warning_count": sum(1 for item in technical_evaluations if str((item.get("technical_confirmation_summary") or {}).get("status", "")).lower() == "warning"),
            "evaluations": technical_evaluations,
        }
        _audit_if_run_id(db_path, logging_metadata, "volume_profile_evaluated", selection_result["technical_confirmation_summary"])
        _audit_if_run_id(db_path, logging_metadata, "timeframe_confirmation_evaluated", selection_result["technical_confirmation_summary"])

        filing_summary = _filing_sentiment_summary(selection_result)
        selection_result["filing_sentiment_summary"] = filing_summary
        _audit_if_run_id(db_path, logging_metadata, "sec_filings_loaded", filing_summary)
        _audit_if_run_id(db_path, logging_metadata, "filing_analysis_completed", filing_summary)
        _audit_if_run_id(db_path, logging_metadata, "earnings_8k_analyzed", filing_summary)
        _audit_if_run_id(db_path, logging_metadata, "filing_sentiment_evaluated", filing_summary)
        research_risk_summary = _research_risk_summary(selection_result)
        selection_result["research_risk_summary"] = research_risk_summary
        _audit_if_run_id(db_path, logging_metadata, "short_interest_evaluated", research_risk_summary)
        _audit_if_run_id(db_path, logging_metadata, "borrow_pressure_evaluated", research_risk_summary)
        _audit_if_run_id(db_path, logging_metadata, "recent_news_loaded", research_risk_summary)
        _audit_if_run_id(db_path, logging_metadata, "news_sentiment_evaluated", research_risk_summary)

    option_research = None
    if include_options and isinstance(selection_result, dict) and selection_result.get("ok"):
        selected_stock_candidates = selection_result.get("selected_trades", [])
        option_research = scan_options_for_weekly_selection(
            selected_stock_candidates,
            max_contracts_per_ticker=max_option_contracts_per_trade,
        )
        option_results_by_ticker = {
            str(result.get("ticker", "")).upper(): result
            for result in option_research.get("results", [])
            if isinstance(result, dict)
        }
        if isinstance(selected_stock_candidates, list):
            for candidate in selected_stock_candidates:
                if not isinstance(candidate, dict):
                    continue
                option_result = option_results_by_ticker.get(_normalize_ticker(candidate.get("ticker")), {})
                candidate["option_alternatives"] = option_result.get("best_option_candidates", [])
                candidate["option_research_summary"] = option_result.get("summary")
                candidate["option_research_errors"] = option_result.get("errors", [])
                candidate["option_strategy_candidates"] = option_result.get("option_strategy_candidates", [])
                candidate["selected_option_strategy"] = option_result.get("selected_option_strategy")
                candidate["option_strategy_summary"] = option_result.get("option_strategy_summary", {})
        risk_evaluations = []
        for collection_name in ("best_option_candidates", "watchlist_option_candidates", "rejected_option_candidates"):
            for option_candidate in option_research.get(collection_name, []) if isinstance(option_research.get(collection_name), list) else []:
                if not isinstance(option_candidate, dict):
                    continue
                risk_evaluations.append(
                    {
                        "option_contract": option_candidate.get("option_contract"),
                        "underlying_ticker": option_candidate.get("underlying_ticker"),
                        "bucket": collection_name,
                        "iv_context": option_candidate.get("iv_context"),
                        "greeks_monitoring": option_candidate.get("greeks_monitoring"),
                        "option_trade_risk": option_candidate.get("option_trade_risk"),
                        "options_research_status": option_candidate.get("options_research_status"),
                    }
                )
        option_risk_summary = {
            "ok": True,
            "evaluated_count": len(risk_evaluations),
            "approved_count": sum(1 for item in risk_evaluations if ((item.get("option_trade_risk") or {}).get("approved") is True)),
            "research_only_count": sum(1 for item in risk_evaluations if str((item.get("option_trade_risk") or {}).get("status", "")).lower() == "research_only"),
            "blocked_count": sum(1 for item in risk_evaluations if str((item.get("option_trade_risk") or {}).get("status", "")).lower() == "blocked"),
            "evaluations": risk_evaluations,
        }
        option_research["option_risk_summary"] = option_risk_summary
        selection_result["option_risk_summary"] = option_risk_summary
        _audit_if_run_id(db_path, logging_metadata, "iv_context_evaluated", option_risk_summary)
        _audit_if_run_id(db_path, logging_metadata, "greeks_evaluated", option_risk_summary)
        _audit_if_run_id(db_path, logging_metadata, "option_trade_risk_evaluated", option_risk_summary)
        option_strategy_summary = (option_research.get("summary") or {}).get("option_strategy_summary", {})
        selection_result["option_strategy_summary"] = option_strategy_summary
        _audit_if_run_id(db_path, logging_metadata, "option_strategies_built", option_strategy_summary)
        _audit_if_run_id(db_path, logging_metadata, "option_strategy_evaluated", option_strategy_summary)
        _audit_if_run_id(db_path, logging_metadata, "option_strategy_selected", option_strategy_summary)

    resolved_prefer_options = prefer_options and not (
        include_market_regime
        and isinstance(market_regime, dict)
        and str(market_regime.get("options_aggressiveness", "")).lower() == "avoid"
    )
    portfolio_risk = None
    risk_rejected: list[dict] = []

    if include_portfolio_risk:
        preliminary_decisions = decide_final_recommendations(
            selection_result=selection_result,
            max_trades=max_trades,
            auto_log=False,
            db_path=db_path,
            logging_metadata=logging_metadata,
            prefer_options=resolved_prefer_options,
            account_size=account_size,
            risk_mode=risk_mode,
            include_position_sizing=include_position_sizing,
            include_memory_context=include_memory_context,
        )
        portfolio_risk = apply_portfolio_risk_limits(
            proposed_trades=preliminary_decisions.get("final_recommendations", []),
            existing_open_trades=existing_open_trades if isinstance(existing_open_trades, list) else [],
            account_size=account_size,
            config={
                "risk_mode": risk_mode,
                "max_trades_per_week": max_trades,
            },
        )
        risk_rejected = list(portfolio_risk.get("rejected_trades", [])) if isinstance(portfolio_risk.get("rejected_trades"), list) else []
        decision_result = {
            **preliminary_decisions,
            "final_recommendations": list(portfolio_risk.get("approved_trades", [])),
            "portfolio_risk_context": portfolio_risk,
            "risk_rejected": risk_rejected,
        }
        not_selected = list(decision_result.get("not_selected", []))
        not_selected.extend(
            {
                "ticker": str(item.get("ticker", "")),
                "reason": item.get("rejection_reason", "Rejected for portfolio-level risk."),
                "candidate": item.get("trade"),
            }
            for item in risk_rejected
            if isinstance(item, dict)
        )
        decision_result["not_selected"] = not_selected
        decision_result["message"] = (
            portfolio_risk.get("risk_summary", {}).get("message")
            if isinstance(portfolio_risk, dict)
            else decision_result.get("message")
        ) or decision_result.get("message")

        if auto_log:
            logged_recommendations: list[dict] = []
            for decision in decision_result.get("final_recommendations", []):
                logged = _log_final_recommendation_with_metadata(decision, db_path=db_path, logging_metadata=logging_metadata)
                if logged.get("ok"):
                    logged_recommendations.append(logged)
                else:
                    errors.append(logged.get("error", f"Failed to log {_normalize_ticker(decision.get('ticker'))}."))
            decision_result["logged_recommendations"] = logged_recommendations
            decision_result["message"] = (
                f"Built {len(decision_result.get('final_recommendations', []))} final recommendations."
                f" Logged {len(logged_recommendations)} recommendations."
                if decision_result.get("final_recommendations")
                else "No final recommendations passed the trading brain and portfolio risk guardrails."
            )
    else:
        decision_result = decide_final_recommendations(
            selection_result=selection_result,
            max_trades=max_trades,
            auto_log=auto_log,
            db_path=db_path,
            logging_metadata=logging_metadata,
            prefer_options=resolved_prefer_options,
            account_size=account_size,
            risk_mode=risk_mode,
            include_position_sizing=include_position_sizing,
            include_memory_context=include_memory_context,
        )
    if include_research_briefs and isinstance(decision_result, dict):
        from research.deep_research import build_research_brief

        enriched_recommendations: list[dict] = []
        for decision in decision_result.get("final_recommendations", []):
            if not isinstance(decision, dict):
                continue
            ticker = _normalize_ticker(decision.get("ticker"))
            research_brief = build_research_brief(
                ticker=ticker,
                include_market_regime=include_market_regime,
                include_relative_strength=include_relative_strength,
                include_catalysts=include_catalysts,
                include_statistics=True,
                include_options=include_options,
                include_memory_context=include_memory_context,
                db_path=db_path,
            )
            if not research_brief.get("ok") and research_brief.get("error"):
                errors.append(f"{ticker} research brief: {research_brief['error']}")
            enriched_recommendations.append(_apply_research_brief_to_decision(decision, research_brief))
        decision_result["final_recommendations"] = enriched_recommendations
    if isinstance(decision_result, dict):
        memory_write_results: list[dict] = []
        if store_memory:
            for decision in decision_result.get("final_recommendations", []):
                if not isinstance(decision, dict):
                    continue
                memory_write_results.append(store_trade_decision_memory(decision, db_path=db_path))
                research_brief = decision.get("research_brief")
                if isinstance(research_brief, dict):
                    memory_write_results.append(store_research_brief_memory(research_brief, db_path=db_path))
        decision_result["memory_write_results"] = memory_write_results
    if isinstance(decision_result, dict):
        decision_result["market_regime"] = market_regime
        decision_result["macro_risk"] = macro_risk
        decision_result["circuit_breaker"] = circuit_breaker
        decision_result["setup_decay"] = setup_decay
        decision_result["concentration_summary"] = selection_result.get("concentration_summary") or concentration_summary
        if include_portfolio_risk:
            decision_result["portfolio_risk_context"] = portfolio_risk
    errors.extend(str(error) for error in decision_result.get("errors", []) if error)
    if include_options and isinstance(option_research, dict):
        errors.extend(str(error) for error in option_research.get("errors", []) if error)

    performance_context = {
        "open_trade_count": len(existing_open_trades) if isinstance(existing_open_trades, list) else 0,
        "win_loss_record": get_win_loss_record(db_path=db_path),
        "strategy_performance": get_strategy_performance(db_path=db_path),
    }
    final_concentration_summary = selection_result.get("concentration_summary") if isinstance(selection_result, dict) else None
    if not final_concentration_summary:
        final_concentration_summary = concentration_summary
    final_technical_summary = selection_result.get("technical_confirmation_summary") if isinstance(selection_result, dict) else None
    final_filing_summary = selection_result.get("filing_sentiment_summary") if isinstance(selection_result, dict) else None
    final_research_risk_summary = selection_result.get("research_risk_summary") if isinstance(selection_result, dict) else None
    final_option_risk_summary = None
    if isinstance(option_research, dict):
        final_option_risk_summary = option_research.get("option_risk_summary")
    if not final_option_risk_summary and isinstance(selection_result, dict):
        final_option_risk_summary = selection_result.get("option_risk_summary")
    final_option_strategy_summary = selection_result.get("option_strategy_summary") if isinstance(selection_result, dict) else None
    memory_summary = _memory_summary_from_decisions(decision_result)

    selected_count = len(decision_result.get("final_recommendations", []))
    logged_count = len(decision_result.get("logged_recommendations", []))
    summary_message = decision_result.get("message") or selection_result.get("selection_summary", {}).get("message") or "Weekly trade hunt completed."
    if include_market_regime and isinstance(market_regime, dict) and market_regime.get("summary"):
        summary_message = f"{summary_message} {market_regime['summary']}"
    if isinstance(macro_risk, dict) and macro_risk.get("macro_risk_level") != "low":
        summary_message = f"{summary_message} Macro risk is {macro_risk.get('macro_risk_level')}."
    if include_portfolio_risk and isinstance(portfolio_risk, dict):
        risk_message = portfolio_risk.get("risk_summary", {}).get("message")
        if risk_message:
            summary_message = f"{summary_message} {risk_message}"

    return {
        "ok": bool(selection_result.get("ok")) and bool(decision_result.get("ok")),
        "mode": "weekly_trade_hunt",
        "timestamp": _now_iso(),
        "universe_result": universe_result,
        "scan_result": scan_result,
        "scan_execution_summary": scan_execution_summary,
        "selection_result": selection_result,
        "macro_risk": macro_risk,
        "market_regime": market_regime,
        "concentration_summary": final_concentration_summary,
        "technical_confirmation_summary": final_technical_summary,
        "filing_sentiment_summary": final_filing_summary,
        "research_risk_summary": final_research_risk_summary,
        "option_risk_summary": final_option_risk_summary,
        "option_strategy_summary": final_option_strategy_summary,
        "memory_summary": memory_summary,
        "portfolio_risk": portfolio_risk,
        "option_research": option_research,
        "decision_result": decision_result,
        "performance_context": performance_context,
        "summary": {
            "tickers_scanned": universe_result.get("count", 0),
            "profiles_run": scan_result.get("profiles_run", profiles or []),
            "selected_count": selected_count,
            "logged_count": logged_count,
            "macro_risk": macro_risk,
            "circuit_breaker": circuit_breaker,
            "setup_decay": setup_decay,
            "concentration_summary": final_concentration_summary,
            "technical_confirmation_summary": final_technical_summary,
            "filing_sentiment_summary": final_filing_summary,
            "research_risk_summary": final_research_risk_summary,
            "option_risk_summary": final_option_risk_summary,
            "option_strategy_summary": final_option_strategy_summary,
            "memory_summary": memory_summary,
            "data_quality": scan_result.get("data_quality_summary"),
            "scan_execution_summary": scan_execution_summary,
            "message": summary_message,
        },
        "errors": errors,
    }


def review_ticker_opportunity(
    ticker: str,
    include_catalysts: bool = True,
    include_research_brief: bool = True,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
    include_options: bool = False,
    include_memory_context: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_ticker = _normalize_ticker(ticker)
    market_snapshot = get_market_snapshot(normalized_ticker, lookback_days=180)
    if not market_snapshot.get("ok"):
        return {
            "ok": False,
            "mode": "review_ticker",
            "timestamp": _now_iso(),
            "ticker": normalized_ticker,
            "status": "rejected",
            "candidate": None,
            "decision": None,
            "failed_constraints": [],
            "reasons": [market_snapshot.get("error", "Failed to load market snapshot.")],
            "statistical_context": None,
            "catalyst_context": None,
            "market_snapshot": market_snapshot,
            "trade_levels": None,
        }

    candidate = build_stock_candidate(normalized_ticker, market_snapshot)
    trade_levels = calculate_trade_levels(candidate.get("technical_snapshot", {}), direction=candidate.get("direction", "long"))
    if trade_levels.get("ok"):
        candidate.update(
            {
                "entry_price": trade_levels.get("entry_price"),
                "target_price": trade_levels.get("target_price"),
                "stop_loss": trade_levels.get("stop_loss"),
                "risk_reward": trade_levels.get("risk_reward"),
            }
        )
    else:
        candidate["trade_level_error"] = trade_levels.get("error")

    constraint_result = evaluate_stock_constraints(candidate)
    candidate["score"] = constraint_result["score"]
    candidate["recommendation_status"] = constraint_result["recommendation_status"]
    candidate["constraint_results"] = constraint_result["constraint_results"]
    candidate["failed_constraints"] = constraint_result["failed_constraints"]
    candidate["rejection_reason"] = constraint_result["rejection_reason"]
    candidate["passed"] = constraint_result["passed"]

    candidate = enrich_candidate_with_statistics(candidate, db_path=db_path)
    if include_catalysts:
        candidate = enrich_candidate_with_catalysts(candidate)

    decision = build_trade_decision(
        candidate,
        db_path=db_path,
        include_memory_context=include_memory_context,
    )
    research_brief = None
    if include_research_brief:
        from research.deep_research import build_research_brief

        research_brief = build_research_brief(
            ticker=normalized_ticker,
            include_market_regime=True,
            include_relative_strength=True,
            include_catalysts=include_catalysts,
            include_statistics=True,
            include_sec_filings=include_sec_filings,
            include_earnings_transcripts=include_earnings_transcripts,
            include_options=include_options,
            include_memory_context=include_memory_context,
            db_path=db_path,
        )
        decision = _apply_research_brief_to_decision(decision, research_brief)
    status = {
        "recommend": "recommendable",
        "watchlist": "watchlist",
        "reject": "rejected",
    }[decision["decision"]]

    reasons = decision["why_selected"] if status != "rejected" else decision["risks"] or [candidate.get("rejection_reason", "Rejected by objective rules.")]
    if isinstance(research_brief, dict) and research_brief.get("research_summary"):
        summary = str(research_brief["research_summary"])
        if summary not in reasons:
            reasons = [summary, *reasons]

    return {
        "ok": True,
        "mode": "review_ticker",
        "timestamp": _now_iso(),
        "ticker": normalized_ticker,
        "status": status,
        "candidate": candidate,
        "decision": decision,
        "failed_constraints": candidate.get("failed_constraints", []),
        "reasons": reasons,
        "statistical_context": candidate.get("statistical_context"),
        "catalyst_context": candidate.get("catalyst_context"),
        "market_snapshot": market_snapshot,
        "trade_levels": trade_levels,
        "research_brief": research_brief,
    }


def monitor_open_trades(
    update_outcomes: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    update_result = None
    if update_outcomes:
        update_result = update_open_recommendations(db_path=db_path)

    open_recommendations = get_open_recommendations(db_path=db_path)
    open_count = len(open_recommendations) if isinstance(open_recommendations, list) else 0
    performance_context = {
        "win_loss_record": get_win_loss_record(db_path=db_path),
        "strategy_performance": get_strategy_performance(db_path=db_path),
    }

    return {
        "ok": (update_result is None or bool(update_result.get("ok"))) and not isinstance(open_recommendations, dict),
        "mode": "monitor_open_trades",
        "timestamp": _now_iso(),
        "update_result": update_result,
        "open_recommendations": open_recommendations if isinstance(open_recommendations, list) else [],
        "performance_context": performance_context,
        "summary": {
            "open_trade_count": open_count,
            "message": "Open trade monitoring completed." if update_result is None or update_result.get("ok") else "Open trades loaded, but outcome update returned errors.",
        },
        "errors": [] if update_result is None or update_result.get("ok") else [update_result.get("error", "Outcome update returned errors.")],
    }
