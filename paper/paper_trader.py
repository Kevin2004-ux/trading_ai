from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agent.trading_brain import monitor_open_trades, run_weekly_trade_hunt
from analytics.setup_decay import evaluate_all_setup_decay
from config.startup_validator import validate_startup_config
from db.audit_log import append_audit_event, verify_audit_chain
from db.checkpoints import (
    complete_pipeline_run,
    fail_pipeline_run,
    get_pipeline_run,
    list_checkpoints,
    record_checkpoint,
    start_pipeline_run,
)
from journal.trade_journal import review_closed_trades
from risk.circuit_breaker import evaluate_drawdown_circuit_breaker
from tracking.trade_logger import init_trade_tracking_db


PAPER_MODE = "paper_trading"
TERMINAL_OUTCOMES = {"win", "loss", "expired", "manual_review"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_checkpoint(db_path: str, run_id: str | None, checkpoint_name: str, status: str, payload: dict | None = None, error: dict | None = None) -> dict:
    if not run_id:
        return {"ok": False, "warning": "No pipeline run id available."}
    return record_checkpoint(db_path, run_id, checkpoint_name, status, payload=payload, error=error)


def _safe_audit(db_path: str, event_type: str, payload: dict, run_id: str | None = None, entity_type: str | None = None, entity_id: str | None = None) -> dict:
    return append_audit_event(
        db_path=db_path,
        event_type=event_type,
        payload=payload,
        run_id=run_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def _append_observability_warning(warnings: list[str], result: dict, label: str) -> None:
    if isinstance(result, dict) and not result.get("ok", False):
        warnings.append(f"{label}: {result.get('error') or result.get('warning') or 'logging failed'}")


def _audit_trade_hunt(db_path: str, run_id: str | None, trade_hunt: dict, warnings: list[str]) -> None:
    if not run_id or not isinstance(trade_hunt, dict):
        return

    universe_result = trade_hunt.get("universe_result") if isinstance(trade_hunt.get("universe_result"), dict) else {}
    scan_result = trade_hunt.get("scan_result") if isinstance(trade_hunt.get("scan_result"), dict) else {}
    selection_result = trade_hunt.get("selection_result") if isinstance(trade_hunt.get("selection_result"), dict) else {}
    decision_result = trade_hunt.get("decision_result") if isinstance(trade_hunt.get("decision_result"), dict) else {}
    summary = trade_hunt.get("summary") if isinstance(trade_hunt.get("summary"), dict) else {}

    events = [
        ("universe_selected", {"universe": universe_result.get("universe"), "count": universe_result.get("count")}),
        ("async_scan_completed", trade_hunt.get("scan_execution_summary") or summary.get("scan_execution_summary") or {}),
        ("data_quality_summary", scan_result.get("data_quality_summary") or summary.get("data_quality") or {}),
        ("macro_risk_evaluated", trade_hunt.get("macro_risk") or summary.get("macro_risk") or {}),
        ("market_regime_evaluated", trade_hunt.get("market_regime") or {}),
        ("correlation_snapshot_loaded", (trade_hunt.get("concentration_summary") or {}).get("snapshot") or {}),
        ("concentration_risk_evaluated", trade_hunt.get("concentration_summary") or summary.get("concentration_summary") or {}),
        ("volume_profile_evaluated", trade_hunt.get("technical_confirmation_summary") or summary.get("technical_confirmation_summary") or {}),
        ("timeframe_confirmation_evaluated", trade_hunt.get("technical_confirmation_summary") or summary.get("technical_confirmation_summary") or {}),
        ("sec_filings_loaded", trade_hunt.get("filing_sentiment_summary") or summary.get("filing_sentiment_summary") or {}),
        ("filing_analysis_completed", trade_hunt.get("filing_sentiment_summary") or summary.get("filing_sentiment_summary") or {}),
        ("earnings_8k_analyzed", trade_hunt.get("filing_sentiment_summary") or summary.get("filing_sentiment_summary") or {}),
        ("filing_sentiment_evaluated", trade_hunt.get("filing_sentiment_summary") or summary.get("filing_sentiment_summary") or {}),
        ("short_interest_evaluated", trade_hunt.get("research_risk_summary") or summary.get("research_risk_summary") or {}),
        ("borrow_pressure_evaluated", trade_hunt.get("research_risk_summary") or summary.get("research_risk_summary") or {}),
        ("recent_news_loaded", trade_hunt.get("research_risk_summary") or summary.get("research_risk_summary") or {}),
        ("news_sentiment_evaluated", trade_hunt.get("research_risk_summary") or summary.get("research_risk_summary") or {}),
        ("iv_context_evaluated", ((trade_hunt.get("option_research") or {}).get("option_risk_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("greeks_evaluated", ((trade_hunt.get("option_research") or {}).get("option_risk_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("option_trade_risk_evaluated", ((trade_hunt.get("option_research") or {}).get("option_risk_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("option_strategies_built", ((trade_hunt.get("option_research") or {}).get("summary", {}).get("option_strategy_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("option_strategy_evaluated", ((trade_hunt.get("option_research") or {}).get("summary", {}).get("option_strategy_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("option_strategy_selected", ((trade_hunt.get("option_research") or {}).get("summary", {}).get("option_strategy_summary") if isinstance(trade_hunt.get("option_research"), dict) else {}) or {}),
        ("portfolio_risk_evaluated", trade_hunt.get("portfolio_risk") or {}),
        ("circuit_breaker_evaluated", summary.get("circuit_breaker") or {}),
        ("setup_decay_evaluated", summary.get("setup_decay") or {}),
    ]
    for event_type, payload in events:
        _append_observability_warning(warnings, _safe_audit(db_path, event_type, payload, run_id=run_id), event_type)

    for candidate in scan_result.get("rejected_candidates", []) if isinstance(scan_result.get("rejected_candidates"), list) else []:
        if isinstance(candidate, dict):
            _append_observability_warning(
                warnings,
                _safe_audit(db_path, "candidate_rejected", {"ticker": candidate.get("ticker"), "reason": candidate.get("rejection_reason")}, run_id=run_id, entity_type="candidate", entity_id=str(candidate.get("ticker"))),
                "candidate_rejected",
            )
    for candidate in selection_result.get("watchlist_alternatives", []) if isinstance(selection_result.get("watchlist_alternatives"), list) else []:
        if isinstance(candidate, dict):
            _append_observability_warning(warnings, _safe_audit(db_path, "candidate_watchlisted", candidate, run_id=run_id, entity_type="candidate", entity_id=str(candidate.get("ticker"))), "candidate_watchlisted")
    for candidate in decision_result.get("final_recommendations", []) if isinstance(decision_result.get("final_recommendations"), list) else []:
        if not isinstance(candidate, dict):
            continue
        _append_observability_warning(warnings, _safe_audit(db_path, "candidate_selected", candidate, run_id=run_id, entity_type="candidate", entity_id=str(candidate.get("ticker"))), "candidate_selected")
        if candidate.get("position_sizing"):
            _append_observability_warning(warnings, _safe_audit(db_path, "position_sizing_calculated", candidate.get("position_sizing"), run_id=run_id, entity_type="candidate", entity_id=str(candidate.get("ticker"))), "position_sizing_calculated")
        if candidate.get("paper_fill"):
            _append_observability_warning(warnings, _safe_audit(db_path, "fill_model_applied", candidate.get("paper_fill"), run_id=run_id, entity_type="candidate", entity_id=str(candidate.get("ticker"))), "fill_model_applied")
    for logged in decision_result.get("logged_recommendations", []) if isinstance(decision_result.get("logged_recommendations"), list) else []:
        recommendation = logged.get("data", {}).get("recommendation") if isinstance(logged, dict) else None
        if isinstance(recommendation, dict):
            _append_observability_warning(warnings, _safe_audit(db_path, "final_recommendation_logged", {"recommendation_id": recommendation.get("id"), "ticker": recommendation.get("ticker")}, run_id=run_id, entity_type="recommendation", entity_id=str(recommendation.get("id"))), "final_recommendation_logged")



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


def _is_paper_trade(recommendation: dict) -> bool:
    if not isinstance(recommendation, dict):
        return False

    for payload_name in ("model_outputs_json", "data_snapshot_json"):
        payload = recommendation.get(payload_name)
        if isinstance(payload, dict):
            if payload.get("paper_trading") is True:
                return True
            if str(payload.get("execution_mode", "")).lower() == PAPER_MODE:
                return True
            if str(payload.get("mode", "")).lower() == PAPER_MODE:
                return True
    return False


def _load_paper_recommendations(db_path: str) -> list[dict]:
    init_result = init_trade_tracking_db(db_path=db_path)
    if not init_result.get("ok"):
        raise sqlite3.Error(init_result.get("error", "Failed to initialize trade tracking database."))

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
            SELECT
                tr.*,
                lo.realized_return AS latest_realized_return
            FROM trade_recommendations tr
            LEFT JOIN latest_outcomes lo
                ON lo.recommendation_id = tr.id
            ORDER BY tr.created_at ASC, tr.id ASC
            """
        ).fetchall()

    recommendations: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("data_snapshot_json", "constraint_results_json", "model_outputs_json"):
            item[key] = _deserialize_json(item.get(key))
        if _is_paper_trade(item):
            recommendations.append(item)
    return recommendations


def _paper_open_trades(recommendations: list[dict]) -> list[dict]:
    return [
        recommendation
        for recommendation in recommendations
        if recommendation.get("closed_at") is None
        and str(recommendation.get("status", "open")).lower() not in TERMINAL_OUTCOMES
    ]


def _paper_closed_trades(recommendations: list[dict]) -> list[dict]:
    return [
        recommendation
        for recommendation in recommendations
        if str(recommendation.get("outcome", "")).lower() in TERMINAL_OUTCOMES
    ]


def _paper_win_loss_record(recommendations: list[dict]) -> dict:
    wins = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "win")
    losses = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "loss")
    expired = sum(1 for recommendation in recommendations if str(recommendation.get("outcome", "")).lower() == "expired")
    open_count = sum(1 for recommendation in recommendations if recommendation.get("closed_at") is None and str(recommendation.get("status", "open")).lower() not in TERMINAL_OUTCOMES)
    closed = wins + losses
    return {
        "total_recommendations": len(recommendations),
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "open": open_count,
        "closed_trades": closed,
        "win_rate": round((wins / closed) * 100.0, 2) if closed else 0.0,
    }


def _realized_return(recommendation: dict) -> float | None:
    latest_realized_return = _safe_float(recommendation.get("latest_realized_return"))
    if latest_realized_return is not None:
        return latest_realized_return

    entry_price = _safe_float(recommendation.get("entry_price"))
    exit_price = _safe_float(recommendation.get("exit_price"))
    if entry_price in (None, 0) or exit_price is None:
        return None
    realized_return = ((exit_price - entry_price) / entry_price) * 100.0
    if str(recommendation.get("direction", "")).lower() == "short":
        realized_return = ((entry_price - exit_price) / entry_price) * 100.0
    return realized_return


def _paper_strategy_performance(recommendations: list[dict]) -> dict:
    overall = {
        "total_recommendations": len(recommendations),
        "average_score": None,
        "average_confidence": None,
        "average_risk_reward": None,
    }
    if recommendations:
        score_values = [_safe_float(item.get("score")) for item in recommendations if _safe_float(item.get("score")) is not None]
        confidence_values = [_safe_float(item.get("confidence")) for item in recommendations if _safe_float(item.get("confidence")) is not None]
        rr_values = [_safe_float(item.get("risk_reward")) for item in recommendations if _safe_float(item.get("risk_reward")) is not None]
        if score_values:
            overall["average_score"] = sum(score_values) / len(score_values)
        if confidence_values:
            overall["average_confidence"] = sum(confidence_values) / len(confidence_values)
        if rr_values:
            overall["average_risk_reward"] = sum(rr_values) / len(rr_values)

    def grouped(rows: list[dict], field_name: str, default: str) -> list[dict]:
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            key = row.get(field_name) or default
            buckets.setdefault(str(key), []).append(row)

        output: list[dict] = []
        for key, bucket in buckets.items():
            return_values = [value for value in (_realized_return(item) for item in bucket) if value is not None]
            wins = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "win")
            losses = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "loss")
            expired = sum(1 for item in bucket if str(item.get("outcome", "")).lower() == "expired")
            output.append(
                {
                    field_name: key,
                    "total_recommendations": len(bucket),
                    "wins": wins,
                    "losses": losses,
                    "expired": expired,
                    "average_score": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("score")) for item in bucket) if value is not None]) else None,
                    "average_confidence": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("confidence")) for item in bucket) if value is not None]) else None,
                    "average_risk_reward": (sum(values) / len(values)) if (values := [value for value in (_safe_float(item.get("risk_reward")) for item in bucket) if value is not None]) else None,
                    "average_realized_return": (sum(return_values) / len(return_values)) if return_values else None,
                }
            )
        output.sort(key=lambda item: item["total_recommendations"], reverse=True)
        return output

    return {
        "overall": overall,
        "by_strategy": grouped(recommendations, "strategy", "unknown"),
        "by_setup_type": grouped(recommendations, "setup_type", "unspecified"),
    }


def run_paper_trade_cycle(
    universe: str = "large_cap",
    max_tickers: int = 500,
    profiles: list[str] | None = None,
    max_trades: int = 5,
    min_trades: int = 2,
    include_catalysts: bool = True,
    include_market_regime: bool = True,
    include_relative_strength: bool = True,
    include_options: bool = False,
    prefer_options: bool = False,
    max_option_contracts_per_trade: int = 3,
    include_portfolio_risk: bool = True,
    include_position_sizing: bool = True,
    include_memory_context: bool = True,
    store_memory: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    db_path: str = "strategy_library.db",
    scan_max_concurrency: int = 5,
    scan_ticker_timeout_seconds: float = 15.0,
    scan_total_timeout_seconds: float = 180.0,
    use_async_scan: bool = True,
    startup_config: dict | None = None,
) -> dict:
    observability_warnings: list[str] = []
    validation_config = {
        **(startup_config or {}),
        "DATABASE_PATH": db_path,
        "INCLUDE_OPTIONS": str(bool(include_options)).lower(),
        "PREFER_OPTIONS": str(bool(prefer_options)).lower(),
        "STOCK_ONLY": str(not bool(include_options)).lower(),
        "OPTIONS_REQUIRED": "false",
        "STOCK_FALLBACK_ALLOWED": "true",
        "SCAN_MAX_CONCURRENCY": scan_max_concurrency,
        "SCAN_TICKER_TIMEOUT_SECONDS": scan_ticker_timeout_seconds,
        "SCAN_TOTAL_TIMEOUT_SECONDS": scan_total_timeout_seconds,
    }
    startup_readiness = validate_startup_config(validation_config)
    pipeline_start = start_pipeline_run(
        db_path,
        "paper_cycle",
        metadata={
            "universe": universe,
            "max_tickers": max_tickers,
            "max_trades": max_trades,
            "min_trades": min_trades,
            "include_options": include_options,
            "use_async_scan": use_async_scan,
        },
    )
    run_id = pipeline_start.get("run_id") or (pipeline_start.get("pipeline_run") or {}).get("run_id")
    _append_observability_warning(observability_warnings, pipeline_start, "start_pipeline_run")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "paper_cycle_started", "completed", payload={"universe": universe, "max_tickers": max_tickers}), "paper_cycle_started")
    _append_observability_warning(observability_warnings, _safe_audit(db_path, "paper_cycle_started", {"universe": universe, "max_tickers": max_tickers}, run_id=run_id), "paper_cycle_started_audit")
    if startup_readiness.get("ok"):
        _append_observability_warning(observability_warnings, _safe_audit(db_path, "startup_validation_passed", startup_readiness, run_id=run_id), "startup_validation_passed_audit")
    else:
        _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "startup_validation_failed", "failed", error=startup_readiness), "startup_validation_failed")
        _append_observability_warning(observability_warnings, _safe_audit(db_path, "startup_validation_failed", startup_readiness, run_id=run_id), "startup_validation_failed_audit")
        pipeline_result = fail_pipeline_run(db_path, run_id, {"startup_readiness": startup_readiness}) if run_id else {"ok": False, "error": "No run id."}
        checkpoint_summary = list_checkpoints(db_path, run_id) if run_id else {"ok": False, "checkpoints": [], "count": 0}
        audit_status = verify_audit_chain(db_path)
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "run_id": run_id,
            "timestamp": _now_iso(),
            "startup_readiness": startup_readiness,
            "trade_hunt": None,
            "pipeline_run": pipeline_result.get("pipeline_run") if isinstance(pipeline_result, dict) else None,
            "checkpoint_summary": {
                "ok": checkpoint_summary.get("ok"),
                "count": checkpoint_summary.get("count", 0),
                "checkpoints": checkpoint_summary.get("checkpoints", []),
            },
            "audit_status": audit_status,
            "paper_trades_logged": [],
            "summary": {
                "selected_count": 0,
                "logged_count": 0,
                "failed_ticker_count": 0,
                "failed_tickers": [],
                "timed_out_ticker_count": 0,
                "data_quality": None,
                "scan_execution_summary": None,
                "pipeline_run_id": run_id,
                "checkpoint_count": checkpoint_summary.get("count", 0),
                "audit_chain_ok": audit_status.get("ok"),
                "startup_readiness": startup_readiness,
                "message": "Paper trading cycle blocked by startup validation.",
            },
            "warning": "Paper trading is simulated only. No live brokerage orders were placed.",
            "errors": list(startup_readiness.get("errors", [])) + observability_warnings,
        }

    trade_hunt = run_weekly_trade_hunt(
        universe=universe,
        max_tickers=max_tickers,
        profiles=profiles,
        max_trades=max_trades,
        min_trades=min_trades,
        include_catalysts=include_catalysts,
        include_market_regime=include_market_regime,
        include_relative_strength=include_relative_strength,
        include_options=include_options,
        prefer_options=prefer_options,
        max_option_contracts_per_trade=max_option_contracts_per_trade,
        include_portfolio_risk=include_portfolio_risk,
        include_position_sizing=include_position_sizing,
        include_memory_context=include_memory_context,
        store_memory=store_memory,
        account_size=account_size,
        risk_mode=risk_mode,
        auto_log=True,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": PAPER_MODE, "mode": PAPER_MODE, "run_id": run_id},
        scan_max_concurrency=scan_max_concurrency,
        scan_ticker_timeout_seconds=scan_ticker_timeout_seconds,
        scan_total_timeout_seconds=scan_total_timeout_seconds,
        use_async_scan=use_async_scan,
    )
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "universe_loaded", "completed", payload=trade_hunt.get("universe_result") if isinstance(trade_hunt, dict) else None), "universe_loaded")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "async_scan_completed", "completed", payload=trade_hunt.get("scan_execution_summary") if isinstance(trade_hunt, dict) else None), "async_scan_completed")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "candidates_ranked", "completed", payload=trade_hunt.get("selection_result") if isinstance(trade_hunt, dict) else None), "candidates_ranked")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "macro_risk_evaluated", "completed", payload=trade_hunt.get("macro_risk") if isinstance(trade_hunt, dict) else None), "macro_risk_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "market_regime_evaluated", "completed", payload=trade_hunt.get("market_regime") if isinstance(trade_hunt, dict) else None), "market_regime_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "correlation_snapshot_loaded", "completed", payload=(trade_hunt.get("concentration_summary") or {}).get("snapshot") if isinstance(trade_hunt, dict) else None), "correlation_snapshot_loaded")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "concentration_risk_evaluated", "completed", payload=trade_hunt.get("concentration_summary") if isinstance(trade_hunt, dict) else None), "concentration_risk_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "volume_profile_evaluated", "completed", payload=trade_hunt.get("technical_confirmation_summary") if isinstance(trade_hunt, dict) else None), "volume_profile_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "timeframe_confirmation_evaluated", "completed", payload=trade_hunt.get("technical_confirmation_summary") if isinstance(trade_hunt, dict) else None), "timeframe_confirmation_evaluated")
    filing_sentiment_summary = trade_hunt.get("filing_sentiment_summary") if isinstance(trade_hunt, dict) else None
    if not isinstance(filing_sentiment_summary, dict) and isinstance(trade_hunt, dict):
        filing_sentiment_summary = (trade_hunt.get("summary") or {}).get("filing_sentiment_summary")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "sec_filings_loaded", "completed", payload=filing_sentiment_summary), "sec_filings_loaded")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "filing_analysis_completed", "completed", payload=filing_sentiment_summary), "filing_analysis_completed")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "earnings_8k_analyzed", "completed", payload=filing_sentiment_summary), "earnings_8k_analyzed")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "filing_sentiment_evaluated", "completed", payload=filing_sentiment_summary), "filing_sentiment_evaluated")
    research_risk_summary = trade_hunt.get("research_risk_summary") if isinstance(trade_hunt, dict) else None
    if not isinstance(research_risk_summary, dict) and isinstance(trade_hunt, dict):
        research_risk_summary = (trade_hunt.get("summary") or {}).get("research_risk_summary")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "short_interest_evaluated", "completed", payload=research_risk_summary), "short_interest_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "borrow_pressure_evaluated", "completed", payload=research_risk_summary), "borrow_pressure_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "recent_news_loaded", "completed", payload=research_risk_summary), "recent_news_loaded")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "news_sentiment_evaluated", "completed", payload=research_risk_summary), "news_sentiment_evaluated")
    option_risk_summary = ((trade_hunt.get("option_research") or {}).get("option_risk_summary") if isinstance(trade_hunt, dict) and isinstance(trade_hunt.get("option_research"), dict) else None)
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "iv_context_evaluated", "completed", payload=option_risk_summary), "iv_context_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "greeks_evaluated", "completed", payload=option_risk_summary), "greeks_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "option_trade_risk_evaluated", "completed", payload=option_risk_summary), "option_trade_risk_evaluated")
    option_strategy_summary = ((trade_hunt.get("option_research") or {}).get("summary", {}).get("option_strategy_summary") if isinstance(trade_hunt, dict) and isinstance(trade_hunt.get("option_research"), dict) else None)
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "option_strategies_built", "completed", payload=option_strategy_summary), "option_strategies_built")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "option_strategy_evaluated", "completed", payload=option_strategy_summary), "option_strategy_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "option_strategy_selected", "completed", payload=option_strategy_summary), "option_strategy_selected")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "portfolio_risk_evaluated", "completed", payload=trade_hunt.get("portfolio_risk") if isinstance(trade_hunt, dict) else None), "portfolio_risk_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "circuit_breaker_evaluated", "completed", payload=(trade_hunt.get("summary") or {}).get("circuit_breaker") if isinstance(trade_hunt, dict) else None), "circuit_breaker_evaluated")
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "final_selection_completed", "completed", payload=trade_hunt.get("decision_result") if isinstance(trade_hunt, dict) else None), "final_selection_completed")

    decision_result = trade_hunt.get("decision_result", {}) if isinstance(trade_hunt, dict) else {}
    logged_entries = decision_result.get("logged_recommendations", []) if isinstance(decision_result, dict) else []
    paper_trades_logged = [
        entry.get("data", {}).get("recommendation")
        for entry in logged_entries
        if isinstance(entry, dict) and isinstance(entry.get("data"), dict) and entry.get("data", {}).get("recommendation")
    ]

    selected_count = len(decision_result.get("final_recommendations", [])) if isinstance(decision_result, dict) else 0
    logged_count = len(paper_trades_logged)
    scan_result = trade_hunt.get("scan_result", {}) if isinstance(trade_hunt, dict) else {}
    data_quality_summary = scan_result.get("data_quality_summary") if isinstance(scan_result, dict) else None
    scan_execution_summary = trade_hunt.get("scan_execution_summary") if isinstance(trade_hunt, dict) else None
    if not isinstance(scan_execution_summary, dict) and isinstance(scan_result, dict):
        scan_execution_summary = scan_result.get("scan_execution_summary")
    rejected_candidates = scan_result.get("rejected_candidates", []) if isinstance(scan_result, dict) and isinstance(scan_result.get("rejected_candidates"), list) else []
    failed_tickers = {
        str(candidate.get("ticker"))
        for candidate in rejected_candidates
        if isinstance(candidate, dict)
        and isinstance(candidate.get("data_quality"), dict)
        and candidate["data_quality"].get("quality_label") in {"poor", "unavailable"}
    }
    failed_ticker_count = len(failed_tickers)
    message = (
        "Paper trading cycle completed. Recommendations were logged as simulated trades only."
        if trade_hunt.get("ok")
        else "Paper trading cycle failed before simulated trades could be logged."
    )
    summary_payload = {
        "selected_count": selected_count,
        "logged_count": logged_count,
        "failed_ticker_count": failed_ticker_count,
        "timed_out_ticker_count": len(scan_execution_summary.get("timed_out_tickers", [])) if isinstance(scan_execution_summary, dict) else 0,
        "scan_execution_summary": scan_execution_summary,
        "memory_summary": (trade_hunt.get("summary") or {}).get("memory_summary") if isinstance(trade_hunt, dict) else None,
        "message": message,
    }
    _audit_trade_hunt(db_path, run_id, trade_hunt, observability_warnings)
    _append_observability_warning(observability_warnings, _safe_checkpoint(db_path, run_id, "paper_logging_completed", "completed", payload={"logged_count": logged_count}), "paper_logging_completed")
    if trade_hunt.get("ok"):
        pipeline_result = complete_pipeline_run(db_path, run_id, summary_payload, status="completed") if run_id else {"ok": False, "error": "No run id."}
        _append_observability_warning(observability_warnings, _safe_audit(db_path, "paper_cycle_completed", summary_payload, run_id=run_id), "paper_cycle_completed_audit")
    else:
        pipeline_result = fail_pipeline_run(db_path, run_id, {"errors": trade_hunt.get("errors", [])}) if run_id else {"ok": False, "error": "No run id."}
        _append_observability_warning(observability_warnings, _safe_audit(db_path, "paper_cycle_failed", {"errors": trade_hunt.get("errors", [])}, run_id=run_id), "paper_cycle_failed_audit")
    _append_observability_warning(observability_warnings, pipeline_result, "complete_pipeline_run")
    checkpoint_summary = list_checkpoints(db_path, run_id) if run_id else {"ok": False, "checkpoints": []}
    audit_status = verify_audit_chain(db_path)
    pipeline_run = get_pipeline_run(db_path, run_id) if run_id else pipeline_result

    return {
        "ok": bool(trade_hunt.get("ok")),
        "mode": PAPER_MODE,
        "run_id": run_id,
        "timestamp": _now_iso(),
        "startup_readiness": startup_readiness,
        "trade_hunt": trade_hunt,
        "pipeline_run": pipeline_run.get("pipeline_run") if isinstance(pipeline_run, dict) else None,
        "checkpoint_summary": {
            "ok": checkpoint_summary.get("ok"),
            "count": checkpoint_summary.get("count", 0),
            "checkpoints": checkpoint_summary.get("checkpoints", []),
        },
        "audit_status": audit_status,
        "paper_trades_logged": paper_trades_logged,
        "summary": {
            "selected_count": selected_count,
            "logged_count": logged_count,
            "failed_ticker_count": failed_ticker_count,
            "failed_tickers": sorted(failed_tickers),
            "timed_out_ticker_count": len(scan_execution_summary.get("timed_out_tickers", [])) if isinstance(scan_execution_summary, dict) else 0,
            "data_quality": data_quality_summary,
            "scan_execution_summary": scan_execution_summary,
            "memory_summary": summary_payload.get("memory_summary"),
            "pipeline_run_id": run_id,
            "checkpoint_count": checkpoint_summary.get("count", 0),
            "audit_chain_ok": audit_status.get("ok"),
            "startup_readiness": startup_readiness,
            "message": message,
        },
        "warning": "Paper trading is simulated only. No live brokerage orders were placed.",
        "errors": (trade_hunt.get("errors", []) if isinstance(trade_hunt, dict) else ["Paper trading cycle failed."]) + list(startup_readiness.get("warnings", [])) + observability_warnings,
    }


def review_paper_portfolio(
    update_outcomes: bool = True,
    include_trade_reviews: bool = True,
    store_review_memory: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        monitoring_result = monitor_open_trades(update_outcomes=update_outcomes, db_path=db_path)
        trade_review_summary = None
        if include_trade_reviews:
            trade_review_summary = review_closed_trades(
                db_path=db_path,
                store_memory=store_review_memory,
            )

        paper_recommendations = _load_paper_recommendations(db_path)
        paper_ids = {recommendation["id"] for recommendation in paper_recommendations}
        update_result = monitoring_result.get("update_result") if isinstance(monitoring_result, dict) else None
        recent_results = update_result.get("results", []) if isinstance(update_result, dict) else []
        recently_closed_paper_trades = [
            result
            for result in recent_results
            if isinstance(result, dict) and result.get("recommendation_id") in paper_ids and str(result.get("outcome", "")).lower() in TERMINAL_OUTCOMES
        ]

        summary = get_paper_trading_summary(db_path=db_path)
        return {
            "ok": bool(monitoring_result.get("ok")) and bool(summary.get("ok")),
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "monitoring_result": monitoring_result,
            "open_paper_trades": summary.get("open_paper_trades", []),
            "recently_closed_paper_trades": recently_closed_paper_trades,
            "win_loss_record": summary.get("win_loss_record"),
            "strategy_performance": summary.get("strategy_performance"),
            "trade_review_summary": trade_review_summary,
            "warning": "Paper trading performance is simulated only and is not live brokerage P/L.",
            "errors": list(monitoring_result.get("errors", []))
            + list(summary.get("errors", []))
            + list(trade_review_summary.get("errors", []) if isinstance(trade_review_summary, dict) else []),
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "monitoring_result": None,
            "open_paper_trades": [],
            "recently_closed_paper_trades": [],
            "win_loss_record": None,
            "strategy_performance": None,
            "trade_review_summary": None,
            "warning": "Paper trading performance is simulated only and is not live brokerage P/L.",
            "errors": [str(exc)],
        }


def get_paper_trading_summary(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        recommendations = _load_paper_recommendations(db_path)
        open_paper_trades = _paper_open_trades(recommendations)
        closed_paper_trades = _paper_closed_trades(recommendations)
        win_loss_record = _paper_win_loss_record(recommendations)
        strategy_performance = _paper_strategy_performance(recommendations)
        setup_types = strategy_performance.get("by_setup_type", [])
        ranked_setups = [setup for setup in setup_types if setup.get("average_realized_return") is not None]
        ranked_setups.sort(key=lambda item: item["average_realized_return"], reverse=True)
        best_setup_type = ranked_setups[0]["setup_type"] if ranked_setups else None
        worst_setup_type = ranked_setups[-1]["setup_type"] if ranked_setups else None

        return {
            "ok": True,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "open_paper_trades": open_paper_trades,
            "closed_paper_trades_count": len(closed_paper_trades),
            "win_loss_record": win_loss_record,
            "strategy_performance": strategy_performance,
            "best_setup_type": best_setup_type,
            "worst_setup_type": worst_setup_type,
            "warning": "This is simulated paper-trading performance, not live brokerage P/L.",
            "errors": [],
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "open_paper_trades": [],
            "closed_paper_trades_count": 0,
            "win_loss_record": None,
            "strategy_performance": None,
            "best_setup_type": None,
            "worst_setup_type": None,
            "warning": "This is simulated paper-trading performance, not live brokerage P/L.",
            "errors": [str(exc)],
        }


def get_paper_risk_diagnostics(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        recommendations = _load_paper_recommendations(db_path)
        open_paper_trades = _paper_open_trades(recommendations)
        circuit_breaker = evaluate_drawdown_circuit_breaker(recommendations, open_trades=open_paper_trades)
        setup_decay = evaluate_all_setup_decay(recommendations)
        return {
            "ok": True,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "circuit_breaker": circuit_breaker,
            "setup_decay": setup_decay,
            "open_paper_trades_count": len(open_paper_trades),
            "closed_paper_trades_count": len(_paper_closed_trades(recommendations)),
            "warnings": circuit_breaker.get("warnings", []) + setup_decay.get("warnings", []),
            "errors": [],
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "mode": PAPER_MODE,
            "timestamp": _now_iso(),
            "circuit_breaker": None,
            "setup_decay": None,
            "open_paper_trades_count": 0,
            "closed_paper_trades_count": 0,
            "warnings": [],
            "errors": [str(exc)],
        }
