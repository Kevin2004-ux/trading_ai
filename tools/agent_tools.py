from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.trading_brain import (
    monitor_open_trades,
    review_ticker_opportunity,
    run_weekly_trade_hunt,
)
from analytics.market_regime import get_market_regime_snapshot
from analytics.options_mispricing import evaluate_option_mispricing
from analytics.relative_strength import get_relative_strength_snapshot
from analytics.statistical_brain import (
    analyze_profile_performance,
    analyze_setup_performance,
    analyze_ticker_history,
)
from memory.vector_memory import (
    find_similar_setups,
    search_memory,
    store_memory_item,
)
from journal.trade_journal import (
    build_trade_review,
    get_trade_reviews,
    review_closed_trades,
)
from risk.portfolio_manager import apply_portfolio_risk_limits
from risk.position_sizing import calculate_position_size
from research.deep_research import build_research_brief
from research.earnings_transcripts import get_earnings_transcript_snapshot
from research.sec_filings import get_sec_filing_snapshot
from paper.paper_trader import (
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)
from reports.report_generator import (
    generate_full_paper_trading_report,
    generate_open_trade_review_report,
    generate_performance_diagnostics_report,
    generate_performance_report,
    generate_post_trade_review_report,
    generate_ticker_research_memo,
    generate_weekly_trade_plan_report,
)
from scanner.options_scanner import (
    scan_options_for_stock_candidate,
    scan_options_for_weekly_selection,
)
from scanner.universe_builder import get_default_universe
from selector.weekly_selector import select_weekly_trades
from engine.constraint_engine import evaluate_stock_constraints
from realtime.catalyst_enrichment import get_catalyst_snapshot, get_earnings_snapshot, get_news_snapshot
from realtime.market_data import get_market_snapshot
from scanner.swing_scanner import (
    build_stock_candidate,
    calculate_trade_levels,
    scan_multi_strategy_candidates,
    scan_swing_candidates,
)
from tracking.outcome_grader import update_open_recommendations
from tracking.trade_logger import (
    get_recommendation,
    get_open_recommendations,
    get_strategy_performance,
    get_win_loss_record,
    log_recommendation,
)


