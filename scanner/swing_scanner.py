from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import sqlite3

from engine.constraint_engine import evaluate_stock_constraints
from realtime.market_data import get_market_snapshot
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

    technical_snapshot = technical_snapshot if isinstance(technical_snapshot, dict) else {}
    data_freshness = data_freshness if isinstance(data_freshness, dict) else {}
    quote = quote if isinstance(quote, dict) else {}

    current_price = _safe_float(quote.get("last_price"))
    if current_price is None:
        current_price = _safe_float(technical_snapshot.get("current_price"))

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
            evaluated_candidates.append(rejected)
            errors.append({"ticker": ticker, "type": "market_data", "message": reason})
            continue

        candidate = build_stock_candidate(ticker, market_snapshot, config=cfg)
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
                continue

            market_snapshot = get_market_snapshot(ticker, lookback_days=lookback_days)
            if not market_snapshot.get("ok"):
                candidate = _rejected_candidate(ticker, market_snapshot.get("error", "Market data request failed."))
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
            candidate["scan_profile"] = profile_name
            candidate["profile_description"] = profile["description"]

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
        "errors": errors,
        "message": message,
    }
