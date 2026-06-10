from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import floor
from typing import Any


DEFAULT_PORTFOLIO_RISK_CONFIG = {
    "account_size": 10000.0,
    "max_risk_per_trade_percent": 0.01,
    "max_total_open_risk_percent": 0.05,
    "max_new_weekly_risk_percent": 0.03,
    "max_trades_per_week": 5,
    "max_same_sector_trades": 2,
    "max_same_theme_trades": 2,
    "max_option_premium_percent": 0.01,
    "max_total_option_premium_percent": 0.03,
    "allow_options": True,
    "risk_mode": "normal",
}

TERMINAL_RECOMMENDATION_STATUSES = {"win", "loss", "expired", "manual_review", "closed"}
QUALITY_BUCKET_RANK = {
    "A+": 4,
    "A": 3,
    "B": 2,
    "WATCHLIST": 1,
    "REJECTED": 0,
}
EPSILON = 1e-9
CONFIDENCE_RANK = {
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_config(account_size: float | None = None, config: dict | None = None) -> dict:
    normalized = dict(DEFAULT_PORTFOLIO_RISK_CONFIG)
    if isinstance(config, dict):
        normalized.update(config)
    if account_size is not None:
        normalized["account_size"] = float(account_size)

    risk_mode = str(normalized.get("risk_mode", "normal")).strip().lower()
    normalized["risk_mode"] = risk_mode or "normal"

    # Keep the interface simple: conservative tightens caps, aggressive loosens them modestly.
    if normalized["risk_mode"] == "conservative":
        normalized["max_risk_per_trade_percent"] = min(float(normalized["max_risk_per_trade_percent"]), 0.0075)
        normalized["max_total_open_risk_percent"] = min(float(normalized["max_total_open_risk_percent"]), 0.04)
        normalized["max_new_weekly_risk_percent"] = min(float(normalized["max_new_weekly_risk_percent"]), 0.02)
        normalized["max_option_premium_percent"] = min(float(normalized["max_option_premium_percent"]), 0.0075)
        normalized["max_total_option_premium_percent"] = min(float(normalized["max_total_option_premium_percent"]), 0.02)
        normalized["max_same_sector_trades"] = min(int(normalized["max_same_sector_trades"]), 1)
    elif normalized["risk_mode"] == "aggressive":
        normalized["max_risk_per_trade_percent"] = max(float(normalized["max_risk_per_trade_percent"]), 0.0125)
        normalized["max_total_open_risk_percent"] = max(float(normalized["max_total_open_risk_percent"]), 0.06)
        normalized["max_new_weekly_risk_percent"] = max(float(normalized["max_new_weekly_risk_percent"]), 0.04)
        normalized["max_option_premium_percent"] = max(float(normalized["max_option_premium_percent"]), 0.0125)
        normalized["max_total_option_premium_percent"] = max(float(normalized["max_total_option_premium_percent"]), 0.04)

    return normalized


def _asset_type(trade: dict) -> str:
    preferred_instrument = str(trade.get("preferred_instrument", "")).strip().lower()
    explicit_asset_type = str(trade.get("asset_type", "")).strip().lower()
    if preferred_instrument == "option":
        return "option"
    if explicit_asset_type == "option":
        return "option"
    if trade.get("option_contract"):
        return "option"
    return "stock"


def _base_ticker(trade: dict) -> str:
    if _asset_type(trade) == "option":
        return _normalize_ticker(
            trade.get("underlying_ticker")
            or (trade.get("source_candidate", {}) or {}).get("underlying_ticker")
            or trade.get("ticker")
        )
    return _normalize_ticker(trade.get("ticker") or (trade.get("source_candidate", {}) or {}).get("ticker"))


def _sector_key(trade: dict) -> str:
    source_candidate = trade.get("source_candidate", {}) if isinstance(trade.get("source_candidate"), dict) else {}
    sector = (
        trade.get("sector")
        or trade.get("industry_sector")
        or source_candidate.get("sector")
        or source_candidate.get("industry_sector")
        or "unknown"
    )
    return str(sector).strip().lower() or "unknown"


def _theme_key(trade: dict) -> str:
    source_candidate = trade.get("source_candidate", {}) if isinstance(trade.get("source_candidate"), dict) else {}
    theme = (
        trade.get("selected_profile")
        or trade.get("scan_profile")
        or trade.get("setup_type")
        or trade.get("strategy")
        or source_candidate.get("selected_profile")
        or source_candidate.get("scan_profile")
        or source_candidate.get("setup_type")
        or source_candidate.get("strategy")
        or "unknown"
    )
    return str(theme).strip().lower() or "unknown"


def _confidence_value(trade: dict) -> int:
    label = trade.get("confidence_label")
    if label is None:
        source_candidate = trade.get("source_candidate", {})
        if isinstance(source_candidate, dict):
            label = source_candidate.get("confidence_label")
            if label is None:
                statistical_context = source_candidate.get("statistical_context", {})
                if isinstance(statistical_context, dict):
                    label = statistical_context.get("confidence_label")
    return CONFIDENCE_RANK.get(str(label or "").strip().upper(), 0)


def _quality_value(trade: dict) -> int:
    quality = trade.get("quality_bucket")
    if quality is None:
        source_candidate = trade.get("source_candidate", {})
        if isinstance(source_candidate, dict):
            quality = source_candidate.get("quality_bucket")
    return QUALITY_BUCKET_RANK.get(str(quality or "").strip().upper(), 0)


def _score_value(trade: dict) -> float:
    score = _safe_float(trade.get("score"))
    if score is not None:
        return score
    source_candidate = trade.get("source_candidate", {})
    if isinstance(source_candidate, dict):
        return _safe_float(source_candidate.get("score")) or 0.0
    return 0.0


def _risk_reward_value(trade: dict) -> float:
    return _safe_float(trade.get("risk_reward")) or 0.0


def _sort_key(trade: dict) -> tuple[float, float, float, float]:
    return (
        float(_quality_value(trade)),
        float(_score_value(trade)),
        float(_confidence_value(trade)),
        float(_risk_reward_value(trade)),
    )


def _is_open_trade(trade: dict) -> bool:
    status = str(trade.get("status", trade.get("recommendation_status", "open"))).strip().lower()
    outcome = str(trade.get("outcome", "")).strip().lower()
    return outcome not in TERMINAL_RECOMMENDATION_STATUSES and status not in TERMINAL_RECOMMENDATION_STATUSES


def _is_recommendable_trade(trade: dict) -> tuple[bool, str | None]:
    decision = str(trade.get("decision", "")).strip().lower()
    status = str(trade.get("recommendation_status", "")).strip().lower()
    if decision and decision != "recommend":
        return False, f"Trade decision is {decision}, not recommend."
    if status and status != "recommendable":
        return False, f"Trade is {status}, not recommendable."

    passed = trade.get("passed")
    if passed is not None and not bool(passed):
        return False, "Trade failed hard constraints."

    constraint_results = trade.get("constraint_results")
    if isinstance(constraint_results, dict) and "passed" in constraint_results and not bool(constraint_results.get("passed")):
        return False, "Trade failed hard constraints."

    source_candidate = trade.get("source_candidate")
    if isinstance(source_candidate, dict):
        candidate_status = str(source_candidate.get("recommendation_status", "")).strip().lower()
        if candidate_status and candidate_status != "recommendable":
            return False, f"Source candidate is {candidate_status}, not recommendable."
        candidate_passed = source_candidate.get("passed")
        if candidate_passed is not None and not bool(candidate_passed):
            return False, "Source candidate failed hard constraints."
    return True, None


def calculate_trade_risk(trade: dict, account_size: float = 10000.0, config: dict | None = None) -> dict:
    normalized = _normalize_config(account_size=account_size, config=config)
    if not isinstance(trade, dict):
        return {
            "ok": False,
            "timestamp": _now_iso(),
            "ticker": "",
            "asset_type": "unknown",
            "risk_known": False,
            "error": "Trade must be a dictionary.",
            "warnings": ["Trade must be a dictionary."],
            "flags": ["invalid_trade"],
            "config": normalized,
        }

    asset_type = _asset_type(trade)
    ticker = _base_ticker(trade)
    quantity = _safe_int(trade.get("quantity"))
    contracts = _safe_int(trade.get("contracts")) or _safe_int(trade.get("quantity")) if asset_type == "option" else None
    warnings: list[str] = []
    flags: list[str] = []

    if asset_type == "option":
        premium = _safe_float(trade.get("entry_price"))
        if premium is None:
            premium = _safe_float(trade.get("mid"))
        if premium is None:
            premium = _safe_float(trade.get("premium"))
        if premium is None or premium <= 0:
            warnings.append("Missing option premium; max premium risk is unknown.")
            flags.append("missing_option_premium")
            return {
                "ok": False,
                "timestamp": _now_iso(),
                "ticker": ticker,
                "asset_type": asset_type,
                "risk_known": False,
                "error": "Missing option premium.",
                "warnings": warnings,
                "flags": flags,
                "contracts": contracts,
                "config": normalized,
            }

        estimated_contracts = contracts if contracts is not None and contracts > 0 else 1
        if contracts is None:
            warnings.append("Contracts were missing; estimated one contract for premium-at-risk.")
            flags.append("estimated_contracts")
        estimated_dollar_risk = float(estimated_contracts) * premium * 100.0
        risk_percent_of_account = estimated_dollar_risk / float(normalized["account_size"]) if normalized["account_size"] else None
        premium_percent_of_account = risk_percent_of_account

        return {
            "ok": True,
            "timestamp": _now_iso(),
            "ticker": ticker,
            "asset_type": asset_type,
            "risk_known": True,
            "entry_price": premium,
            "stop_loss": _safe_float(trade.get("stop_loss")),
            "target_price": _safe_float(trade.get("target_price")),
            "contracts": estimated_contracts,
            "estimated_dollar_risk": estimated_dollar_risk,
            "risk_percent_of_account": risk_percent_of_account,
            "premium_at_risk": estimated_dollar_risk,
            "premium_percent_of_account": premium_percent_of_account,
            "option_contract": trade.get("option_contract") or trade.get("preferred_option_contract"),
            "sector": _sector_key(trade),
            "theme": _theme_key(trade),
            "warnings": warnings,
            "flags": flags,
            "config": normalized,
        }

    entry_price = _safe_float(trade.get("entry_price"))
    stop_loss = _safe_float(trade.get("stop_loss"))
    if entry_price is None or stop_loss is None or entry_price <= 0:
        warnings.append("Missing stock entry or stop loss; dollar risk is unknown.")
        flags.append("missing_stock_risk_inputs")
        return {
            "ok": False,
            "timestamp": _now_iso(),
            "ticker": ticker,
            "asset_type": asset_type,
            "risk_known": False,
            "error": "Missing stock entry or stop loss.",
            "warnings": warnings,
            "flags": flags,
            "config": normalized,
        }

    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        warnings.append("Stock entry and stop loss produce zero risk-per-share.")
        flags.append("zero_stock_risk")
        return {
            "ok": False,
            "timestamp": _now_iso(),
            "ticker": ticker,
            "asset_type": asset_type,
            "risk_known": False,
            "error": "Risk per share must be greater than zero.",
            "warnings": warnings,
            "flags": flags,
            "config": normalized,
        }

    risk_budget_dollars = float(normalized["account_size"]) * float(normalized["max_risk_per_trade_percent"])
    estimated_quantity = quantity
    if estimated_quantity is None or estimated_quantity <= 0:
        quantity_from_risk = max(int(floor(risk_budget_dollars / risk_per_share)), 1)
        quantity_from_capital = max(int(floor(float(normalized["account_size"]) / entry_price)), 1)
        estimated_quantity = min(quantity_from_risk, quantity_from_capital)
        warnings.append("Quantity was missing; estimated share count from portfolio risk budget.")
        flags.append("estimated_quantity")

    estimated_dollar_risk = float(estimated_quantity) * risk_per_share
    risk_percent_entry = risk_per_share / entry_price
    risk_percent_of_account = estimated_dollar_risk / float(normalized["account_size"]) if normalized["account_size"] else None

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "ticker": ticker,
        "asset_type": asset_type,
        "risk_known": True,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_price": _safe_float(trade.get("target_price")),
        "quantity": estimated_quantity,
        "risk_per_share": risk_per_share,
        "risk_percent_entry": risk_percent_entry,
        "estimated_dollar_risk": estimated_dollar_risk,
        "risk_percent_of_account": risk_percent_of_account,
        "position_value_estimate": float(estimated_quantity) * entry_price,
        "sector": _sector_key(trade),
        "theme": _theme_key(trade),
        "warnings": warnings,
        "flags": flags,
        "config": normalized,
    }