DEFAULT_MINIMUM_RISK_REWARD = 2.0
SUPPORTED_ASSET_TYPES = {"stock", "option"}
SUPPORTED_DIRECTIONS = {"long", "short"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(tool_name: str, ok: bool, data: Any = None, error: str | None = None) -> dict:
    return {
        "ok": ok,
        "tool": tool_name,
        "timestamp": _now_iso(),
        "data": data,
        "error": error,
    }


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _minimum_risk_reward_threshold(constraint_results: dict | None) -> float:
    if not isinstance(constraint_results, dict):
        return DEFAULT_MINIMUM_RISK_REWARD
    config = constraint_results.get("config", {})
    if isinstance(config, dict):
        threshold = _safe_float(config.get("minimum_risk_reward"))
        if threshold is not None:
            return threshold
    return DEFAULT_MINIMUM_RISK_REWARD


def scan_candidates_tool(
    tickers: list[str],
    universe: str = "custom",
    max_candidates: int = 10,
    db_path: str = "strategy_library.db",
    multi_strategy: bool = True,
    profiles: list[str] | None = None,
) -> dict:
    try:
        if multi_strategy:
            result = scan_multi_strategy_candidates(
                tickers=tickers,
                profiles=profiles,
                universe=universe,
                db_path=db_path,
                max_total_candidates=max_candidates,
            )
        else:
            result = scan_swing_candidates(
                tickers=tickers,
                universe=universe,
                db_path=db_path,
                max_candidates=max_candidates,
            )
        return _response("scan_candidates_tool", bool(result.get("ok")), data=result, error=None if result.get("ok") else "Scanner returned no usable result.")
    except Exception as exc:
        return _response("scan_candidates_tool", False, error=f"Failed to scan candidates: {exc}")


def get_candidate_details_tool(
    ticker: str,
    lookback_days: int = 180,
) -> dict:
    try:
        market_snapshot = get_market_snapshot(ticker, lookback_days=lookback_days)
        if not market_snapshot.get("ok"):
            return _response("get_candidate_details_tool", False, error=market_snapshot.get("error", "Failed to load market snapshot."))

        candidate = build_stock_candidate(ticker, market_snapshot)
        technical_snapshot = candidate.get("technical_snapshot", {})
        trade_levels = calculate_trade_levels(technical_snapshot, direction=candidate.get("direction", "long"))
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

        return _response(
            "get_candidate_details_tool",
            True,
            data={
                "market_snapshot": market_snapshot,
                "candidate": candidate,
                "constraint_result": constraint_result,
                "trade_levels": trade_levels,
            },
        )
    except Exception as exc:
        return _response("get_candidate_details_tool", False, error=f"Failed to load candidate details: {exc}")


def scan_options_for_candidate_tool(
    candidate: dict,
    max_contracts: int = 5,
) -> dict:
    try:
        result = scan_options_for_stock_candidate(candidate, max_contracts=max_contracts)
        return _response(
            "scan_options_for_candidate_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else (result.get("errors", [result.get("summary", {}).get("message", "Options scan failed.")])[0] if isinstance(result.get("errors"), list) and result.get("errors") else result.get("summary", {}).get("message", "Options scan failed.")),
        )
    except Exception as exc:
        return _response("scan_options_for_candidate_tool", False, error=f"Failed to scan options for candidate: {exc}")


def evaluate_option_mispricing_tool(
    option_candidate: dict,
    underlying_candidate: dict,
    historical_volatility: float | None = None,
) -> dict:
    try:
        result = evaluate_option_mispricing(
            option_candidate=option_candidate,
            underlying_candidate=underlying_candidate,
            historical_volatility=historical_volatility,
        )
        return _response(
            "evaluate_option_mispricing_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to evaluate option mispricing."),
        )
    except Exception as exc:
        return _response("evaluate_option_mispricing_tool", False, error=f"Failed to evaluate option mispricing: {exc}")


def get_market_regime_tool(
    include_breadth: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_market_regime_snapshot(include_breadth=include_breadth, db_path=db_path)
        return _response(
            "get_market_regime_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to load market regime."),
        )
    except Exception as exc:
        return _response("get_market_regime_tool", False, error=f"Failed to load market regime: {exc}")


def get_relative_strength_tool(
    ticker: str,
    sector: str | None = None,
    include_sector: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_relative_strength_snapshot(
            ticker=ticker,
            sector=sector,
            include_sector=include_sector,
            db_path=db_path,
        )
        return _response(
            "get_relative_strength_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to load relative strength."),
        )
    except Exception as exc:
        return _response("get_relative_strength_tool", False, error=f"Failed to load relative strength: {exc}")


def get_portfolio_risk_tool(
    proposed_trades: list[dict],
    account_size: float = 10000.0,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        existing_open_trades = get_open_recommendations(db_path=db_path)
        if isinstance(existing_open_trades, dict) and existing_open_trades.get("ok") is False:
            return _response(
                "get_portfolio_risk_tool",
                False,
                error=existing_open_trades.get("error", "Failed to load open recommendations."),
            )

        result = apply_portfolio_risk_limits(
            proposed_trades=proposed_trades,
            existing_open_trades=existing_open_trades if isinstance(existing_open_trades, list) else [],
            account_size=account_size,
        )
        return _response(
            "get_portfolio_risk_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to analyze portfolio risk."),
        )
    except Exception as exc:
        return _response("get_portfolio_risk_tool", False, error=f"Failed to analyze portfolio risk: {exc}")


def calculate_position_size_tool(
    trade: dict,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
) -> dict:
    try:
        result = calculate_position_size(
            trade=trade,
            account_size=account_size,
            risk_mode=risk_mode,
        )
        return _response(
            "calculate_position_size_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to calculate position size."),
        )
    except Exception as exc:
        return _response("calculate_position_size_tool", False, error=f"Failed to calculate position size: {exc}")


