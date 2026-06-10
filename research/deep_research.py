from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from analytics.market_regime import get_market_regime_snapshot
from analytics.relative_strength import get_relative_strength_snapshot
from analytics.statistical_brain import analyze_ticker_history, enrich_candidate_with_statistics
from engine.constraint_engine import evaluate_stock_constraints
from memory.vector_memory import find_similar_setups
from realtime.catalyst_enrichment import get_catalyst_snapshot, score_catalyst_strength
from realtime.market_data import get_market_snapshot
from research.earnings_transcripts import get_earnings_transcript_snapshot
from research.sec_filings import get_sec_filing_snapshot
from scanner.options_scanner import scan_options_for_stock_candidate
from scanner.swing_scanner import build_stock_candidate, calculate_trade_levels


DEFAULT_HOLDING_PERIOD_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("ok"))


def _catalyst_score_payload(catalyst_context: dict | None) -> dict:
    if not isinstance(catalyst_context, dict):
        return {}
    data = catalyst_context.get("data")
    if isinstance(data, dict):
        score_payload = data.get("catalyst_score")
        if isinstance(score_payload, dict):
            return score_payload
    return catalyst_context if isinstance(catalyst_context.get("catalyst_label"), str) else {}


def _filing_analysis_payload(filing_context: dict | None) -> dict:
    if not isinstance(filing_context, dict):
        return {}
    data = filing_context.get("data")
    if isinstance(data, dict):
        filing_analysis = data.get("filing_analysis")
        if isinstance(filing_analysis, dict):
            return filing_analysis
    return filing_context if isinstance(filing_context.get("filing_risk_label"), str) else {}


def _earnings_quality_payload(earnings_context: dict | None) -> dict:
    if not isinstance(earnings_context, dict):
        return {}
    data = earnings_context.get("data")
    if isinstance(data, dict):
        earnings_quality = data.get("earnings_quality")
        if isinstance(earnings_quality, dict):
            return earnings_quality
    return earnings_context if isinstance(earnings_context.get("earnings_quality_label"), str) else {}


def _requested_context_keys(
    *,
    include_market_regime: bool,
    include_relative_strength: bool,
    include_catalysts: bool,
    include_statistics: bool,
    include_options: bool,
    include_sec_filings: bool,
    include_earnings_transcripts: bool,
    include_memory_context: bool,
) -> list[str]:
    requested = ["market_snapshot", "candidate_details"]
    if include_statistics:
        requested.append("statistical_context")
    if include_catalysts:
        requested.append("catalyst_context")
    if include_market_regime:
        requested.append("market_regime")
    if include_relative_strength:
        requested.append("relative_strength")
    if include_options:
        requested.append("options_context")
    if include_sec_filings:
        requested.append("filing_context")
    if include_earnings_transcripts:
        requested.append("earnings_transcript_context")
    if include_memory_context:
        requested.append("memory_context")
    return requested


def _candidate_details(
    ticker: str,
    db_path: str,
) -> dict | None:
    market_snapshot = get_market_snapshot(ticker, lookback_days=180)
    if not market_snapshot.get("ok"):
        return None

    candidate = build_stock_candidate(ticker, market_snapshot)
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
    constraint_result = evaluate_stock_constraints(candidate)
    candidate["score"] = constraint_result["score"]
    candidate["recommendation_status"] = constraint_result["recommendation_status"]
    candidate["constraint_results"] = constraint_result["constraint_results"]
    candidate["failed_constraints"] = constraint_result["failed_constraints"]
    candidate["rejection_reason"] = constraint_result["rejection_reason"]
    candidate["passed"] = constraint_result["passed"]
    candidate = enrich_candidate_with_statistics(candidate, db_path=db_path)
    return {
        "market_snapshot": market_snapshot,
        "candidate": candidate,
        "constraint_result": constraint_result,
        "trade_levels": trade_levels,
    }


def _missing_sections(raw_context: dict, requested_sections: list[str]) -> list[str]:
    missing = []
    for key in requested_sections:
        value = raw_context.get(key)
        if key == "market_snapshot":
            if not _is_ok(value):
                missing.append(key)
        elif key == "candidate_details":
            if not isinstance(value, dict):
                missing.append(key)
        elif key == "statistical_context":
            if not isinstance(value, dict):
                missing.append(key)
        else:
            if not _is_ok(value):
                missing.append(key)
    return missing