def analyze_portfolio_exposure(
    proposed_trades: list[dict],
    existing_open_trades: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    normalized = _normalize_config(config=config)
    proposed = [trade for trade in (proposed_trades or []) if isinstance(trade, dict)]
    existing = [trade for trade in (existing_open_trades or []) if isinstance(trade, dict) and _is_open_trade(trade)]

    proposed_risks = [calculate_trade_risk(trade, account_size=float(normalized["account_size"]), config=normalized) for trade in proposed]
    existing_risks = [calculate_trade_risk(trade, account_size=float(normalized["account_size"]), config=normalized) for trade in existing]

    def _sum_percent(items: list[dict], key: str) -> float:
        return round(
            sum(_safe_float(item.get(key)) or 0.0 for item in items if isinstance(item, dict) and item.get("risk_known")),
            6,
        )

    def _count_by(items: list[dict], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get(field) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

    existing_base_tickers = [_base_ticker(trade) for trade in existing if _base_ticker(trade)]
    proposed_base_tickers = [_base_ticker(trade) for trade in proposed if _base_ticker(trade)]
    duplicate_tickers = sorted({ticker for ticker in proposed_base_tickers if proposed_base_tickers.count(ticker) > 1 or ticker in existing_base_tickers})

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "config": normalized,
        "existing_open_trades_count": len(existing),
        "proposed_trades_count": len(proposed),
        "existing_open_risk_percent": _sum_percent(existing_risks, "risk_percent_of_account"),
        "proposed_risk_percent": _sum_percent(proposed_risks, "risk_percent_of_account"),
        "total_open_risk_percent_if_approved": round(
            _sum_percent(existing_risks, "risk_percent_of_account") + _sum_percent(proposed_risks, "risk_percent_of_account"),
            6,
        ),
        "existing_option_premium_percent": _sum_percent(existing_risks, "premium_percent_of_account"),
        "proposed_option_premium_percent": _sum_percent(proposed_risks, "premium_percent_of_account"),
        "total_option_premium_percent_if_approved": round(
            _sum_percent(existing_risks, "premium_percent_of_account") + _sum_percent(proposed_risks, "premium_percent_of_account"),
            6,
        ),
        "sector_counts_existing": _count_by(existing_risks, "sector"),
        "sector_counts_proposed": _count_by(proposed_risks, "sector"),
        "theme_counts_existing": _count_by(existing_risks, "theme"),
        "theme_counts_proposed": _count_by(proposed_risks, "theme"),
        "duplicate_tickers": duplicate_tickers,
        "proposed_trade_risks": proposed_risks,
        "existing_trade_risks": existing_risks,
    }


def score_portfolio_fit(
    trade: dict,
    existing_open_trades: list[dict] | None = None,
    selected_trades: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    normalized = _normalize_config(config=config)
    existing = [item for item in (existing_open_trades or []) if isinstance(item, dict) and _is_open_trade(item)]
    selected = [item for item in (selected_trades or []) if isinstance(item, dict)]
    trade_risk = calculate_trade_risk(trade, account_size=float(normalized["account_size"]), config=normalized)

    if not trade_risk.get("risk_known"):
        return {
            "ok": False,
            "timestamp": _now_iso(),
            "ticker": _base_ticker(trade),
            "score": 0.0,
            "confidence": "low",
            "warnings": trade_risk.get("warnings", []),
            "flags": trade_risk.get("flags", []) + ["unknown_trade_risk"],
            "config": normalized,
        }

    score = 100.0
    warnings: list[str] = []
    flags: list[str] = []
    ticker = _base_ticker(trade)
    sector = _sector_key(trade)
    theme = _theme_key(trade)
    risk_percent = _safe_float(trade_risk.get("risk_percent_of_account")) or 0.0
    premium_percent = _safe_float(trade_risk.get("premium_percent_of_account")) or 0.0

    existing_tickers = {_base_ticker(item) for item in existing if _base_ticker(item)}
    selected_tickers = {_base_ticker(item) for item in selected if _base_ticker(item)}
    if ticker and (ticker in existing_tickers or ticker in selected_tickers):
        score -= 60.0
        warnings.append("Trade duplicates an existing or already-selected underlying.")
        flags.append("duplicate_ticker")

    sector_count = sum(1 for item in [*existing, *selected] if _sector_key(item) == sector and sector != "unknown")
    theme_count = sum(1 for item in [*existing, *selected] if _theme_key(item) == theme and theme != "unknown")
    if sector_count >= int(normalized["max_same_sector_trades"]):
        score -= 25.0
        warnings.append("Sector concentration is already near the configured limit.")
        flags.append("sector_concentration")
    if theme_count >= int(normalized["max_same_theme_trades"]):
        score -= 20.0
        warnings.append("Theme concentration is already near the configured limit.")
        flags.append("theme_concentration")

    if risk_percent > float(normalized["max_risk_per_trade_percent"]):
        score -= 35.0
        warnings.append("Trade-level risk exceeds the configured per-trade cap.")
        flags.append("per_trade_risk_exceeded")
    elif risk_percent > float(normalized["max_risk_per_trade_percent"]) * 0.8:
        score -= 10.0
        warnings.append("Trade-level risk uses most of the configured per-trade budget.")

    if _asset_type(trade) == "option":
        if premium_percent > float(normalized["max_option_premium_percent"]):
            score -= 35.0
            warnings.append("Option premium exposure exceeds the configured per-trade cap.")
            flags.append("option_premium_exceeded")
        elif premium_percent > float(normalized["max_option_premium_percent"]) * 0.8:
            score -= 10.0
            warnings.append("Option premium uses most of the configured per-trade budget.")

    score = max(round(score, 2), 0.0)
    confidence = "high" if score >= 75 else "medium" if score >= 50 else "low"
    return {
        "ok": True,
        "timestamp": _now_iso(),
        "ticker": ticker,
        "score": score,
        "confidence": confidence,
        "trade_risk": trade_risk,
        "warnings": warnings,
        "flags": flags,
        "config": normalized,
    }


def build_portfolio_risk_summary(
    approved_trades: list[dict],
    rejected_trades: list[dict],
    exposure_analysis: dict,
    config: dict | None = None,
) -> dict:
    normalized = _normalize_config(config=config)
    exposure = exposure_analysis if isinstance(exposure_analysis, dict) else {}
    approved = [trade for trade in (approved_trades or []) if isinstance(trade, dict)]
    rejected = [trade for trade in (rejected_trades or []) if isinstance(trade, dict)]

    approved_tickers = [_base_ticker(trade) for trade in approved if _base_ticker(trade)]
    rejected_tickers = [_base_ticker(item.get("trade", item)) for item in rejected if isinstance(item, dict)]
    approved_risk = round(sum(_safe_float((trade.get("portfolio_risk_context") or {}).get("trade_risk", {}).get("risk_percent_of_account")) or 0.0 for trade in approved), 6)
    approved_option_premium = round(sum(_safe_float((trade.get("portfolio_risk_context") or {}).get("trade_risk", {}).get("premium_percent_of_account")) or 0.0 for trade in approved), 6)

    message = "Portfolio risk check completed."
    if not approved:
        message = "Portfolio risk check rejected every proposed trade."

    return {
        "timestamp": _now_iso(),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "approved_tickers": approved_tickers,
        "rejected_tickers": rejected_tickers,
        "approved_new_risk_percent": approved_risk,
        "approved_option_premium_percent": approved_option_premium,
        "existing_open_risk_percent": exposure.get("existing_open_risk_percent", 0.0),
        "total_open_risk_percent_if_approved": round((exposure.get("existing_open_risk_percent", 0.0) or 0.0) + approved_risk, 6),
        "existing_option_premium_percent": exposure.get("existing_option_premium_percent", 0.0),
        "total_option_premium_percent_if_approved": round((exposure.get("existing_option_premium_percent", 0.0) or 0.0) + approved_option_premium, 6),
        "max_trades_per_week": int(normalized["max_trades_per_week"]),
        "max_same_sector_trades": int(normalized["max_same_sector_trades"]),
        "max_same_theme_trades": int(normalized["max_same_theme_trades"]),
        "risk_mode": normalized["risk_mode"],
        "message": message,
    }


def apply_portfolio_risk_limits(
    proposed_trades: list[dict],
    existing_open_trades: list[dict] | None = None,
    account_size: float = 10000.0,
    config: dict | None = None,
) -> dict:
    normalized = _normalize_config(account_size=account_size, config=config)
    proposed = [deepcopy(trade) for trade in (proposed_trades or []) if isinstance(trade, dict)]
    existing = [deepcopy(trade) for trade in (existing_open_trades or []) if isinstance(trade, dict) and _is_open_trade(trade)]

    exposure_analysis = analyze_portfolio_exposure(proposed, existing, config=normalized)
    sorted_proposed = sorted(proposed, key=_sort_key, reverse=True)

    approved_trades: list[dict] = []
    rejected_trades: list[dict] = []

    existing_tickers = {_base_ticker(trade) for trade in existing if _base_ticker(trade)}
    approved_tickers: set[str] = set()
    sector_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}

    for trade in existing:
        sector = _sector_key(trade)
        theme = _theme_key(trade)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        theme_counts[theme] = theme_counts.get(theme, 0) + 1

    total_existing_risk = float(exposure_analysis.get("existing_open_risk_percent", 0.0) or 0.0)
    total_existing_option_premium = float(exposure_analysis.get("existing_option_premium_percent", 0.0) or 0.0)
    approved_new_risk = 0.0
    approved_new_option_premium = 0.0

    for trade in sorted_proposed:
        trade_copy = deepcopy(trade)
        ticker = _base_ticker(trade_copy)
        portfolio_fit = score_portfolio_fit(
            trade_copy,
            existing_open_trades=existing,
            selected_trades=approved_trades,
            config=normalized,
        )
        trade_risk = calculate_trade_risk(
            trade_copy,
            account_size=float(normalized["account_size"]),
            config=normalized,
        )

        rejection_reasons: list[str] = []
        allowed, recommendation_reason = _is_recommendable_trade(trade_copy)
        if not allowed and recommendation_reason:
            rejection_reasons.append(recommendation_reason)

        if not ticker:
            rejection_reasons.append("Missing ticker for portfolio-level risk tracking.")

        if _asset_type(trade_copy) == "option" and not bool(normalized["allow_options"]):
            rejection_reasons.append("Options are disabled by the current portfolio risk configuration.")

        if ticker and (ticker in existing_tickers or ticker in approved_tickers):
            rejection_reasons.append("Duplicate underlying ticker would increase overlapping exposure.")

        if not trade_risk.get("risk_known"):
            rejection_reasons.append(trade_risk.get("error", "Critical trade-risk data is missing."))

        risk_percent = _safe_float(trade_risk.get("risk_percent_of_account")) or 0.0
        if trade_risk.get("risk_known") and risk_percent > (float(normalized["max_risk_per_trade_percent"]) + EPSILON):
            rejection_reasons.append("Trade risk exceeds max_risk_per_trade_percent.")

        if (total_existing_risk + approved_new_risk + risk_percent) > (float(normalized["max_total_open_risk_percent"]) + EPSILON):
            rejection_reasons.append("Trade would exceed max_total_open_risk_percent.")

        if (approved_new_risk + risk_percent) > (float(normalized["max_new_weekly_risk_percent"]) + EPSILON):
            rejection_reasons.append("Trade would exceed max_new_weekly_risk_percent.")

        sector = _sector_key(trade_copy)
        if sector != "unknown" and (sector_counts.get(sector, 0) + 1) > int(normalized["max_same_sector_trades"]):
            rejection_reasons.append("Trade would exceed max_same_sector_trades.")

        theme = _theme_key(trade_copy)
        if theme != "unknown" and (theme_counts.get(theme, 0) + 1) > int(normalized["max_same_theme_trades"]):
            rejection_reasons.append("Trade would exceed max_same_theme_trades.")

        premium_percent = _safe_float(trade_risk.get("premium_percent_of_account")) or 0.0
        if _asset_type(trade_copy) == "option":
            if premium_percent > (float(normalized["max_option_premium_percent"]) + EPSILON):
                rejection_reasons.append("Option premium exposure exceeds max_option_premium_percent.")
            if (total_existing_option_premium + approved_new_option_premium + premium_percent) > (float(normalized["max_total_option_premium_percent"]) + EPSILON):
                rejection_reasons.append("Option premium exposure would exceed max_total_option_premium_percent.")

        if len(approved_trades) >= int(normalized["max_trades_per_week"]):
            rejection_reasons.append("Trade would exceed max_trades_per_week.")

        risk_context = {
            "portfolio_fit_score": portfolio_fit.get("score"),
            "portfolio_fit_confidence": portfolio_fit.get("confidence"),
            "warnings": portfolio_fit.get("warnings", []),
            "flags": sorted(set([*(portfolio_fit.get("flags", []) or []), *(trade_risk.get("flags", []) or [])])),
            "trade_risk": trade_risk,
            "risk_mode": normalized["risk_mode"],
        }

        if rejection_reasons:
            rejected_trades.append(
                {
                    "ticker": ticker,
                    "trade": trade_copy,
                    "rejection_reason": "; ".join(rejection_reasons),
                    "rejection_reasons": rejection_reasons,
                    "portfolio_risk_context": risk_context,
                }
            )
            continue

        trade_copy["portfolio_risk_context"] = risk_context
        approved_trades.append(trade_copy)
        approved_tickers.add(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        approved_new_risk += risk_percent
        approved_new_option_premium += premium_percent

    approved_exposure = analyze_portfolio_exposure(approved_trades, existing, config=normalized)
    risk_summary = build_portfolio_risk_summary(
        approved_trades=approved_trades,
        rejected_trades=rejected_trades,
        exposure_analysis=approved_exposure,
        config=normalized,
    )

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "config": normalized,
        "approved_trades": approved_trades,
        "rejected_trades": rejected_trades,
        "exposure_analysis": approved_exposure,
        "initial_exposure_analysis": exposure_analysis,
        "risk_summary": risk_summary,
    }