def search_trade_memory_tool(
    query: str,
    top_k: int = 5,
) -> dict:
    try:
        result = search_memory(query=query, top_k=top_k)
        return _response(
            "search_trade_memory_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Semantic memory is unavailable."),
        )
    except Exception as exc:
        return _response("search_trade_memory_tool", False, error=f"Failed to search trade memory: {exc}")


def store_trade_memory_tool(
    item: dict,
    item_type: str = "manual_note",
) -> dict:
    try:
        result = store_memory_item(item=item, item_type=item_type)
        return _response(
            "store_trade_memory_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Semantic memory is unavailable."),
        )
    except Exception as exc:
        return _response("store_trade_memory_tool", False, error=f"Failed to store trade memory: {exc}")


def find_similar_setups_tool(
    candidate_or_trade: dict,
    top_k: int = 5,
) -> dict:
    try:
        result = find_similar_setups(candidate_or_trade=candidate_or_trade, top_k=top_k)
        return _response(
            "find_similar_setups_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Semantic memory is unavailable."),
        )
    except Exception as exc:
        return _response("find_similar_setups_tool", False, error=f"Failed to find similar setups: {exc}")


def build_trade_review_tool(
    recommendation_id: int,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        recommendation = get_recommendation(recommendation_id, db_path=db_path)
        if recommendation is None:
            return _response("build_trade_review_tool", False, error=f"Recommendation {recommendation_id} not found.")
        if isinstance(recommendation, dict) and recommendation.get("ok") is False:
            return _response("build_trade_review_tool", False, error=recommendation.get("error", "Failed to load recommendation."))

        review = build_trade_review(
            recommendation=recommendation,
            db_path=db_path,
        )
        return _response(
            "build_trade_review_tool",
            bool(review.get("ok")),
            data=review,
            error=None if review.get("ok") else review.get("error", "Failed to build trade review."),
        )
    except Exception as exc:
        return _response("build_trade_review_tool", False, error=f"Failed to build trade review: {exc}")


def review_closed_trades_tool(
    db_path: str = "strategy_library.db",
    store_memory: bool = False,
) -> dict:
    try:
        result = review_closed_trades(
            db_path=db_path,
            store_memory=store_memory,
        )
        return _response(
            "review_closed_trades_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else (result.get("errors", ["Failed to review closed trades."])[0] if result.get("errors") else "Failed to review closed trades."),
        )
    except Exception as exc:
        return _response("review_closed_trades_tool", False, error=f"Failed to review closed trades: {exc}")


def get_trade_reviews_tool(
    recommendation_id: int | None = None,
    ticker: str | None = None,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_trade_reviews(
            recommendation_id=recommendation_id,
            ticker=ticker,
            db_path=db_path,
        )
        return _response(
            "get_trade_reviews_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to load trade reviews."),
        )
    except Exception as exc:
        return _response("get_trade_reviews_tool", False, error=f"Failed to load trade reviews: {exc}")


def generate_report_tool(
    report_type: str,
    payload: dict | None = None,
    format: str = "markdown",
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_type = str(report_type or "").strip().lower()
    payload = payload if isinstance(payload, dict) else {}

    try:
        if normalized_type == "weekly_trade_plan":
            result = generate_weekly_trade_plan_report(payload, format=format)
        elif normalized_type == "open_trade_review":
            result = generate_open_trade_review_report(payload, format=format)
        elif normalized_type == "performance":
            result = generate_performance_report(payload, format=format)
        elif normalized_type == "ticker_research":
            result = generate_ticker_research_memo(payload, format=format)
        elif normalized_type == "post_trade_review":
            result = generate_post_trade_review_report(payload.get("reviews", payload), format=format)
        elif normalized_type == "full_paper_trading":
            result = generate_full_paper_trading_report(db_path=db_path, format=format)
        elif normalized_type == "performance_diagnostics":
            result = generate_performance_diagnostics_report(db_path=db_path, format=format)
        else:
            return _response("generate_report_tool", False, error=f"Unsupported report_type: {report_type}")

        return _response(
            "generate_report_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Report generation failed."),
        )
    except Exception as exc:
        return _response("generate_report_tool", False, error=f"Failed to generate report: {exc}")


def get_deep_research_brief_tool(
    ticker: str,
    include_market_regime: bool = True,
    include_relative_strength: bool = True,
    include_catalysts: bool = True,
    include_statistics: bool = True,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
    include_options: bool = False,
    include_memory_context: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = build_research_brief(
            ticker=ticker,
            include_market_regime=include_market_regime,
            include_relative_strength=include_relative_strength,
            include_catalysts=include_catalysts,
            include_statistics=include_statistics,
            include_sec_filings=include_sec_filings,
            include_earnings_transcripts=include_earnings_transcripts,
            include_options=include_options,
            include_memory_context=include_memory_context,
            db_path=db_path,
        )
        return _response(
            "get_deep_research_brief_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to build research brief."),
        )
    except Exception as exc:
        return _response("get_deep_research_brief_tool", False, error=f"Failed to build research brief: {exc}")


def get_sec_filing_brain_tool(
    ticker: str,
    lookback_days: int = 120,
) -> dict:
    try:
        result = get_sec_filing_snapshot(
            ticker=ticker,
            lookback_days=lookback_days,
        )
        return _response(
            "get_sec_filing_brain_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to load SEC filing context."),
        )
    except Exception as exc:
        return _response("get_sec_filing_brain_tool", False, error=f"Failed to load SEC filing context: {exc}")


