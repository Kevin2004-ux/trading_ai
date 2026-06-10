from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from analytics.market_regime import (
    apply_regime_to_trade_selection,
    get_market_regime_snapshot,
)
from analytics.relative_strength import get_relative_strength_snapshot
from analytics.statistical_brain import enrich_candidate_with_statistics
from engine.constraint_engine import evaluate_stock_constraints
from memory.vector_memory import (
    find_similar_setups,
    store_research_brief_memory,
    store_trade_decision_memory,
)
from realtime.catalyst_enrichment import enrich_candidate_with_catalysts
from realtime.market_data import get_market_snapshot
from risk.portfolio_manager import apply_portfolio_risk_limits
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
    }


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


def _select_preferred_option(candidate: dict) -> tuple[dict | None, str | None]:
    option_alternatives = _best_option_alternatives(candidate, limit=3)
    if not option_alternatives:
        return None, "No option alternatives were available."

    preferred_option = option_alternatives[0]
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
            else:
                option_selection_reason = option_reason
                if option_reason:
                    option_risks.append(option_reason)
        else:
            option_selection_reason = "Option alternatives are available as research, but stock remains the default preferred instrument."

    position_sizing = None
    if include_position_sizing:
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
        )
        if isinstance(position_sizing, dict):
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
    if include_memory_context:
        similar_setup_context = find_similar_setups(
            {
                **candidate_copy,
                "ticker": ticker,
                "decision": decision,
            },
            top_k=5,
        )

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
        "option_alternatives": option_alternatives,
        "preferred_instrument": preferred_instrument,
        "preferred_option_contract": preferred_option_contract,
        "option_selection_reason": option_selection_reason,
        "option_risks": option_risks,
        "preferred_option_mispricing_context": preferred_option_mispricing_context,
        "position_sizing": position_sizing,
        "similar_setup_context": similar_setup_context,
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
    }
    model_outputs = {
        "scan_profile": source_candidate.get("scan_profile"),
        "selected_profile": source_candidate.get("selected_profile"),
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
            }
        )
        model_outputs.update(
            {
                "option_contract": option_contract,
                "expiration": expiration,
                "preferred_instrument": "option",
            }
        )
        constraint_results = option_constraint_payload

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
) -> dict:
    errors: list[str] = []
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
    )
    if not scan_result.get("ok"):
        return {
            "ok": False,
            "mode": "weekly_trade_hunt",
            "timestamp": _now_iso(),
            "universe_result": universe_result,
            "scan_result": scan_result,
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
                "message": "Scanner failed.",
            },
            "errors": [scan_result.get("error", "Scanner failed.")],
        }

    existing_open_trades = get_open_recommendations(db_path=db_path)
    if isinstance(existing_open_trades, dict) and existing_open_trades.get("ok") is False:
        errors.append(existing_open_trades.get("error", "Failed to load open recommendations."))
        existing_open_trades = []

    market_regime = None
    if include_market_regime:
        market_regime = get_market_regime_snapshot(include_breadth=True, db_path=db_path)

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

    selected_count = len(decision_result.get("final_recommendations", []))
    logged_count = len(decision_result.get("logged_recommendations", []))
    summary_message = decision_result.get("message") or selection_result.get("selection_summary", {}).get("message") or "Weekly trade hunt completed."
    if include_market_regime and isinstance(market_regime, dict) and market_regime.get("summary"):
        summary_message = f"{summary_message} {market_regime['summary']}"
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
        "selection_result": selection_result,
        "market_regime": market_regime,
        "portfolio_risk": portfolio_risk,
        "option_research": option_research,
        "decision_result": decision_result,
        "performance_context": performance_context,
        "summary": {
            "tickers_scanned": universe_result.get("count", 0),
            "profiles_run": scan_result.get("profiles_run", profiles or []),
            "selected_count": selected_count,
            "logged_count": logged_count,
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
