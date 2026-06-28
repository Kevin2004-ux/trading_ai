from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
import sqlite3

from analytics.timeframe_confirmation import evaluate_timeframe_confirmation
from analytics.volume_profile import evaluate_volume_profile_confirmation
from engine.constraint_engine import evaluate_stock_constraints
from features import (
    build_core_market_feature_provenance,
    provenance_warning_messages,
    summarize_feature_provenance,
)
from pipeline.async_scanner import run_async_scan_tickers
from quality.data_quality import build_data_quality_summary, validate_market_data_quality
from realtime.market_data import get_market_snapshot
from research.earnings_8k_analyzer import analyze_earnings_8k
from research.filing_analyzer import analyze_recent_filings
from research.filing_sentiment import evaluate_filing_sentiment
from research.news_provider import fetch_recent_news
from research.news_sentiment import evaluate_news_sentiment
from research.sec_edgar_provider import fetch_filing_text, fetch_recent_filings
from research.short_interest import evaluate_borrow_pressure, evaluate_short_interest
from scanner.scan_profiles import get_default_scan_profiles, get_scan_profile
from tracking.trade_logger import init_trade_tracking_db, log_candidate_evaluation, log_scanner_run


DEFAULT_SCANNER_CONFIG = {
    "direction": "long",
    "asset_type": "stock",
    "stop_atr_multiplier": 1.5,
    "target_atr_multiplier": 3.0,
    "high_20_rr_threshold": 2.0,
    "momentum_breakout_threshold": 0.99,
    "trend_pullback_distance_percent": 0.02,
    "constraint_config": None,
    "sec_research_enabled": None,
    "short_interest_enabled": None,
    "news_research_enabled": None,
}
STATUS_PRIORITY = {"recommendable": 2, "watchlist": 1, "rejected": 0}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_config(config: dict | None = None) -> dict:
    merged = deepcopy(DEFAULT_SCANNER_CONFIG)
    if config:
        merged.update(config)
    return merged


def _safe_float(value):
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _intent_constraints_from_config(config: dict | None = None) -> dict:
    if not isinstance(config, dict):
        return {}
    intent = config.get("intent_constraints")
    if isinstance(intent, dict):
        return intent
    return {}


def _price_bounds_from_config(config: dict | None = None) -> tuple[float | None, float | None]:
    intent = _intent_constraints_from_config(config)
    soft = config.get("soft_scanner_preferences") if isinstance(config, dict) and isinstance(config.get("soft_scanner_preferences"), dict) else {}
    min_price = _safe_float(intent.get("min_stock_price") if intent.get("min_stock_price") is not None else soft.get("min_stock_price"))
    max_price = _safe_float(intent.get("max_stock_price") if intent.get("max_stock_price") is not None else soft.get("max_stock_price"))
    return min_price, max_price


def _apply_request_price_bounds(candidate: dict, config: dict | None = None) -> tuple[dict, bool]:
    min_price, max_price = _price_bounds_from_config(config)
    if min_price is None and max_price is None:
        return candidate, True
    current_price = _safe_float(candidate.get("current_price"))
    if current_price is None:
        return candidate, True
    failed = []
    if min_price is not None and current_price < min_price:
        failed.append("min_stock_price")
    if max_price is not None and current_price > max_price:
        failed.append("max_stock_price")
    if not failed:
        return candidate, True

    rejected = deepcopy(candidate)
    rejected["recommendation_status"] = "rejected"
    rejected["failed_constraints"] = list(dict.fromkeys(list(rejected.get("failed_constraints") or []) + failed))
    reasons = []
    if "min_stock_price" in failed:
        reasons.append(f"Current price {current_price:.2f} is below requested min stock price {min_price:.2f}.")
    if "max_stock_price" in failed:
        reasons.append(f"Current price {current_price:.2f} is above requested max stock price {max_price:.2f}.")
    rejected["rejection_reason"] = "; ".join(reasons)
    rejected["passed"] = False
    return rejected, False


def _quality_bucket(candidate: dict) -> str:
    status = str(candidate.get("recommendation_status", "rejected")).lower()
    score = _safe_float(candidate.get("score")) or 0.0
    if status == "rejected":
        return "rejected"
    if status == "watchlist":
        return "watchlist"
    if score >= 95:
        return "A+"
    if score >= 88:
        return "A"
    return "B"


