from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from analytics.relative_strength import (
    apply_relative_strength_to_candidate,
    get_relative_strength_snapshot,
)
from analytics.statistical_brain import enrich_candidate_with_statistics
from realtime.catalyst_enrichment import enrich_candidate_with_catalysts


DEFAULT_SELECTOR_CONFIG = {
    "minimum_weekly_score": 74.0,
    "minimum_watchlist_score": 66.0,
    "same_sector_limit": 2,
    "watchlist_limit": 5,
    "include_catalysts": False,
    "include_relative_strength": True,
    "reject_on_earnings_risk": False,
    "earnings_risk_penalty": 12.0,
    "negative_catalyst_penalty": 10.0,
    "high_risk_catalyst_penalty": 16.0,
    "positive_catalyst_boost_cap": 8.0,
    "quality_bucket_bonus": {
        "A+": 10.0,
        "A": 7.0,
        "B": 4.0,
        "watchlist": 0.5,
        "rejected": -20.0,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_config(config: dict | None = None) -> dict:
    merged = deepcopy(DEFAULT_SELECTOR_CONFIG)
    if config:
        for key, value in config.items():
            if key == "quality_bucket_bonus" and isinstance(value, dict):
                merged[key].update(value)
            else:
                merged[key] = value
    return merged


def _normalize_ticker(ticker: str | None) -> str:
    return str(ticker or "").strip().upper()


def _candidate_sector(candidate: dict) -> str | None:
    for value in (
        candidate.get("sector"),
        candidate.get("industry_sector"),
        candidate.get("technical_snapshot", {}).get("sector") if isinstance(candidate.get("technical_snapshot"), dict) else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _candidate_status(candidate: dict) -> str:
    return str(candidate.get("recommendation_status", "rejected")).lower()


def _quality_bonus(candidate: dict, cfg: dict) -> float:
    bucket = str(candidate.get("quality_bucket", "rejected"))
    return float(cfg["quality_bucket_bonus"].get(bucket, 0.0))


def _catalyst_placeholder(candidate: dict) -> dict:
    return {
        "ok": True,
        "source": "placeholder",
        "has_news_catalyst_data": False,
        "catalyst_bias": 0.0,
        "notes": f"No catalyst enrichment is available yet for {candidate.get('ticker')}.",
    }


def _apply_catalyst_adjustments(candidate: dict, cfg: dict) -> tuple[float, bool]:
    catalyst_context = candidate.get("catalyst_context", {})
    if not isinstance(catalyst_context, dict):
        return 0.0, False

    label = str(catalyst_context.get("catalyst_label", "unavailable")).lower()
    if label == "unavailable":
        return 0.0, False

    adjustment = 0.0
    reject_candidate = False

    bias = _safe_float(catalyst_context.get("catalyst_bias")) or 0.0
    if bias > 0:
        adjustment += min(float(cfg["positive_catalyst_boost_cap"]), bias)

    if label == "negative":
        adjustment -= float(cfg["negative_catalyst_penalty"])
    elif label == "high_risk":
        adjustment -= float(cfg["high_risk_catalyst_penalty"])

    risk_flags = catalyst_context.get("risk_flags", [])
    if isinstance(risk_flags, list) and any("earnings" in str(flag).lower() for flag in risk_flags):
        adjustment -= float(cfg["earnings_risk_penalty"])
        if cfg.get("reject_on_earnings_risk"):
            reject_candidate = True

    return adjustment, reject_candidate


def _apply_statistical_adjustments(candidate: dict) -> float:
    statistical_context = candidate.get("statistical_context", {})
    if not isinstance(statistical_context, dict):
        return 0.0

    confidence_label = str(statistical_context.get("confidence_label", "low")).lower()
    confidence_multiplier = {
        "low": 0.05,
        "medium": 0.10,
        "high": 0.15,
    }.get(confidence_label, 0.08)

    adjustment = 0.0
    stat_score = _safe_float(statistical_context.get("statistical_score"))
    if stat_score is not None:
        adjustment += stat_score * confidence_multiplier

    setup = statistical_context.get("setup_performance") or {}
    if isinstance(setup, dict) and setup.get("meets_min_sample_size"):
        expectancy = _safe_float(setup.get("expectancy"))
        if expectancy is not None:
            if expectancy > 0:
                adjustment += min(8.0, expectancy * 100.0)
            elif expectancy < 0:
                adjustment -= min(10.0, abs(expectancy) * 100.0)

    profile = statistical_context.get("profile_performance") or {}
    if isinstance(profile, dict) and profile.get("meets_min_sample_size"):
        avg_return = _safe_float(profile.get("avg_realized_return"))
        if avg_return is not None:
            if avg_return > 0:
                adjustment += min(5.0, avg_return * 100.0)
            elif avg_return < 0:
                adjustment -= min(6.0, abs(avg_return) * 100.0)

    ticker_history = statistical_context.get("ticker_history") or {}
    if isinstance(ticker_history, dict):
        closed_trades = int(ticker_history.get("closed_trades") or 0)
        edge = str(ticker_history.get("historical_edge", "neutral")).lower()
        if closed_trades >= 5:
            if edge == "positive":
                adjustment += 4.0
            elif edge == "negative":
                adjustment -= 8.0

    return adjustment


def _apply_relative_strength_adjustments(candidate: dict) -> float:
    relative_strength_context = candidate.get("relative_strength_context", {})
    if not isinstance(relative_strength_context, dict):
        return 0.0

    label = str(relative_strength_context.get("relative_strength_label", "unknown")).lower()
    if label == "market_leader":
        return 6.0
    if label == "outperforming":
        return 3.0
    if label == "underperforming":
        return -4.0
    if label == "market_laggard":
        return -7.0
    return 0.0


def score_weekly_candidate(
    candidate: dict,
    existing_open_trades: list[dict] | None = None,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
) -> float:
    del existing_open_trades
    del db_path

    cfg = _merge_config(config)
    scanner_score = min(max(_safe_float(candidate.get("score")) or 0.0, 0.0), 100.0)
    risk_reward = max(_safe_float(candidate.get("risk_reward")) or 0.0, 0.0)
    relative_volume = max(_safe_float(candidate.get("relative_volume")) or 0.0, 0.0)
    profile_reasons = candidate.get("why_this_profile_matched")
    if not isinstance(profile_reasons, list):
        profile_reasons = []

    score = scanner_score * 0.58
    score += min(risk_reward, 4.0) / 4.0 * 14.0
    score += min(relative_volume, 3.0) / 3.0 * 10.0
    score += _quality_bonus(candidate, cfg)
    score += min(len(profile_reasons), 4) * 1.5
    score += _apply_statistical_adjustments(candidate)
    score += _apply_relative_strength_adjustments(candidate)

    if _candidate_status(candidate) == "watchlist":
        score -= 6.0
    elif _candidate_status(candidate) == "rejected":
        score -= 25.0

    catalyst_adjustment, _ = _apply_catalyst_adjustments(candidate, cfg)
    score += catalyst_adjustment

    return round(min(max(score, 0.0), 100.0), 2)


def apply_portfolio_limits(
    candidates: list[dict],
    existing_open_trades: list[dict] | None = None,
    config: dict | None = None,
) -> list[dict]:
    cfg = _merge_config(config)
    existing_open_trades = existing_open_trades or []

    existing_tickers = {_normalize_ticker(trade.get("ticker")) for trade in existing_open_trades if _normalize_ticker(trade.get("ticker"))}
    selected_tickers: set[str] = set()
    sector_counts: dict[str, int] = {}

    for trade in existing_open_trades:
        sector = _candidate_sector(trade)
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    selected: list[dict] = []
    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get("ticker"))
        sector = _candidate_sector(candidate)
        candidate["portfolio_limit_reason"] = None

        if not ticker:
            candidate["portfolio_limit_reason"] = "Missing ticker."
            continue
        if ticker in existing_tickers:
            candidate["portfolio_limit_reason"] = "Ticker already exists in open trades."
            continue
        if ticker in selected_tickers:
            candidate["portfolio_limit_reason"] = "Duplicate ticker in weekly selection pool."
            continue
        if sector and sector_counts.get(sector, 0) >= int(cfg.get("same_sector_limit", 2)):
            candidate["portfolio_limit_reason"] = f"Sector exposure limit reached for {sector}."
            continue

        selected.append(candidate)
        selected_tickers.add(ticker)
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    return selected


def _sorted_candidates(candidates: list[dict]) -> list[dict]:
    ranked = [deepcopy(candidate) for candidate in candidates]
    ranked.sort(
        key=lambda candidate: (
            _safe_float(candidate.get("weekly_score")) or 0.0,
            _safe_float(candidate.get("score")) or 0.0,
            _safe_float(candidate.get("risk_reward")) or 0.0,
            _safe_float(candidate.get("relative_volume")) or 0.0,
        ),
        reverse=True,
    )
    return ranked


def _enrich_candidate(candidate: dict, db_path: str, config: dict | None = None) -> dict:
    enriched = enrich_candidate_with_statistics(candidate, db_path=db_path)
    if not isinstance(enriched, dict):
        enriched = dict(candidate)
    if not isinstance(enriched.get("catalyst_context"), dict):
        enriched["catalyst_context"] = _catalyst_placeholder(enriched)
    cfg = _merge_config(config)
    if cfg.get("include_relative_strength") and not isinstance(enriched.get("relative_strength_context"), dict):
        sector = _candidate_sector(enriched)
        relative_strength = get_relative_strength_snapshot(
            ticker=_normalize_ticker(enriched.get("ticker")),
            sector=sector,
            include_sector=True,
            db_path=db_path,
        )
        enriched = apply_relative_strength_to_candidate(enriched, relative_strength)
    return enriched


def select_weekly_trades(
    scan_result: dict,
    max_trades: int = 5,
    min_trades: int = 2,
    existing_open_trades: list[dict] | None = None,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
) -> dict:
    timestamp = _now_iso()
    cfg = _merge_config(config)
    errors: list[str] = []

    if not isinstance(scan_result, dict) or not scan_result.get("ok"):
        return {
            "ok": False,
            "timestamp": timestamp,
            "selected_trades": [],
            "watchlist_alternatives": [],
            "rejected_for_portfolio_limits": [],
            "selection_summary": {
                "max_trades": max_trades,
                "min_trades": min_trades,
                "selected_count": 0,
                "watchlist_count": 0,
                "message": "Scan result was missing or invalid.",
            },
            "errors": ["Scan result was missing or invalid."],
        }

    base_candidates = scan_result.get("best_candidates")
    if not isinstance(base_candidates, list):
        base_candidates = scan_result.get("passed_candidates", [])

    watchlist_candidates = scan_result.get("watchlist_candidates", [])
    candidate_pool: list[dict] = []
    for bucket in (base_candidates, watchlist_candidates):
        if not isinstance(bucket, list):
            continue
        for candidate in bucket:
            if isinstance(candidate, dict):
                candidate_pool.append(deepcopy(candidate))

    if not candidate_pool:
        return {
            "ok": True,
            "timestamp": timestamp,
            "selected_trades": [],
            "watchlist_alternatives": [],
            "rejected_for_portfolio_limits": [],
            "selection_summary": {
                "max_trades": max_trades,
                "min_trades": min_trades,
                "selected_count": 0,
                "watchlist_count": 0,
                "message": "No candidates were available for weekly selection.",
            },
            "errors": [],
        }

    enriched_candidates: list[dict] = []
    for candidate in candidate_pool:
        try:
            enriched = _enrich_candidate(candidate, db_path=db_path, config=cfg)
            if cfg.get("include_catalysts"):
                enriched = enrich_candidate_with_catalysts(enriched)
            enriched["weekly_score"] = score_weekly_candidate(
                enriched,
                existing_open_trades=existing_open_trades,
                db_path=db_path,
                config=cfg,
            )
            _, rejected_by_catalyst = _apply_catalyst_adjustments(enriched, cfg)
            if rejected_by_catalyst:
                enriched["recommendation_status"] = "watchlist"
                enriched["portfolio_limit_reason"] = "Rejected by earnings-risk catalyst policy."
            enriched_candidates.append(enriched)
        except Exception as exc:
            errors.append(f"Failed to enrich candidate {candidate.get('ticker')}: {exc}")

    recommendable_candidates = [
        candidate
        for candidate in enriched_candidates
        if _candidate_status(candidate) == "recommendable"
        and (_safe_float(candidate.get("weekly_score")) or 0.0) >= float(cfg["minimum_weekly_score"])
    ]
    recommendable_candidates = _sorted_candidates(recommendable_candidates)

    limited_recommendable = apply_portfolio_limits(
        recommendable_candidates,
        existing_open_trades=existing_open_trades,
        config=cfg,
    )
    selected_trades = limited_recommendable[:max_trades]

    selected_tickers = {_normalize_ticker(candidate.get("ticker")) for candidate in selected_trades}
    rejected_for_portfolio_limits = [
        candidate
        for candidate in recommendable_candidates
        if candidate.get("portfolio_limit_reason") and _normalize_ticker(candidate.get("ticker")) not in selected_tickers
    ]

    alternative_pool = [
        candidate
        for candidate in enriched_candidates
        if _normalize_ticker(candidate.get("ticker")) not in selected_tickers
        and (
            _candidate_status(candidate) == "watchlist"
            or (_candidate_status(candidate) == "recommendable" and (_safe_float(candidate.get("weekly_score")) or 0.0) < float(cfg["minimum_weekly_score"]))
        )
    ]
    alternative_pool = [
        candidate
        for candidate in _sorted_candidates(alternative_pool)
        if (_safe_float(candidate.get("weekly_score")) or 0.0) >= float(cfg["minimum_watchlist_score"])
    ]
    watchlist_alternatives = alternative_pool[: int(cfg["watchlist_limit"])]

    if not selected_trades and not watchlist_alternatives:
        fallback_watchlist = [
            candidate
            for candidate in _sorted_candidates(
                [
                    candidate
                    for candidate in enriched_candidates
                    if _normalize_ticker(candidate.get("ticker")) not in selected_tickers
                    and _candidate_status(candidate) == "watchlist"
                ]
            )
        ]
        watchlist_alternatives = fallback_watchlist[: int(cfg["watchlist_limit"])]

    if not selected_trades:
        message = "No trades met weekly selection standards. Watchlist candidates are provided, but no final trade should be taken yet."
    elif len(selected_trades) < min_trades:
        message = "Only a small number of trades met weekly selection standards. Watchlist alternatives are provided, but no extra trades were forced."
    else:
        message = f"Selected {len(selected_trades)} trade ideas for the week."

    return {
        "ok": True,
        "timestamp": timestamp,
        "selected_trades": selected_trades,
        "watchlist_alternatives": watchlist_alternatives,
        "rejected_for_portfolio_limits": rejected_for_portfolio_limits,
        "selection_summary": {
            "max_trades": max_trades,
            "min_trades": min_trades,
            "selected_count": len(selected_trades),
            "watchlist_count": len(watchlist_alternatives),
            "message": message,
        },
        "errors": errors,
    }