def summarize_bull_case(
    inputs: dict,
) -> dict:
    points: list[str] = []
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    constraint_result = inputs.get("constraint_result") if isinstance(inputs.get("constraint_result"), dict) else {}
    technical = inputs.get("technical_snapshot") if isinstance(inputs.get("technical_snapshot"), dict) else {}
    statistical_context = inputs.get("statistical_context") if isinstance(inputs.get("statistical_context"), dict) else {}
    catalyst_context = inputs.get("catalyst_context") if isinstance(inputs.get("catalyst_context"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    options_context = inputs.get("options_context") if isinstance(inputs.get("options_context"), dict) else {}
    filing_context = inputs.get("filing_context") if isinstance(inputs.get("filing_context"), dict) else {}
    earnings_transcript_context = inputs.get("earnings_transcript_context") if isinstance(inputs.get("earnings_transcript_context"), dict) else {}

    if constraint_result.get("passed"):
        points.append("Technical setup passed objective constraints.")
    if _safe_float(technical.get("current_price")) is not None:
        if _safe_float(technical.get("sma_20")) is not None and _safe_float(technical.get("current_price")) > _safe_float(technical.get("sma_20")):
            points.append("Price is above the 20-day moving average.")
        if _safe_float(technical.get("sma_50")) is not None and _safe_float(technical.get("current_price")) > _safe_float(technical.get("sma_50")):
            points.append("Price is above the 50-day moving average.")
    risk_reward = _safe_float(candidate.get("risk_reward"))
    if risk_reward is not None and risk_reward >= 2.0:
        points.append(f"Risk/reward is favorable at {round(risk_reward, 2)} to 1.")

    setup_performance = statistical_context.get("setup_performance")
    if isinstance(setup_performance, dict) and _safe_float(setup_performance.get("expectancy")) is not None and _safe_float(setup_performance.get("expectancy")) > 0:
        points.append("Historical setup expectancy is positive.")
    ticker_history = statistical_context.get("ticker_history")
    if isinstance(ticker_history, dict) and str(ticker_history.get("historical_edge", "")).lower() == "positive":
        points.append("Ticker history shows a positive edge.")

    catalyst_score = _catalyst_score_payload(catalyst_context)
    if str(catalyst_score.get("catalyst_label", "")).lower() in {"positive", "strong_positive"}:
        points.append("Catalyst backdrop is positive.")
    earnings_snapshot = catalyst_context.get("data", {}).get("earnings_snapshot") if isinstance(catalyst_context.get("data"), dict) else catalyst_context.get("earnings_snapshot")
    if isinstance(earnings_snapshot, dict) and not earnings_snapshot.get("is_earnings_risk", False):
        points.append("There is no near-term earnings risk flag.")

    if str(market_regime.get("regime", "")).lower() in {"risk_on_uptrend", "risk_on_extended"}:
        points.append(f"Market regime is {str(market_regime.get('regime')).replace('_', ' ')}.")
    if str(relative_strength.get("relative_strength_label", "")).lower() in {"market_leader", "outperforming"}:
        points.append(f"Relative strength is {str(relative_strength.get('relative_strength_label')).replace('_', ' ')}.")

    filing_analysis = _filing_analysis_payload(filing_context)
    if str(filing_analysis.get("filing_risk_label", "")).lower() == "low":
        points.append("Recent SEC filing risk is low.")
    positive_filing_signals = filing_analysis.get("positive_filing_signals", [])
    if isinstance(positive_filing_signals, list) and positive_filing_signals:
        points.append(f"SEC filing support: {positive_filing_signals[0]}")

    earnings_quality = _earnings_quality_payload(earnings_transcript_context)
    earnings_label = str(earnings_quality.get("earnings_quality_label", "")).lower()
    if earnings_label == "strong":
        points.append("Recent earnings transcript quality is strong.")
    management_tone = str(earnings_quality.get("management_tone", "")).lower()
    if management_tone == "positive":
        points.append("Management tone in recent transcripts was positive.")
    guidance_label = str(earnings_quality.get("guidance_label", "")).lower()
    if guidance_label in {"raised", "maintained"}:
        points.append(f"Recent transcript guidance was {guidance_label}.")

    if options_context.get("ok"):
        best_options = options_context.get("best_option_candidates", [])
        if isinstance(best_options, list) and best_options:
            top_option = best_options[0]
            if str(top_option.get("mispricing_label", "")).lower() in {"attractive_value", "fair_value"}:
                points.append(f"Top option alternative is labeled {str(top_option.get('mispricing_label')).replace('_', ' ')}.")

    if len(points) >= 5:
        strength = "strong"
    elif len(points) >= 3:
        strength = "moderate"
    else:
        strength = "weak"
    return {"points": points, "strength": strength}


def summarize_bear_case(
    inputs: dict,
) -> dict:
    points: list[str] = []
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    constraint_result = inputs.get("constraint_result") if isinstance(inputs.get("constraint_result"), dict) else {}
    statistical_context = inputs.get("statistical_context") if isinstance(inputs.get("statistical_context"), dict) else {}
    catalyst_context = inputs.get("catalyst_context") if isinstance(inputs.get("catalyst_context"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    options_context = inputs.get("options_context") if isinstance(inputs.get("options_context"), dict) else {}
    filing_context = inputs.get("filing_context") if isinstance(inputs.get("filing_context"), dict) else {}
    earnings_transcript_context = inputs.get("earnings_transcript_context") if isinstance(inputs.get("earnings_transcript_context"), dict) else {}
    data_quality = inputs.get("data_quality") if isinstance(inputs.get("data_quality"), dict) else {}

    if not constraint_result.get("passed"):
        points.append("The setup does not currently pass objective constraints.")
    elif str(candidate.get("recommendation_status", "")).lower() == "watchlist":
        points.append("The setup is watchlist-only, not a final recommendation.")

    rs_label = str(relative_strength.get("relative_strength_label", "")).lower()
    if rs_label in {"underperforming", "market_laggard"}:
        points.append(f"Relative strength is {rs_label.replace('_', ' ')}.")

    regime_label = str(market_regime.get("regime", "")).lower()
    if regime_label in {"risk_off_downtrend", "high_volatility", "neutral_chop"}:
        points.append(f"Market regime is {regime_label.replace('_', ' ')}, which reduces trade quality.")

    catalyst_label = str(_catalyst_score_payload(catalyst_context).get("catalyst_label", "")).lower()
    if catalyst_label in {"negative", "high_risk"}:
        points.append(f"Catalyst context is {catalyst_label.replace('_', ' ')}.")

    ticker_history = statistical_context.get("ticker_history")
    if isinstance(ticker_history, dict) and str(ticker_history.get("historical_edge", "")).lower() == "negative":
        points.append("Ticker history shows a negative edge.")

    if isinstance(options_context, dict) and options_context.get("ok"):
        best_options = options_context.get("best_option_candidates", [])
        if isinstance(best_options, list) and best_options:
            top_option = best_options[0]
            if str(top_option.get("mispricing_label", "")).lower() in {"high_iv_risky", "cheap_but_low_probability", "overpriced"}:
                points.append(f"Top option alternative is labeled {str(top_option.get('mispricing_label')).replace('_', ' ')}.")

    filing_analysis = _filing_analysis_payload(filing_context)
    filing_risk_label = str(filing_analysis.get("filing_risk_label", "")).lower()
    if filing_risk_label == "high":
        points.append("Recent SEC filing risk is high.")
    elif filing_risk_label == "medium":
        points.append("Recent SEC filing risk is elevated.")
    negative_filing_signals = filing_analysis.get("negative_filing_signals", [])
    if isinstance(negative_filing_signals, list) and negative_filing_signals:
        points.append(f"SEC filing risk: {negative_filing_signals[0]}")

    earnings_quality = _earnings_quality_payload(earnings_transcript_context)
    earnings_label = str(earnings_quality.get("earnings_quality_label", "")).lower()
    if earnings_label == "weak":
        points.append("Recent earnings transcript quality is weak.")
    management_tone = str(earnings_quality.get("management_tone", "")).lower()
    if management_tone in {"cautious", "negative"}:
        points.append(f"Management tone was {management_tone}.")
    guidance_label = str(earnings_quality.get("guidance_label", "")).lower()
    if guidance_label == "lowered":
        points.append("Management lowered guidance in recent transcripts.")

    if data_quality.get("missing_sections"):
        points.append("Some research sections are unavailable.")
    if data_quality.get("stale_data_flags"):
        points.append("Some market data appears stale.")

    if len(points) >= 5:
        severity = "high"
    elif len(points) >= 3:
        severity = "medium"
    else:
        severity = "low"
    return {"points": points, "severity": severity}


def identify_key_risks(
    inputs: dict,
) -> dict:
    risks: list[str] = []
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    statistical_context = inputs.get("statistical_context") if isinstance(inputs.get("statistical_context"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    data_quality = inputs.get("data_quality") if isinstance(inputs.get("data_quality"), dict) else {}
    options_context = inputs.get("options_context") if isinstance(inputs.get("options_context"), dict) else {}
    filing_context = inputs.get("filing_context") if isinstance(inputs.get("filing_context"), dict) else {}
    earnings_transcript_context = inputs.get("earnings_transcript_context") if isinstance(inputs.get("earnings_transcript_context"), dict) else {}

    failed_constraints = candidate.get("failed_constraints", [])
    if isinstance(failed_constraints, list):
        risks.extend(f"Constraint risk: {item}" for item in failed_constraints if item)

    for section in (
        statistical_context.get("warnings", []),
        market_regime.get("risk_flags", []),
        relative_strength.get("risk_flags", []),
    ):
        if isinstance(section, list):
            risks.extend(str(item) for item in section if item)

    catalyst_payload = _catalyst_score_payload(inputs.get("catalyst_context") if isinstance(inputs.get("catalyst_context"), dict) else {})
    if isinstance(catalyst_payload, dict):
        for key in ("negative_catalysts", "risk_flags"):
            items = catalyst_payload.get(key, [])
            if isinstance(items, list):
                risks.extend(str(item) for item in items if item)

    filing_analysis = _filing_analysis_payload(filing_context)
    if isinstance(filing_analysis, dict):
        for key in ("risk_flags", "negative_filing_signals"):
            items = filing_analysis.get(key, [])
            if isinstance(items, list):
                risks.extend(f"Filing risk: {item}" for item in items if item)

    earnings_quality = _earnings_quality_payload(earnings_transcript_context)
    if isinstance(earnings_quality, dict):
        for key in ("risk_flags", "negative_signals"):
            items = earnings_quality.get(key, [])
            if isinstance(items, list):
                risks.extend(f"Transcript risk: {item}" for item in items if item)

    if isinstance(options_context, dict):
        for bucket_name in ("best_option_candidates", "watchlist_option_candidates", "rejected_option_candidates"):
            options = options_context.get(bucket_name, [])
            if not isinstance(options, list):
                continue
            for option in options[:1]:
                mispricing_context = option.get("mispricing_context", {})
                if isinstance(mispricing_context, dict):
                    warnings = mispricing_context.get("warnings", [])
                    if isinstance(warnings, list):
                        risks.extend(f"Option risk: {item}" for item in warnings if item)

    if isinstance(data_quality.get("missing_sections"), list):
        risks.extend(f"Missing section: {item}" for item in data_quality["missing_sections"] if item)
    if isinstance(data_quality.get("stale_data_flags"), list):
        risks.extend(str(item) for item in data_quality["stale_data_flags"] if item)

    deduped = list(dict.fromkeys(risks))
    return {"key_risks": deduped}


def generate_trade_thesis(
    inputs: dict,
) -> dict:
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    technical = inputs.get("technical_snapshot") if isinstance(inputs.get("technical_snapshot"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    conviction = inputs.get("research_conviction") if isinstance(inputs.get("research_conviction"), dict) else {}

    ticker = str(inputs.get("ticker", "")).upper()
    direction = str(candidate.get("direction", "long")).lower()
    setup_type = candidate.get("setup_type") or candidate.get("selected_profile") or candidate.get("scan_profile") or "unknown"
    current_price = _safe_float(technical.get("current_price"))
    stop_loss = _safe_float(candidate.get("stop_loss"))
    target_price = _safe_float(candidate.get("target_price"))
    rs_label = str(relative_strength.get("relative_strength_label", "unknown")).replace("_", " ")
    regime_label = str(market_regime.get("regime", "unknown")).replace("_", " ")

    thesis_parts = []
    if str(candidate.get("recommendation_status", "")).lower() == "recommendable":
        thesis_parts.append(f"{ticker} has a valid {setup_type} setup on the {direction} side.")
    elif str(candidate.get("recommendation_status", "")).lower() == "watchlist":
        thesis_parts.append(f"{ticker} has an interesting {setup_type} setup, but it remains watchlist-only.")
    else:
        thesis_parts.append(f"{ticker} has research value, but it does not currently qualify as a final trade.")

    if current_price is not None:
        thesis_parts.append(f"Price is around {round(current_price, 2)}.")
    if rs_label != "unknown":
        thesis_parts.append(f"Relative strength is {rs_label}.")
    if regime_label != "unknown":
        thesis_parts.append(f"Market regime is {regime_label}.")

    thesis = " ".join(thesis_parts)
    if stop_loss is not None:
        invalidation = f"The thesis weakens if price loses the stop area near {round(stop_loss, 2)}."
    else:
        invalidation = "The thesis weakens if the technical structure breaks down."

    if target_price is not None and current_price is not None:
        time_horizon = f"{DEFAULT_HOLDING_PERIOD_DAYS}-day swing window toward {round(target_price, 2)}."
    else:
        time_horizon = f"{DEFAULT_HOLDING_PERIOD_DAYS}-day swing timeframe."

    return {
        "direction": direction,
        "setup_type": setup_type,
        "thesis": thesis,
        "invalidation": invalidation,
        "time_horizon": time_horizon,
        "confidence_label": conviction.get("label", "low"),
    }


def score_research_conviction(
    inputs: dict,
) -> dict:
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    statistical_context = inputs.get("statistical_context") if isinstance(inputs.get("statistical_context"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    data_quality = inputs.get("data_quality") if isinstance(inputs.get("data_quality"), dict) else {}
    catalyst_payload = _catalyst_score_payload(inputs.get("catalyst_context") if isinstance(inputs.get("catalyst_context"), dict) else {})
    options_context = inputs.get("options_context") if isinstance(inputs.get("options_context"), dict) else {}
    filing_context = inputs.get("filing_context") if isinstance(inputs.get("filing_context"), dict) else {}
    earnings_transcript_context = inputs.get("earnings_transcript_context") if isinstance(inputs.get("earnings_transcript_context"), dict) else {}

    score = 50.0
    drivers: list[str] = []
    penalties: list[str] = []

    if candidate.get("passed"):
        score += 15.0
        drivers.append("Objective constraints passed.")
    status = str(candidate.get("recommendation_status", "")).lower()
    if status == "recommendable":
        score += 8.0
        drivers.append("Candidate is recommendable.")
    elif status == "watchlist":
        score -= 8.0
        penalties.append("Candidate is watchlist-only.")
    elif status == "rejected":
        score -= 20.0
        penalties.append("Candidate is rejected by current rules.")

    candidate_score = _safe_float(candidate.get("score"))
    if candidate_score is not None:
        score += max(min((candidate_score - 50.0) * 0.2, 10.0), -10.0)

    rr = _safe_float(candidate.get("risk_reward"))
    if rr is not None and rr >= 2.0:
        score += min(rr * 2.0, 6.0)
        drivers.append("Risk/reward is favorable.")

    setup_performance = statistical_context.get("setup_performance")
    if isinstance(setup_performance, dict) and setup_performance.get("meets_min_sample_size") and _safe_float(setup_performance.get("expectancy")) is not None:
        expectancy = _safe_float(setup_performance.get("expectancy")) or 0.0
        if expectancy > 0:
            score += min(expectancy * 100.0, 8.0)
            drivers.append("Setup history has positive expectancy.")
        elif expectancy < 0:
            score -= min(abs(expectancy) * 100.0, 8.0)
            penalties.append("Setup history has negative expectancy.")

    catalyst_score = _safe_float(catalyst_payload.get("catalyst_score"))
    catalyst_label = str(catalyst_payload.get("catalyst_label", "")).lower()
    if catalyst_score is not None:
        if catalyst_label in {"positive", "strong_positive"}:
            score += 6.0
            drivers.append("Catalyst context is supportive.")
        elif catalyst_label in {"negative", "high_risk"}:
            score -= 8.0
            penalties.append("Catalyst context is unfavorable.")

    regime_label = str(market_regime.get("regime", "")).lower()
    if regime_label == "risk_on_uptrend":
        score += 6.0
        drivers.append("Market regime is favorable.")
    elif regime_label in {"risk_off_downtrend", "high_volatility"}:
        score -= 10.0
        penalties.append("Market regime is unfavorable.")
    elif regime_label == "neutral_chop":
        score -= 4.0
        penalties.append("Market regime is choppy.")

    rs_label = str(relative_strength.get("relative_strength_label", "")).lower()
    if rs_label == "market_leader":
        score += 8.0
        drivers.append("Relative strength is market-leading.")
    elif rs_label == "outperforming":
        score += 5.0
        drivers.append("Relative strength is favorable.")
    elif rs_label == "underperforming":
        score -= 7.0
        penalties.append("Relative strength is underperforming.")
    elif rs_label == "market_laggard":
        score -= 10.0
        penalties.append("Relative strength is a market laggard.")

    filing_analysis = _filing_analysis_payload(filing_context)
    filing_risk_label = str(filing_analysis.get("filing_risk_label", "")).lower()
    filing_risk_score = _safe_float(filing_analysis.get("filing_risk_score"))
    if filing_risk_label == "low":
        score += 4.0
        drivers.append("Recent SEC filing risk is low.")
    elif filing_risk_label == "medium":
        score -= 6.0
        penalties.append("Recent SEC filing risk is elevated.")
    elif filing_risk_label == "high":
        score -= 14.0
        penalties.append("Recent SEC filing risk is high.")
    if filing_risk_score is not None and filing_risk_score >= 80:
        score -= 4.0

    earnings_quality = _earnings_quality_payload(earnings_transcript_context)
    earnings_quality_label = str(earnings_quality.get("earnings_quality_label", "")).lower()
    guidance_label = str(earnings_quality.get("guidance_label", "")).lower()
    management_tone = str(earnings_quality.get("management_tone", "")).lower()
    if earnings_quality_label == "strong":
        score += 7.0
        drivers.append("Recent earnings transcript quality is strong.")
    elif earnings_quality_label == "weak":
        score -= 10.0
        penalties.append("Recent earnings transcript quality is weak.")
    if guidance_label == "raised":
        score += 4.0
        drivers.append("Management raised guidance.")
    elif guidance_label == "lowered":
        score -= 8.0
        penalties.append("Management lowered guidance.")
    if management_tone in {"cautious", "negative"}:
        score -= 4.0
        penalties.append("Management tone is cautious or negative.")

    missing_sections = data_quality.get("missing_sections", [])
    stale_flags = data_quality.get("stale_data_flags", [])
    if isinstance(missing_sections, list):
        score -= min(len(missing_sections) * 3.0, 12.0)
        if missing_sections:
            penalties.append("Key research sections are missing.")
    if isinstance(stale_flags, list):
        score -= min(len(stale_flags) * 2.0, 8.0)
        if stale_flags:
            penalties.append("Some data is stale.")

    if isinstance(options_context, dict) and options_context.get("ok"):
        best_options = options_context.get("best_option_candidates", [])
        if isinstance(best_options, list) and best_options:
            label = str(best_options[0].get("mispricing_label", "")).lower()
            if label in {"high_iv_risky", "cheap_but_low_probability", "overpriced"}:
                score -= 4.0
                penalties.append("Best option alternative has elevated valuation or probability risk.")

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 75:
        label = "high"
    elif score >= 50:
        label = "medium"
    else:
        label = "low"
    return {"score": score, "label": label, "drivers": drivers, "penalties": penalties}


def build_evidence_table(
    inputs: dict,
) -> dict:
    rows: list[dict] = []
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    constraint_result = inputs.get("constraint_result") if isinstance(inputs.get("constraint_result"), dict) else {}
    statistical_context = inputs.get("statistical_context") if isinstance(inputs.get("statistical_context"), dict) else {}
    catalyst_context = inputs.get("catalyst_context") if isinstance(inputs.get("catalyst_context"), dict) else {}
    market_regime = inputs.get("market_regime") if isinstance(inputs.get("market_regime"), dict) else {}
    relative_strength = inputs.get("relative_strength") if isinstance(inputs.get("relative_strength"), dict) else {}
    options_context = inputs.get("options_context") if isinstance(inputs.get("options_context"), dict) else {}
    filing_context = inputs.get("filing_context") if isinstance(inputs.get("filing_context"), dict) else {}
    earnings_transcript_context = inputs.get("earnings_transcript_context") if isinstance(inputs.get("earnings_transcript_context"), dict) else {}
    requested_sections = inputs.get("requested_sections", [])
    if not isinstance(requested_sections, list):
        requested_sections = []

    if constraint_result:
        rows.append(
            {
                "category": "technical",
                "claim": "Technical setup passed objective constraints" if constraint_result.get("passed") else "Technical setup did not pass objective constraints",
                "evidence": f"status={candidate.get('recommendation_status')}, score={candidate.get('score')}, risk_reward={candidate.get('risk_reward')}",
                "confidence": "high" if constraint_result.get("passed") else "medium",
                "source": "system",
            }
        )
    else:
        rows.append(
            {
                "category": "technical",
                "claim": "Technical constraint evidence unavailable",
                "evidence": "Candidate details or constraint results are unavailable.",
                "confidence": "low",
                "source": "unavailable",
            }
        )

    setup_performance = statistical_context.get("setup_performance")
    if isinstance(setup_performance, dict):
        rows.append(
            {
                "category": "statistical",
                "claim": "Setup history is available",
                "evidence": f"expectancy={setup_performance.get('expectancy')}, sample_size={setup_performance.get('sample_size')}",
                "confidence": str(setup_performance.get("confidence_label", "medium")),
                "source": "sqlite",
            }
        )
    else:
        rows.append(
            {
                "category": "statistical",
                "claim": "Setup history unavailable",
                "evidence": "No matching setup statistics were found.",
                "confidence": "low",
                "source": "unavailable",
            }
        )

    if "catalyst_context" in requested_sections:
        catalyst_score = _catalyst_score_payload(catalyst_context)
        if isinstance(catalyst_score, dict) and catalyst_score:
            rows.append(
                {
                    "category": "catalyst",
                    "claim": f"Catalyst score is {catalyst_score.get('catalyst_label', 'unknown')}",
                    "evidence": catalyst_score.get("summary", "Catalyst score available."),
                    "confidence": "medium" if catalyst_context.get("ok") else "low",
                    "source": catalyst_context.get("source", "fmp") if catalyst_context.get("ok") else "unavailable",
                }
            )
        else:
            rows.append(
                {
                    "category": "catalyst",
                    "claim": "Catalyst context unavailable",
                    "evidence": "No catalyst score is available.",
                    "confidence": "low",
                    "source": "unavailable",
                }
            )

    if "market_regime" in requested_sections and market_regime:
        rows.append(
            {
                "category": "regime",
                "claim": f"Market regime is {str(market_regime.get('regime', 'unknown')).replace('_', ' ')}",
                "evidence": market_regime.get("summary", "Market regime snapshot available."),
                "confidence": market_regime.get("confidence_label", "medium"),
                "source": "system" if market_regime.get("ok") else "unavailable",
            }
        )
    elif "market_regime" in requested_sections:
        rows.append(
            {
                "category": "regime",
                "claim": "Market regime unavailable",
                "evidence": "No market regime snapshot is available.",
                "confidence": "low",
                "source": "unavailable",
            }
        )

    if "relative_strength" in requested_sections and relative_strength:
        rows.append(
            {
                "category": "relative_strength",
                "claim": f"Relative strength is {str(relative_strength.get('relative_strength_label', 'unknown')).replace('_', ' ')}",
                "evidence": relative_strength.get("summary", "Relative strength snapshot available."),
                "confidence": "medium" if relative_strength.get("ok") else "low",
                "source": "market_data" if relative_strength.get("ok") else "unavailable",
            }
        )
    elif "relative_strength" in requested_sections:
        rows.append(
            {
                "category": "relative_strength",
                "claim": "Relative strength unavailable",
                "evidence": "Relative strength comparison was not available.",
                "confidence": "low",
                "source": "unavailable",
            }
        )

    if "options_context" in requested_sections:
        best_options = options_context.get("best_option_candidates", [])
        if isinstance(best_options, list) and best_options:
            option = best_options[0]
            rows.append(
                {
                    "category": "options",
                    "claim": f"Option alternative is {str(option.get('mispricing_label', 'unknown')).replace('_', ' ')}",
                    "evidence": option.get("mispricing_context", {}).get("explanation", "Option alternative available."),
                    "confidence": "medium",
                    "source": "system",
                }
            )
        else:
            rows.append(
                {
                    "category": "options",
                    "claim": "Option alternative unavailable",
                    "evidence": options_context.get("summary", {}).get("message", "No option alternative was available.") if isinstance(options_context, dict) else "No option alternative was available.",
                    "confidence": "low",
                    "source": "unavailable" if not isinstance(options_context, dict) or not options_context.get("ok") else "system",
                }
            )

    if "filing_context" in requested_sections:
        filing_analysis = _filing_analysis_payload(filing_context)
        if filing_analysis:
            rows.append(
                {
                    "category": "sec_filings",
                    "claim": f"SEC filing risk is {filing_analysis.get('filing_risk_label', 'unavailable')}",
                    "evidence": filing_analysis.get("summary", "SEC filing analysis is available."),
                    "confidence": "medium" if filing_context.get("ok") else "low",
                    "source": filing_context.get("source", "fmp") if filing_context.get("ok") else "unavailable",
                }
            )
        else:
            rows.append(
                {
                    "category": "sec_filings",
                    "claim": "SEC filing context unavailable",
                    "evidence": "No SEC filing analysis was available.",
                    "confidence": "low",
                    "source": "unavailable",
                }
            )

    if "earnings_transcript_context" in requested_sections:
        earnings_quality = _earnings_quality_payload(earnings_transcript_context)
        if earnings_quality:
            rows.append(
                {
                    "category": "earnings_transcript",
                    "claim": f"Earnings transcript quality is {earnings_quality.get('earnings_quality_label', 'unavailable')}",
                    "evidence": earnings_quality.get("summary", "Earnings transcript analysis is available."),
                    "confidence": "medium" if earnings_transcript_context.get("ok") else "low",
                    "source": earnings_transcript_context.get("source", "fmp") if earnings_transcript_context.get("ok") else "unavailable",
                }
            )
        else:
            rows.append(
                {
                    "category": "earnings_transcript",
                    "claim": "Earnings transcript context unavailable",
                    "evidence": "No earnings transcript analysis was available.",
                    "confidence": "low",
                    "source": "unavailable",
                }
            )

    risk_items = identify_key_risks(inputs).get("key_risks", [])
    if risk_items:
        rows.append(
            {
                "category": "risk",
                "claim": "Key risk factors are present",
                "evidence": risk_items[0],
                "confidence": "medium",
                "source": "system",
            }
        )
    else:
        rows.append(
            {
                "category": "risk",
                "claim": "No major consolidated risk flags",
                "evidence": "No high-priority risk flags were consolidated from the available inputs.",
                "confidence": "low",
                "source": "system",
            }
        )

    return {"evidence_table": rows}


def build_research_brief(
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
    normalized_ticker = str(ticker or "").strip().upper()
    timestamp = _now_iso()
    requested_sections = _requested_context_keys(
        include_market_regime=include_market_regime,
        include_relative_strength=include_relative_strength,
        include_catalysts=include_catalysts,
        include_statistics=include_statistics,
        include_options=include_options,
        include_sec_filings=include_sec_filings,
        include_earnings_transcripts=include_earnings_transcripts,
        include_memory_context=include_memory_context,
    )

    candidate_details = _candidate_details(normalized_ticker, db_path=db_path)
    market_snapshot = candidate_details.get("market_snapshot") if isinstance(candidate_details, dict) else get_market_snapshot(normalized_ticker, lookback_days=180)
    candidate = candidate_details.get("candidate") if isinstance(candidate_details, dict) else None
    constraint_result = candidate_details.get("constraint_result") if isinstance(candidate_details, dict) else None
    trade_levels = candidate_details.get("trade_levels") if isinstance(candidate_details, dict) else None

    statistical_context = candidate.get("statistical_context") if isinstance(candidate, dict) and include_statistics else None
    if include_statistics and not isinstance(statistical_context, dict):
        statistical_context = {"ticker_history": analyze_ticker_history(normalized_ticker, db_path=db_path)}

    catalyst_context = get_catalyst_snapshot(normalized_ticker, lookback_days=7) if include_catalysts else None
    market_regime = get_market_regime_snapshot(include_breadth=True, db_path=db_path) if include_market_regime else None
    sector = None
    if isinstance(candidate, dict):
        sector = candidate.get("sector") or candidate.get("industry_sector")
    relative_strength = get_relative_strength_snapshot(normalized_ticker, sector=sector if isinstance(sector, str) else None, include_sector=include_relative_strength, db_path=db_path) if include_relative_strength else None
    filing_context = get_sec_filing_snapshot(normalized_ticker, lookback_days=120) if include_sec_filings else None
    earnings_transcript_context = get_earnings_transcript_snapshot(normalized_ticker, lookback_quarters=2) if include_earnings_transcripts else None
    options_context = scan_options_for_stock_candidate(candidate, max_contracts=3) if include_options and isinstance(candidate, dict) else None
    memory_context = find_similar_setups(candidate or {"ticker": normalized_ticker}, top_k=5) if include_memory_context else None

    if include_catalysts and isinstance(catalyst_context, dict) and isinstance(catalyst_context.get("data"), dict):
        combined_catalyst_score = score_catalyst_strength(
            news_snapshot=catalyst_context["data"].get("news_snapshot"),
            earnings_snapshot=catalyst_context["data"].get("earnings_snapshot"),
            market_snapshot=market_snapshot if isinstance(market_snapshot, dict) else None,
            filing_context=filing_context,
            earnings_transcript_context=earnings_transcript_context,
        )
        catalyst_context = {
            **catalyst_context,
            "data": {
                **catalyst_context["data"],
                "catalyst_score": combined_catalyst_score,
            },
        }

    freshness = None
    if isinstance(market_snapshot, dict) and isinstance(market_snapshot.get("data"), dict):
        freshness = market_snapshot["data"].get("data_freshness")
    stale_flags: list[str] = []
    if isinstance(freshness, dict) and freshness.get("is_stale"):
        stale_flags.append(f"Market data freshness is {freshness.get('freshness_label')}.")
    if isinstance(market_snapshot, dict) and market_snapshot.get("quote_error"):
        stale_flags.append(str(market_snapshot.get("quote_error")))

    raw_context = {
        "market_snapshot": market_snapshot,
        "candidate_details": candidate_details,
        "statistical_context": statistical_context,
        "catalyst_context": catalyst_context,
        "market_regime": market_regime,
        "relative_strength": relative_strength,
        "filing_context": filing_context,
        "earnings_transcript_context": earnings_transcript_context,
        "options_context": options_context,
        "memory_context": memory_context,
    }
    missing_sections = _missing_sections(raw_context, requested_sections)
    data_quality = {
        "missing_sections": missing_sections,
        "stale_data_flags": stale_flags,
        "requested_sections": requested_sections,
        "source_count": sum(
            1
            for item in (
                market_snapshot,
                candidate_details,
                statistical_context,
                catalyst_context,
                market_regime,
                relative_strength,
                filing_context,
                earnings_transcript_context,
                options_context,
                memory_context,
            )
            if item is not None
        ),
        "confidence_warning": "Research brief is using partial data." if missing_sections or stale_flags else "",
    }
    if include_memory_context and isinstance(memory_context, dict) and not memory_context.get("ok"):
        data_quality.setdefault("memory_warning", memory_context.get("error") or "Semantic memory is unavailable.")

    inputs = {
        "ticker": normalized_ticker,
        "candidate": candidate or {},
        "constraint_result": constraint_result or {},
        "trade_levels": trade_levels or {},
        "technical_snapshot": (market_snapshot.get("data", {}).get("technical_snapshot", {}) if isinstance(market_snapshot, dict) and isinstance(market_snapshot.get("data"), dict) else {}),
        "statistical_context": statistical_context or {},
        "catalyst_context": catalyst_context or {},
        "market_regime": market_regime or {},
        "relative_strength": relative_strength or {},
        "filing_context": filing_context or {},
        "earnings_transcript_context": earnings_transcript_context or {},
        "options_context": options_context or {},
        "memory_context": memory_context or {},
        "data_quality": data_quality,
        "requested_sections": requested_sections,
    }

    bull_case = summarize_bull_case(inputs)
    bear_case = summarize_bear_case(inputs)
    key_risks = identify_key_risks(inputs).get("key_risks", [])
    evidence_table = build_evidence_table(inputs).get("evidence_table", [])
    research_conviction = score_research_conviction(inputs)
    inputs["research_conviction"] = research_conviction
    trade_thesis = generate_trade_thesis(inputs)

    research_summary = (
        f"{normalized_ticker} research brief: {trade_thesis['thesis']} "
        f"Conviction is {research_conviction['label']} ({research_conviction['score']})."
    )

    ok = any(
        item is not None and (not isinstance(item, dict) or item.get("ok", True))
        for item in (market_snapshot, candidate_details, statistical_context, catalyst_context, market_regime, relative_strength, filing_context, earnings_transcript_context)
    )

    return {
        "ok": bool(ok),
        "timestamp": timestamp,
        "ticker": normalized_ticker,
        "brief_type": "deep_research",
        "research_summary": research_summary,
        "trade_thesis": trade_thesis,
        "bull_case": bull_case,
        "bear_case": bear_case,
        "key_risks": key_risks,
        "evidence_table": evidence_table,
        "research_conviction": research_conviction,
        "data_quality": data_quality,
        "raw_context": raw_context,
        "error": None if ok else "No research inputs were available.",
    }