def _profile_rank_candidates(candidates: list[dict]) -> list[dict]:
    ranked = [deepcopy(candidate) for candidate in candidates]
    ranked.sort(
        key=lambda candidate: (
            STATUS_PRIORITY.get(str(candidate.get("recommendation_status", "rejected")).lower(), 0),
            _safe_float(candidate.get("score")) or 0.0,
            _safe_float(candidate.get("risk_reward")) or 0.0,
            _safe_float(candidate.get("relative_volume")) or 0.0,
        ),
        reverse=True,
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate["rank"] = index
    return ranked


def _profile_summary_label(candidates: list[dict]) -> str | None:
    labels = []
    for candidate in candidates:
        freshness = candidate.get("data_freshness", {})
        if isinstance(freshness, dict) and freshness.get("freshness_label"):
            labels.append(freshness["freshness_label"])
    if not labels:
        return None
    return ",".join(sorted(set(labels)))


def _preference_score(profile_name: str, candidate: dict, profile: dict) -> tuple[float, list[str]]:
    technical = candidate.get("technical_snapshot", {}) if isinstance(candidate.get("technical_snapshot"), dict) else {}
    prefs = profile.get("strategy_preferences", {})
    current_price = _safe_float(candidate.get("current_price"))
    sma_20 = _safe_float(candidate.get("sma_20"))
    sma_50 = _safe_float(candidate.get("sma_50"))
    high_20 = _safe_float(technical.get("high_20"))
    relative_volume = _safe_float(candidate.get("relative_volume"))
    rsi_14 = _safe_float(technical.get("rsi_14"))
    daily_return = _safe_float(technical.get("daily_return"))
    atr_percent = _safe_float(candidate.get("atr_percent"))

    score = 0.0
    reasons: list[str] = []

    if profile_name == "momentum_breakout":
        if current_price is not None and sma_20 is not None and current_price > sma_20:
            score += 20
            reasons.append("Price is above SMA 20.")
        if current_price is not None and sma_50 is not None and current_price > sma_50:
            score += 20
            reasons.append("Price is above SMA 50.")
        target_rv = _safe_float(prefs.get("relative_volume_target")) or 1.8
        if relative_volume is not None:
            score += min(25.0, (relative_volume / target_rv) * 25.0)
            if relative_volume >= 1.2:
                reasons.append("Relative volume confirms breakout participation.")
        proximity = _safe_float(prefs.get("high_20_proximity_percent")) or 0.015
        if current_price is not None and high_20 not in (None, 0):
            gap = abs(high_20 - current_price) / high_20
            if current_price >= high_20 or gap <= proximity:
                score += 25
                reasons.append("Price is near or above the 20-day high.")
        if daily_return is not None and daily_return >= 1.0:
            score += 10
            reasons.append("Daily return is supportive.")

    elif profile_name == "trend_pullback":
        if current_price is not None and sma_50 is not None and current_price > sma_50:
            score += 25
            reasons.append("Price remains above SMA 50.")
        distance_target = _safe_float(prefs.get("pullback_to_sma20_distance_percent")) or 0.025
        if current_price is not None and sma_20 not in (None, 0):
            distance = abs(current_price - sma_20) / sma_20
            score += max(0.0, 30.0 * (1.0 - min(distance / max(distance_target, 1e-9), 1.0)))
            if distance <= distance_target:
                reasons.append("Price is near SMA 20 support.")
        target_rv = _safe_float(prefs.get("relative_volume_target")) or 1.15
        if relative_volume is not None:
            score += min(20.0, (relative_volume / target_rv) * 20.0)
        if daily_return is not None and daily_return > -1.0:
            score += 10
            reasons.append("Daily return suggests orderly pullback behavior.")
        if current_price is not None and sma_20 is not None and current_price >= sma_20:
            score += 15
            reasons.append("Price is holding or reclaiming SMA 20.")

    elif profile_name == "oversold_reversal":
        threshold = _safe_float(prefs.get("oversold_rsi_threshold")) or 38
        if rsi_14 is not None:
            if rsi_14 <= threshold:
                score += 30
                reasons.append("RSI is in an oversold or recovery zone.")
            elif rsi_14 <= threshold + 7:
                score += 15
        if current_price is not None and sma_20 is not None and current_price >= sma_20:
            score += 25
            reasons.append("Price is reclaiming SMA 20.")
        elif daily_return is not None and daily_return > 0:
            score += 15
            reasons.append("Positive daily return supports a reversal attempt.")
        if relative_volume is not None:
            score += min(20.0, (relative_volume / ((_safe_float(prefs.get("relative_volume_target")) or 1.1))) * 20.0)
        if atr_percent is not None and atr_percent <= 6.0:
            score += 15
            reasons.append("Volatility is elevated but not extreme.")
        if daily_return is not None and daily_return >= 0.5:
            score += 10

    elif profile_name == "relative_strength":
        if current_price is not None and sma_20 is not None and current_price > sma_20:
            score += 18
            reasons.append("Price is above SMA 20.")
        if current_price is not None and sma_50 is not None and current_price > sma_50:
            score += 18
            reasons.append("Price is above SMA 50.")
        target_rv = _safe_float(prefs.get("relative_volume_target")) or 1.7
        if relative_volume is not None:
            score += min(24.0, (relative_volume / target_rv) * 24.0)
            if relative_volume >= 1.3:
                reasons.append("Relative volume supports leadership.")
        if daily_return is not None:
            score += max(0.0, min(20.0, daily_return / 2.0 * 20.0))
            if daily_return >= 1.2:
                reasons.append("Daily return reflects relative strength.")
        if current_price is not None and sma_50 not in (None, 0):
            distance = (current_price - sma_50) / sma_50
            if distance >= 0.03:
                score += 20
                reasons.append("Price has strong separation from SMA 50.")

    elif profile_name == "catalyst_watch":
        avg_vol = _safe_float(candidate.get("average_volume_20"))
        if avg_vol is not None and avg_vol >= 1_500_000:
            score += 25
            reasons.append("Liquidity is strong enough for catalyst monitoring.")
        if relative_volume is not None:
            score += min(20.0, (relative_volume / ((_safe_float(prefs.get("relative_volume_target")) or 1.1))) * 20.0)
            if relative_volume >= 1.0:
                reasons.append("Relative volume is supportive.")
        if atr_percent is not None and 1.5 <= atr_percent <= 8.0:
            score += 20
            reasons.append("Volatility is tradable for a catalyst watchlist.")
        if daily_return is not None and abs(daily_return) >= 0.5:
            score += 15
            reasons.append("Recent price movement suggests catalyst potential.")
        if current_price is not None and sma_50 is not None and current_price > sma_50:
            score += 20
            reasons.append("Underlying trend is constructive.")

    return min(score, 100.0), reasons


def _finalize_profile_candidate(candidate: dict, base_result: dict, profile: dict) -> dict:
    profile_name = profile["name"]
    preference_score, reasons = _preference_score(profile_name, candidate, profile)
    base_score = _safe_float(base_result.get("score")) or 0.0
    final_score = round((base_score * 0.55) + (preference_score * 0.45), 2)
    status = "rejected"
    if base_result.get("passed"):
        if final_score >= profile.get("minimum_score_to_recommend", 80):
            status = "recommendable"
        elif final_score >= profile.get("minimum_score_to_watchlist", 65):
            status = "watchlist"
        else:
            status = "rejected"

    candidate["score"] = final_score
    candidate["scan_profile"] = profile_name
    candidate["profile_description"] = profile.get("description")
    candidate["recommendation_status"] = status
    candidate["constraint_results"] = base_result["constraint_results"]
    candidate["failed_constraints"] = base_result["failed_constraints"] if status == "rejected" else []
    candidate["rejection_reason"] = base_result["rejection_reason"] if status == "rejected" else ""
    candidate["why_this_profile_matched"] = reasons
    candidate["quality_bucket"] = _quality_bucket(candidate)
    candidate["passed"] = status != "rejected"
    candidate["selected_profile"] = profile_name
    candidate["duplicate_reason"] = None
    return candidate


def _history_from_snapshot(market_snapshot: dict) -> list[dict]:
    data = market_snapshot.get("data", {}) if isinstance(market_snapshot, dict) else {}
    bars = data.get("bars") if isinstance(data, dict) else None
    return [bar for bar in bars if isinstance(bar, dict)] if isinstance(bars, list) else []


def _apply_technical_confirmations(candidate: dict, market_snapshot: dict, config: dict | None = None) -> dict:
    enriched = deepcopy(candidate)
    daily_history = _history_from_snapshot(market_snapshot)
    volume_confirmation = evaluate_volume_profile_confirmation(enriched, daily_history, config=config)
    timeframe_confirmation = evaluate_timeframe_confirmation(enriched, daily_history, weekly_history=None, config=config)

    score_adjustment = (_safe_float(volume_confirmation.get("score_adjustment")) or 0.0) + (
        _safe_float(timeframe_confirmation.get("score_adjustment")) or 0.0
    )
    risk_multiplier = _safe_float(timeframe_confirmation.get("risk_multiplier"))
    if risk_multiplier is None:
        risk_multiplier = 1.0

    warnings = []
    warnings.extend(str(item) for item in volume_confirmation.get("warnings", []) if item)
    warnings.extend(str(item) for item in timeframe_confirmation.get("warnings", []) if item)
    reasons = []
    reasons.extend(str(item) for item in volume_confirmation.get("reasons", []) if item)
    reasons.extend(str(item) for item in timeframe_confirmation.get("reasons", []) if item)

    status = "confirmed"
    if volume_confirmation.get("confirmation_status") == "rejected" or timeframe_confirmation.get("confirmation_status") == "rejected":
        status = "rejected"
    elif volume_confirmation.get("confirmation_status") == "warning" or timeframe_confirmation.get("confirmation_status") == "warning":
        status = "warning"
    elif volume_confirmation.get("confirmation_status") == "neutral" or timeframe_confirmation.get("confirmation_status") == "neutral":
        status = "neutral"

    enriched["volume_profile_confirmation"] = volume_confirmation
    enriched["timeframe_confirmation"] = timeframe_confirmation
    enriched["technical_confirmation_summary"] = {
        "status": status,
        "score_adjustment": round(score_adjustment, 2),
        "risk_multiplier": round(risk_multiplier, 4),
        "warnings": warnings,
        "reasons": reasons,
    }
    enriched["score"] = max(round((_safe_float(enriched.get("score")) or 0.0) + score_adjustment, 2), 0.0)

    if status == "rejected":
        enriched["recommendation_status"] = "rejected"
        enriched["passed"] = False
        enriched["failed_constraints"] = list(enriched.get("failed_constraints", [])) + ["technical_confirmation_rejected"]
        enriched["rejection_reason"] = "; ".join(reasons or ["Rejected by technical confirmation."])
    elif status == "warning" and enriched.get("recommendation_status") == "recommendable":
        enriched["recommendation_status"] = "watchlist"
        enriched["passed"] = True
        enriched["downgrade_reason"] = "; ".join(reasons or ["Technical confirmation warning."])
    enriched["quality_bucket"] = _quality_bucket(enriched)
    return enriched


def _boolish(value, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _sec_research_enabled(config: dict | None = None) -> bool:
    if isinstance(config, dict) and config.get("sec_research_enabled") is not None:
        return _boolish(config.get("sec_research_enabled"))
    return _boolish(os.getenv("SEC_RESEARCH_ENABLED") or os.getenv("ENABLE_SEC_RESEARCH"), default=False)


def _short_interest_enabled(config: dict | None = None) -> bool:
    if isinstance(config, dict) and config.get("short_interest_enabled") is not None:
        return _boolish(config.get("short_interest_enabled"), default=True)
    return _boolish(os.getenv("SHORT_INTEREST_ENABLED"), default=True)


def _news_research_enabled(config: dict | None = None) -> bool:
    if isinstance(config, dict) and config.get("news_research_enabled") is not None:
        return _boolish(config.get("news_research_enabled"))
    return _boolish(os.getenv("NEWS_RESEARCH_ENABLED"), default=False)


def _apply_filing_research(candidate: dict, config: dict | None = None) -> dict:
    enriched = deepcopy(candidate)
    ticker = str(enriched.get("ticker", "")).upper()
    if not _sec_research_enabled(config):
        enriched["filing_sentiment"] = {
            "ok": True,
            "ticker": ticker,
            "sentiment_label": "unknown",
            "filing_risk_level": "unknown",
            "trade_impact": "unknown",
            "risk_multiplier": 1.0,
            "score_adjustment": 0.0,
            "reasons": ["SEC research is disabled."],
            "warnings": [],
            "enabled": False,
        }
        return enriched

    recent = fetch_recent_filings(ticker, forms=["8-K", "10-Q", "10-K"], limit=10, config={"SEC_RESEARCH_ENABLED": "true"})
    if not recent.get("ok"):
        analysis = {
            "ok": True,
            "ticker": ticker,
            "filing_risk_level": "unknown",
            "recent_filings": [],
            "material_events": [],
            "risk_flags": [],
            "positive_flags": [],
            "warnings": recent.get("warnings", []) or ["SEC filings are unavailable."],
            "errors": recent.get("errors", []),
        }
        enriched["filing_analysis"] = analysis
        enriched["earnings_8k_analysis"] = None
        enriched["filing_sentiment"] = evaluate_filing_sentiment(ticker, analysis)
        return enriched

    filings = recent.get("filings", [])
    analysis = analyze_recent_filings(ticker, filings)
    earnings_analysis = None
    earnings_filing = next(
        (
            filing for filing in filings
            if str(filing.get("form", "")).upper() == "8-K"
            and ("2.02" in " ".join(filing.get("items", [])) or "earnings" in str(filing.get("description", "")).lower())
        ),
        None,
    )
    if isinstance(earnings_filing, dict):
        text_result = fetch_filing_text(earnings_filing.get("filing_url"), config={"SEC_RESEARCH_ENABLED": "true"}) if earnings_filing.get("filing_url") else {"ok": False}
        filing_text = text_result.get("text") if isinstance(text_result, dict) and text_result.get("ok") else earnings_filing.get("description", "")
        earnings_analysis = analyze_earnings_8k(ticker, earnings_filing, filing_text)
    sentiment = evaluate_filing_sentiment(ticker, analysis, earnings_analysis)
    enriched["filing_analysis"] = analysis
    enriched["earnings_8k_analysis"] = earnings_analysis
    enriched["filing_sentiment"] = sentiment
    enriched["score"] = max(0.0, round((_safe_float(enriched.get("score")) or 0.0) + (_safe_float(sentiment.get("score_adjustment")) or 0.0), 2))
    if str(sentiment.get("trade_impact", "")).lower() == "blocking":
        enriched["recommendation_status"] = "rejected"
        enriched["passed"] = False
        enriched["failed_constraints"] = list(enriched.get("failed_constraints", [])) + ["critical_filing_risk"]
        enriched["rejection_reason"] = "; ".join(sentiment.get("reasons", []) or ["Critical filing risk blocks candidate."])
    elif str(sentiment.get("filing_risk_level", "")).lower() == "high" and enriched.get("recommendation_status") == "recommendable":
        enriched["recommendation_status"] = "watchlist"
        enriched["downgrade_reason"] = "; ".join(sentiment.get("reasons", []) or ["High filing risk."])
    enriched["quality_bucket"] = _quality_bucket(enriched)
    return enriched


def _apply_short_news_research(candidate: dict, market_snapshot: dict | None = None, config: dict | None = None) -> dict:
    enriched = deepcopy(candidate)
    ticker = str(enriched.get("ticker", "")).upper()
    short_data = config.get("short_data") if isinstance(config, dict) and isinstance(config.get("short_data"), dict) else None
    if isinstance(short_data, dict) and isinstance(short_data.get(ticker), dict):
        short_data = short_data[ticker]
    borrow_data = config.get("borrow_data") if isinstance(config, dict) and isinstance(config.get("borrow_data"), dict) else None
    if isinstance(borrow_data, dict) and isinstance(borrow_data.get(ticker), dict):
        borrow_data = borrow_data[ticker]

    if _short_interest_enabled(config):
        short_context = evaluate_short_interest(
            ticker,
            short_data=short_data,
            market_snapshot=market_snapshot or enriched.get("technical_snapshot"),
            config={"direction": enriched.get("direction"), "setup_type": enriched.get("setup_type")},
        )
        borrow_context = evaluate_borrow_pressure(ticker, borrow_data=borrow_data)
    else:
        short_context = evaluate_short_interest(ticker, short_data=None, market_snapshot=None)
        short_context["warnings"] = ["Short-interest research is disabled."]
        short_context["short_interest_level"] = "unknown"
        short_context["squeeze_risk"] = "unknown"
        borrow_context = evaluate_borrow_pressure(ticker, borrow_data=None)
        borrow_context["warnings"] = ["Borrow-pressure research is disabled."]
    enriched["short_interest"] = short_context
    enriched["borrow_pressure"] = borrow_context

    if _news_research_enabled(config):
        news_result = fetch_recent_news(ticker, limit=10, config={"NEWS_RESEARCH_ENABLED": "true", **(config or {})})
        articles = news_result.get("articles", []) if isinstance(news_result, dict) else []
        news_context = evaluate_news_sentiment(ticker, articles)
        news_context["provider_result"] = news_result
    else:
        news_context = evaluate_news_sentiment(ticker, [])
        news_context["warnings"] = ["News research is disabled."]
        news_context["enabled"] = False
    enriched["news_sentiment"] = news_context

    for context in (short_context, news_context):
        enriched["score"] = max(0.0, round((_safe_float(enriched.get("score")) or 0.0) + (_safe_float(context.get("score_adjustment")) or 0.0), 2))

    direction = str(enriched.get("direction", "long")).lower()
    if direction == "short" and isinstance(borrow_context, dict) and not borrow_context.get("short_trade_allowed", True):
        enriched["recommendation_status"] = "rejected"
        enriched["passed"] = False
        enriched["failed_constraints"] = list(enriched.get("failed_constraints", [])) + ["borrow_pressure_blocked"]
        enriched["rejection_reason"] = "Borrow pressure blocks short-style candidates."
    elif isinstance(news_context, dict) and str(news_context.get("trade_impact", "")).lower() == "blocking":
        enriched["recommendation_status"] = "rejected"
        enriched["passed"] = False
        enriched["failed_constraints"] = list(enriched.get("failed_constraints", [])) + ["critical_news_risk"]
        enriched["rejection_reason"] = "; ".join(news_context.get("risk_flags", []) or ["Critical headline risk blocks candidate."])
    elif isinstance(short_context, dict) and str(short_context.get("short_interest_level", "")).lower() == "extreme" and str(short_context.get("trade_impact", "")).lower() == "caution" and enriched.get("recommendation_status") == "recommendable":
        enriched["recommendation_status"] = "watchlist"
        enriched["downgrade_reason"] = "; ".join(short_context.get("reasons", []) or ["Extreme short interest requires stronger confirmation."])
    elif isinstance(news_context, dict) and str(news_context.get("headline_risk_level", "")).lower() == "high" and enriched.get("recommendation_status") == "recommendable":
        enriched["recommendation_status"] = "watchlist"
        enriched["downgrade_reason"] = "; ".join(news_context.get("risk_flags", []) or ["High headline risk."])
    enriched["quality_bucket"] = _quality_bucket(enriched)
    return enriched


def _candidate_sort_key(candidate: dict) -> tuple:
    return (
        STATUS_PRIORITY.get(str(candidate.get("recommendation_status", "rejected")).lower(), 0),
        _safe_float(candidate.get("score")) or 0.0,
        _safe_float(candidate.get("risk_reward")) or 0.0,
        _safe_float(candidate.get("relative_volume")) or 0.0,
    )


def _deduplicate_profile_candidates(candidates: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate["ticker"], []).append(candidate)

    deduped = []
    for ticker, ticker_candidates in grouped.items():
        sorted_group = sorted(ticker_candidates, key=_candidate_sort_key, reverse=True)
        selected = deepcopy(sorted_group[0])
        if len(sorted_group) > 1:
            matched_profiles = [candidate.get("scan_profile") for candidate in sorted_group if candidate.get("scan_profile")]
            selected["duplicate_reason"] = (
                f"Matched multiple profiles ({', '.join(matched_profiles)}). "
                f"Selected {selected.get('scan_profile')} because it had the strongest score."
            )
            selected["selected_profile"] = selected.get("scan_profile")
        deduped.append(selected)
    deduped.sort(key=_candidate_sort_key, reverse=True)
    for index, candidate in enumerate(deduped, start=1):
        candidate["rank"] = index
    return deduped


def _update_scanner_run_totals(
    scanner_run_id: int | None,
    total_passed: int,
    total_rejected: int,
    market_data_freshness: str | None,
    notes: str | None,
    db_path: str,
) -> dict | None:
    if scanner_run_id is None:
        return None

    try:
        init_trade_tracking_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                UPDATE scanner_runs
                SET total_passed = ?,
                    total_rejected = ?,
                    market_data_freshness = ?,
                    notes = ?
                WHERE id = ?
                """,
                (total_passed, total_rejected, market_data_freshness, notes, scanner_run_id),
            )
        return {"ok": True}
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "scanner_run_id": scanner_run_id}


def _extract_freshness_label(candidate: dict) -> str | None:
    freshness = candidate.get("data_freshness", {})
    if isinstance(freshness, dict):
        return freshness.get("freshness_label")
    return None


def _classify_setup_type(current_price: float | None, sma_20: float | None, sma_50: float | None, high_20: float | None, cfg: dict) -> str:
    if current_price is None:
        return "trend_candidate"

    above_sma_20 = sma_20 is not None and current_price > sma_20
    above_sma_50 = sma_50 is not None and current_price > sma_50
    near_or_above_high_20 = high_20 is not None and current_price >= (high_20 * cfg["momentum_breakout_threshold"])

    if above_sma_20 and above_sma_50 and near_or_above_high_20:
        return "momentum_breakout"

    if above_sma_50 and sma_20 not in (None, 0):
        distance_from_sma_20 = abs(current_price - sma_20) / sma_20
        if distance_from_sma_20 <= cfg["trend_pullback_distance_percent"]:
            return "trend_pullback"

    return "trend_candidate"


def build_stock_candidate(
    ticker: str,
    market_snapshot: dict,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    snapshot_data = market_snapshot.get("data", {}) if isinstance(market_snapshot, dict) else {}
    technical_snapshot = snapshot_data.get("technical_snapshot") if isinstance(snapshot_data, dict) else None
    data_freshness = snapshot_data.get("data_freshness") if isinstance(snapshot_data, dict) else None
    quote = snapshot_data.get("quote") if isinstance(snapshot_data, dict) else None
    data_quality = snapshot_data.get("data_quality") if isinstance(snapshot_data, dict) else None

    technical_snapshot = technical_snapshot if isinstance(technical_snapshot, dict) else {}
    data_freshness = data_freshness if isinstance(data_freshness, dict) else {}
    quote = quote if isinstance(quote, dict) else {}
    data_quality = data_quality if isinstance(data_quality, dict) else validate_market_data_quality(market_snapshot)

    current_price = _safe_float(quote.get("last_price"))
    if current_price is None:
        current_price = _safe_float(technical_snapshot.get("current_price"))

    feature_provenance = build_core_market_feature_provenance(ticker, market_snapshot, data_quality=data_quality)
    provenance_warnings = provenance_warning_messages(feature_provenance)
    candidate = {
        "ticker": ticker.upper(),
        "asset_type": cfg["asset_type"],
        "direction": cfg["direction"],
        "setup_type": _classify_setup_type(
            current_price,
            _safe_float(technical_snapshot.get("sma_20")),
            _safe_float(technical_snapshot.get("sma_50")),
            _safe_float(technical_snapshot.get("high_20")),
            cfg,
        ),
        "current_price": current_price,
        "entry_price": None,
        "target_price": None,
        "stop_loss": None,
        "risk_reward": None,
        "score": 0.0,
        "rank": None,
        "recommendation_status": "rejected",
        "technical_snapshot": technical_snapshot,
        "data_freshness": data_freshness,
        "constraint_results": {},
        "failed_constraints": [],
        "rejection_reason": "",
        "sma_20": _safe_float(technical_snapshot.get("sma_20")),
        "sma_50": _safe_float(technical_snapshot.get("sma_50")),
        "sma_200": _safe_float(technical_snapshot.get("sma_200")),
        "average_volume_20": _safe_float(technical_snapshot.get("average_volume_20")),
        "relative_volume": _safe_float(technical_snapshot.get("relative_volume")),
        "atr_percent": _safe_float(technical_snapshot.get("atr_percent")),
        "data_quality": data_quality,
        "price_source": data_quality.get("price_source"),
        "quote_status": data_quality.get("quote_status"),
        "feature_provenance": feature_provenance,
        "feature_provenance_summary": summarize_feature_provenance(feature_provenance),
        "provenance_warnings": provenance_warnings,
    }
    return candidate


def calculate_trade_levels(
    technical_snapshot: dict,
    direction: str = "long",
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    if direction.lower() != "long":
        return {
            "ok": False,
            "direction": direction,
            "entry_price": None,
            "target_price": None,
            "stop_loss": None,
            "risk_reward": None,
            "error": "Only long swing-trade level calculation is implemented in this MVP.",
        }

    current_price = _safe_float(technical_snapshot.get("current_price"))
    atr_14 = _safe_float(technical_snapshot.get("atr_14"))
    sma_20 = _safe_float(technical_snapshot.get("sma_20"))
    high_20 = _safe_float(technical_snapshot.get("high_20"))

    if current_price is None:
        return {
            "ok": False,
            "direction": direction,
            "entry_price": None,
            "target_price": None,
            "stop_loss": None,
            "risk_reward": None,
            "error": "Current price is missing from technical snapshot.",
        }

    if atr_14 is None or atr_14 <= 0:
        return {
            "ok": False,
            "direction": direction,
            "entry_price": current_price,
            "target_price": None,
            "stop_loss": None,
            "risk_reward": None,
            "error": "ATR is missing or invalid, so trade levels cannot be calculated.",
        }

    entry_price = current_price
    atr_stop = current_price - (cfg["stop_atr_multiplier"] * atr_14)
    sma_stop = sma_20 if sma_20 is not None and sma_20 < current_price else None
    stop_loss = min([value for value in [atr_stop, sma_stop] if value is not None])

    risk = entry_price - stop_loss
    if risk <= 0:
        return {
            "ok": False,
            "direction": direction,
            "entry_price": entry_price,
            "target_price": None,
            "stop_loss": stop_loss,
            "risk_reward": None,
            "error": "Calculated stop loss is not below entry price.",
        }

    atr_target = current_price + (cfg["target_atr_multiplier"] * atr_14)
    target_price = atr_target

    if high_20 is not None and high_20 > current_price:
        high_20_rr = (high_20 - entry_price) / risk
        if high_20_rr >= cfg["high_20_rr_threshold"] and high_20 > target_price:
            target_price = high_20

    reward = target_price - entry_price
    risk_reward = reward / risk if risk > 0 else None

    return {
        "ok": True,
        "direction": direction,
        "entry_price": round(entry_price, 4),
        "target_price": round(target_price, 4),
        "stop_loss": round(stop_loss, 4),
        "risk_reward": round(risk_reward, 4) if risk_reward is not None else None,
        "error": None,
    }


def rank_candidates(candidates: list[dict]) -> list[dict]:
    ranked_candidates = [deepcopy(candidate) for candidate in candidates]
    ranked_candidates.sort(
        key=lambda candidate: (
            _safe_float(candidate.get("score")) or 0.0,
            _safe_float(candidate.get("risk_reward")) or 0.0,
            _safe_float(candidate.get("relative_volume")) or 0.0,
        ),
        reverse=True,
    )

    for index, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = index
    return ranked_candidates


def _rejected_candidate(ticker: str, reason: str, asset_type: str = "stock", direction: str = "long") -> dict:
    return {
        "ticker": ticker.upper(),
        "asset_type": asset_type,
        "direction": direction,
        "setup_type": "trend_candidate",
        "current_price": None,
        "entry_price": None,
        "target_price": None,
        "stop_loss": None,
        "risk_reward": None,
        "score": 0.0,
        "rank": None,
        "recommendation_status": "rejected",
        "technical_snapshot": {},
        "data_freshness": {},
        "constraint_results": {},
        "failed_constraints": ["scanner_error"],
        "rejection_reason": reason,
        "passed": False,
        "data_quality": {
            "quality_label": "unavailable",
            "final_recommendation_allowed": False,
            "warnings": [],
            "errors": [reason],
        },
    }


def _candidate_metrics(candidate: dict) -> dict:
    technical_snapshot = candidate.get("technical_snapshot", {})
    return {
        "current_price": candidate.get("current_price"),
        "relative_volume": candidate.get("relative_volume"),
        "atr_percent": candidate.get("atr_percent"),
        "risk_reward": candidate.get("risk_reward"),
        "entry_price": candidate.get("entry_price"),
        "target_price": candidate.get("target_price"),
        "stop_loss": candidate.get("stop_loss"),
        "setup_type": candidate.get("setup_type"),
        "freshness_label": candidate.get("data_freshness", {}).get("freshness_label") if isinstance(candidate.get("data_freshness"), dict) else None,
        "current_price_from_snapshot": technical_snapshot.get("current_price") if isinstance(technical_snapshot, dict) else None,
        "data_quality_label": candidate.get("data_quality", {}).get("quality_label") if isinstance(candidate.get("data_quality"), dict) else None,
        "price_source": candidate.get("price_source"),
        "quote_status": candidate.get("quote_status"),
        "feature_provenance_summary": candidate.get("feature_provenance_summary"),
        "technical_confirmation_summary": candidate.get("technical_confirmation_summary"),
        "volume_profile_confirmation": candidate.get("volume_profile_confirmation"),
        "timeframe_confirmation": candidate.get("timeframe_confirmation"),
        "filing_sentiment": candidate.get("filing_sentiment"),
        "filing_analysis": candidate.get("filing_analysis"),
        "earnings_8k_analysis": candidate.get("earnings_8k_analysis"),
        "short_interest": candidate.get("short_interest"),
        "borrow_pressure": candidate.get("borrow_pressure"),
        "news_sentiment": candidate.get("news_sentiment"),
    }


def _scan_execution_summary(async_result: dict | None, total_tickers: int, warnings: list[str] | None = None) -> dict:
    if not isinstance(async_result, dict):
        return {
            "total_tickers": total_tickers,
            "completed_tickers": total_tickers,
            "failed_tickers": [],
            "timed_out_tickers": [],
            "partial_results_used": False,
            "duration_seconds": None,
            "warnings": warnings or [],
        }
    failed = async_result.get("failed_tickers", [])
    timed_out = async_result.get("timed_out_tickers", [])
    return {
        "total_tickers": async_result.get("total_tickers", total_tickers),
        "completed_tickers": async_result.get("completed_tickers", 0),
        "failed_tickers": failed if isinstance(failed, list) else [],
        "timed_out_tickers": timed_out if isinstance(timed_out, list) else [],
        "partial_results_used": not bool(async_result.get("completed", True)),
        "duration_seconds": async_result.get("duration_seconds"),
        "warnings": async_result.get("warnings", []) if isinstance(async_result.get("warnings"), list) else warnings or [],
    }


def scan_swing_candidates(
    tickers: list[str],
    universe: str = "custom",
    lookback_days: int = 180,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
    max_candidates: int = 10,
) -> dict:
    cfg = _merge_config(config)
    timestamp = _now_iso()
    errors: list[dict] = []

    if not tickers:
        return {
            "ok": False,
            "scanner_run_id": None,
            "universe": universe,
            "timestamp": timestamp,
            "total_scanned": 0,
            "total_passed": 0,
            "total_rejected": 0,
            "passed_candidates": [],
            "rejected_candidates": [],
            "errors": [{"type": "input", "message": "Ticker list is empty."}],
        }

    scanner_run = log_scanner_run(
        universe=universe,
        total_scanned=len(tickers),
        total_passed=0,
        total_rejected=0,
        market_data_freshness=None,
        config_json=cfg,
        notes="Initial swing scan run created.",
        db_path=db_path,
    )

    scanner_run_id = scanner_run.get("id") if isinstance(scanner_run, dict) and scanner_run.get("ok", True) else None
    if not isinstance(scanner_run, dict) or scanner_run.get("ok") is False:
        errors.append(
            {
                "type": "logging",
                "message": scanner_run.get("error", "Failed to create scanner run.") if isinstance(scanner_run, dict) else "Failed to create scanner run.",
            }
        )

    evaluated_candidates: list[dict] = []
    freshness_labels: list[str] = []

    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            rejected = _rejected_candidate("UNKNOWN", "Ticker symbol is empty or invalid.")
            evaluated_candidates.append(rejected)
            errors.append({"ticker": "UNKNOWN", "type": "input", "message": rejected["rejection_reason"]})
            continue

        market_snapshot = get_market_snapshot(ticker, lookback_days=lookback_days)
        if not market_snapshot.get("ok"):
            reason = market_snapshot.get("error", "Market data request failed.")
            rejected = _rejected_candidate(ticker, reason)
            rejected["data_quality"] = validate_market_data_quality(market_snapshot)
            rejected["feature_provenance"] = build_core_market_feature_provenance(ticker, market_snapshot, data_quality=rejected["data_quality"])
            rejected["feature_provenance_summary"] = summarize_feature_provenance(rejected["feature_provenance"])
            rejected["provenance_warnings"] = provenance_warning_messages(rejected["feature_provenance"])
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "market_data", "message": reason})
            continue

        candidate = build_stock_candidate(ticker, market_snapshot, config=cfg)
        data_quality = candidate.get("data_quality") if isinstance(candidate.get("data_quality"), dict) else validate_market_data_quality(market_snapshot)
        if not data_quality.get("final_recommendation_allowed", False):
            rejected = deepcopy(candidate)
            rejected["recommendation_status"] = "rejected"
            rejected["failed_constraints"] = ["data_quality"]
            rejected["rejection_reason"] = "; ".join(data_quality.get("errors") or data_quality.get("warnings") or ["Market data quality is insufficient."])
            rejected["passed"] = False
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "data_quality", "message": rejected["rejection_reason"]})
            continue
        technical_snapshot = candidate.get("technical_snapshot", {})
        if not isinstance(technical_snapshot, dict) or technical_snapshot.get("ok") is False:
            reason = technical_snapshot.get("error", "Technical snapshot is missing or invalid.") if isinstance(technical_snapshot, dict) else "Technical snapshot is missing or invalid."
            rejected = _rejected_candidate(ticker, reason)
            rejected["technical_snapshot"] = technical_snapshot if isinstance(technical_snapshot, dict) else {}
            rejected["data_freshness"] = candidate.get("data_freshness", {})
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "technical_snapshot", "message": reason})
            continue

        if candidate.get("current_price") is None:
            rejected = deepcopy(candidate)
            rejected["recommendation_status"] = "rejected"
            rejected["failed_constraints"] = ["missing_current_price"]
            rejected["rejection_reason"] = "Current price is missing from market snapshot."
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "candidate_build", "message": rejected["rejection_reason"]})
            continue

        bounded_candidate, price_ok = _apply_request_price_bounds(candidate, cfg)
        if not price_ok:
            evaluated_candidates.append(bounded_candidate)
            errors.append({"ticker": ticker, "type": "intent_constraints", "message": bounded_candidate["rejection_reason"]})
            continue

        trade_levels = calculate_trade_levels(technical_snapshot, direction=candidate["direction"], config=cfg)
        if not trade_levels.get("ok"):
            rejected = deepcopy(candidate)
            rejected["recommendation_status"] = "rejected"
            rejected["failed_constraints"] = ["trade_level_error"]
            rejected["rejection_reason"] = trade_levels.get("error", "Trade level calculation failed.")
            rejected["entry_price"] = trade_levels.get("entry_price")
            rejected["target_price"] = trade_levels.get("target_price")
            rejected["stop_loss"] = trade_levels.get("stop_loss")
            rejected["risk_reward"] = trade_levels.get("risk_reward")
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "trade_levels", "message": rejected["rejection_reason"]})
            continue

        candidate.update(
            {
                "entry_price": trade_levels["entry_price"],
                "target_price": trade_levels["target_price"],
                "stop_loss": trade_levels["stop_loss"],
                "risk_reward": trade_levels["risk_reward"],
            }
        )

        constraint_result = evaluate_stock_constraints(candidate, config=cfg.get("constraint_config"))
        candidate["score"] = constraint_result["score"]
        candidate["recommendation_status"] = constraint_result["recommendation_status"]
        candidate["constraint_results"] = constraint_result["constraint_results"]
        candidate["failed_constraints"] = constraint_result["failed_constraints"]
        candidate["rejection_reason"] = constraint_result["rejection_reason"]
        candidate["passed"] = constraint_result["passed"]
        candidate = _apply_technical_confirmations(candidate, market_snapshot, config=cfg)
        candidate = _apply_filing_research(candidate, config=cfg)
        candidate = _apply_short_news_research(candidate, market_snapshot=market_snapshot, config=cfg)
        evaluated_candidates.append(candidate)

        freshness_label = _extract_freshness_label(candidate)
        if freshness_label:
            freshness_labels.append(freshness_label)

    passed_candidates = [candidate for candidate in evaluated_candidates if candidate.get("passed")]
    rejected_candidates = [candidate for candidate in evaluated_candidates if not candidate.get("passed")]

    ranked_passed = rank_candidates(passed_candidates)[:max_candidates]
    rank_lookup = {candidate["ticker"]: candidate["rank"] for candidate in ranked_passed}
    included_passed_tickers = set(rank_lookup)

    for candidate in passed_candidates:
        if candidate["ticker"] in included_passed_tickers:
            candidate["rank"] = rank_lookup[candidate["ticker"]]
        else:
            candidate["rank"] = None

    log_targets = ranked_passed + rejected_candidates + [candidate for candidate in passed_candidates if candidate["ticker"] not in included_passed_tickers]
    for candidate in log_targets:
        logged = log_candidate_evaluation(
            scanner_run_id=scanner_run_id,
            ticker=candidate["ticker"],
            asset_type=candidate.get("asset_type"),
            direction=candidate.get("direction"),
            setup_type=candidate.get("setup_type"),
            passed_constraints=1 if candidate.get("passed") else 0,
            score=candidate.get("score"),
            rank=candidate.get("rank"),
            rejection_reason=candidate.get("rejection_reason"),
            failed_constraints_json=candidate.get("failed_constraints"),
            metrics_json=_candidate_metrics(candidate),
            constraint_results_json={
                "passed": candidate.get("passed", False),
                "recommendation_status": candidate.get("recommendation_status"),
                "score": candidate.get("score"),
                "constraint_results": candidate.get("constraint_results"),
                "failed_constraints": candidate.get("failed_constraints"),
                "rejection_reason": candidate.get("rejection_reason"),
            },
            db_path=db_path,
        )
        if isinstance(logged, dict) and logged.get("ok") is False:
            errors.append({"ticker": candidate["ticker"], "type": "logging", "message": logged.get("error", "Failed to log candidate evaluation.")})

    freshness_summary = ",".join(sorted(set(freshness_labels))) if freshness_labels else "unknown"
    finalize_result = _update_scanner_run_totals(
        scanner_run_id=scanner_run_id,
        total_passed=len(passed_candidates),
        total_rejected=len(rejected_candidates),
        market_data_freshness=freshness_summary,
        notes=f"Completed swing scan for {len(tickers)} tickers.",
        db_path=db_path,
    )
    if isinstance(finalize_result, dict) and finalize_result.get("ok") is False:
        errors.append({"type": "logging", "message": finalize_result.get("error", "Failed to finalize scanner run totals.")})

    return {
        "ok": len(ranked_passed) > 0 or len(rejected_candidates) > 0,
        "scanner_run_id": scanner_run_id,
        "universe": universe,
        "timestamp": timestamp,
        "total_scanned": len(tickers),
        "total_passed": len(passed_candidates),
        "total_rejected": len(rejected_candidates),
        "passed_candidates": ranked_passed,
        "rejected_candidates": rejected_candidates,
        "errors": errors,
    }


def scan_multi_strategy_candidates(
    tickers: list[str],
    profiles: list[str] | None = None,
    universe: str = "custom",
    lookback_days: int = 180,
    db_path: str = "strategy_library.db",
    max_candidates_per_profile: int = 10,
    max_total_candidates: int = 25,
    use_async_scan: bool = True,
    scan_config: dict | None = None,
) -> dict:
    timestamp = _now_iso()
    errors: list[dict] = []
    profile_registry = get_default_scan_profiles()
    profiles_to_run = profiles or list(profile_registry.keys())

    if not tickers:
        return {
            "ok": False,
            "universe": universe,
            "timestamp": timestamp,
            "profiles_run": [],
            "total_tickers_scanned": 0,
            "total_profile_evaluations": 0,
            "total_recommendable": 0,
            "total_watchlist": 0,
            "total_rejected": 0,
            "best_candidates": [],
            "candidates_by_profile": {},
            "watchlist_candidates": [],
            "rejected_candidates": [],
            "errors": [{"type": "input", "message": "Ticker list is empty."}],
            "scan_execution_summary": _scan_execution_summary(None, 0),
            "message": "No tickers were provided for scanning.",
        }

    scanner_run = log_scanner_run(
        universe=universe,
        total_scanned=len(tickers),
        total_passed=0,
        total_rejected=0,
        market_data_freshness=None,
        config_json={"profiles": profiles_to_run, "max_candidates_per_profile": max_candidates_per_profile, "max_total_candidates": max_total_candidates},
        notes="Initial multi-strategy swing scan run created.",
        db_path=db_path,
    )
    scanner_run_id = scanner_run.get("id") if isinstance(scanner_run, dict) and scanner_run.get("ok", True) else None
    if not isinstance(scanner_run, dict) or scanner_run.get("ok") is False:
        errors.append(
            {
                "type": "logging",
                "message": scanner_run.get("error", "Failed to create scanner run.") if isinstance(scanner_run, dict) else "Failed to create scanner run.",
            }
        )

    candidates_by_profile: dict[str, list[dict]] = {}
    all_candidates: list[dict] = []
    total_profile_evaluations = 0
    market_snapshot_cache: dict[str, dict] = {}
    quality_results: list[dict] = []
    reported_market_failures: set[tuple[str, str]] = set()
    async_scan_result = None

    def _get_cached_market_snapshot(ticker: str) -> dict:
        if ticker not in market_snapshot_cache:
            try:
                market_snapshot_cache[ticker] = get_market_snapshot(ticker, lookback_days=lookback_days)
            except Exception as exc:
                market_snapshot_cache[ticker] = {
                    "ok": False,
                    "ticker": ticker,
                    "source": "unavailable",
                    "data": None,
                    "error": f"Market data request failed unexpectedly: {exc}",
                }
        return market_snapshot_cache[ticker]

    if use_async_scan:
        async_scan_result = run_async_scan_tickers(
            tickers,
            lambda ticker: get_market_snapshot(ticker, lookback_days=lookback_days),
            config=scan_config,
        )
        async_items = async_scan_result.get("results", []) if isinstance(async_scan_result, dict) else []
        for item in async_items:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            if item.get("ok"):
                market_snapshot_cache[ticker] = item.get("result")
            else:
                market_snapshot_cache[ticker] = {
                    "ok": False,
                    "ticker": ticker,
                    "source": "async_scan",
                    "data": None,
                    "error": item.get("error", "Market data request failed."),
                    "error_type": item.get("error_type", "market_data"),
                }
                errors.append(
                    {
                        "ticker": ticker,
                        "type": item.get("error_type", "market_data"),
                        "message": item.get("error", "Market data request failed."),
                    }
                )
        if isinstance(async_scan_result, dict):
            async_warnings = async_scan_result.get("warnings", []) if isinstance(async_scan_result.get("warnings"), list) else []
            for warning in async_warnings:
                errors.append({"type": "scan_execution", "message": warning})

    for raw_profile_name in profiles_to_run:
        profile_lookup = get_scan_profile(raw_profile_name)
        if not profile_lookup.get("ok"):
            errors.append({"type": "profile", "message": profile_lookup["error"]})
            continue

        profile = profile_lookup["profile"]
        profile_name = profile["name"]
        profile_candidates: list[dict] = []

        for raw_ticker in tickers:
            ticker = str(raw_ticker).strip().upper()
            if not ticker:
                candidate = _rejected_candidate("UNKNOWN", "Ticker symbol is empty or invalid.")
                candidate.update(
                    {
                        "scan_profile": profile_name,
                        "profile_description": profile["description"],
                        "why_this_profile_matched": [],
                        "quality_bucket": "rejected",
                        "duplicate_reason": None,
                        "selected_profile": profile_name,
                    }
                )
                profile_candidates.append(candidate)
                total_profile_evaluations += 1
                failure_key = (ticker, "market_data")
                if failure_key not in reported_market_failures:
                    errors.append({"ticker": ticker, "type": "market_data", "message": candidate["rejection_reason"]})
                    reported_market_failures.add(failure_key)
                continue

            market_snapshot = _get_cached_market_snapshot(ticker)
            if not market_snapshot.get("ok"):
                candidate = _rejected_candidate(ticker, market_snapshot.get("error", "Market data request failed."))
                candidate["data_quality"] = validate_market_data_quality(market_snapshot)
                candidate["feature_provenance"] = build_core_market_feature_provenance(ticker, market_snapshot, data_quality=candidate["data_quality"])
                candidate["feature_provenance_summary"] = summarize_feature_provenance(candidate["feature_provenance"])
                candidate["provenance_warnings"] = provenance_warning_messages(candidate["feature_provenance"])
                candidate.update(
                    {
                        "scan_profile": profile_name,
                        "profile_description": profile["description"],
                        "why_this_profile_matched": [],
                        "quality_bucket": "rejected",
                        "duplicate_reason": None,
                        "selected_profile": profile_name,
                    }
                )
                profile_candidates.append(candidate)
                total_profile_evaluations += 1
                continue

            candidate = build_stock_candidate(ticker, market_snapshot)
            data_quality = candidate.get("data_quality") if isinstance(candidate.get("data_quality"), dict) else validate_market_data_quality(market_snapshot)
            if profile_name == profile["name"]:
                quality_results.append(data_quality)
            candidate["scan_profile"] = profile_name
            candidate["profile_description"] = profile["description"]

            if not data_quality.get("final_recommendation_allowed", False):
                reason = "; ".join(data_quality.get("errors") or data_quality.get("warnings") or ["Market data quality is insufficient."])
                rejected = deepcopy(candidate)
                rejected.update(
                    {
                        "recommendation_status": "rejected",
                        "failed_constraints": ["data_quality"],
                        "rejection_reason": reason,
                        "why_this_profile_matched": [],
                        "quality_bucket": "rejected",
                        "duplicate_reason": None,
                        "selected_profile": profile_name,
                        "passed": False,
                    }
                )
                profile_candidates.append(rejected)
                total_profile_evaluations += 1
                failure_key = (ticker, "data_quality")
                if failure_key not in reported_market_failures:
                    errors.append({"ticker": ticker, "type": "data_quality", "message": reason})
                    reported_market_failures.add(failure_key)
                continue

            technical_snapshot = candidate.get("technical_snapshot", {})
            if not isinstance(technical_snapshot, dict) or technical_snapshot.get("ok") is False:
                reason = technical_snapshot.get("error", "Technical snapshot is missing or invalid.") if isinstance(technical_snapshot, dict) else "Technical snapshot is missing or invalid."
                rejected = _rejected_candidate(ticker, reason)
                rejected.update(
                    {
                        "scan_profile": profile_name,
                        "profile_description": profile["description"],
                        "technical_snapshot": technical_snapshot if isinstance(technical_snapshot, dict) else {},
                        "data_freshness": candidate.get("data_freshness", {}),
                        "why_this_profile_matched": [],
                        "quality_bucket": "rejected",
                        "duplicate_reason": None,
                        "selected_profile": profile_name,
                    }
                )
                profile_candidates.append(rejected)
                total_profile_evaluations += 1
                continue

            bounded_candidate, price_ok = _apply_request_price_bounds(candidate, scan_config)
            if not price_ok:
                bounded_candidate.update(
                    {
                        "scan_profile": profile_name,
                        "profile_description": profile["description"],
                        "why_this_profile_matched": [],
                        "quality_bucket": "rejected",
                        "duplicate_reason": None,
                        "selected_profile": profile_name,
                    }
                )
                profile_candidates.append(bounded_candidate)
                total_profile_evaluations += 1
                continue

            trade_levels = calculate_trade_levels(technical_snapshot, direction=candidate.get("direction", "long"))
            if not trade_levels.get("ok"):
                rejected = deepcopy(candidate)
                rejected["recommendation_status"] = "rejected"
                rejected["failed_constraints"] = ["trade_level_error"]
                rejected["rejection_reason"] = trade_levels.get("error", "Trade level calculation failed.")
                rejected["entry_price"] = trade_levels.get("entry_price")
                rejected["target_price"] = trade_levels.get("target_price")
                rejected["stop_loss"] = trade_levels.get("stop_loss")
                rejected["risk_reward"] = trade_levels.get("risk_reward")
                rejected["why_this_profile_matched"] = []
                rejected["quality_bucket"] = "rejected"
                rejected["duplicate_reason"] = None
                rejected["selected_profile"] = profile_name
                rejected["passed"] = False
                profile_candidates.append(rejected)
                total_profile_evaluations += 1
                continue

            candidate.update(
                {
                    "entry_price": trade_levels["entry_price"],
                    "target_price": trade_levels["target_price"],
                    "stop_loss": trade_levels["stop_loss"],
                    "risk_reward": trade_levels["risk_reward"],
                }
            )

            merged_constraint_config = deepcopy(profile.get("hard_constraints", {}))
            merged_constraint_config["minimum_score_to_recommend"] = profile.get("minimum_score_to_recommend", 80)
            constraint_result = evaluate_stock_constraints(candidate, config=merged_constraint_config)
            candidate = _finalize_profile_candidate(candidate, constraint_result, profile)
            candidate = _apply_technical_confirmations(candidate, market_snapshot)
            candidate = _apply_filing_research(candidate, config=scan_config)
            candidate = _apply_short_news_research(candidate, market_snapshot=market_snapshot, config=scan_config)

            if candidate["recommendation_status"] == "rejected" and not candidate.get("rejection_reason"):
                candidate["rejection_reason"] = "Candidate did not meet profile-adjusted recommendation or watchlist thresholds."
                candidate["failed_constraints"] = candidate.get("failed_constraints") or ["profile_thresholds"]

            profile_candidates.append(candidate)
            total_profile_evaluations += 1

        ranked_profile_candidates = _profile_rank_candidates(profile_candidates)
        for candidate in ranked_profile_candidates:
            if candidate["recommendation_status"] == "rejected":
                candidate["rank"] = None
        candidates_by_profile[profile_name] = ranked_profile_candidates[: profile.get("max_results", max_candidates_per_profile)]
        all_candidates.extend(ranked_profile_candidates)

    deduped_positive = _deduplicate_profile_candidates(
        [candidate for candidate in all_candidates if candidate.get("recommendation_status") in {"recommendable", "watchlist"}]
    )
    recommendable_candidates = [candidate for candidate in deduped_positive if candidate.get("recommendation_status") == "recommendable"]
    watchlist_candidates = [candidate for candidate in deduped_positive if candidate.get("recommendation_status") == "watchlist"]
    rejected_candidates = _deduplicate_profile_candidates(
        [candidate for candidate in all_candidates if candidate.get("recommendation_status") == "rejected"]
    )
    for candidate in rejected_candidates:
        candidate["rank"] = None

    if recommendable_candidates:
        best_candidates = recommendable_candidates[:max_total_candidates]
        message = f"Found {len(recommendable_candidates)} recommendable candidates across {len(candidates_by_profile)} profiles."
    elif watchlist_candidates:
        best_candidates = watchlist_candidates[:max_total_candidates]
        message = "No candidates passed recommendation thresholds, but these watchlist names came closest."
        errors.append({"type": "scan_summary", "message": message})
    else:
        best_candidates = []
        message = "No candidates passed recommendation thresholds and no watchlist names came close."

    freshness_summary = _profile_summary_label(all_candidates) or "unknown"
    total_recommendable = len(recommendable_candidates)
    total_watchlist = len(watchlist_candidates)
    total_rejected = len(rejected_candidates)
    data_quality_summary = build_data_quality_summary(
        [
            candidate.get("data_quality")
            for candidate in all_candidates
            if isinstance(candidate.get("data_quality"), dict)
        ]
    )

    for candidate in all_candidates:
        logged = log_candidate_evaluation(
            scanner_run_id=scanner_run_id,
            ticker=candidate["ticker"],
            asset_type=candidate.get("asset_type"),
            direction=candidate.get("direction"),
            setup_type=candidate.get("setup_type"),
            passed_constraints=1 if candidate.get("recommendation_status") in {"recommendable", "watchlist"} else 0,
            score=candidate.get("score"),
            rank=candidate.get("rank"),
            rejection_reason=candidate.get("rejection_reason"),
            failed_constraints_json=candidate.get("failed_constraints"),
            metrics_json={
                **_candidate_metrics(candidate),
                "scan_profile": candidate.get("scan_profile"),
                "quality_bucket": candidate.get("quality_bucket"),
            },
            constraint_results_json={
                "recommendation_status": candidate.get("recommendation_status"),
                "score": candidate.get("score"),
                "constraint_results": candidate.get("constraint_results"),
                "failed_constraints": candidate.get("failed_constraints"),
                "rejection_reason": candidate.get("rejection_reason"),
                "scan_profile": candidate.get("scan_profile"),
                "why_this_profile_matched": candidate.get("why_this_profile_matched"),
                "quality_bucket": candidate.get("quality_bucket"),
                "duplicate_reason": candidate.get("duplicate_reason"),
                "selected_profile": candidate.get("selected_profile"),
            },
            db_path=db_path,
        )
        if isinstance(logged, dict) and logged.get("ok") is False:
            errors.append({"ticker": candidate["ticker"], "type": "logging", "message": logged.get("error", "Failed to log candidate evaluation.")})

    finalize_result = _update_scanner_run_totals(
        scanner_run_id=scanner_run_id,
        total_passed=total_recommendable + total_watchlist,
        total_rejected=total_rejected,
        market_data_freshness=freshness_summary,
        notes=f"Completed multi-strategy scan across profiles: {', '.join(candidates_by_profile.keys())}.",
        db_path=db_path,
    )
    if isinstance(finalize_result, dict) and finalize_result.get("ok") is False:
        errors.append({"type": "logging", "message": finalize_result.get("error", "Failed to finalize scanner run totals.")})

    return {
        "ok": bool(candidates_by_profile),
        "scanner_run_id": scanner_run_id,
        "universe": universe,
        "timestamp": timestamp,
        "profiles_run": list(candidates_by_profile.keys()),
        "total_tickers_scanned": len(tickers),
        "total_profile_evaluations": total_profile_evaluations,
        "total_recommendable": total_recommendable,
        "total_watchlist": total_watchlist,
        "total_rejected": total_rejected,
        "best_candidates": best_candidates,
        "candidates_by_profile": candidates_by_profile,
        "watchlist_candidates": watchlist_candidates[:max_total_candidates],
        "rejected_candidates": rejected_candidates,
        "data_quality_summary": data_quality_summary,
        "scan_execution_summary": _scan_execution_summary(async_scan_result, len(tickers)),
        "errors": errors,
        "message": message,
    }