def get_earnings_transcript_brain_tool(
    ticker: str,
    lookback_quarters: int = 2,
) -> dict:
    try:
        result = get_earnings_transcript_snapshot(
            ticker=ticker,
            lookback_quarters=lookback_quarters,
        )
        return _response(
            "get_earnings_transcript_brain_tool",
            bool(result.get("ok")),
            data=result,
            error=None if result.get("ok") else result.get("error", "Failed to load earnings transcript context."),
        )
    except Exception as exc:
        return _response("get_earnings_transcript_brain_tool", False, error=f"Failed to load earnings transcript context: {exc}")


def log_recommendation_tool(
    ticker: str,
    asset_type: str,
    direction: str,
    strategy: str,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    setup_type: str | None = None,
    risk_reward: float | None = None,
    holding_period_days: int | None = None,
    expiration: str | None = None,
    option_contract: str | None = None,
    confidence: float | None = None,
    score: float | None = None,
    thesis: str | None = None,
    invalidation: str | None = None,
    data_snapshot: dict | None = None,
    constraint_results: dict | None = None,
    model_outputs: dict | None = None,
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    normalized_asset_type = str(asset_type or "").lower()
    normalized_direction = str(direction or "").lower()

    if not normalized_ticker:
        return _response("log_recommendation_tool", False, error="Ticker is required.")
    if normalized_asset_type not in SUPPORTED_ASSET_TYPES:
        return _response("log_recommendation_tool", False, error="Unsupported asset type. Only stock and option are allowed.")
    if normalized_direction not in SUPPORTED_DIRECTIONS:
        return _response("log_recommendation_tool", False, error="Unsupported direction. Only long and short are allowed.")

    required_fields = {
        "entry_price": _safe_float(entry_price),
        "target_price": _safe_float(target_price),
        "stop_loss": _safe_float(stop_loss),
    }
    for field_name, field_value in required_fields.items():
        if field_value is None:
            return _response("log_recommendation_tool", False, error=f"{field_name} is required.")

    threshold = _minimum_risk_reward_threshold(constraint_results)
    normalized_risk_reward = _safe_float(risk_reward)
    if normalized_risk_reward is None:
        return _response("log_recommendation_tool", False, error="risk_reward is required.")
    if normalized_risk_reward < threshold:
        return _response("log_recommendation_tool", False, error=f"risk_reward must be at least {threshold}.")

    if not isinstance(constraint_results, dict):
        return _response("log_recommendation_tool", False, error="constraint_results with a passing recommendable decision are required.")

    passed = bool(constraint_results.get("passed"))
    recommendation_status = str(constraint_results.get("recommendation_status", "")).lower()
    if not passed:
        return _response("log_recommendation_tool", False, error="Failed constraints cannot be logged as recommendations.")
    if recommendation_status != "recommendable":
        return _response("log_recommendation_tool", False, error="Only recommendable candidates can be logged.")

    try:
        logged = log_recommendation(
            ticker=normalized_ticker,
            asset_type=normalized_asset_type,
            direction=normalized_direction,
            strategy=strategy,
            entry_price=required_fields["entry_price"],
            target_price=required_fields["target_price"],
            stop_loss=required_fields["stop_loss"],
            setup_type=setup_type,
            risk_reward=normalized_risk_reward,
            holding_period_days=holding_period_days,
            expiration=expiration,
            option_contract=option_contract,
            confidence=confidence,
            score=score,
            thesis=thesis,
            invalidation=invalidation,
            data_snapshot_json=data_snapshot,
            constraint_results_json=constraint_results,
            model_outputs_json=model_outputs,
            recommendation_status="open",
            status="open",
            db_path=db_path,
        )
        if isinstance(logged, dict) and logged.get("ok") is False:
            return _response("log_recommendation_tool", False, error=logged.get("error", "Failed to log recommendation."))

        return _response(
            "log_recommendation_tool",
            True,
            data={
                "recommendation_id": logged.get("id") if isinstance(logged, dict) else None,
                "recommendation": logged,
            },
        )
    except Exception as exc:
        return _response("log_recommendation_tool", False, error=f"Failed to log recommendation: {exc}")


def get_open_recommendations_tool(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_open_recommendations(db_path=db_path)
        if isinstance(result, dict) and result.get("ok") is False:
            return _response("get_open_recommendations_tool", False, error=result.get("error", "Failed to load open recommendations."))
        return _response("get_open_recommendations_tool", True, data={"recommendations": result})
    except Exception as exc:
        return _response("get_open_recommendations_tool", False, error=f"Failed to load open recommendations: {exc}")


def update_outcomes_tool(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = update_open_recommendations(db_path=db_path)
        return _response("update_outcomes_tool", bool(result.get("ok")), data=result, error=None if result.get("ok") else "Outcome update returned errors.")
    except Exception as exc:
        return _response("update_outcomes_tool", False, error=f"Failed to update outcomes: {exc}")


def get_win_loss_record_tool(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_win_loss_record(db_path=db_path)
        if isinstance(result, dict) and result.get("ok") is False:
            return _response("get_win_loss_record_tool", False, error=result.get("error", "Failed to load win/loss record."))
        return _response("get_win_loss_record_tool", True, data=result)
    except Exception as exc:
        return _response("get_win_loss_record_tool", False, error=f"Failed to load win/loss record: {exc}")


def get_strategy_performance_tool(
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        result = get_strategy_performance(db_path=db_path)
        if isinstance(result, dict) and result.get("ok") is False:
            return _response("get_strategy_performance_tool", False, error=result.get("error", "Failed to load strategy performance."))
        return _response("get_strategy_performance_tool", True, data=result)
    except Exception as exc:
        return _response("get_strategy_performance_tool", False, error=f"Failed to load strategy performance: {exc}")


def get_statistical_brain_tool(
    ticker: str | None = None,
    setup_type: str | None = None,
    scan_profile: str | None = None,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        setup_analysis = analyze_setup_performance(db_path=db_path)
        if not setup_analysis.get("ok"):
            return _response("get_statistical_brain_tool", False, error=setup_analysis.get("error", "Failed to analyze setup performance."))

        setup_groups = setup_analysis.get("groups", [])
        if setup_type is not None:
            setup_groups = [group for group in setup_groups if group.get("setup_type") == setup_type]

        ticker_history = analyze_ticker_history(ticker, db_path=db_path) if ticker else None
        if ticker and not ticker_history.get("ok"):
            return _response("get_statistical_brain_tool", False, error=ticker_history.get("error", "Failed to analyze ticker history."))

        profile_analysis = analyze_profile_performance(scan_profile=scan_profile, db_path=db_path)
        if not profile_analysis.get("ok"):
            return _response("get_statistical_brain_tool", False, error=profile_analysis.get("error", "Failed to analyze profile performance."))

        return _response(
            "get_statistical_brain_tool",
            True,
            data={
                "ticker_history": ticker_history,
                "setup_performance": setup_groups,
                "profile_performance": profile_analysis.get("profiles", []),
            },
        )
    except Exception as exc:
        return _response("get_statistical_brain_tool", False, error=f"Failed to load statistical brain data: {exc}")


def get_catalyst_brain_tool(
    ticker: str,
    lookback_days: int = 7,
) -> dict:
    try:
        news_snapshot = get_news_snapshot(ticker, lookback_days=lookback_days)
        earnings_snapshot = get_earnings_snapshot(ticker)
        catalyst_snapshot = get_catalyst_snapshot(ticker, lookback_days=lookback_days)
        return _response(
            "get_catalyst_brain_tool",
            bool(catalyst_snapshot.get("ok")),
            data={
                "news_snapshot": news_snapshot,
                "earnings_snapshot": earnings_snapshot,
                "catalyst_score": catalyst_snapshot.get("data", {}).get("catalyst_score"),
            },
            error=None if catalyst_snapshot.get("ok") else catalyst_snapshot.get("error", "Failed to load catalyst data."),
        )
    except Exception as exc:
        return _response("get_catalyst_brain_tool", False, error=f"Failed to load catalyst data: {exc}")


def scan_market_for_weekly_trades_tool(
    universe: str = "large_cap",
    max_tickers: int = 500,
    profiles: list[str] | None = None,
    max_trades: int = 5,
    min_trades: int = 2,
    include_catalysts: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    try:
        universe_result = get_default_universe(universe=universe, max_tickers=max_tickers)
        if not universe_result.get("ok"):
            return _response(
                "scan_market_for_weekly_trades_tool",
                False,
                data={"universe_result": universe_result},
                error="Failed to build ticker universe.",
            )

        scan_result = scan_multi_strategy_candidates(
            tickers=universe_result.get("tickers", []),
            profiles=profiles,
            universe=universe,
            db_path=db_path,
        )
        if not scan_result.get("ok"):
            return _response(
                "scan_market_for_weekly_trades_tool",
                False,
                data={"universe_result": universe_result, "scan_result": scan_result},
                error="Market scan failed.",
            )

        open_recommendations = get_open_recommendations(db_path=db_path)
        if isinstance(open_recommendations, dict) and open_recommendations.get("ok") is False:
            return _response(
                "scan_market_for_weekly_trades_tool",
                False,
                data={"universe_result": universe_result, "scan_result": scan_result},
                error=open_recommendations.get("error", "Failed to load open recommendations."),
            )

        selection_result = select_weekly_trades(
            scan_result=scan_result,
            max_trades=max_trades,
            min_trades=min_trades,
            existing_open_trades=open_recommendations,
            db_path=db_path,
            config={"include_catalysts": include_catalysts},
        )
        if not selection_result.get("ok"):
            return _response(
                "scan_market_for_weekly_trades_tool",
                False,
                data={
                    "universe_result": universe_result,
                    "scan_result": scan_result,
                    "selection_result": selection_result,
                },
                error="Weekly selection failed.",
            )

        return _response(
            "scan_market_for_weekly_trades_tool",
            True,
            data={
                "universe_result": universe_result,
                "scan_result": scan_result,
                "selection_result": selection_result,
            },
        )
    except Exception as exc:
        return _response("scan_market_for_weekly_trades_tool", False, error=f"Failed to scan market for weekly trades: {exc}")


def run_trading_brain_tool(
    mode: str = "weekly_trade_hunt",
    ticker: str | None = None,
    universe: str = "large_cap",
    max_tickers: int = 500,
    max_trades: int = 5,
    min_trades: int = 2,
    include_catalysts: bool = True,
    include_market_regime: bool = True,
    include_relative_strength: bool = True,
    include_research_brief: bool = True,
    include_research_briefs: bool = False,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
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
) -> dict:
    normalized_mode = str(mode or "").strip().lower()
    try:
        if normalized_mode == "weekly_trade_hunt":
            result = run_weekly_trade_hunt(
                universe=universe,
                max_tickers=max_tickers,
                max_trades=max_trades,
                min_trades=min_trades,
                include_catalysts=include_catalysts,
                include_market_regime=include_market_regime,
                include_relative_strength=include_relative_strength,
                include_research_briefs=include_research_briefs,
                include_options=include_options,
                prefer_options=prefer_options,
                max_option_contracts_per_trade=max_option_contracts_per_trade,
                include_portfolio_risk=include_portfolio_risk,
                include_position_sizing=include_position_sizing,
                include_memory_context=include_memory_context,
                store_memory=store_memory,
                account_size=account_size,
                risk_mode=risk_mode,
                auto_log=auto_log,
                db_path=db_path,
            )
        elif normalized_mode == "review_ticker":
            if not ticker:
                return _response("run_trading_brain_tool", False, error="ticker is required for mode=review_ticker")
            result = review_ticker_opportunity(
                ticker=ticker,
                include_catalysts=include_catalysts,
                include_research_brief=include_research_brief,
                include_sec_filings=include_sec_filings,
                include_earnings_transcripts=include_earnings_transcripts,
                db_path=db_path,
            )
        elif normalized_mode == "monitor_open_trades":
            result = monitor_open_trades(
                update_outcomes=True,
                db_path=db_path,
            )
        else:
            return _response("run_trading_brain_tool", False, error=f"Unsupported mode: {mode}")

        if isinstance(result, dict):
            result = dict(result)
            result.setdefault(
                "gemini_validation",
                {
                    "available": True,
                    "validation_status": "not_run",
                    "deterministic_fallback_used": False,
                    "gemini_called": False,
                    "note": "Gemini is only an explanation layer; deterministic trading-brain output remains source of truth.",
                },
            )
        return _response("run_trading_brain_tool", bool(result.get("ok")), data=result, error=None if result.get("ok") else result.get("errors", [result.get("error", "Trading brain failed.")])[0] if isinstance(result.get("errors"), list) and result.get("errors") else result.get("error", "Trading brain failed."))
    except Exception as exc:
        return _response("run_trading_brain_tool", False, error=f"Failed to run trading brain: {exc}")


def run_paper_trading_tool(
    action: str = "cycle",
    universe: str = "large_cap",
    max_tickers: int = 500,
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
    include_trade_reviews: bool = True,
    store_review_memory: bool = False,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    update_outcomes: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_action = str(action or "").strip().lower()
    try:
        if normalized_action == "cycle":
            result = run_paper_trade_cycle(
                universe=universe,
                max_tickers=max_tickers,
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
                db_path=db_path,
            )
        elif normalized_action == "review":
            result = review_paper_portfolio(
                update_outcomes=update_outcomes,
                include_trade_reviews=include_trade_reviews,
                store_review_memory=store_review_memory,
                db_path=db_path,
            )
        elif normalized_action == "summary":
            result = get_paper_trading_summary(db_path=db_path)
        else:
            return _response("run_paper_trading_tool", False, error=f"Unsupported paper trading action: {action}")

        error = None
        if not result.get("ok"):
            errors = result.get("errors")
            if isinstance(errors, list) and errors:
                error = str(errors[0])
            else:
                error = result.get("error", "Paper trading action failed.")
        return _response("run_paper_trading_tool", bool(result.get("ok")), data=result, error=error)
    except Exception as exc:
        return _response("run_paper_trading_tool", False, error=f"Failed to run paper trading workflow: {exc}")
